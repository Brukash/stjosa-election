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
        "WHATSAPP_PROVIDER": "meta",
        "WHATSAPP_ACCESS_TOKEN": "test-wa-token",
        "WHATSAPP_PHONE_NUMBER_ID": "123456789",
        "WHATSAPP_API_BASE": "http://127.0.0.1:8899",
        "WHATSAPP_REGISTRATION_TEMPLATE_NAME": "sjc_registration_confirmation",
        "WHATSAPP_REGISTRATION_TEMPLATE_LANGUAGE": "en_US",
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
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AccreditationRecord,
    AccreditationSession,
    AuditLog,
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
        assert notice["whatsapp_sent"] == eligible - 1, notice
        assert notice["whatsapp_no_consent"] == 1, notice
        assert notice["email_failed"] == 0 and notice["whatsapp_failed"] == 0, notice
        assert len(notice_calls) == 2 * eligible - 1, [call["path"] for call in notice_calls]

        email_notice = json.loads(next(call for call in notice_calls if call["path"] == "/emails")["body"])
        whatsapp_notice = json.loads(
            next(call for call in notice_calls if call["path"] == "/123456789/messages")["body"]
        )
        assert "Voter ID SJC/AL/" in email_notice["subject"], email_notice["subject"]
        assert "Your Voter ID is SJC/AL/" in email_notice["text"], email_notice["text"]
        assert "OTP" not in email_notice["text"]
        assert "one-time password" not in email_notice["text"].lower()
        assert whatsapp_notice["template"]["name"] == "sjc_registration_confirmation"
        wa_params = whatsapp_notice["template"]["components"][0]["parameters"]
        assert len(wa_params) == 3, wa_params
        assert all(item["type"] == "text" and item["text"] for item in wa_params)
        ok("approval emails the member's Voter ID and sends the WhatsApp utility notice")

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
        ok("notice deliveries are recorded separately per channel and voter")

        # ── 5. repeated approval does not resend successful notices ──────────
        again_start = len(CAPTURED)
        again = client.post(f"/api/register/{election_id}/approve", headers=chair_headers)
        assert again.status_code == 200, again.text
        again_notice = again.json()["notifications"]
        assert len(CAPTURED) == again_start
        assert again_notice["email_already_sent"] == eligible, again_notice
        assert again_notice["whatsapp_already_sent"] == eligible - 1, again_notice
        assert again_notice["whatsapp_no_consent"] == 1, again_notice
        ok("repeated register approval does not resend successful notices")

        # ── 6. read boundaries and provider readiness ────────────────────────
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
        assert delivery_stats["sent"] >= 2 * eligible - 1
        assert delivery_stats["failed"] == 0
        assert {row["channel"] for row in delivery_stats["by_channel"]} >= {
            "email",
            "whatsapp",
        }
        assert overview.json()["live"]["failed_identity_checks"] >= 1
        ok("committee monitoring reports notice delivery and failed identity checks without secrets")

        # ── 7. casting records turnout without linking it to the ballot ─────
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
        cast = client.post(
            f"/api/voting/{prepared['prepared_id']}/cast", json=credential
        )
        assert cast.status_code == 200, cast.text

        with SessionLocal() as db:
            voted_voter = db.execute(
                select(Voter).where(Voter.voter_id == "SJC/AL/2004/001")
            ).scalar_one()
            assert voted_voter.has_voted_at is not None
            assert voted_voter.turnout_token_hash is None

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
