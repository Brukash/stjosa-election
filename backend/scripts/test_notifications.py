"""End-to-end accreditation and registration-notice tests.

Runs the real FastAPI app against a temporary SQLite database and local mock
providers for Resend and Meta WhatsApp. No real credentials are used.

Run:  .venv/Scripts/python.exe scripts/test_notifications.py
"""
from __future__ import annotations

import json
import math
import os
import secrets
import sys
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="sjc-notification-test-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{TMP / 'test.db'}",
        "KEYS_DIR": str(TMP / "keys"),
        "ENVIRONMENT": "development",
        "APP_ORIGIN": "http://localhost:3000",
        "API_ORIGIN": "http://localhost:8000",
        "EMAIL_PROVIDER": "resend",
        "RESEND_API_KEY": "test-resend-key",
        "EMAIL_FROM": "SJC Election <election@example.test>",
        "EMAIL_API_BASE": "http://127.0.0.1:8899",
        "SMS_PROVIDER": "termii",
        "TERMII_API_KEY": "test-termii-key",
        "TERMII_SENDER_ID": "SJC-ALUMNI",
        "TERMII_API_BASE": "http://127.0.0.1:8899",
        "WHATSAPP_PROVIDER": "meta",
        "WHATSAPP_ACCESS_TOKEN": "test-wa-token",
        "WHATSAPP_PHONE_NUMBER_ID": "123456789",
        "WHATSAPP_API_BASE": "http://127.0.0.1:8899",
        "WHATSAPP_REGISTRATION_TEMPLATE_NAME": "sjc_registration_confirmation",
        "WHATSAPP_REGISTRATION_TEMPLATE_LANGUAGE": "en_US",
        "WHATSAPP_VOTE_CONFIRMATION_TEMPLATE_NAME": "sjc_vote_confirmation",
        "WHATSAPP_VOTE_CONFIRMATION_TEMPLATE_LANGUAGE": "en_US",
        "WHATSAPP_RESULTS_TEMPLATE_NAME": "sjc_results_declared",
        "WHATSAPP_RESULTS_TEMPLATE_LANGUAGE": "en_US",
        "WHATSAPP_APP_SECRET": "test-app-secret",
        "WHATSAPP_VERIFY_TOKEN": "test-verify-token",
        "DEMO_SEED": "true",
        "SEED_DEFAULT_PASSWORD": "ChangeMe!2026",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app import crypto  # noqa: E402
from app import notifications as notifications_module  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AccreditationRecord,
    AccreditationSession,
    AuditLog,
    Election,
    NotificationDelivery,
    Voter,
)

CAPTURED: list[dict] = []
PASSED: list[str] = []
MOCK_COUNTER = 0


def ok(label: str) -> None:
    PASSED.append(label)
    print(f"  PASS  {label}")


class MockProvider(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        global MOCK_COUNTER
        MOCK_COUNTER += 1
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length).decode("utf-8", "replace")
        CAPTURED.append(
            {
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body,
            }
        )
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "id": f"email-mock-{MOCK_COUNTER}",
                    "message_id": f"meta-mock-{MOCK_COUNTER}",
                    "messages": [{"id": f"wamid.mock.{MOCK_COUNTER}"}],
                }
            ).encode()
        )

    def log_message(self, *args):  # silence request logging
        return


def call_for(calls: list[dict], path: str) -> dict:
    matches = [call for call in calls if call["path"] == path]
    assert len(matches) == 1, (path, [call["path"] for call in calls])
    return matches[0]


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8899), MockProvider)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    with TestClient(app) as client:
        election = client.get("/api/public/election").json()["election"]
        election_id = election["id"]

        # ── 1. a matching Voter ID opens accreditation without OTP delivery ──
        start = len(CAPTURED)
        verified = client.post(
            "/api/accreditation/verify-voter",
            json={"election_id": election_id, "voter_id": "SJC/AL/2004/001"},
        )
        assert verified.status_code == 200, verified.text
        data = verified.json()
        assert data["voter"]["voter_id"] == "SJC/AL/2004/001"
        assert data["accreditation_token"]
        assert len(CAPTURED) == start, "Voter ID verification sent a notification"
        with SessionLocal() as db:
            voter = db.execute(
                select(Voter).where(Voter.voter_id == "SJC/AL/2004/001")
            ).scalar_one()
            accreditation = db.execute(
                select(AccreditationRecord).where(
                    AccreditationRecord.election_id == election_id,
                    AccreditationRecord.voter_row_id == voter.id,
                )
            ).scalar_one()
            session = db.execute(
                select(AccreditationSession).where(
                    AccreditationSession.election_id == election_id,
                    AccreditationSession.voter_row_id == voter.id,
                )
            ).scalars().first()
            audit = db.execute(
                select(AuditLog).where(
                    AuditLog.election_id == election_id,
                    AuditLog.action == "voter.verify",
                    AuditLog.outcome == "success",
                )
            ).scalars().first()
            assert accreditation.method == "voter_id"
            assert session is not None
            assert audit is not None
        ok("a matching Voter ID creates an accreditation session with no OTP delivery")

        # ── 2. the retired OTP routes are unavailable ───────────────────────
        for path in (
            "/api/accreditation/request-otp",
            "/api/accreditation/verify-otp",
            "/api/accreditation/otp-options",
        ):
            response = client.post(
                path,
                json={"election_id": election_id, "voter_id": "SJC/AL/2004/001"},
            )
            assert response.status_code == 404, (path, response.status_code, response.text)
        ok("the old OTP accreditation routes are removed")

        # ── 3. an unknown or ineligible Voter ID is rejected ───────────────
        rejected = client.post(
            "/api/accreditation/verify-voter",
            json={"election_id": election_id, "voter_id": "SJC/AL/9999/999"},
        )
        assert rejected.status_code == 404, rejected.text
        assert "not on the approved electoral register" in rejected.text
        ok("an unknown Voter ID is rejected against the approved register")

        # ── 4. approval sends email and WhatsApp notices with the Voter ID ──
        chair_login = client.post(
            "/api/auth/login",
            json={"email": "chairman@sjcjos-alumni.org", "password": "ChangeMe!2026"},
        )
        assert chair_login.status_code == 200, chair_login.text
        chair_headers = {"authorization": f"Bearer {chair_login.json()['access_token']}"}
        with SessionLocal() as db:
            eligible = db.scalar(
                select(func.count(Voter.id)).where(
                    Voter.election_id == election_id, Voter.is_eligible.is_(True)
                )
            ) or 0
            no_consent = db.execute(
                select(Voter).where(
                    Voter.election_id == election_id, Voter.voter_id == "SJC/AL/2012/017"
                )
            ).scalar_one()
            no_consent.whatsapp_consent = False
            db.commit()

        notice_start = len(CAPTURED)
        approved = client.post(
            f"/api/register/{election_id}/approve", headers=chair_headers
        )
        assert approved.status_code == 200, approved.text
        notice = approved.json()["notifications"]
        notice_calls = CAPTURED[notice_start:]
        assert notice["voters"] == eligible, notice
        assert notice["email_sent"] == eligible, notice
        assert notice["sms_sent"] == eligible, notice
        assert notice["whatsapp_sent"] == eligible - 1, notice
        assert notice["whatsapp_no_consent"] == 1, notice
        assert notice["email_failed"] == 0 and notice["sms_failed"] == 0, notice
        assert notice["whatsapp_failed"] == 0, notice
        assert len(notice_calls) == 3 * eligible - 1, [call["path"] for call in notice_calls]

        email_notice = json.loads(next(call for call in notice_calls if call["path"] == "/emails")["body"])
        whatsapp_notice = json.loads(
            next(call for call in notice_calls if call["path"] == "/123456789/messages")["body"]
        )
        sms_notice = json.loads(
            next(call for call in notice_calls if call["path"] == "/api/sms/send")["body"]
        )
        assert "Voter ID SJC/AL/" in email_notice["subject"], email_notice["subject"]
        assert "Your Voter ID is SJC/AL/" in email_notice["text"], email_notice["text"]
        assert "OTP" not in email_notice["text"]
        assert "one-time password" not in email_notice["text"].lower()
        assert whatsapp_notice["template"]["name"] == "sjc_registration_confirmation"
        wa_params = whatsapp_notice["template"]["components"][0]["parameters"]
        assert len(wa_params) == 3, wa_params
        assert all(item["type"] == "text" and item["text"] for item in wa_params)
        assert "Voter ID SJC/AL/" in sms_notice["sms"], sms_notice["sms"]
        assert "accredit" in sms_notice["sms"], sms_notice["sms"]
        assert len(sms_notice["sms"]) <= 160, len(sms_notice["sms"])
        ok(
            "approval sends the Voter ID by email, SMS and the WhatsApp utility notice; "
            "SMS stays within one part"
        )

        with SessionLocal() as db:
            rows = db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.election_id == election_id,
                    NotificationDelivery.purpose == "registration",
                )
            ).scalars().all()
            assert len(rows) == 3 * eligible - 1
            assert {row.channel for row in rows} == {"email", "sms", "whatsapp"}
            assert all(row.status == "sent" and row.challenge_id is None for row in rows)
            assert db.scalar(
                select(func.count(Voter.id)).where(
                    Voter.election_id == election_id,
                    Voter.registration_email_sent_at.is_not(None),
                    Voter.registration_sms_sent_at.is_not(None),
                    Voter.registration_whatsapp_sent_at.is_not(None),
                )
            ) == eligible - 1
        ok("notice deliveries are recorded separately per channel and voter")

        # ── 5. repeated approval does not resend successful notices ──────────
        again_start = len(CAPTURED)
        again = client.post(f"/api/register/{election_id}/approve", headers=chair_headers)
        assert again.status_code == 200, again.text
        again_notice = again.json()["notifications"]
        assert len(CAPTURED) == again_start
        assert again_notice["email_already_sent"] == eligible, again_notice
        assert again_notice["sms_already_sent"] == eligible, again_notice
        assert again_notice["whatsapp_already_sent"] == eligible - 1, again_notice
        assert again_notice["whatsapp_no_consent"] == 1, again_notice
        ok("repeated register approval does not resend successful notices")

        # ── 6. a locked register can still resend undelivered notices ────────
        with SessionLocal() as db:
            election_row = db.get(Election, election_id)
            assert election_row is not None
            election_row.locked_at = datetime.now(timezone.utc)  # the first ballot was cast
            failed_voter = db.execute(
                select(Voter).where(
                    Voter.election_id == election_id,
                    Voter.is_eligible.is_(True),
                    Voter.register_status == "approved",
                    Voter.registration_email_sent_at.is_not(None),
                )
            ).scalars().first()
            assert failed_voter is not None
            failed_voter.registration_email_sent_at = None  # a notice that never arrived
            db.commit()

        locked_approve = client.post(f"/api/register/{election_id}/approve", headers=chair_headers)
        assert locked_approve.status_code == 409, locked_approve.text

        retry_start = len(CAPTURED)
        retried = client.post(
            f"/api/register/{election_id}/notifications/retry", headers=chair_headers
        )
        assert retried.status_code == 200, retried.text
        retry_body = retried.json()
        assert retry_body["register_locked"] is True, retry_body
        retry_notices = retry_body["notifications"]
        assert retry_notices["email_sent"] == 1, retry_notices
        assert retry_notices["email_already_sent"] == eligible - 1, retry_notices
        assert retry_notices["sms_already_sent"] == eligible, retry_notices
        retry_calls = CAPTURED[retry_start:]
        assert len(retry_calls) == 1, [call["path"] for call in retry_calls]
        ok("a locked register still resends only the notices that were not delivered")

        # ── 7. one member can be resent on demand ──────────────────────────
        with SessionLocal() as db:
            every_email = [
                (voter.email or "").strip().lower()
                for voter in db.execute(
                    select(Voter).where(Voter.election_id == election_id)
                ).scalars()
            ]
            candidates = db.execute(
                select(Voter).where(
                    Voter.election_id == election_id,
                    Voter.is_eligible.is_(True),
                    Voter.register_status == "approved",
                    Voter.registration_email_sent_at.is_not(None),
                    Voter.email.is_not(None),
                )
            ).scalars().all()
            target = next(
                voter
                for voter in candidates
                if every_email.count((voter.email or "").strip().lower()) == 1
            )
            target_row_id = target.id
            target_voter_id = target.voter_id
            target_email = (target.email or "").strip()
            deliveries_before = db.scalar(
                select(func.count(NotificationDelivery.id)).where(
                    NotificationDelivery.election_id == election_id,
                    NotificationDelivery.voter_row_id == target_row_id,
                    NotificationDelivery.purpose == "registration",
                    NotificationDelivery.channel == "email",
                )
            )

        resend_start = len(CAPTURED)
        resent = client.post(
            f"/api/register/{election_id}/notifications/resend",
            headers=chair_headers,
            json={"voter": target_voter_id},
        )
        assert resent.status_code == 200, resent.text
        resent_body = resent.json()
        assert resent_body["voter"]["voter_id"] == target_voter_id, resent_body
        assert resent_body["delivery"]["status"] == "sent", resent_body
        assert [call["path"] for call in CAPTURED[resend_start:]] == ["/emails"], [
            call["path"] for call in CAPTURED[resend_start:]
        ]
        with SessionLocal() as db:
            deliveries_after = db.scalar(
                select(func.count(NotificationDelivery.id)).where(
                    NotificationDelivery.election_id == election_id,
                    NotificationDelivery.voter_row_id == target_row_id,
                    NotificationDelivery.purpose == "registration",
                    NotificationDelivery.channel == "email",
                )
            )
            assert deliveries_after == deliveries_before + 1, (
                deliveries_before,
                deliveries_after,
            )
        ok("the resend field sends one member's registration email again")

        by_email = client.post(
            f"/api/register/{election_id}/notifications/resend",
            headers=chair_headers,
            json={"voter": target_email},
        )
        assert by_email.status_code == 200, by_email.text
        assert by_email.json()["voter"]["voter_id"] == target_voter_id, by_email.text
        ok("the resend field also finds a member by email address")

        unknown = client.post(
            f"/api/register/{election_id}/notifications/resend",
            headers=chair_headers,
            json={"voter": "SJC/AL/1999/999"},
        )
        assert unknown.status_code == 404, unknown.text
        assert len(CAPTURED) == resend_start + 2, "an unknown member was emailed"
        ok("an unknown member is refused instead of emailed")

        with SessionLocal() as db:
            db.get(Election, election_id).locked_at = None
            db.commit()

        # ── 7. an SMTP batch reuses one connection and defers the overflow ───

        class FakeSmtpSession:
            """Stands in for a real cPanel session; records connections and sends."""

            instances: list["FakeSmtpSession"] = []

            def __init__(self) -> None:
                self.server = None
                self.connections = 0
                self.sent = 0
                FakeSmtpSession.instances.append(self)

            def connect(self, *, timeout_seconds=None) -> None:
                self.connections += 1
                self.server = object()
                # The batch must already hold the shared connection slot while
                # its session is open, so a concurrent single send cannot push
                # the mailbox past SMTP_MAX_CONNECTIONS.
                assert notifications_module._smtp_slots().acquire(blocking=False) is False, (
                    "the batch session did not take a shared SMTP slot"
                )

            def close(self) -> None:
                self.server = None

            def send(self, message) -> str:
                assert self.server is not None, "send without a connection"
                self.sent += 1
                return str(message["Message-ID"])

        with SessionLocal() as db:
            for voter in db.execute(
                select(Voter).where(
                    Voter.election_id == election_id,
                    Voter.is_eligible.is_(True),
                    Voter.register_status == "approved",
                )
            ).scalars():
                voter.registration_email_sent_at = None
            db.commit()

        original_session = notifications_module._SmtpSession
        original_provider = settings.email_provider
        original_host = settings.smtp_host
        original_batch = settings.smtp_batch_size
        original_delay = settings.smtp_send_delay_ms
        original_max_connections = settings.smtp_max_connections
        original_slots = notifications_module._SMTP_SLOTS
        notifications_module._SmtpSession = FakeSmtpSession
        notifications_module._SMTP_SLOTS = None
        settings.email_provider = "smtp"
        settings.smtp_host = "smtp.example.test"
        settings.smtp_batch_size = 2
        settings.smtp_send_delay_ms = 0
        # One slot makes the batch's hold observable from inside connect().
        settings.smtp_max_connections = 1
        try:
            first = client.post(
                f"/api/register/{election_id}/notifications/retry", headers=chair_headers
            )
            assert first.status_code == 200, first.text
            first_notices = first.json()["notifications"]
            assert first_notices["email_sent"] == 2, first_notices
            assert first_notices["email_deferred"] == eligible - 2, first_notices
            assert len(FakeSmtpSession.instances) == 1, len(FakeSmtpSession.instances)
            assert FakeSmtpSession.instances[0].connections == 1
            assert FakeSmtpSession.instances[0].sent == 2

            remaining = eligible - 2
            while remaining > 0:
                run = client.post(
                    f"/api/register/{election_id}/notifications/retry", headers=chair_headers
                )
                assert run.status_code == 200, run.text
                run_notices = run.json()["notifications"]
                sent = min(2, remaining)
                assert run_notices["email_sent"] == sent, run_notices
                assert run_notices["email_already_sent"] == eligible - remaining, run_notices
                remaining -= sent
            assert run_notices["email_deferred"] == 0, run_notices
            assert all(session.connections == 1 for session in FakeSmtpSession.instances)
            assert all(session.sent <= 2 for session in FakeSmtpSession.instances)
            assert sum(session.sent for session in FakeSmtpSession.instances) == eligible
            ok(
                "an SMTP batch reuses one connection per run, caps the batch "
                "and defers the rest to the next run"
            )
        finally:
            notifications_module._SmtpSession = original_session
            notifications_module._SMTP_SLOTS = original_slots
            settings.email_provider = original_provider
            settings.smtp_host = original_host
            settings.smtp_batch_size = original_batch
            settings.smtp_send_delay_ms = original_delay
            settings.smtp_max_connections = original_max_connections

        # ── 8. read boundaries and provider readiness ────────────────────────
        login = client.post(
            "/api/auth/login",
            json={"email": "observer@sjcjos-alumni.org", "password": "ChangeMe!2026"},
        )
        assert login.status_code == 200, login.text
        observer_headers = {"authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get(
            f"/api/register/{election_id}", headers=observer_headers
        ).status_code == 403
        ok("voter contact records remain inaccessible without register permission")

        super_login = client.post(
            "/api/auth/login",
            json={"email": "superadmin@sjcjos-alumni.org", "password": "ChangeMe!2026"},
        )
        assert super_login.status_code == 200, super_login.text
        super_headers = {"authorization": f"Bearer {super_login.json()['access_token']}"}
        delivery_settings = client.get("/api/settings/delivery", headers=super_headers)
        assert delivery_settings.status_code == 200, delivery_settings.text
        readiness = delivery_settings.json()
        assert "otp" not in readiness
        assert readiness["whatsapp"]["registration_template_name"] == "sjc_registration_confirmation"
        assert readiness["whatsapp"]["vote_confirmation_template_name"] == "sjc_vote_confirmation"
        assert readiness["whatsapp"]["results_template_name"] == "sjc_results_declared"
        assert next(
            provider for provider in readiness["providers"] if provider["channel"] == "sms"
        )["configured"] is True
        assert all(
            provider["configured"]
            for provider in readiness["providers"]
            if provider["channel"] in {"email", "whatsapp"}
        )
        assert "test-resend-key" not in delivery_settings.text
        assert "test-wa-token" not in delivery_settings.text
        overview = client.get(
            f"/api/monitoring/{election_id}/overview", headers=super_headers
        )
        assert overview.status_code == 200, overview.text
        delivery_stats = overview.json()["live"]["registration_delivery"]
        assert delivery_stats["sent"] >= 3 * eligible - 1
        assert delivery_stats["failed"] == 0
        assert {row["channel"] for row in delivery_stats["by_channel"]} >= {
            "email",
            "sms",
            "whatsapp",
        }
        assert overview.json()["live"]["failed_identity_checks"] >= 1
        ok("committee monitoring reports notice delivery and failed identity checks without secrets")

        # ── 9. casting records turnout without linking it to the ballot ─────
        numbers = crypto.credential_public_numbers()
        modulus, exponent = int(numbers["n"], 16), int(numbers["e"], 16)
        token_hex = secrets.token_hex(32)
        message_hash = crypto.fdh(
            crypto.credential_message(election["reference"], token_hex), modulus
        )
        while True:
            blinding = secrets.randbelow(modulus - 2) + 2
            if math.gcd(blinding, modulus) == 1:
                break
        blinded = (message_hash * pow(blinding, exponent, modulus)) % modulus
        signed = client.post(
            "/api/accreditation/credential",
            json={
                "accreditation_token": data["accreditation_token"],
                "blinded_message": format(blinded, "x"),
            },
        )
        assert signed.status_code == 200, signed.text
        unblinded = (
            int(signed.json()["blind_signature"], 16) * pow(blinding, -1, modulus)
        ) % modulus
        credential = {
            "token": token_hex,
            "signature": format(unblinded, "x"),
            "turnout_token": data["turnout_token"],
        }
        selections = {
            position["id"]: position["candidates"][0]["id"]
            for position in election["positions"]
        }
        prepared_response = client.post(
            "/api/voting/prepare",
            json={"election_id": election_id, **credential, "selections": selections},
        )
        assert prepared_response.status_code == 200, prepared_response.text
        prepared = prepared_response.json()

        missing_turnout = client.post(
            f"/api/voting/{prepared['prepared_id']}/cast",
            json={"token": credential["token"], "signature": credential["signature"]},
        )
        assert missing_turnout.status_code == 401, missing_turnout.text
        cast_start = len(CAPTURED)
        cast = client.post(
            f"/api/voting/{prepared['prepared_id']}/cast", json=credential
        )
        assert cast.status_code == 200, cast.text
        cast_calls = CAPTURED[cast_start:]
        assert len(cast_calls) == 3, [call["path"] for call in cast_calls]
        vote_email = json.loads(
            next(call for call in cast_calls if call["path"] == "/emails")["body"]
        )
        vote_whatsapp = json.loads(
            next(call for call in cast_calls if call["path"] == "/123456789/messages")["body"]
        )
        vote_sms = json.loads(
            next(call for call in cast_calls if call["path"] == "/api/sms/send")["body"]
        )
        assert "submitted successfully" in vote_email["subject"], vote_email["subject"]
        assert "submitted successfully" in vote_email["text"], vote_email["text"]
        assert "does not include your candidate selections" in vote_email["text"]
        assert vote_whatsapp["template"]["name"] == "sjc_vote_confirmation"
        wa_vote_params = vote_whatsapp["template"]["components"][0]["parameters"]
        assert len(wa_vote_params) == 3, wa_vote_params
        assert all(item["type"] == "text" and item["text"] for item in wa_vote_params)
        assert "ballot was received" in vote_sms["sms"], vote_sms["sms"]
        assert "Amina" not in vote_sms["sms"], vote_sms["sms"]
        assert len(vote_sms["sms"]) <= 160, len(vote_sms["sms"])
        ok(
            "a cast sends email, SMS and WhatsApp submission confirmations "
            "without selections; SMS stays within one part"
        )

        with SessionLocal() as db:
            voted_voter = db.execute(
                select(Voter).where(Voter.voter_id == "SJC/AL/2004/001")
            ).scalar_one()
            assert voted_voter.has_voted_at is not None
            assert voted_voter.turnout_token_hash is None
            confirmation_rows = db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.election_id == election_id,
                    NotificationDelivery.purpose == "vote_confirmation",
                )
            ).scalars().all()
            assert len(confirmation_rows) == 3, confirmation_rows
            assert {row.channel for row in confirmation_rows} == {"email", "sms", "whatsapp"}
            assert all(row.status == "sent" and row.challenge_id is None for row in confirmation_rows)
        ok("vote confirmation deliveries are recorded separately per channel")

        replay_start = len(CAPTURED)
        replay = client.post(
            f"/api/voting/{prepared['prepared_id']}/cast", json=credential
        )
        assert replay.status_code == 200, replay.text
        assert len(CAPTURED) == replay_start, "idempotent cast replay resent a confirmation"
        ok("an idempotent cast replay does not resend vote confirmations")

        report = client.get(
            f"/api/monitoring/{election_id}/overview", headers=super_headers
        )
        assert report.status_code == 200, report.text
        jos = next(
            row for row in report.json()["turnout_by_set"]
            if row["alumni_set"] == "Jos Chapter"
        )
        assert jos["voted"] == 1 and jos["pending"] == jos["eligible"] - 1, jos
        assert jos["target"] == 3 and jos["target_remaining"] == 2, jos
        participation = client.get(
            f"/api/monitoring/{election_id}/participation", headers=observer_headers
        )
        assert participation.status_code == 200, participation.text
        assert next(
            row for row in participation.json()["sets"]
            if row["alumni_set"] == "Jos Chapter"
        )["voted"] == 1
        assert "Emeka Nwosu" not in report.text
        assert "SJC/AL/2004/001" not in report.text
        ok("a cast records a private turnout marker and the dashboard reports aggregate progress")

    server.shutdown()
    print("\n" + "=" * 72)
    print(f"ACCREDITATION + REGISTRATION NOTICE TESTS PASSED: {len(PASSED)} checks")
    print("=" * 72)
    for label in PASSED:
        print(f"  • {label}")


if __name__ == "__main__":
    main()
