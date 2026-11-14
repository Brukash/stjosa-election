"""OTP delivery over email (Resend or SMTP) and SMS (Twilio).

Security rules enforced here:
  * The OTP is sent to the contact on the approved register, never to a value
    supplied by the caller.
  * The OTP is never logged and never written to the database; only a masked
    recipient, provider message id and failure reason are recorded.
  * Outside local development the OTP is never returned by the API. If no
    delivery channel is configured, the request fails instead of revealing it.
  * Delivery failures never expose the OTP or provider credentials.
"""
from __future__ import annotations

import base64
import html
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import Election, NotificationDelivery, Voter

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass
class DeliveryResult:
    channel: str          # email | sms | development
    provider: str         # resend | smtp | twilio | on-screen | none
    status: str           # sent | failed | skipped
    recipient_masked: str
    provider_message_id: str | None = None
    error: str | None = None

    @property
    def delivered(self) -> bool:
        return self.status in {"sent", "skipped"}


def mask_email(value: str) -> str:
    local, _, domain = value.partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


def mask_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 5:
        return "***"
    return f"+{digits[:3]}***{digits[-2:]}"


def _normalise_phone(value: str) -> str | None:
    raw = value.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if not raw.startswith("+") or not raw[1:].isdigit() or len(raw) < 8:
        return None
    return raw


def choose_channel(voter: Voter) -> tuple[str, str, str] | None:
    """Return (channel, provider, destination) for the voter's registered contact.

    Email is preferred; SMS is used when no email channel is configured or the
    voter has no email address. Development on-screen display is a last resort
    available only on a local development deployment.
    """
    if voter.email and settings.email_configured:
        return ("email", settings.email_provider.strip().lower(), voter.email.strip())
    if voter.phone and settings.sms_configured:
        phone = _normalise_phone(voter.phone)
        if phone:
            return ("sms", "twilio", phone)
    if settings.expose_dev_otp:
        return ("development", "on-screen", mask_email(voter.email) if voter.email else mask_phone(voter.phone or ""))
    return None


def delivery_available(voter: Voter) -> bool:
    return choose_channel(voter) is not None


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
        f"If you did not request this password, do not share it. Report the request to the "
        f"Electoral Committee at accreditation@sjcjos-alumni.org.\n"
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
          <p style="margin:14px 0 0;font-size:13px;color:#55635A">
            If you did not request this password, do not share it. Report the request to the Electoral Committee.
          </p>
        </td></tr>
        <tr><td style="background:#EEF4EC;padding:16px 26px;font-size:11px;color:#55635A">
          This message never asks for your ballot choices. Officials will never ask for your OTP.
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
def _post_with_retry(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = client.post(url, **kwargs)
            if response.status_code < 300 or response.status_code not in RETRYABLE_STATUS:
                return response
            last_error = httpx.HTTPStatusError(
                f"provider returned {response.status_code}", request=response.request, response=response
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
        time.sleep(0.4 * (attempt + 1))
    raise last_error or RuntimeError("delivery failed")


def _send_resend(
    destination: str, subject: str, text_body: str, html_body: str | None = None
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
    with httpx.Client(timeout=settings.otp_delivery_timeout_seconds) as client:
        response = _post_with_retry(client, f"{settings.email_api_base}/emails", json=payload, headers=headers)
    if response.status_code >= 300:
        return None, f"email provider rejected the message ({response.status_code})"
    try:
        return str(response.json().get("id") or ""), None
    except ValueError:
        return None, None


def _send_smtp(destination: str, subject: str, body: str) -> tuple[str | None, str | None]:
    message = EmailMessage()
    display_name, address = parseaddr(settings.email_from)
    message["From"] = formataddr((display_name or "SJC Alumni Election", address or settings.email_from))
    message["To"] = destination
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.otp_delivery_timeout_seconds) as server:
            server.ehlo()
            if settings.smtp_starttls:
                server.starttls()
                server.ehlo()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
        return None, None
    except (smtplib.SMTPException, OSError) as exc:
        return None, f"smtp delivery failed: {type(exc).__name__}"


def _send_twilio(destination: str, body: str) -> tuple[str | None, str | None]:
    sid = settings.twilio_account_sid
    credentials = base64.b64encode(f"{sid}:{settings.twilio_auth_token}".encode()).decode()
    url = f"{settings.sms_api_base}/2010-04-01/Accounts/{sid}/Messages.json"
    data = {"From": settings.twilio_from_number, "To": destination, "Body": body}
    with httpx.Client(timeout=settings.otp_delivery_timeout_seconds) as client:
        response = _post_with_retry(
            client, url, data=data, headers={"Authorization": f"Basic {credentials}"}
        )
    if response.status_code >= 300:
        return None, f"sms provider rejected the message ({response.status_code})"
    try:
        return str(response.json().get("sid") or ""), None
    except ValueError:
        return None, None


# ── entry point ─────────────────────────────────────────────────────────────
def deliver_otp(
    db: Session,
    *,
    election: Election,
    voter: Voter,
    otp: str,
    challenge_id: str,
    request_ip: str | None = None,
) -> DeliveryResult:
    """Send the OTP to the voter's registered contact and record the attempt."""
    choice = choose_channel(voter)
    if not choice:
        result = DeliveryResult(
            channel="none",
            provider="none",
            status="failed",
            recipient_masked="—",
            error="no OTP delivery channel configured",
        )
    else:
        channel, provider, destination = choice
        subject, text_body, html_body = _email_body(election, otp)
        if channel == "email":
            masked = mask_email(destination)
            try:
                if provider == "smtp":
                    message_id, error = _send_smtp(destination, subject, text_body)
                else:
                    message_id, error = _send_resend(destination, subject, text_body, html_body)
            except Exception as exc:  # transport failure, malformed response, timeout
                message_id, error = None, f"email delivery unavailable ({type(exc).__name__})"
            result = DeliveryResult(
                channel="email",
                provider=provider,
                status="failed" if error else "sent",
                recipient_masked=masked,
                provider_message_id=message_id,
                error=error,
            )
        elif channel == "sms":
            masked = mask_phone(destination)
            try:
                message_id, error = _send_twilio(destination, _sms_body(election, otp))
            except Exception as exc:
                message_id, error = None, f"sms delivery unavailable ({type(exc).__name__})"
            result = DeliveryResult(
                channel="sms",
                provider="twilio",
                status="failed" if error else "sent",
                recipient_masked=masked,
                provider_message_id=message_id,
                error=error,
            )
        else:
            # Local development only: the OTP is displayed to the voter on screen.
            result = DeliveryResult(
                channel="development",
                provider="on-screen",
                status="skipped",
                recipient_masked=destination or "development",
            )

    db.add(
        NotificationDelivery(
            election_id=election.id,
            voter_row_id=voter.id,
            challenge_id=challenge_id,
            channel=result.channel,
            provider=result.provider,
            status=result.status,
            recipient_masked=result.recipient_masked,
            provider_message_id=result.provider_message_id,
            error=(result.error or "")[:300] or None,
            request_ip=request_ip,
        )
    )
    return result
