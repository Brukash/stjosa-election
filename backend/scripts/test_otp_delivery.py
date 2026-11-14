"""Integration test for OTP delivery and the development-exposure gate.

Runs the real FastAPI app against a temporary SQLite database and a local mock
HTTP provider, so the Resend/Twilio request paths and payloads are exercised
without any real credentials.

Run:  .venv/Scripts/python.exe scripts/test_otp_delivery.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="sjc-otp-test-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{TMP / 'test.db'}",
        "KEYS_DIR": str(TMP / "keys"),
        "ENVIRONMENT": "development",
        "APP_ORIGIN": "http://localhost:3000",
        "DEV_EXPOSE_OTP": "false",
        "EMAIL_PROVIDER": "resend",
        "RESEND_API_KEY": "test-resend-key",
        "EMAIL_API_BASE": "http://127.0.0.1:8899",
        "SMS_PROVIDER": "none",
        "DEMO_SEED": "true",
        "SEED_DEFAULT_PASSWORD": "ChangeMe!2026",
        "OTP_RESEND_SECONDS": "0",
        "OTP_DELIVERY_TIMEOUT_SECONDS": "3",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import NotificationDelivery  # noqa: E402

CAPTURED: list[dict] = []
PASSED: list[str] = []


def ok(label: str) -> None:
    PASSED.append(label)
    print(f"  PASS  {label}")


class MockProvider(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length).decode("utf-8", "replace")
        CAPTURED.append(
            {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
        )
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"id": "mock-message-1", "sid": "SM_mock_1"}).encode())

    def log_message(self, *args):  # silence request logging
        return


def six_digit_code(text: str) -> str | None:
    match = re.search(r"\b(\d{6})\b", text)
    return match.group(1) if match else None


def otp_payload(response) -> dict:
    return response.json()


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8899), MockProvider)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    with TestClient(app) as client:
        election = client.get("/api/public/election").json()["election"]
        election_id = election["id"]

        # ── 1. real email delivery through the Resend HTTP API ──────────────
        response = client.post(
            "/api/accreditation/request-otp",
            json={"election_id": election_id, "voter_id": "SJC/AL/2004/001"},
        )
        assert response.status_code == 200, response.text
        data = otp_payload(response)
        assert data["delivery_channel"] == "email", data
        assert data["dev_otp"] is None, "OTP leaked to the client while DEV_EXPOSE_OTP=false"
        assert data["delivery"].startswith("e***@"), data["delivery"]
        ok("OTP delivered by email, no OTP in the API response")

        assert len(CAPTURED) == 1, f"expected one provider call, got {len(CAPTURED)}"
        call = CAPTURED[0]
        assert call["path"] == "/emails", call["path"]
        assert call["headers"]["authorization"] == "Bearer test-resend-key"
        payload = json.loads(call["body"])
        assert payload["to"] == ["emeka.nwosu@alumni.sjcjos.edu.ng"], payload["to"]
        email_otp = six_digit_code(payload["text"])
        assert email_otp and email_otp in payload["html"]
        assert email_otp not in response.text, "the OTP appeared in the HTTP response"
        ok("provider received the OTP for the registered email only (never logged/returned)")

        verified = client.post(
            "/api/accreditation/verify-otp",
            json={
                "election_id": election_id,
                "voter_id": "SJC/AL/2004/001",
                "challenge_id": data["challenge_id"],
                "otp": email_otp,
            },
        )
        assert verified.status_code == 200, verified.text
        ok("the emailed OTP completes accreditation")

        with SessionLocal() as db:
            rows = db.execute(select(NotificationDelivery)).scalars().all()
            assert rows and rows[-1].status == "sent"
            assert email_otp not in (rows[-1].error or "")
            assert rows[-1].recipient_masked.startswith("e***@")
        ok("delivery is recorded without the OTP or full address")

        # ── 2. exposure policy ──────────────────────────────────────────────
        settings.dev_expose_otp = True
        settings.environment = "development"
        settings.app_origin = "https://elections.example.org"
        assert settings.expose_dev_otp is False, "non-loopback origin exposed the OTP"
        settings.app_origin = "http://localhost:3000"
        settings.environment = "production"
        assert settings.expose_dev_otp is False, "production exposed the OTP"
        settings.environment = "staging"
        assert settings.expose_dev_otp is False, "staging exposed the OTP"
        settings.environment = "development"
        assert settings.expose_dev_otp is True
        ok("on-screen OTP is refused outside local development")

        # ── 3. production without a provider must fail closed ───────────────
        settings.email_provider = "none"
        settings.resend_api_key = ""
        settings.sms_provider = "none"
        settings.environment = "production"
        settings.dev_expose_otp = True  # still must not expose anything
        blocked = client.post(
            "/api/accreditation/request-otp",
            json={"election_id": election_id, "voter_id": "SJC/AL/2005/003"},
        )
        assert blocked.status_code == 503, f"expected 503, got {blocked.status_code}: {blocked.text}"
        assert "dev_otp" not in blocked.text
        ok("production without a delivery provider fails closed (503, no OTP)")

        # ── 4. SMS fallback through Twilio ──────────────────────────────────
        settings.environment = "development"
        settings.app_origin = "http://localhost:3000"
        settings.sms_provider = "twilio"
        settings.twilio_account_sid = "AC_test"
        settings.twilio_auth_token = "test-token"
        settings.twilio_from_number = "+2348000000000"
        settings.sms_api_base = "http://127.0.0.1:8899"
        sms = client.post(
            "/api/accreditation/request-otp",
            json={"election_id": election_id, "voter_id": "SJC/AL/2006/005"},
        )
        assert sms.status_code == 200, sms.text
        sms_data = sms.json()
        assert sms_data["delivery_channel"] == "sms", sms_data
        assert sms_data["dev_otp"] is None
        sms_call = CAPTURED[-1]
        assert "/Messages.json" in sms_call["path"]
        assert sms_call["headers"]["authorization"].startswith("Basic ")
        from urllib.parse import parse_qs

        sent = parse_qs(sms_call["body"])
        assert sent["To"][0].startswith("+234"), sent["To"]
        assert sent["From"] == ["+2348000000000"], sent["From"]
        sms_otp = six_digit_code(sent["Body"][0])
        assert sms_otp and "SJC Jos Alumni Election" in sent["Body"][0]
        verified_sms = client.post(
            "/api/accreditation/verify-otp",
            json={
                "election_id": election_id,
                "voter_id": "SJC/AL/2006/005",
                "challenge_id": sms_data["challenge_id"],
                "otp": sms_otp,
            },
        )
        assert verified_sms.status_code == 200, verified_sms.text
        ok("SMS fallback sends an E.164 message and the code accredits the voter")

        # ── 5. provider failure is reported without exposing the OTP ────────
        settings.email_provider = "resend"
        settings.resend_api_key = "test-resend-key"
        settings.email_api_base = "http://127.0.0.1:8898"  # nothing listening
        settings.sms_provider = "none"
        failed = client.post(
            "/api/accreditation/request-otp",
            json={"election_id": election_id, "voter_id": "SJC/AL/2007/007"},
        )
        assert failed.status_code == 502, f"expected 502, got {failed.status_code}: {failed.text}"
        assert "dev_otp" not in failed.text
        with SessionLocal() as db:
            last = db.execute(select(NotificationDelivery)).scalars().all()[-1]
            assert last.status == "failed" and "smtp" not in (last.error or "")
        ok("provider outage fails safely, records the failure, and never leaks the OTP")

        # ── 6. local development on-screen mode ─────────────────────────────
        settings.email_provider = "none"
        settings.sms_provider = "none"
        settings.environment = "development"
        settings.dev_expose_otp = True
        local = client.post(
            "/api/accreditation/request-otp",
            json={"election_id": election_id, "voter_id": "SJC/AL/2008/009"},
        )
        assert local.status_code == 200, local.text
        local_data = local.json()
        assert local_data["delivery_channel"] == "development"
        assert local_data["dev_otp"] and len(local_data["dev_otp"]) == 6
        ok("local development still shows the OTP when explicitly enabled")

    server.shutdown()
    print("\n" + "=" * 64)
    print(f"OTP DELIVERY TESTS PASSED: {len(PASSED)} checks")
    print("=" * 64)
    for label in PASSED:
        print(f"  • {label}")


if __name__ == "__main__":
    main()
