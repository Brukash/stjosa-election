"""OTP, registration-notice and vote-confirmation delivery over email, SMS and WhatsApp.

Security rules enforced here:
  * The OTP is sent to the contact on the approved register, never to a value
    supplied by the caller.
  * The OTP is never logged and never written to the database; only a masked
    recipient, provider message id and failure reason are recorded.
  * WhatsApp is only offered where the voter has a recorded opt-in. It uses an
    official WhatsApp Business Platform (Meta Cloud API or a Termii WhatsApp
    device), never a personal account or browser automation.
  * Outside local development the OTP is never returned by the API. If no
    delivery channel is configured, the request fails instead of revealing it.
  * Delivery failures never expose the OTP or provider credentials.
"""
from __future__ import annotations

import base64
import html
import smtplib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import Election, NotificationDelivery, Voter
from .services import now

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
CHANNEL_LABELS = {"email": "Email", "sms": "SMS", "whatsapp": "WhatsApp", "development": "Development"}


@dataclass
class ChannelOption:
    channel: str
    label: str
    available: bool
    destination_masked: str
    provider: str
    reason: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeliveryResult:
    channel: str          # email | sms | whatsapp | development
    provider: str         # resend | smtp | termii | twilio | meta | on-screen | none
    status: str           # sent | failed | unavailable | skipped
    recipient_masked: str
    provider_message_id: str | None = None
    error: str | None = None

    @property
    def delivered(self) -> bool:
        return self.status in {"sent", "skipped"}

    def as_dict(self) -> dict:
        return asdict(self)


def mask_email(value: str) -> str:
    local, _, domain = value.partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}******@{domain}"


def mask_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return f"******{digits[-4:]}"


def _normalise_phone(value: str) -> str | None:
    raw = value.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if not raw.startswith("+") or not raw[1:].isdigit() or len(raw) < 8:
        return None
    return raw


def _email_provider() -> str:
    return settings.email_provider.strip().lower()


def _sms_provider() -> str:
    return settings.sms_provider.strip().lower()


def _termii_whatsapp_template_id(purpose: str) -> str:
    """The approved Termii template id for one notice purpose."""
    return {
        "otp": settings.termii_whatsapp_otp_template_id,
        "registration": settings.termii_whatsapp_registration_template_id,
        "vote_confirmation": settings.termii_whatsapp_vote_confirmation_template_id,
        "results": settings.termii_whatsapp_results_template_id,
    }[purpose].strip()


def whatsapp_template_reference(purpose: str) -> str:
    """Template name (Meta) or template id (Termii) for one notice purpose."""
    if settings.whatsapp_provider_key == "termii":
        return _termii_whatsapp_template_id(purpose)
    return {
        "registration": settings.whatsapp_registration_template_name,
        "vote_confirmation": settings.whatsapp_vote_confirmation_template_name,
        "results": settings.whatsapp_results_template_name,
    }[purpose]


def whatsapp_template_language(purpose: str) -> str:
    """The Meta template language for one purpose.

    Each Meta template has its own approved language, so the purpose selects
    the matching setting. A Termii template id already fixes the language, so
    no language is reported for that provider.
    """
    if settings.whatsapp_provider_key == "termii":
        return ""
    return {
        "registration": settings.whatsapp_registration_template_language,
        "vote_confirmation": settings.whatsapp_vote_confirmation_template_language,
        "results": settings.whatsapp_results_template_language,
    }[purpose]


def channel_options(voter: Voter) -> list[ChannelOption]:
    """All three registered channels, with availability and masked destination.

    Unavailable options are returned intentionally so the voter can see which
    registered channels will and will not receive the shared OTP. No full
    contact detail is ever included.
    """
    email_reason: str | None = None
    if not voter.email:
        email_reason = "No email address is registered for this Voter ID."
    elif not settings.email_configured:
        email_reason = "Email delivery is not configured by the Electoral Committee."
    email_masked = mask_email(voter.email) if voter.email else "—"

    phone = _normalise_phone(voter.phone or "")
    sms_reason: str | None = None
    if not phone:
        sms_reason = "No valid mobile number is registered for this Voter ID."
    elif not settings.sms_configured:
        sms_reason = "SMS delivery is not configured by the Electoral Committee."

    whatsapp_reason: str | None = None
    if not phone:
        whatsapp_reason = "No valid mobile number is registered for this Voter ID."
    elif not voter.whatsapp_consent:
        whatsapp_reason = "The voter has not consented to WhatsApp messages."
    elif not settings.whatsapp_configured:
        whatsapp_reason = "WhatsApp delivery is not configured by the Electoral Committee."

    options = [
        ChannelOption(
            channel="email",
            label=CHANNEL_LABELS["email"],
            available=email_reason is None,
            destination_masked=email_masked,
            provider=_email_provider() if settings.email_configured else "none",
            reason=email_reason,
        ),
        ChannelOption(
            channel="sms",
            label=CHANNEL_LABELS["sms"],
            available=sms_reason is None,
            destination_masked=mask_phone(phone) if phone else "—",
            provider=_sms_provider() if settings.sms_configured else "none",
            reason=sms_reason,
        ),
        ChannelOption(
            channel="whatsapp",
            label=CHANNEL_LABELS["whatsapp"],
            available=whatsapp_reason is None,
            destination_masked=mask_phone(phone) if phone else "—",
            provider=settings.whatsapp_provider_key if settings.whatsapp_configured else "none",
            reason=whatsapp_reason,
        ),
    ]

    # Local-only on-screen delivery keeps development usable when no real
    # provider is configured. It is never offered alongside a working provider,
    # and production/loopback rules are enforced by settings.expose_dev_otp.
    if settings.expose_dev_otp and not any(option.available for option in options):
        options.append(
            ChannelOption(
                channel="development",
                label="On-screen (development only)",
                available=True,
                destination_masked="This screen",
                provider="on-screen",
                reason=None,
            )
        )
    return options


TERMII_PENDING_SENDER_ID = "SJCALUMNI"


def _sms_readiness_reason() -> str | None:
    """Why SMS cannot send, in the Super Administrator's words.

    A sender ID is the name Nigerian networks show as the sender of an SMS.
    Termii rejects every message without an approved one, so a valid API key
    alone is not enough to call SMS configured.
    """
    if _sms_provider() == "termii":
        if not settings.termii_api_key:
            return "TERMII_API_KEY is not set, so no SMS can be sent."
        if not settings.termii_sender_id:
            return (
                "SMS is not configured because no approved Termii sender ID exists. "
                f"The {TERMII_PENDING_SENDER_ID} application is still a draft: open "
                "Termii → Rental → SMS Sender IDs, choose country Nigeria and submit "
                "it for review. Set TERMII_SENDER_ID only after Termii approves it."
            )
        return None
    if _sms_provider() == "twilio":
        missing = [
            name
            for name, value in (
                ("TWILIO_ACCOUNT_SID", settings.twilio_account_sid),
                ("TWILIO_AUTH_TOKEN", settings.twilio_auth_token),
                ("TWILIO_FROM_NUMBER", settings.twilio_from_number),
            )
            if not value
        ]
        if missing:
            return "Twilio is selected but " + ", ".join(missing) + " is not set."
        return None
    return "No SMS provider is selected; set SMS_PROVIDER=termii."


def provider_status() -> list[dict]:
    """Safe provider readiness for the Super Administrator and committee.

    Values are intentionally limited to configuration state. Secrets are never
    included in an API response.
    """
    return [
        {
            "channel": "email",
            "label": "Email",
            "provider": _email_provider(),
            "configured": settings.email_configured,
            "required_settings": [
                "EMAIL_PROVIDER=resend",
                "RESEND_API_KEY",
                "EMAIL_FROM",
            ]
            if _email_provider() == "resend"
            else [
                "EMAIL_PROVIDER=smtp",
                "EMAIL_FROM",
                "SMTP_HOST",
                "SMTP_PORT",
                "SMTP_USERNAME",
                "SMTP_PASSWORD",
                "SMTP_SSL=true (port 465) or SMTP_STARTTLS=true (port 587)",
            ],
        },
        {
            "channel": "sms",
            "label": "SMS",
            "provider": _sms_provider(),
            "configured": settings.sms_configured,
            "reason": _sms_readiness_reason(),
            "required_settings": (
                ["SMS_PROVIDER=termii", "TERMII_API_KEY", "TERMII_SENDER_ID"]
                if _sms_provider() == "termii"
                else [
                    "SMS_PROVIDER=twilio",
                    "TWILIO_ACCOUNT_SID",
                    "TWILIO_AUTH_TOKEN",
                    "TWILIO_FROM_NUMBER",
                ]
            ),
        },
        {
            "channel": "whatsapp",
            "label": "WhatsApp",
            "provider": settings.whatsapp_provider_key,
            "configured": settings.whatsapp_configured,
            "required_settings": (
                [
                    "WHATSAPP_PROVIDER=termii",
                    "TERMII_API_KEY",
                    "TERMII_WHATSAPP_DEVICE_ID",
                    "TERMII_WHATSAPP_REGISTRATION_TEMPLATE_ID",
                    "TERMII_WHATSAPP_VOTE_CONFIRMATION_TEMPLATE_ID",
                    "TERMII_WHATSAPP_RESULTS_TEMPLATE_ID",
                ]
                if settings.whatsapp_provider_key == "termii"
                else [
                    "WHATSAPP_PROVIDER=meta",
                    "WHATSAPP_ACCESS_TOKEN",
                    "WHATSAPP_PHONE_NUMBER_ID",
                    "WHATSAPP_REGISTRATION_TEMPLATE_NAME",
                    "WHATSAPP_VOTE_CONFIRMATION_TEMPLATE_NAME",
                    "WHATSAPP_RESULTS_TEMPLATE_NAME",
                ]
            ),
            "template": whatsapp_template_reference("registration"),
            "template_language": whatsapp_template_language("registration"),
            "consent_required": True,
            "delivery_status_webhook": {
                "url": f"{settings.api_origin}/api/webhooks/whatsapp",
                "signature_configured": bool(settings.whatsapp_app_secret),
                "verification_configured": bool(settings.whatsapp_verify_token),
            },
        },
    ]


# ── message rendering ───────────────────────────────────────────────────────
def _email_body(election: Election, otp: str) -> tuple[str, str, str]:
    minutes = max(1, settings.otp_ttl_seconds // 60)
    subject = f"Your {election.reference} voting one-time password"
    text = (
        f"St. John's College Jos Alumni Association\n"
        f"{election.title}\n\n"
        f"Your one-time password is: {otp}\n\n"
        f"It expires in {minutes} minutes and can be used once. Enter it on the election "
        f"accreditation page to continue.\n\n"
        f"Election reference: {election.reference}\n"
        f"Verification portal: {settings.app_origin}/verify\n\n"
        f"Never share this OTP with anyone. Officials will never ask you for it. "
        f"If you did not request this password, report the request to the Electoral Committee "
        f"at accreditation@sjcjos-alumni.org.\n"
    )
    html_body = f"""\
<!doctype html>
<html><body style="margin:0;padding:0;background:#FAF8EC;font-family:Segoe UI,Arial,sans-serif;color:#0B3D24">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FAF8EC;padding:24px 12px">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="max-width:520px;background:#ffffff;border:1px solid #DCE5D8;border-radius:14px;overflow:hidden">
        <tr><td style="background:#0B3D24;padding:22px 26px;color:#ffffff">
          <img src="{settings.app_origin}/Josa.png" alt="St. John's College Jos" height="52" style="display:block;margin:0 0 12px;border-radius:6px" />
          <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;opacity:.6">St. John's College Jos</div>
          <div style="font-size:18px;font-weight:700;margin-top:4px">Alumni Election Accreditation</div>
        </td></tr>
        <tr><td style="height:5px;background:#E7D21C;font-size:0;line-height:0">&nbsp;</td></tr>
        <tr><td style="padding:26px">
          <p style="margin:0 0 6px;font-size:14px;color:#55635A">{html.escape(election.title)}</p>
          <p style="margin:0 0 18px;font-size:14px;color:#55635A">Reference {html.escape(election.reference)}</p>
          <p style="margin:0 0 10px;font-size:14px">Your one-time password is:</p>
          <div style="font-family:Consolas,monospace;font-size:34px;font-weight:700;letter-spacing:10px;
                      background:#EEF4EC;border-radius:10px;padding:14px 18px;text-align:center">{otp}</div>
          <p style="margin:18px 0 0;font-size:13px;color:#55635A">
            It expires in {minutes} minutes and can be used once. Enter it on the accreditation page to continue.
          </p>
          <p style="margin:14px 0 0;font-size:13px;color:#B42318;font-weight:600">
            Never share this OTP with anyone. Officials will never ask you for it.
          </p>
          <p style="margin:10px 0 0;font-size:13px;color:#55635A">
            If you did not request this password, report the request to the Electoral Committee.
          </p>
        </td></tr>
        <tr><td style="background:#EEF4EC;padding:16px 26px;font-size:11px;color:#55635A">
          This message never asks for your ballot choices. St. John's College Jos Alumni Election.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return subject, text, html_body


def _sms_body(election: Election, otp: str) -> str:
    minutes = max(1, settings.otp_ttl_seconds // 60)
    return (
        f"SJC Jos Alumni Election ({election.reference}): your OTP is {otp}. "
        f"Expires in {minutes} minutes. Never share it. Not you? Contact the Electoral Committee."
    )


# ── providers ───────────────────────────────────────────────────────────────
def _post_with_retry(
    client: httpx.Client, url: str, *, attempts: int = 2, **kwargs
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            response = client.post(url, **kwargs)
            if response.status_code < 300 or response.status_code not in RETRYABLE_STATUS:
                return response
            last_error = httpx.HTTPStatusError(
                f"provider returned {response.status_code}", request=response.request, response=response
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(0.4 * (attempt + 1))
    raise last_error or RuntimeError("delivery failed")


def _send_resend(
    destination: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
    *,
    timeout_seconds: int | None = None,
    attempts: int = 2,
) -> tuple[str | None, str | None]:
    payload = {
        "from": settings.email_from,
        "to": [destination],
        "subject": subject,
        "text": text_body.strip(),
    }
    if html_body:
        payload["html"] = html_body
    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }
    timeout = timeout_seconds or settings.otp_delivery_timeout_seconds
    with httpx.Client(timeout=timeout) as client:
        response = _post_with_retry(
            client,
            f"{settings.email_api_base}/emails",
            attempts=attempts,
            json=payload,
            headers=headers,
        )
    if response.status_code >= 300:
        return None, f"email provider rejected the message ({response.status_code})"
    try:
        message_id = str(response.json().get("id") or "")
        if not message_id:
            return None, "email provider did not confirm a message id"
        return message_id, None
    except ValueError:
        return None, "email provider returned an invalid response"


_SMTP_SLOTS: threading.Semaphore | None = None
_SMTP_SLOTS_LOCK = threading.Lock()


def _smtp_slots() -> threading.Semaphore:
    """Shared cap on simultaneous SMTP connections.

    Shared cPanel/Exim hosting limits concurrent connections per mailbox and
    temporarily blocks a mailbox that exceeds them, so a 150-voter batch must
    not open one connection per worker thread.
    """
    global _SMTP_SLOTS
    with _SMTP_SLOTS_LOCK:
        if _SMTP_SLOTS is None:
            _SMTP_SLOTS = threading.Semaphore(max(1, settings.smtp_max_connections))
        return _SMTP_SLOTS


_SMTP_PACE_LOCK = threading.Lock()
_SMTP_LAST_SEND = 0.0


def _smtp_pace() -> None:
    """Space SMTP messages at least SMTP_SEND_DELAY_MS apart, app-wide.

    Every notification path that sends email — OTPs, registration notices, vote
    confirmations and declared results — shares this pacer, so the mailbox is
    never hit with back-to-back messages from several threads or notice types
    at once. Callers queue instead of bursting, and the delay is configurable
    (0 disables it for a host that does not throttle message rate).
    """
    global _SMTP_LAST_SEND
    delay = max(0, settings.smtp_send_delay_ms) / 1000
    if not delay:
        return
    with _SMTP_PACE_LOCK:
        wait = _SMTP_LAST_SEND + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _SMTP_LAST_SEND = time.monotonic()


def _smtp_message(
    destination: str, subject: str, body: str, html_body: str | None = None
) -> EmailMessage:
    message = EmailMessage()
    display_name, address = parseaddr(settings.email_from)
    sender_address = address or settings.email_from
    sender_domain = sender_address.partition("@")[2] or None
    message["From"] = formataddr((display_name or "SJC Alumni Election", sender_address))
    message["To"] = destination
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=sender_domain)
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    return message


class _SmtpSession:
    """One authenticated SMTP connection, reused for a batch of messages.

    cPanel/Exim counts connections per mailbox and throttles one that opens
    many of them quickly, so a notification batch authenticates once and sends
    every message over that session instead of reconnecting per recipient.
    Port 465 uses implicit TLS (SMTP_SSL); port 587 uses STARTTLS.
    """

    def __init__(self) -> None:
        self.server: smtplib.SMTP | None = None
        self.use_ssl = settings.smtp_ssl or settings.smtp_port == 465

    def connect(self, *, timeout_seconds: int | None = None) -> None:
        self.close()
        timeout = timeout_seconds or settings.otp_delivery_timeout_seconds
        if self.use_ssl:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=timeout)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)
        try:
            server.ehlo()
            if not self.use_ssl and settings.smtp_starttls:
                server.starttls()
                server.ehlo()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
        except (smtplib.SMTPException, OSError):
            try:
                server.close()
            except (smtplib.SMTPException, OSError):
                pass
            raise
        self.server = server

    def close(self) -> None:
        server, self.server = self.server, None
        if server is None:
            return
        try:
            server.quit()
        except (smtplib.SMTPException, OSError):
            try:
                server.close()
            except (smtplib.SMTPException, OSError):
                pass

    def send(self, message: EmailMessage) -> str:
        if self.server is None:
            raise smtplib.SMTPServerDisconnected("the SMTP session is not connected")
        self.server.send_message(message)
        return str(message["Message-ID"])


def _send_smtp(
    destination: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    *,
    timeout_seconds: int | None = None,
) -> tuple[str | None, str | None]:
    """Send one message through an authenticated SMTP mailbox such as cPanel's.

    The envelope sender is EMAIL_FROM, which cPanel only accepts when the
    mailbox belongs to the same account (or is an alias on that domain).
    Batches use `_send_registration_email_batch` instead, so they authenticate
    once rather than opening a connection per recipient.
    """
    message = _smtp_message(destination, subject, body, html_body)
    session = _SmtpSession()
    try:
        # One message per call, but it still waits for the app-wide pacer and a
        # shared connection slot so a burst of OTPs or vote confirmations can
        # never exceed the mailbox's limits.
        _smtp_pace()
        with _smtp_slots():
            session.connect(timeout_seconds=timeout_seconds)
            return session.send(message), None
    except (smtplib.SMTPException, OSError) as exc:
        return None, f"smtp delivery failed: {type(exc).__name__}"
    finally:
        session.close()


def _send_twilio(
    destination: str, body: str, *, timeout_seconds: int | None = None
) -> tuple[str | None, str | None]:
    sid = settings.twilio_account_sid
    credentials = base64.b64encode(f"{sid}:{settings.twilio_auth_token}".encode()).decode()
    url = f"{settings.sms_api_base}/2010-04-01/Accounts/{sid}/Messages.json"
    data = {"From": settings.twilio_from_number, "To": destination, "Body": body}
    timeout = timeout_seconds or settings.otp_delivery_timeout_seconds
    with httpx.Client(timeout=timeout) as client:
        response = _post_with_retry(
            client, url, data=data, headers={"Authorization": f"Basic {credentials}"}
        )
    if response.status_code >= 300:
        return None, f"sms provider rejected the message ({response.status_code})"
    try:
        message_id = str(response.json().get("sid") or "")
        if not message_id:
            return None, "sms provider did not confirm a message id"
        return message_id, None
    except ValueError:
        return None, "sms provider returned an invalid response"


_TERMII_SUCCESS_CODES = {"ok", "success", "00", "0", "200"}


def _termii_accepted_message(
    response: httpx.Response, channel: str
) -> tuple[str | None, str | None]:
    """Read one Termii send response the same way for SMS and WhatsApp.

    Termii confirms an accepted message with `code: "ok"` and a `message_id`.
    A non-2xx status or any other code means the message was not accepted.
    """
    if response.status_code >= 300:
        return None, f"{channel} provider rejected the message ({response.status_code})"
    try:
        data = response.json()
        code = str(data.get("code") or "").lower()
        message_id = str(data.get("message_id") or "")
    except (ValueError, AttributeError):
        return None, f"{channel} provider returned an invalid response"
    if code and code not in _TERMII_SUCCESS_CODES:
        return None, f"{channel} provider did not confirm delivery"
    if not message_id:
        return None, f"{channel} provider did not confirm a message id"
    return message_id, None


def _send_termii(
    destination: str, body: str, *, timeout_seconds: int | None = None
) -> tuple[str | None, str | None]:
    """Send a transactional SMS through Termii.

    The DND route is used for OTPs; Termii's generic route is promotional and
    may be blocked for DND numbers.
    """
    payload = {
        "api_key": settings.termii_api_key,
        "to": destination,
        "from": settings.termii_sender_id,
        "sms": body,
        "type": "plain",
        "channel": settings.termii_channel or "dnd",
    }
    url = f"{settings.termii_api_base}/api/sms/send"
    timeout = timeout_seconds or settings.otp_delivery_timeout_seconds
    with httpx.Client(timeout=timeout) as client:
        response = _post_with_retry(client, url, json=payload)
    return _termii_accepted_message(response, "sms")


def _send_termii_whatsapp(
    destination: str,
    template_id: str,
    variables: list[str],
    *,
    timeout_seconds: int | None = None,
    attempts: int = 2,
) -> tuple[str | None, str | None]:
    """Send an approved WhatsApp template through Termii's WhatsApp device.

    Termii fills the <%1%>, <%2%>, … placeholders of the template approved in
    the dashboard from `data` keys "1", "2", … in the same order. The device id
    chooses which WhatsApp number sends, and each notice purpose uses its own
    template id from TERMII_WHATSAPP_*_TEMPLATE_ID.
    """
    if not template_id:
        return None, "whatsapp template id is not configured for this notice"
    payload = {
        "api_key": settings.termii_api_key,
        "phone_number": "".join(ch for ch in destination if ch.isdigit()),
        "device_id": settings.termii_whatsapp_device_id,
        "template_id": template_id,
        "data": {str(index): value for index, value in enumerate(variables, start=1)},
    }
    url = f"{settings.termii_api_base}/api/send/template"
    timeout = timeout_seconds or settings.otp_delivery_timeout_seconds
    with httpx.Client(timeout=timeout) as client:
        response = _post_with_retry(client, url, attempts=attempts, json=payload)
    return _termii_accepted_message(response, "whatsapp")


def _termii_whatsapp_result(
    purpose: str,
    variables: list[str],
    destination: str,
    *,
    timeout_seconds: int | None = None,
    attempts: int = 2,
) -> DeliveryResult:
    """DeliveryResult wrapper around the Termii WhatsApp template sender."""
    try:
        message_id, error = _send_termii_whatsapp(
            destination,
            _termii_whatsapp_template_id(purpose),
            variables,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
        )
    except Exception as exc:
        message_id, error = None, f"whatsapp delivery unavailable ({type(exc).__name__})"
    return DeliveryResult(
        channel="whatsapp",
        provider="termii",
        status="failed" if error else "sent",
        recipient_masked=mask_phone(destination),
        provider_message_id=message_id,
        error=error,
    )


def _send_whatsapp(destination: str, otp: str) -> tuple[str | None, str | None]:
    """Send an approved authentication template through the configured provider.

    Meta authentication templates require the code in both the body and the OTP
    button; the button is exposed as a URL button after approval. A Termii OTP
    template receives the code as its only variable.
    """
    if settings.whatsapp_provider_key == "termii":
        return _send_termii_whatsapp(
            destination, _termii_whatsapp_template_id("otp"), [otp]
        )
    to = "".join(ch for ch in destination if ch.isdigit())
    parameters = [{"type": "text", "text": otp}]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": settings.whatsapp_template_name,
            "language": {"code": settings.whatsapp_template_language},
            "components": [
                {"type": "body", "parameters": parameters},
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [{"type": "text", "text": otp}],
                },
            ],
        },
    }
    url = f"{settings.whatsapp_api_base}/{settings.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=settings.otp_delivery_timeout_seconds) as client:
        response = _post_with_retry(client, url, json=payload, headers=headers)
    if response.status_code >= 300:
        return None, f"whatsapp provider rejected the message ({response.status_code})"
    try:
        messages = response.json().get("messages") or []
        message_id = str(messages[0].get("id") or "") if messages else ""
        if not message_id:
            return None, "whatsapp provider did not confirm a message id"
        return message_id, None
    except (ValueError, AttributeError, IndexError):
        return None, "whatsapp provider returned an invalid response"


# ── sms ─────────────────────────────────────────────────────────────────────
def _send_sms(
    destination: str, body: str, *, timeout_seconds: int | None = None
) -> tuple[str | None, str | None]:
    """One entry point for SMS, whichever gateway is configured."""
    provider = _sms_provider()
    if provider == "termii":
        return _send_termii(destination, body, timeout_seconds=timeout_seconds)
    if provider == "twilio":
        return _send_twilio(destination, body, timeout_seconds=timeout_seconds)
    return None, "sms provider is not configured"


# ── registration notices ─────────────────────────────────────────────────────
def _registration_email_body(election: Election, voter: Voter) -> tuple[str, str, str]:
    link = f"{settings.app_origin.rstrip('/')}/accredit"
    subject = f"{election.reference}: You are registered to vote — Voter ID {voter.voter_id}"
    text = (
        f"Dear {voter.full_name},\n\n"
        f"You have been approved on the electoral register for {election.title}.\n"
        f"Your Voter ID is {voter.voter_id}.\n\n"
        f"To accredit, open {link} and enter your Voter ID. If it matches the approved "
        f"register, you can create your anonymous voting credential and vote.\n\n"
        f"Keep this email and your Voter ID private. Officials will never ask for your voting credential.\n\n"
        f"St. John's College Jos Alumni Election"
    )
    html_body = f"""<!doctype html><html><body style="margin:0;background:#F4F6F2;font-family:Arial,sans-serif;color:#1E2A22">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#fff;border-radius:12px;overflow:hidden">
<tr><td style="background:#0F3D2E;padding:22px 26px;color:#fff;font-size:18px;font-weight:700">St. John's College Jos Alumni Election</td></tr>
<tr><td style="height:5px;background:#E7D21C;font-size:0;line-height:0">&nbsp;</td></tr>
<tr><td style="padding:26px">
<p style="margin:0 0 12px;font-size:15px">Dear {html.escape(voter.full_name)},</p>
<p style="margin:0 0 12px;font-size:14px;line-height:1.6">You have been approved on the electoral register for <strong>{html.escape(election.title)}</strong>.</p>
<p style="margin:0 0 18px;font-size:14px">Your Voter ID is <strong style="font-family:Consolas,monospace">{html.escape(voter.voter_id)}</strong>.</p>
<p style="margin:0 0 18px;font-size:14px;line-height:1.6">To accredit, open the accreditation page and enter your Voter ID. If it matches the approved register, you can create your anonymous voting credential and vote.</p>
<p style="margin:0 0 18px"><a href="{html.escape(link)}" style="display:inline-block;background:#0F3D2E;color:#fff;text-decoration:none;padding:11px 18px;border-radius:7px;font-size:14px;font-weight:600">Open accreditation</a></p>
<p style="margin:0;font-size:13px;color:#55635A">Keep this email and your Voter ID private. Officials will never ask for your voting credential.</p>
</td></tr>
<tr><td style="background:#EEF4EC;padding:16px 26px;font-size:11px;color:#55635A">This message never asks for your ballot choices.</td></tr>
</table></td></tr></table></body></html>"""
    return subject, text, html_body


def _registration_sms_body(election: Election, voter: Voter) -> str:
    """The registration summary in one 160-character SMS part.

    SMS has no rich formatting and is billed per part, so this repeats only the
    facts a member needs: they are registered, their Voter ID, and the one link
    that opens accreditation.
    """
    link = f"{settings.app_origin.rstrip('/')}/accredit"
    return (
        f"SJC Alumni Election {election.reference}: registered. "
        f"Voter ID {voter.voter_id}. Accredit: {link}"
    )


def _send_registration_sms(
    voter: Voter, election: Election, destination: str
) -> DeliveryResult:
    try:
        message_id, error = _send_sms(destination, _registration_sms_body(election, voter))
    except Exception as exc:
        message_id, error = None, f"sms delivery unavailable ({type(exc).__name__})"
    return DeliveryResult(
        channel="sms",
        provider=_sms_provider() or "none",
        status="failed" if error else "sent",
        recipient_masked=mask_phone(destination),
        provider_message_id=message_id,
        error=error,
    )


def _send_registration_email(voter: Voter, election: Election) -> DeliveryResult:
    destination = (voter.email or "").strip()
    provider = _email_provider()
    try:
        subject, text, html_body = _registration_email_body(election, voter)
        if provider == "smtp":
            message_id, error = _send_smtp(destination, subject, text, html_body)
        elif provider == "resend":
            message_id, error = _send_resend(destination, subject, text, html_body)
        else:
            message_id, error = None, "email provider is not configured"
    except Exception as exc:
        message_id, error = None, f"email delivery unavailable ({type(exc).__name__})"
    return _email_result(provider, destination, message_id, error)


def _send_smtp_batch(
    prepared: list[tuple[Any, str, EmailMessage]],
    *,
    timeout_seconds: int | None = None,
) -> tuple[list[tuple[DeliveryResult, Any]], int]:
    """Send prepared messages over one authenticated SMTP session.

    Every bulk notification type uses this: one connection, one shared
    connection slot for the whole session, and the app-wide pacer between
    messages, so a 160-voter run neither opens 160 connections nor arrives as a
    burst. The caller caps how many go out in one invocation. If the host
    refuses the connection the run stops there instead of retrying for every
    remaining recipient; those messages are returned as a deferred count so the
    same idempotent action can finish them later.
    """
    results: list[tuple[DeliveryResult, Any]] = []
    deferred = 0
    session = _SmtpSession()
    try:
        # Hold one of the shared connection slots for the whole batch, so a
        # batch running beside an OTP or vote confirmation never pushes the
        # mailbox past SMTP_MAX_CONNECTIONS.
        with _smtp_slots():
            for index, (item, destination, message) in enumerate(prepared):
                if index:
                    _smtp_pace()
                if session.server is None:
                    try:
                        session.connect(timeout_seconds=timeout_seconds)
                    except (smtplib.SMTPException, OSError) as exc:
                        error = f"smtp delivery failed: {type(exc).__name__}"
                        results.append((_email_result("smtp", destination, None, error), item))
                        deferred = len(prepared) - index - 1
                        break
                try:
                    message_id = session.send(message)
                except (smtplib.SMTPException, OSError) as exc:
                    error = f"smtp delivery failed: {type(exc).__name__}"
                    results.append((_email_result("smtp", destination, None, error), item))
                    # The socket may be dead; authenticate again for the next message.
                    session.close()
                    continue
                results.append((_email_result("smtp", destination, message_id, None), item))
    finally:
        session.close()
    return results, deferred


def _send_registration_email_batch(
    voters: list[Voter], election: Election
) -> tuple[list[tuple[DeliveryResult, Voter]], int]:
    """Send registration emails over one authenticated SMTP connection."""
    prepared: list[tuple[Voter, str, EmailMessage]] = []
    for voter in voters:
        destination = (voter.email or "").strip()
        subject, text, html_body = _registration_email_body(election, voter)
        prepared.append(
            (voter, destination, _smtp_message(destination, subject, text, html_body))
        )
    return _send_smtp_batch(prepared)


def _email_result(
    provider: str, destination: str, message_id: str | None, error: str | None
) -> DeliveryResult:
    """The one DeliveryResult shape for every email attempt."""
    return DeliveryResult(
        channel="email",
        provider=provider or "none",
        status="failed" if error else "sent",
        recipient_masked=mask_email(destination),
        provider_message_id=message_id,
        error=error,
    )


def _worker_result(future, channel: str) -> DeliveryResult:
    try:
        return future.result()
    except Exception as exc:
        return DeliveryResult(
            channel=channel,
            provider="unknown",
            status="failed",
            recipient_masked="***",
            error=f"notification worker failed ({type(exc).__name__})",
        )


def send_registration_whatsapp(
    *,
    voter_name: str,
    voter_id: str,
    election_title: str,
    destination: str,
) -> DeliveryResult:
    """Send the approved registration utility template through the provider.

    This is the single payload builder used by register approval and the local
    delivery test, so both send exactly the same template and parameters.
    """
    if settings.whatsapp_provider_key == "termii":
        return _termii_whatsapp_result(
            "registration",
            [voter_name, election_title, voter_id],
            destination,
        )
    to = "".join(ch for ch in destination if ch.isdigit())
    parameters = [
        {"type": "text", "text": voter_name},
        {"type": "text", "text": election_title},
        {"type": "text", "text": voter_id},
    ]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": settings.whatsapp_registration_template_name,
            "language": {"code": settings.whatsapp_registration_template_language},
            "components": [{"type": "body", "parameters": parameters}],
        },
    }
    url = f"{settings.whatsapp_api_base}/{settings.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=settings.otp_delivery_timeout_seconds) as client:
            response = _post_with_retry(client, url, json=payload, headers=headers)
        if response.status_code >= 300:
            message_id, error = None, f"whatsapp provider rejected the message ({response.status_code})"
        else:
            messages = response.json().get("messages") or []
            message_id = str(messages[0].get("id") or "") if messages else ""
            error = None if message_id else "whatsapp provider did not confirm a message id"
    except Exception as exc:
        message_id, error = None, f"whatsapp delivery unavailable ({type(exc).__name__})"
    return DeliveryResult(
        channel="whatsapp",
        provider="meta",
        status="failed" if error else "sent",
        recipient_masked=mask_phone(destination),
        provider_message_id=message_id,
        error=error,
    )


def _send_registration_whatsapp(
    voter: Voter, election: Election, destination: str
) -> DeliveryResult:
    """Registration-notice adapter for the shared WhatsApp payload."""
    return send_registration_whatsapp(
        voter_name=voter.full_name,
        voter_id=voter.voter_id,
        election_title=election.title,
        destination=destination,
    )


def notify_registered_voters(
    db: Session,
    *,
    election: Election,
    voters: list[Voter],
    request_ip: str | None = None,
) -> dict:
    """Send one registration notice per approved voter and channel.

    Email, SMS and WhatsApp are tracked separately and carry the same facts;
    the email is the long form and the SMS/WhatsApp messages are a one-screen
    summary. A channel that already succeeded is not sent again, while a failed
    or unavailable channel can be retried on a later register approval.
    Notifications never block register approval.
    """
    summary = {
        "voters": 0,
        "email_sent": 0,
        "email_failed": 0,
        "email_unavailable": 0,
        "email_already_sent": 0,
        "email_deferred": 0,
        "sms_sent": 0,
        "sms_failed": 0,
        "sms_unavailable": 0,
        "sms_already_sent": 0,
        "whatsapp_sent": 0,
        "whatsapp_failed": 0,
        "whatsapp_unavailable": 0,
        "whatsapp_no_consent": 0,
        "whatsapp_already_sent": 0,
    }
    attempts: list[tuple[str, Voter, str]] = []

    for voter in voters:
        if not voter.is_eligible or voter.register_status != "approved":
            continue
        summary["voters"] += 1

        if voter.registration_email_sent_at:
            summary["email_already_sent"] += 1
        elif not (voter.email or "").strip() or not settings.email_configured:
            summary["email_unavailable"] += 1
        else:
            attempts.append(("email", voter, (voter.email or "").strip()))

        phone = _normalise_phone(voter.phone or "")
        if voter.registration_sms_sent_at:
            summary["sms_already_sent"] += 1
        elif not phone or not settings.sms_configured:
            summary["sms_unavailable"] += 1
        else:
            attempts.append(("sms", voter, phone))

        if voter.registration_whatsapp_sent_at:
            summary["whatsapp_already_sent"] += 1
        elif not voter.whatsapp_consent:
            summary["whatsapp_no_consent"] += 1
        elif not phone or not settings.whatsapp_registration_configured:
            summary["whatsapp_unavailable"] += 1
        else:
            attempts.append(("whatsapp", voter, phone))

    if not attempts:
        return summary

    email_attempts = [
        (voter, destination) for channel, voter, destination in attempts if channel == "email"
    ]
    other_attempts = [attempt for attempt in attempts if attempt[0] != "email"]
    results: list[tuple[str, Voter, DeliveryResult]] = []
    deferred = 0

    if email_attempts:
        if _email_provider() == "smtp":
            # One authenticated connection carries the batch: cPanel counts and
            # throttles connections per mailbox, so reconnecting per recipient is
            # what turned a 160-voter send into a refused burst. The cap keeps a
            # single invocation inside the function's time limit; whatever is left
            # is reported as deferred and sent by the next idempotent run.
            batch = email_attempts[: max(1, settings.smtp_batch_size)]
            deferred = len(email_attempts) - len(batch)
            if batch:
                batch_results, refused_by_host = _send_registration_email_batch(
                    [voter for voter, _ in batch], election
                )
                deferred += refused_by_host
                results.extend(("email", voter, result) for result, voter in batch_results)
        else:
            with ThreadPoolExecutor(max_workers=min(8, len(email_attempts))) as executor:
                futures = {
                    executor.submit(_send_registration_email, voter, election): voter
                    for voter, _ in email_attempts
                }
                for future, voter in futures.items():
                    results.append(("email", voter, _worker_result(future, "email")))

    if other_attempts:
        with ThreadPoolExecutor(max_workers=min(8, len(other_attempts))) as executor:
            futures = {}
            for channel, voter, destination in other_attempts:
                if channel == "sms":
                    futures[executor.submit(_send_registration_sms, voter, election, destination)] = (
                        channel,
                        voter,
                    )
                else:
                    futures[
                        executor.submit(_send_registration_whatsapp, voter, election, destination)
                    ] = (channel, voter)
            for future, (channel, voter) in futures.items():
                results.append((channel, voter, _worker_result(future, channel)))

    summary["email_deferred"] = deferred
    for channel, voter, result in results:
        if result.status == "sent":
            summary[f"{channel}_sent"] += 1
            if channel == "email":
                voter.registration_email_sent_at = now()
            elif channel == "sms":
                voter.registration_sms_sent_at = now()
            else:
                voter.registration_whatsapp_sent_at = now()
        else:
            summary[f"{channel}_failed"] += 1
        db.add(
            NotificationDelivery(
                election_id=election.id,
                voter_row_id=voter.id,
                challenge_id=None,
                purpose="registration",
                channel=result.channel,
                provider=result.provider,
                status=result.status,
                recipient_masked=result.recipient_masked,
                provider_message_id=result.provider_message_id,
                error=(result.error or "")[:300] or None,
                request_ip=request_ip,
            )
        )
    db.commit()
    return summary


def resend_registration_email(
    db: Session,
    *,
    election: Election,
    voter: Voter,
    request_ip: str | None = None,
) -> DeliveryResult:
    """Send one voter's registration email again, even if a notice went out before.

    A member may have missed the notice — spam, a full mailbox, or a host
    refusal during a batch — and the register cannot be re-approved once voting
    starts. This sends only that voter's email, over the same paced SMTP path a
    batch uses, records the attempt, and refreshes the sent timestamp only when
    the provider confirmed the message.
    """
    destination = (voter.email or "").strip()
    if not destination:
        return _email_result(
            _email_provider(), "", None, "no email address is registered for this voter"
        )
    if not settings.email_configured:
        return _email_result(
            _email_provider(), destination, None, "email delivery is not configured"
        )
    result = _send_registration_email(voter, election)
    if result.status == "sent":
        voter.registration_email_sent_at = now()
    db.add(
        NotificationDelivery(
            election_id=election.id,
            voter_row_id=voter.id,
            challenge_id=None,
            purpose="registration",
            channel=result.channel,
            provider=result.provider,
            status=result.status,
            recipient_masked=result.recipient_masked,
            provider_message_id=result.provider_message_id,
            error=(result.error or "")[:300] or None,
            request_ip=request_ip,
        )
    )
    db.commit()
    return result


# ── vote-submitted confirmations ──────────────────────────────────────────────
def _vote_submitted_label(election: Election, submitted_at: datetime) -> str:
    """Render the submission time in the election's configured timezone."""
    moment = submitted_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        local = moment.astimezone(ZoneInfo(election.timezone or "Africa/Lagos"))
    except Exception:
        local = moment.astimezone(timezone.utc)
        return local.strftime("%d %b %Y at %I:%M %p UTC")
    return local.strftime("%d %b %Y at %I:%M %p %Z")


def _vote_confirmation_email_body(
    *,
    election_title: str,
    election_reference: str,
    voter_name: str,
    voter_id: str,
    submitted_label: str,
) -> tuple[str, str, str]:
    subject = f"Your ballot was submitted successfully — {election_reference}"
    text = (
        f"Dear {voter_name},\n\n"
        f"Your ballot for {election_title} was received and submitted successfully at "
        f"{submitted_label}.\n\n"
        f"Your vote has been recorded. This confirmation does not include your candidate "
        f"selections.\n\n"
        f"Election reference: {election_reference}\n"
        f"Voter ID: {voter_id}\n\n"
        f"If you did not submit this ballot, contact the Electoral Committee immediately.\n\n"
        f"St. John's College Jos Alumni Election"
    )
    html_body = f"""<!doctype html><html><body style="margin:0;background:#F4F6F2;font-family:Arial,sans-serif;color:#1E2A22">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#fff;border-radius:12px;overflow:hidden">
<tr><td style="background:#0F3D2E;padding:22px 26px;color:#fff;font-size:18px;font-weight:700">St. John's College Jos Alumni Election</td></tr>
<tr><td style="height:5px;background:#E7D21C;font-size:0;line-height:0">&nbsp;</td></tr>
<tr><td style="padding:26px">
<p style="margin:0 0 12px;font-size:15px">Dear {html.escape(voter_name)},</p>
<p style="margin:0 0 12px;font-size:14px;line-height:1.6">Your ballot for <strong>{html.escape(election_title)}</strong> was received and submitted successfully at <strong>{html.escape(submitted_label)}</strong>.</p>
<p style="margin:0 0 18px;font-size:14px;line-height:1.6">Your vote has been recorded. This confirmation does not include your candidate selections.</p>
<p style="margin:0 0 18px;font-size:13px;color:#55635A">Election reference: {html.escape(election_reference)}<br>Voter ID: {html.escape(voter_id)}</p>
<p style="margin:0;font-size:13px;color:#55635A">If you did not submit this ballot, contact the Electoral Committee immediately.</p>
</td></tr>
<tr><td style="background:#EEF4EC;padding:16px 26px;font-size:11px;color:#55635A">This message never contains or reveals your ballot choices.</td></tr>
</table></td></tr></table></body></html>"""
    return subject, text, html_body


def _send_vote_confirmation_email(
    destination: str,
    *,
    election_title: str,
    election_reference: str,
    voter_name: str,
    voter_id: str,
    submitted_label: str,
) -> DeliveryResult:
    provider = _email_provider()
    try:
        subject, text, html_body = _vote_confirmation_email_body(
            election_title=election_title,
            election_reference=election_reference,
            voter_name=voter_name,
            voter_id=voter_id,
            submitted_label=submitted_label,
        )
        if provider == "smtp":
            message_id, error = _send_smtp(
                destination,
                subject,
                text,
                html_body,
                timeout_seconds=settings.vote_confirmation_timeout_seconds,
            )
        elif provider == "resend":
            message_id, error = _send_resend(
                destination,
                subject,
                text,
                html_body,
                timeout_seconds=settings.vote_confirmation_timeout_seconds,
                attempts=1,
            )
        else:
            message_id, error = None, "email provider is not configured"
    except Exception as exc:
        message_id, error = None, f"email delivery unavailable ({type(exc).__name__})"
    return _email_result(provider, destination, message_id, error)


def send_vote_confirmation_whatsapp(
    *,
    voter_name: str,
    election_title: str,
    submitted_label: str,
    destination: str,
) -> DeliveryResult:
    """Send the approved vote-confirmation utility template through the provider."""
    if settings.whatsapp_provider_key == "termii":
        return _termii_whatsapp_result(
            "vote_confirmation",
            [voter_name, election_title, submitted_label],
            destination,
            timeout_seconds=settings.vote_confirmation_timeout_seconds,
            attempts=1,
        )
    to = "".join(ch for ch in destination if ch.isdigit())
    parameters = [
        {"type": "text", "text": voter_name},
        {"type": "text", "text": election_title},
        {"type": "text", "text": submitted_label},
    ]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": settings.whatsapp_vote_confirmation_template_name,
            "language": {"code": settings.whatsapp_vote_confirmation_template_language},
            "components": [{"type": "body", "parameters": parameters}],
        },
    }
    url = f"{settings.whatsapp_api_base}/{settings.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=settings.vote_confirmation_timeout_seconds) as client:
            response = _post_with_retry(
                client, url, attempts=1, json=payload, headers=headers
            )
        if response.status_code >= 300:
            message_id, error = None, f"whatsapp provider rejected the message ({response.status_code})"
        else:
            messages = response.json().get("messages") or []
            message_id = str(messages[0].get("id") or "") if messages else ""
            error = None if message_id else "whatsapp provider did not confirm a message id"
    except Exception as exc:
        message_id, error = None, f"whatsapp delivery unavailable ({type(exc).__name__})"
    return DeliveryResult(
        channel="whatsapp",
        provider="meta",
        status="failed" if error else "sent",
        recipient_masked=mask_phone(destination),
        provider_message_id=message_id,
        error=error,
    )


def _vote_confirmation_sms_body(
    *, election_reference: str, submitted_label: str
) -> str:
    """The submission confirmation in one SMS part, without ballot choices."""
    return (
        f"SJC {election_reference}: your ballot was received at {submitted_label}. "
        f"Your vote is recorded."
    )


def send_vote_confirmation_sms(
    *,
    election_reference: str,
    submitted_label: str,
    destination: str,
) -> DeliveryResult:
    try:
        message_id, error = _send_sms(
            destination,
            _vote_confirmation_sms_body(
                election_reference=election_reference, submitted_label=submitted_label
            ),
            timeout_seconds=settings.vote_confirmation_timeout_seconds,
        )
    except Exception as exc:
        message_id, error = None, f"sms delivery unavailable ({type(exc).__name__})"
    return DeliveryResult(
        channel="sms",
        provider=_sms_provider() or "none",
        status="failed" if error else "sent",
        recipient_masked=mask_phone(destination),
        provider_message_id=message_id,
        error=error,
    )


def notify_vote_submitted(
    db: Session,
    *,
    election: Election,
    voter: Voter,
    submitted_at: datetime,
    request_ip: str | None = None,
) -> dict:
    """Confirm an accepted ballot by email, SMS and WhatsApp without choices.

    The ballot has already been committed when this runs. Delivery failure is
    recorded but never rolls back or invalidates the vote. WhatsApp requires a
    recorded opt-in; email and SMS use the contacts on the approved register.
    """
    summary = {
        "email_sent": 0,
        "email_failed": 0,
        "email_unavailable": 0,
        "sms_sent": 0,
        "sms_failed": 0,
        "sms_unavailable": 0,
        "whatsapp_sent": 0,
        "whatsapp_failed": 0,
        "whatsapp_unavailable": 0,
        "whatsapp_no_consent": 0,
    }
    voter_row_id = voter.id
    voter_name = voter.full_name
    voter_id = voter.voter_id
    email = (voter.email or "").strip()
    phone = _normalise_phone(voter.phone or "")
    submitted_label = _vote_submitted_label(election, submitted_at)
    attempts: list[tuple[str, str]] = []

    if not email or not settings.email_configured:
        summary["email_unavailable"] += 1
    else:
        attempts.append(("email", email))

    if not phone or not settings.sms_configured:
        summary["sms_unavailable"] += 1
    else:
        attempts.append(("sms", phone))

    if not voter.whatsapp_consent:
        summary["whatsapp_no_consent"] += 1
    elif not phone or not settings.whatsapp_vote_confirmation_configured:
        summary["whatsapp_unavailable"] += 1
    else:
        attempts.append(("whatsapp", phone))

    if not attempts:
        return summary

    with ThreadPoolExecutor(max_workers=len(attempts)) as executor:
        futures = {}
        for channel, destination in attempts:
            if channel == "email":
                futures[
                    executor.submit(
                        _send_vote_confirmation_email,
                        destination,
                        election_title=election.title,
                        election_reference=election.reference,
                        voter_name=voter_name,
                        voter_id=voter_id,
                        submitted_label=submitted_label,
                    )
                ] = channel
            elif channel == "sms":
                futures[
                    executor.submit(
                        send_vote_confirmation_sms,
                        election_reference=election.reference,
                        submitted_label=submitted_label,
                        destination=destination,
                    )
                ] = channel
            else:
                futures[
                    executor.submit(
                        send_vote_confirmation_whatsapp,
                        voter_name=voter_name,
                        election_title=election.title,
                        submitted_label=submitted_label,
                        destination=destination,
                    )
                ] = channel
        for future, channel in futures.items():
            try:
                result = future.result()
            except Exception as exc:
                result = DeliveryResult(
                    channel=channel,
                    provider="unknown",
                    status="failed",
                    recipient_masked="***",
                    error=f"notification worker failed ({type(exc).__name__})",
                )
            if result.status == "sent":
                summary[f"{channel}_sent"] += 1
            else:
                summary[f"{channel}_failed"] += 1
            db.add(
                NotificationDelivery(
                    election_id=election.id,
                    voter_row_id=voter_row_id,
                    challenge_id=None,
                    purpose="vote_confirmation",
                    channel=result.channel,
                    provider=result.provider,
                    status=result.status,
                    recipient_masked=result.recipient_masked,
                    provider_message_id=result.provider_message_id,
                    error=(result.error or "")[:300] or None,
                    request_ip=request_ip,
                )
            )
    db.commit()
    return summary


def notify_vote_submitted_by_id(
    *,
    election_id: str,
    voter_id: str,
    submitted_at: datetime,
    request_ip: str | None = None,
) -> None:
    """Background entry point for post-cast confirmations.

    FastAPI runs this after the cast response has been sent. A fresh session is
    used because the request-scoped session is closed when the route returns;
    provider errors are swallowed here so they cannot affect the voter's cast.
    """
    db = SessionLocal()
    try:
        election = db.get(Election, election_id)
        voter = db.get(Voter, voter_id)
        if not election or not voter:
            return
        notify_vote_submitted(
            db,
            election=election,
            voter=voter,
            submitted_at=submitted_at,
            request_ip=request_ip,
        )
    except Exception:
        db.rollback()
    finally:
        db.close()


# ── declared results ────────────────────────────────────────────────────────
def _vote_label(count: int) -> str:
    return f"{count} vote" if count == 1 else f"{count} votes"


def _name_list(names: list[str]) -> str:
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _result_lines(figures: dict) -> list[tuple[str, str]]:
    """One readable line per position: the declared outcome, with no name repeated.

    A tie at the available seats is stated as a tie and names the tied
    candidates. It is never rendered as "no candidate returned", which would
    misstate an official result, and a candidate is named once per line.
    """
    lines: list[tuple[str, str]] = []
    for position in figures.get("positions") or []:
        title = str(position.get("title") or "Position")
        entries = [
            {
                "index": index,
                "name": str(entry.get("full_name") or "Candidate"),
                "votes": int(entry.get("votes") or 0),
            }
            for index, entry in enumerate(position.get("candidates") or [])
        ]
        if not entries:
            lines.append((title, "No candidates stood for this position."))
            continue

        ranked = sorted(entries, key=lambda entry: entry["votes"], reverse=True)
        seats = max(int(position.get("seats") or 1), 1)
        if not any(entry["votes"] > 0 for entry in ranked):
            lines.append((title, "No votes were cast for this position."))
            continue

        # The last available seat sets the winning bar. A group level with more
        # candidates than seats left is an unresolved tie, never a silent win.
        cutoff = ranked[min(seats, len(ranked)) - 1]["votes"]
        elected = [entry for entry in ranked if entry["votes"] > cutoff]
        contested = [entry for entry in ranked if entry["votes"] == cutoff]
        remaining = seats - len(elected)
        named = list(elected)

        if cutoff > 0 and len(contested) > remaining:
            tie_names = _name_list([entry["name"] for entry in contested])
            if elected:
                summary = "Elected: " + ", ".join(
                    f"{entry['name']} ({_vote_label(entry['votes'])})" for entry in elected
                )
                summary += (
                    f". Tie for the remaining {'seat' if remaining == 1 else 'seats'}: "
                    f"{tie_names} on {_vote_label(cutoff)} each - no winner returned."
                )
                named = elected + contested
            else:
                summary = f"Tie: {tie_names} on {_vote_label(cutoff)} each - no winner returned."
                named = contested
        else:
            winners = (elected + contested if cutoff > 0 else elected)[:seats]
            if len(winners) == 1:
                summary = (
                    f"{winners[0]['name']} elected with {_vote_label(winners[0]['votes'])}."
                )
            else:
                summary = "Elected: " + ", ".join(
                    f"{entry['name']} ({_vote_label(entry['votes'])})" for entry in winners
                ) + "."
            named = winners

        named_indexes = {entry["index"] for entry in named}
        others = [entry for entry in entries if entry["index"] not in named_indexes]
        if others:
            summary += " Others: " + "; ".join(
                f"{entry['name']} {entry['votes']}" for entry in others
            ) + "."
        lines.append((title, summary))
    return lines


def _results_email_body(
    *,
    election_title: str,
    election_reference: str,
    voter_name: str,
    declared_label: str,
    version: int,
    results_url: str,
    lines: list[tuple[str, str]],
    totals: dict,
) -> tuple[str, str, str]:
    """Declared-result notice. It reports only official published figures."""
    subject = f"Official results declared - {election_reference}"
    totals_text = (
        f"Votes cast: {totals.get('valid_ballots', 0)} valid of "
        f"{totals.get('eligible_voters', 0)} eligible voters "
        f"({totals.get('turnout_percentage', 0)}% turnout)."
    )
    text_lines = "\n".join(f"{title}: {summary}" for title, summary in lines) or "No positions."
    text = (
        f"Dear {voter_name},\n\n"
        f"The Electoral Committee has declared the official results of {election_title} "
        f"({election_reference}) on {declared_label}. This is declaration version {version}.\n\n"
        f"{text_lines}\n\n"
        f"{totals_text}\n\n"
        f"The declaration is digitally signed and published at {results_url}\n\n"
        f"St. John's College Jos Alumni Election"
    )
    rows = "".join(
        f'<tr><td style="padding:8px 10px;border-bottom:1px solid #E4EBE1;font-size:13px;'
        f'vertical-align:top"><strong>{html.escape(title)}</strong></td>'
        f'<td style="padding:8px 10px;border-bottom:1px solid #E4EBE1;font-size:13px">'
        f"{html.escape(summary)}</td></tr>"
        for title, summary in lines
    )
    html_body = f"""<!doctype html><html><body style="margin:0;background:#F4F6F2;font-family:Arial,sans-serif;color:#1E2A22">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:#fff;border-radius:12px;overflow:hidden">
<tr><td style="background:#0F3D2E;padding:22px 26px;color:#fff;font-size:18px;font-weight:700">St. John's College Jos Alumni Election</td></tr>
<tr><td style="height:5px;background:#E7D21C;font-size:0;line-height:0">&nbsp;</td></tr>
<tr><td style="padding:26px">
<p style="margin:0 0 12px;font-size:15px">Dear {html.escape(voter_name)},</p>
<p style="margin:0 0 18px;font-size:14px;line-height:1.6">The Electoral Committee has declared the official results of <strong>{html.escape(election_title)}</strong> ({html.escape(election_reference)}) on {html.escape(declared_label)}. This is declaration version {version}.</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #E4EBE1;border-radius:8px;overflow:hidden">{rows}</table>
<p style="margin:18px 0 0;font-size:13px;color:#55635A">{html.escape(totals_text)}</p>
<p style="margin:18px 0 0"><a href="{html.escape(results_url)}" style="display:inline-block;background:#0F3D2E;color:#fff;text-decoration:none;padding:11px 18px;border-radius:7px;font-size:14px;font-weight:600">View the signed declaration</a></p>
<p style="margin:16px 0 0;font-size:13px;color:#55635A">Every declared version is preserved with its signature. This message contains no record of how any individual voted.</p>
</td></tr>
<tr><td style="background:#EEF4EC;padding:16px 26px;font-size:11px;color:#55635A">Published results only. Individual ballots are never disclosed.</td></tr>
</table></td></tr></table></body></html>"""
    return subject, text, html_body


def _send_results_email(
    destination: str,
    *,
    election_title: str,
    election_reference: str,
    voter_name: str,
    declared_label: str,
    version: int,
    results_url: str,
    lines: list[tuple[str, str]],
    totals: dict,
) -> DeliveryResult:
    provider = _email_provider()
    try:
        subject, text, html_body = _results_email_body(
            election_title=election_title,
            election_reference=election_reference,
            voter_name=voter_name,
            declared_label=declared_label,
            version=version,
            results_url=results_url,
            lines=lines,
            totals=totals,
        )
        if provider == "smtp":
            message_id, error = _send_smtp(
                destination, subject, text, html_body,
                timeout_seconds=settings.vote_confirmation_timeout_seconds,
            )
        elif provider == "resend":
            message_id, error = _send_resend(
                destination, subject, text, html_body,
                timeout_seconds=settings.vote_confirmation_timeout_seconds,
                attempts=1,
            )
        else:
            message_id, error = None, "email provider is not configured"
    except Exception as exc:
        message_id, error = None, f"email delivery unavailable ({type(exc).__name__})"
    return _email_result(provider, destination, message_id, error)


def _send_results_email_batch(
    recipients: list[tuple[Voter, str]],
    *,
    election_title: str,
    election_reference: str,
    declared_label: str,
    version: int,
    results_url: str,
    lines: list[tuple[str, str]],
    totals: dict,
) -> tuple[list[tuple[DeliveryResult, Voter]], int]:
    """Send declared-result emails over one authenticated SMTP connection."""
    prepared: list[tuple[Voter, str, EmailMessage]] = []
    for voter, destination in recipients:
        subject, text, html_body = _results_email_body(
            election_title=election_title,
            election_reference=election_reference,
            voter_name=voter.full_name,
            declared_label=declared_label,
            version=version,
            results_url=results_url,
            lines=lines,
            totals=totals,
        )
        prepared.append(
            (voter, destination, _smtp_message(destination, subject, text, html_body))
        )
    return _send_smtp_batch(
        prepared, timeout_seconds=settings.vote_confirmation_timeout_seconds
    )


def _results_sms_body(election_reference: str, results_url: str) -> str:
    """The declared-result summary in one SMS part.

    The full figures are too long for SMS and would cost several parts, so the
    summary states the fact and links to the signed, published declaration.
    """
    return (
        f"SJC {election_reference}: official results declared. "
        f"Signed declaration: {results_url}"
    )


def send_results_sms(
    *, election_reference: str, results_url: str, destination: str
) -> DeliveryResult:
    try:
        message_id, error = _send_sms(
            destination,
            _results_sms_body(election_reference, results_url),
            timeout_seconds=settings.vote_confirmation_timeout_seconds,
        )
    except Exception as exc:
        message_id, error = None, f"sms delivery unavailable ({type(exc).__name__})"
    return DeliveryResult(
        channel="sms",
        provider=_sms_provider() or "none",
        status="failed" if error else "sent",
        recipient_masked=mask_phone(destination),
        provider_message_id=message_id,
        error=error,
    )


def send_results_whatsapp(
    *,
    voter_name: str,
    election_title: str,
    results_url: str,
    destination: str,
) -> DeliveryResult:
    """Send the approved results utility template through the provider.

    Parameters: first voter name, second election title, third results link. The
    full figures stay on the published declaration page.
    """
    if settings.whatsapp_provider_key == "termii":
        return _termii_whatsapp_result(
            "results",
            [voter_name, election_title, results_url],
            destination,
            timeout_seconds=settings.vote_confirmation_timeout_seconds,
            attempts=1,
        )
    to = "".join(ch for ch in destination if ch.isdigit())
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": settings.whatsapp_results_template_name,
            "language": {"code": settings.whatsapp_results_template_language},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": voter_name},
                        {"type": "text", "text": election_title},
                        {"type": "text", "text": results_url},
                    ],
                }
            ],
        },
    }
    url = f"{settings.whatsapp_api_base}/{settings.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=settings.vote_confirmation_timeout_seconds) as client:
            response = _post_with_retry(client, url, attempts=1, json=payload, headers=headers)
        if response.status_code >= 300:
            message_id, error = None, f"whatsapp provider rejected the message ({response.status_code})"
        else:
            messages = response.json().get("messages") or []
            message_id = str(messages[0].get("id") or "") if messages else ""
            error = None if message_id else "whatsapp provider did not confirm a message id"
    except Exception as exc:
        message_id, error = None, f"whatsapp delivery unavailable ({type(exc).__name__})"
    return DeliveryResult(
        channel="whatsapp",
        provider="meta",
        status="failed" if error else "sent",
        recipient_masked=mask_phone(destination),
        provider_message_id=message_id,
        error=error,
    )


def notify_results_declared(
    db: Session,
    *,
    election: Election,
    figures: dict,
    declared_at: datetime,
    version: int,
    request_ip: str | None = None,
    skip_delivered: bool = False,
) -> dict:
    """Send the declared result to every approved voter on every channel.

    The email carries the published figures; SMS and WhatsApp carry a one-screen
    summary that links to the signed declaration, because both are length-limited.
    The declaration is already committed when this runs, so a slow or failing
    provider can never roll it back. Each voter receives an individual message
    (never a shared recipient list) containing only the official public figures.

    Results go to the whole register at once, so email uses the same discipline
    as registration notices: one authenticated SMTP session for the batch, the
    app-wide pacer between messages, and at most SMTP_BATCH_SIZE emails per
    invocation. Any remainder is reported as `email_deferred` and finished by
    the retry action, which passes `skip_delivered=True` so a voter who already
    received the result is never emailed twice.
    """
    summary = {
        "voters": 0,
        "email_sent": 0,
        "email_failed": 0,
        "email_unavailable": 0,
        "email_already_sent": 0,
        "email_deferred": 0,
        "sms_sent": 0,
        "sms_failed": 0,
        "sms_unavailable": 0,
        "whatsapp_sent": 0,
        "whatsapp_failed": 0,
        "whatsapp_unavailable": 0,
        "whatsapp_no_consent": 0,
    }
    voters = db.execute(
        select(Voter).where(
            Voter.election_id == election.id,
            Voter.is_eligible.is_(True),
            Voter.register_status == "approved",
        ).order_by(Voter.full_name)
    ).scalars().all()
    summary["voters"] = len(voters)
    already_emailed: set[str] = set()
    if skip_delivered:
        # A successful email delivery row is the record that this voter already
        # has the declared result, so a retry only reaches the ones still missing it.
        already_emailed = {
            row
            for row in db.execute(
                select(NotificationDelivery.voter_row_id).where(
                    NotificationDelivery.election_id == election.id,
                    NotificationDelivery.purpose == "results_declared",
                    NotificationDelivery.channel == "email",
                    NotificationDelivery.status == "sent",
                )
            ).scalars()
            if row
        }
    lines = _result_lines(figures)
    totals = figures.get("totals") or {}
    declared_label = _vote_submitted_label(election, declared_at)
    results_url = f"{settings.app_origin.rstrip('/')}/results"

    seen_email: set[str] = set()
    seen_phone: set[str] = set()
    seen_whatsapp: set[str] = set()
    attempts: list[tuple[str, Voter, str]] = []
    for voter in voters:
        email = (voter.email or "").strip()
        if not email or not settings.email_configured or email.lower() in seen_email:
            summary["email_unavailable"] += 1
        else:
            # The address counts as seen even when this voter already has the
            # result, so a duplicate on the register never gets a second copy.
            seen_email.add(email.lower())
            if voter.id in already_emailed:
                summary["email_already_sent"] += 1
            else:
                attempts.append(("email", voter, email))

        phone = _normalise_phone(voter.phone or "")
        if not phone or not settings.sms_configured or phone in seen_phone:
            summary["sms_unavailable"] += 1
        else:
            seen_phone.add(phone)
            attempts.append(("sms", voter, phone))

        if not phone:
            summary["whatsapp_unavailable"] += 1
        elif not voter.whatsapp_consent:
            summary["whatsapp_no_consent"] += 1
        elif not settings.whatsapp_results_configured or phone in seen_whatsapp:
            summary["whatsapp_unavailable"] += 1
        else:
            seen_whatsapp.add(phone)
            attempts.append(("whatsapp", voter, phone))

    if not attempts:
        return summary

    email_attempts = [
        (voter, destination) for channel, voter, destination in attempts if channel == "email"
    ]
    other_attempts = [attempt for attempt in attempts if attempt[0] != "email"]
    results: list[tuple[str, Voter, DeliveryResult]] = []
    deferred = 0

    if email_attempts:
        if _email_provider() == "smtp":
            # Declaring results emails the whole register at once: one
            # authenticated session, the shared pacer, and a cap per invocation.
            batch = email_attempts[: max(1, settings.smtp_batch_size)]
            deferred = len(email_attempts) - len(batch)
            if batch:
                batch_results, refused_by_host = _send_results_email_batch(
                    batch,
                    election_title=election.title,
                    election_reference=election.reference,
                    declared_label=declared_label,
                    version=version,
                    results_url=results_url,
                    lines=lines,
                    totals=totals,
                )
                deferred += refused_by_host
                results.extend(("email", voter, result) for result, voter in batch_results)
        else:
            with ThreadPoolExecutor(max_workers=min(8, len(email_attempts))) as executor:
                futures = {
                    executor.submit(
                        _send_results_email,
                        destination,
                        election_title=election.title,
                        election_reference=election.reference,
                        voter_name=voter.full_name,
                        declared_label=declared_label,
                        version=version,
                        results_url=results_url,
                        lines=lines,
                        totals=totals,
                    ): voter
                    for voter, destination in email_attempts
                }
                for future, voter in futures.items():
                    results.append(("email", voter, _worker_result(future, "email")))

    if other_attempts:
        with ThreadPoolExecutor(max_workers=min(8, len(other_attempts))) as executor:
            futures = {}
            for channel, voter, destination in other_attempts:
                if channel == "sms":
                    futures[
                        executor.submit(
                            send_results_sms,
                            election_reference=election.reference,
                            results_url=results_url,
                            destination=destination,
                        )
                    ] = (channel, voter)
                else:
                    futures[
                        executor.submit(
                            send_results_whatsapp,
                            voter_name=voter.full_name,
                            election_title=election.title,
                            results_url=results_url,
                            destination=destination,
                        )
                    ] = (channel, voter)
            for future, (channel, voter) in futures.items():
                results.append((channel, voter, _worker_result(future, channel)))

    summary["email_deferred"] = deferred
    for channel, voter, result in results:
        if result.status == "sent":
            summary[f"{channel}_sent"] += 1
        else:
            summary[f"{channel}_failed"] += 1
        db.add(
            NotificationDelivery(
                election_id=election.id,
                voter_row_id=voter.id,
                challenge_id=None,
                purpose="results_declared",
                channel=result.channel,
                provider=result.provider,
                status=result.status,
                recipient_masked=result.recipient_masked,
                provider_message_id=result.provider_message_id,
                error=(result.error or "")[:300] or None,
                request_ip=request_ip,
            )
        )
    db.commit()
    return summary


# ── entry point ─────────────────────────────────────────────────────────────
def _destination_for(voter: Voter, channel: str) -> str | None:
    if channel == "email":
        return voter.email.strip() if voter.email else None
    if channel in {"sms", "whatsapp"}:
        return _normalise_phone(voter.phone or "")
    return "development" if channel == "development" else None


def _attempt_delivery(
    option: ChannelOption,
    *,
    destination: str,
    otp: str,
    subject: str,
    email_text: str,
    email_html: str,
    sms_text: str,
) -> DeliveryResult:
    """Provider call only; this function has no database session and is thread-safe."""
    if option.channel == "email":
        try:
            if option.provider == "smtp":
                message_id, error = _send_smtp(destination, subject, email_text, email_html)
            else:
                message_id, error = _send_resend(destination, subject, email_text, email_html)
        except Exception as exc:
            message_id, error = None, f"email delivery unavailable ({type(exc).__name__})"
        return DeliveryResult(
            channel="email",
            provider=option.provider,
            status="failed" if error else "sent",
            recipient_masked=option.destination_masked,
            provider_message_id=message_id,
            error=error,
        )
    if option.channel == "sms":
        try:
            if option.provider == "termii":
                message_id, error = _send_termii(destination, sms_text)
            else:
                message_id, error = _send_twilio(destination, sms_text)
        except Exception as exc:
            message_id, error = None, f"sms delivery unavailable ({type(exc).__name__})"
        return DeliveryResult(
            channel="sms",
            provider=option.provider,
            status="failed" if error else "sent",
            recipient_masked=option.destination_masked,
            provider_message_id=message_id,
            error=error,
        )
    if option.channel == "whatsapp":
        try:
            message_id, error = _send_whatsapp(destination, otp)
        except Exception as exc:
            message_id, error = None, f"whatsapp delivery unavailable ({type(exc).__name__})"
        return DeliveryResult(
            channel="whatsapp",
            provider="meta",
            status="failed" if error else "sent",
            recipient_masked=option.destination_masked,
            provider_message_id=message_id,
            error=error,
        )
    # Local development only: the OTP is displayed to the voter on screen.
    return DeliveryResult(
        channel="development",
        provider="on-screen",
        status="skipped",
        recipient_masked="This screen",
    )


def deliver_otp_all(
    db: Session,
    *,
    election: Election,
    voter: Voter,
    otp: str,
    challenge_id: str,
    request_ip: str | None = None,
) -> list[DeliveryResult]:
    """Attempt the same OTP on every available registered channel concurrently.

    One provider failure is isolated: the remaining provider calls are still
    completed and their confirmed results are returned. The caller decides
    whether at least one confirmed delivery permits the challenge to remain
    usable.
    """
    options = channel_options(voter)
    subject, email_text, email_html = _email_body(election, otp)
    sms_text = _sms_body(election, otp)
    results: list[DeliveryResult | None] = [None] * len(options)
    attempts: list[tuple[int, ChannelOption, str]] = []

    for index, option in enumerate(options):
        if not option.available:
            results[index] = DeliveryResult(
                channel=option.channel,
                provider=option.provider,
                status="unavailable",
                recipient_masked=option.destination_masked,
                error=option.reason,
            )
            continue
        if option.channel == "development":
            results[index] = DeliveryResult(
                channel="development",
                provider="on-screen",
                status="skipped",
                recipient_masked="This screen",
            )
            continue
        destination = _destination_for(voter, option.channel)
        if not destination:
            results[index] = DeliveryResult(
                channel=option.channel,
                provider=option.provider,
                status="unavailable",
                recipient_masked=option.destination_masked,
                error="No registered destination is available for this channel.",
            )
            continue
        attempts.append((index, option, destination))

    if attempts:
        with ThreadPoolExecutor(max_workers=len(attempts)) as executor:
            futures = {
                executor.submit(
                    _attempt_delivery,
                    option,
                    destination=destination,
                    otp=otp,
                    subject=subject,
                    email_text=email_text,
                    email_html=email_html,
                    sms_text=sms_text,
                ): index
                for index, option, destination in attempts
            }
            for future, index in futures.items():
                try:
                    results[index] = future.result()
                except Exception as exc:  # defensive: a worker must not cancel peers
                    option = options[index]
                    results[index] = DeliveryResult(
                        channel=option.channel,
                        provider=option.provider,
                        status="failed",
                        recipient_masked=option.destination_masked,
                        error=f"delivery worker failed ({type(exc).__name__})",
                    )

    final_results = [result for result in results if result is not None]
    for result in final_results:
        if result.status == "unavailable":
            continue
        db.add(
            NotificationDelivery(
                election_id=election.id,
                voter_row_id=voter.id,
                challenge_id=challenge_id,
                purpose="otp",
                channel=result.channel,
                provider=result.provider,
                status=result.status,
                recipient_masked=result.recipient_masked,
                provider_message_id=result.provider_message_id,
                error=(result.error or "")[:300] or None,
                request_ip=request_ip,
            )
        )
    return final_results
