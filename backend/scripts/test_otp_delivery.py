"""End-to-end OTP and registration-notice delivery tests.

Runs the real FastAPI app against a temporary SQLite database and local mock
providers for Resend, Termii and Meta WhatsApp. No real credentials are used.

Run:  .venv/Scripts/python.exe scripts/test_otp_delivery.py
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="sjc-otp-test-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{TMP / 'test.db'}",
        "KEYS_DIR": str(TMP / "keys"),
        "ENVIRONMENT": "development",
        "APP_ORIGIN": "http://localhost:3000",
        "API_ORIGIN": "http://localhost:8000",
        "DEV_EXPOSE_OTP": "false",
        "EMAIL_PROVIDER": "resend",
        "RESEND_API_KEY": "test-resend-key",
        "EMAIL_API_BASE": "http://127.0.0.1:8899",
        "SMS_PROVIDER": "termii",
        "TERMII_API_KEY": "test-termii-key",
        "TERMII_SENDER_ID": "SJCAlumni",
        "TERMII_CHANNEL": "dnd",
        "TERMII_API_BASE": "http://127.0.0.1:8899",
        "WHATSAPP_PROVIDER": "meta",
        "WHATSAPP_ACCESS_TOKEN": "test-wa-token",
        "WHATSAPP_PHONE_NUMBER_ID": "123456789",
        "WHATSAPP_API_BASE": "http://127.0.0.1:8899",
        "WHATSAPP_TEMPLATE_NAME": "sjc_election_otp",
        "WHATSAPP_TEMPLATE_LANGUAGE": "en_US",
        "WHATSAPP_APP_SECRET": "test-app-secret",
        "WHATSAPP_VERIFY_TOKEN": "test-verify-token",
        "DEMO_SEED": "true",
        "SEED_DEFAULT_PASSWORD": "ChangeMe!2026",
        "OTP_RESEND_SECONDS": "60",
        "OTP_DELIVERY_TIMEOUT_SECONDS": "3",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AccreditationRecord, NotificationDelivery, OtpChallenge, Voter  # noqa: E402
from app.security import as_aware  # noqa: E402
from app.services import now  # noqa: E402

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
                "headers": {k.lower(): v for k, v in self.headers.items()},
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
                    "sid": f"SM_mock_{MOCK_COUNTER}",
                    "message_id": f"termii-mock-{MOCK_COUNTER}",
                    "code": "ok",
                    "message": "Successfully Sent",
                    "messages": [{"id": f"wamid.mock.{MOCK_COUNTER}"}],
                }
            ).encode()
        )

    def log_message(self, *args):  # silence request logging
        return


def six_digit_code(text: str) -> str | None:
    match = re.search(r"\b(\d{6})\b", text)
    return match.group(1) if match else None


def calls_since(start: int) -> list[dict]:
    return CAPTURED[start:]


def call_for(calls: list[dict], path: str) -> dict:
    matches = [call for call in calls if call["path"] == path]
    assert len(matches) == 1, (path, [call["path"] for call in calls])
    return matches[0]


def request_otp(client: TestClient, election_id: str, voter_id: str):
    return client.post(
        "/api/accreditation/request-otp",
        json={"election_id": election_id, "voter_id": voter_id},
    )


def verify(client: TestClient, election_id: str, voter_id: str, challenge_id: str, otp: str):
    return client.post(
        "/api/accreditation/verify-otp",
        json={
            "election_id": election_id,
            "voter_id": voter_id,
            "challenge_id": challenge_id,
            "otp": otp,
        },
    )


def statuses(payload: dict) -> dict[str, str]:
    return {row["channel"]: row["status"] for row in payload["deliveries"]}


def otp_from_calls(calls: list[dict]) -> tuple[str, str, str]:
    email_call = call_for(calls, "/emails")
    sms_call = call_for(calls, "/api/sms/send")
    whatsapp_call = call_for(calls, "/123456789/messages")
    email_payload = json.loads(email_call["body"])
    sms_payload = json.loads(sms_call["body"])
    wa_payload = json.loads(whatsapp_call["body"])
    return (
        six_digit_code(email_payload["text"]) or "",
        six_digit_code(sms_payload.get("sms", "")) or "",
        wa_payload["template"]["components"][0]["parameters"][0]["text"],
    )


def set_voter_consent(voter_id: str, consent: bool) -> None:
    with SessionLocal() as db:
        voter = db.execute(select(Voter).where(Voter.voter_id == voter_id)).scalar_one()
        voter.whatsapp_consent = consent
        db.commit()


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8899), MockProvider)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    with TestClient(app) as client:
        election = client.get("/api/public/election").json()["election"]
        election_id = election["id"]

        # ── 1. one request fans out the same OTP to all three providers ──────
        start = len(CAPTURED)
        response = request_otp(client, election_id, "SJC/AL/2004/001")
        assert response.status_code == 200, response.text
        data = response.json()
        calls = calls_since(start)
        assert len(calls) == 3, [call["path"] for call in calls]
        emails = call_for(calls, "/emails")
        sms = call_for(calls, "/api/sms/send")
        whatsapp = call_for(calls, "/123456789/messages")
        email_payload = json.loads(emails["body"])
        sms_payload = json.loads(sms["body"])
        wa_payload = json.loads(whatsapp["body"])
        assert emails["headers"]["authorization"] == "Bearer test-resend-key"
        assert email_payload["to"] == ["emeka.nwosu@alumni.sjcjos.edu.ng"]
        assert sms_payload["api_key"] == "test-termii-key"
        assert sms_payload["to"].startswith("+234")
        assert sms_payload["from"] == "SJCAlumni"
        assert sms_payload["type"] == "plain"
        assert sms_payload["channel"] == "dnd"
        assert wa_payload["to"].isdigit()
        assert wa_payload["template"]["name"] == "sjc_election_otp"
        assert statuses(data) == {"email": "sent", "sms": "sent", "whatsapp": "sent"}, data
        assert data["delivery_channel"] == "multi"
        assert data["dev_otp"] is None
        assert all(row["recipient_masked"] for row in data["deliveries"])
        email_otp, sms_otp, wa_otp = otp_from_calls(calls)
        assert len(email_otp) == 6 and email_otp == sms_otp == wa_otp, (email_otp, sms_otp, wa_otp)
        wa_components = wa_payload["template"]["components"]
        assert wa_components[0]["type"] == "body"
        assert wa_components[1]["type"] == "button"
        assert wa_components[1]["sub_type"] == "url"
        assert wa_components[1]["index"] == "0"
        assert wa_components[1]["parameters"][0]["text"] == wa_otp
        assert email_otp not in response.text
        assert sms_otp not in response.text
        assert wa_otp not in response.text
        ok("one request sends one identical OTP through Resend, Termii and Meta WhatsApp")

        # ── 2. the same OTP can verify through any channel ───────────────────
        verified = verify(client, election_id, "SJC/AL/2004/001", data["challenge_id"], sms_otp)
        assert verified.status_code == 200, verified.text
        assert verified.json()["voter"]["voter_id"] == "SJC/AL/2004/001"
        with SessionLocal() as db:
            voter = db.execute(
                select(Voter).where(Voter.voter_id == "SJC/AL/2004/001")
            ).scalar_one()
            count = db.scalar(
                select(func.count(AccreditationRecord.id)).where(
                    AccreditationRecord.voter_row_id == voter.id
                )
            )
            deliveries = db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.challenge_id == data["challenge_id"]
                )
            ).scalars().all()
            assert count == 1
            assert {row.channel for row in deliveries} == {"email", "sms", "whatsapp"}
            assert all(row.status == "sent" for row in deliveries)
        ok("verification through the SMS copy completes accreditation")

        # ── 3. successful verification invalidates the OTP across all channels
        reused = verify(client, election_id, "SJC/AL/2004/001", data["challenge_id"], wa_otp)
        assert reused.status_code == 409, reused.text
        with SessionLocal() as db:
            voter = db.execute(
                select(Voter).where(Voter.voter_id == "SJC/AL/2004/001")
            ).scalar_one()
            count = db.scalar(
                select(func.count(AccreditationRecord.id)).where(
                    AccreditationRecord.voter_row_id == voter.id
                )
            )
            assert count == 1
        ok("the same OTP cannot be used again and only one accreditation record exists")

        # ── 4. partial provider failure does not cancel the other channels ──
        settings.email_api_base = "http://127.0.0.1:8898"  # nothing listening
        start = len(CAPTURED)
        partial = request_otp(client, election_id, "SJC/AL/2006/005")
        assert partial.status_code == 200, partial.text
        partial_data = partial.json()
        partial_calls = calls_since(start)
        # The dead email endpoint cannot record a mock request, so only the two
        # surviving providers appear here. Both must still have been attempted.
        assert {call["path"] for call in partial_calls} == {"/api/sms/send", "/123456789/messages"}
        assert statuses(partial_data) == {
            "email": "failed",
            "sms": "sent",
            "whatsapp": "sent",
        }, partial_data
        assert partial_data["deliveries"][0]["error"]
        partial_sms_payload = json.loads(call_for(partial_calls, "/api/sms/send")["body"])
        partial_wa_payload = json.loads(call_for(partial_calls, "/123456789/messages")["body"])
        partial_sms_otp = six_digit_code(partial_sms_payload["sms"]) or ""
        partial_wa_otp = partial_wa_payload["template"]["components"][0]["parameters"][0]["text"]
        assert partial_sms_otp == partial_wa_otp and len(partial_sms_otp) == 6
        verified_partial = verify(
            client, election_id, "SJC/AL/2006/005", partial_data["challenge_id"], partial_sms_otp
        )
        assert verified_partial.status_code == 200, verified_partial.text
        ok("a failed email provider does not cancel Termii and WhatsApp delivery")

        settings.email_api_base = "http://127.0.0.1:8899"

        # ── 5. all provider failures fail safely ─────────────────────────────
        settings.email_api_base = "http://127.0.0.1:8898"
        settings.termii_api_base = "http://127.0.0.1:8898"
        settings.whatsapp_api_base = "http://127.0.0.1:8898"
        failed = request_otp(client, election_id, "SJC/AL/2007/007")
        assert failed.status_code == 502, failed.text
        assert "dev_otp" not in failed.text
        with SessionLocal() as db:
            failed_rows = db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.voter_row_id
                    == db.execute(
                        select(Voter.id).where(Voter.voter_id == "SJC/AL/2007/007")
                    ).scalar_one()
                )
            ).scalars().all()
            assert {row.channel for row in failed_rows} == {"email", "sms", "whatsapp"}
            assert all(row.status == "failed" for row in failed_rows)
        settings.email_api_base = "http://127.0.0.1:8899"
        settings.termii_api_base = "http://127.0.0.1:8899"
        settings.whatsapp_api_base = "http://127.0.0.1:8899"
        ok("all-provider failure returns 502 and records no usable OTP")

        # ── 6. incorrect attempts lock the shared challenge ─────────────────
        wrong_start = len(CAPTURED)
        wrong_request = request_otp(client, election_id, "SJC/AL/2008/009")
        assert wrong_request.status_code == 200, wrong_request.text
        wrong_data = wrong_request.json()
        correct = otp_from_calls(calls_since(wrong_start))[0]
        wrong_code = "000000" if correct != "000000" else "000001"
        for attempt in range(1, 6):
            response = verify(
                client, election_id, "SJC/AL/2008/009", wrong_data["challenge_id"], wrong_code
            )
            assert response.status_code == 401, (attempt, response.text)
        blocked = verify(
            client, election_id, "SJC/AL/2008/009", wrong_data["challenge_id"], correct
        )
        assert blocked.status_code == 429, blocked.text
        ok("five incorrect attempts lock the shared challenge")

        # ── 7. expired OTP is rejected ─────────────────────────────────────
        expired_start = len(CAPTURED)
        expired_request = request_otp(client, election_id, "SJC/AL/2009/011")
        assert expired_request.status_code == 200, expired_request.text
        expired_data = expired_request.json()
        expired_otp, _, _ = otp_from_calls(calls_since(expired_start))
        with SessionLocal() as db:
            challenge = db.get(OtpChallenge, expired_data["challenge_id"])
            challenge.expires_at = now() - timedelta(minutes=1)
            db.commit()
        expired = verify(
            client, election_id, "SJC/AL/2009/011", expired_data["challenge_id"], expired_otp
        )
        assert expired.status_code == 400, expired.text
        assert "expired" in expired.text.lower()
        ok("a five-minute-expired OTP is rejected")

        # ── 8. resend cooldown and one-active-challenge rule ───────────────
        settings.otp_resend_seconds = 60
        first_start = len(CAPTURED)
        first = request_otp(client, election_id, "SJC/AL/2010/013")
        assert first.status_code == 200, first.text
        first_data = first.json()
        first_calls = calls_since(first_start)
        first_otp, _, _ = otp_from_calls(first_calls)
        early = request_otp(client, election_id, "SJC/AL/2010/013")
        assert early.status_code == 429, early.text
        with SessionLocal() as db:
            challenge = db.get(OtpChallenge, first_data["challenge_id"])
            assert as_aware(challenge.expires_at) > now(), "rejected resend destroyed the live OTP"
            challenge.created_at = now() - timedelta(seconds=61)
            db.commit()
        resend_start = len(CAPTURED)
        resent = request_otp(client, election_id, "SJC/AL/2010/013")
        assert resent.status_code == 200, resent.text
        resent_data = resent.json()
        resent_calls = calls_since(resend_start)
        assert len(resent_calls) == 3
        resent_otp, _, _ = otp_from_calls(resent_calls)
        old = verify(
            client, election_id, "SJC/AL/2010/013", first_data["challenge_id"], first_otp
        )
        assert old.status_code == 400, old.text
        new = verify(
            client, election_id, "SJC/AL/2010/013", resent_data["challenge_id"], resent_otp
        )
        assert new.status_code == 200, new.text
        ok("resend cooldown is enforced and a resend invalidates the previous OTP")

        # ── 9. WhatsApp consent controls only that channel ───────────────────
        set_voter_consent("SJC/AL/2012/017", False)
        consent_start = len(CAPTURED)
        no_consent = request_otp(client, election_id, "SJC/AL/2012/017")
        assert no_consent.status_code == 200, no_consent.text
        no_consent_data = no_consent.json()
        assert statuses(no_consent_data)["whatsapp"] == "unavailable"
        assert statuses(no_consent_data)["email"] == "sent"
        assert statuses(no_consent_data)["sms"] == "sent"
        consent_calls = calls_since(consent_start)
        assert {call["path"] for call in consent_calls} == {"/emails", "/api/sms/send"}
        ok("WhatsApp without consent is reported as unavailable without stopping Email or SMS")

        # ── 10. contact privacy ─────────────────────────────────────────────
        no_auth = client.get(f"/api/register/{election_id}")
        assert no_auth.status_code == 401, no_auth.text
        login = client.post(
            "/api/auth/login",
            json={"email": "observer@sjcjos-alumni.org", "password": "ChangeMe!2026"},
        )
        assert login.status_code == 200, login.text
        observer_token = login.json()["access_token"]
        forbidden = client.get(
            f"/api/register/{election_id}",
            headers={"authorization": f"Bearer {observer_token}"},
        )
        assert forbidden.status_code == 403, forbidden.text
        ok("voter contact records remain inaccessible without register permission")

        # ── 11. committee monitoring and Super Administrator readiness ───────
        super_login = client.post(
            "/api/auth/login",
            json={"email": "superadmin@sjcjos-alumni.org", "password": "ChangeMe!2026"},
        )
        assert super_login.status_code == 200, super_login.text
        super_headers = {"authorization": f"Bearer {super_login.json()['access_token']}"}
        delivery_settings = client.get("/api/settings/delivery", headers=super_headers)
        assert delivery_settings.status_code == 200, delivery_settings.text
        readiness = delivery_settings.json()
        assert len(readiness["providers"]) == 3
        assert readiness["providers"][1]["provider"] == "termii"
        assert all(provider["configured"] for provider in readiness["providers"])
        assert "test-termii-key" not in delivery_settings.text
        assert "test-resend-key" not in delivery_settings.text
        overview = client.get(
            f"/api/monitoring/{election_id}/overview", headers=super_headers
        )
        assert overview.status_code == 200, overview.text
        delivery_stats = overview.json()["live"]["otp_delivery"]
        assert delivery_stats["requests"] >= 4
        assert any(row["channel"] == "whatsapp" for row in delivery_stats["by_channel"])
        assert all(key not in overview.text for key in (first_otp, resent_otp, expired_otp))
        ok("committee monitoring exposes channel counts and provider readiness without secrets")

        # ── 12. register approval sends one email and WhatsApp notice ────────
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
        notice_start = len(CAPTURED)
        approved = client.post(
            f"/api/register/{election_id}/approve", headers=chair_headers
        )
        assert approved.status_code == 200, approved.text
        notice = approved.json()["notifications"]
        notice_calls = calls_since(notice_start)
        assert notice["voters"] == eligible, notice
        assert notice["email_sent"] == eligible, notice
        assert notice["whatsapp_sent"] == eligible - 1, notice
        assert notice["whatsapp_no_consent"] == 1, notice
        assert notice["email_failed"] == 0 and notice["whatsapp_failed"] == 0, notice
        assert len(notice_calls) == 2 * eligible - 1, [call["path"] for call in notice_calls]
        email_notice = next(call for call in notice_calls if call["path"] == "/emails")
        whatsapp_notice = next(
            call for call in notice_calls if call["path"] == "/123456789/messages"
        )
        email_notice_payload = json.loads(email_notice["body"])
        whatsapp_notice_payload = json.loads(whatsapp_notice["body"])
        assert email_notice_payload["subject"].endswith("You are registered to vote")
        assert "Voter ID" in email_notice_payload["text"]
        assert "OTP" not in email_notice_payload["text"].split("one-time password")[0]
        assert whatsapp_notice_payload["template"]["name"] == "sjc_registration_confirmation"
        wa_notice_params = whatsapp_notice_payload["template"]["components"][0]["parameters"]
        assert len(wa_notice_params) == 3, wa_notice_params
        assert all(item["type"] == "text" and item["text"] for item in wa_notice_params)
        with SessionLocal() as db:
            rows = db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.election_id == election_id,
                    NotificationDelivery.purpose == "registration",
                )
            ).scalars().all()
            assert len(rows) == 2 * eligible - 1
            assert {row.channel for row in rows} == {"email", "whatsapp"}
            assert all(row.status == "sent" and row.challenge_id is None for row in rows)
            assert db.scalar(
                select(func.count(Voter.id)).where(
                    Voter.election_id == election_id,
                    Voter.registration_email_sent_at.is_not(None),
                    Voter.registration_whatsapp_sent_at.is_not(None),
                )
            ) == eligible - 1
        ok("approval sends an email and an approved WhatsApp utility notice once per voter")

        # ── 13. repeated approval is idempotent for successful channels ──────
        again_start = len(CAPTURED)
        again = client.post(f"/api/register/{election_id}/approve", headers=chair_headers)
        assert again.status_code == 200, again.text
        again_notice = again.json()["notifications"]
        assert len(calls_since(again_start)) == 0
        assert again_notice["email_already_sent"] == eligible, again_notice
        assert again_notice["whatsapp_already_sent"] == eligible - 1, again_notice
        assert again_notice["whatsapp_no_consent"] == 1, again_notice
        ok("repeated register approval does not resend successful notices")

        # ── 14. production fails closed without a provider ──────────────────
        settings.environment = "production"
        settings.email_provider = "none"
        settings.resend_api_key = ""
        settings.sms_provider = "none"
        settings.whatsapp_provider = "none"
        settings.dev_expose_otp = True
        blocked_prod = request_otp(client, election_id, "SJC/AL/2013/019")
        assert blocked_prod.status_code == 503, blocked_prod.text
        assert "dev_otp" not in blocked_prod.text
        ok("production without a configured provider fails closed")

        # ── 13. local development on-screen mode ────────────────────────────
        settings.environment = "development"
        settings.app_origin = "http://localhost:3000"
        settings.dev_expose_otp = True
        local_start = len(CAPTURED)
        local = request_otp(client, election_id, "SJC/AL/2014/021")
        assert local.status_code == 200, local.text
        local_data = local.json()
        assert statuses(local_data)["development"] == "skipped"
        assert local_data["dev_otp"] and len(local_data["dev_otp"]) == 6
        assert len(calls_since(local_start)) == 0
        ok("local development shows one on-screen OTP when no real provider is configured")

        # Restore realistic settings for the final policy check.
        settings.environment = "development"
        settings.dev_expose_otp = False
        settings.email_provider = "resend"
        settings.resend_api_key = "test-resend-key"
        settings.sms_provider = "termii"
        settings.whatsapp_provider = "meta"
        assert settings.expose_dev_otp is False
        settings.environment = "production"
        assert settings.expose_dev_otp is False
        settings.environment = "staging"
        assert settings.expose_dev_otp is False
        settings.environment = "development"
        settings.dev_expose_otp = True
        assert settings.expose_dev_otp is True
        ok("on-screen OTP is refused outside local development")

    server.shutdown()
    print("\n" + "=" * 72)
    print(f"OTP + REGISTRATION NOTICE TESTS PASSED: {len(PASSED)} checks")
    print("=" * 72)
    for label in PASSED:
        print(f"  • {label}")


if __name__ == "__main__":
    main()
