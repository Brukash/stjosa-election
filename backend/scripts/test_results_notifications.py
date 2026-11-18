"""Focused tests for the declared-results voter email path.

Runs the real FastAPI app against a temporary SQLite database and a local mock
Resend provider that can be told to reject specific recipients.

Covers:
  * only approved, eligible voters are emailed;
  * duplicate addresses are skipped and count as unavailable;
  * a delivery row is recorded for every attempted send, sent or failed;
  * a provider failure never breaks or rolls back the declaration.

Run:  .venv/Scripts/python.exe scripts/test_results_notifications.py
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

TMP = Path(tempfile.mkdtemp(prefix="sjc-results-notification-test-"))
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
        "EMAIL_API_BASE": "http://127.0.0.1:8898",
        "DEMO_SEED": "true",
        "SEED_DEFAULT_PASSWORD": "ChangeMe!2026",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import crypto  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Election, NotificationDelivery, ResultDeclaration, Voter  # noqa: E402
from app.notifications import (  # noqa: E402
    _result_lines,
    mask_email,
    notify_results_declared,
)

PASSWORD = "ChangeMe!2026"
RESULTS_SUBJECT = "Official results declared"
CAPTURED: list[dict] = []
FAIL_ADDRESSES: set[str] = set()
PASSED: list[str] = []


def ok(label: str) -> None:
    PASSED.append(label)
    print(f"  PASS  {label}")


class MockEmailProvider(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        recipients = [str(item).lower() for item in body.get("to") or []]
        CAPTURED.append({"path": self.path, "body": body, "recipients": recipients})
        if any(recipient in FAIL_ADDRESSES for recipient in recipients):
            payload = {"message": "simulated provider rejection"}
            self.send_response(500)
        else:
            payload = {"id": f"email-mock-{len(CAPTURED)}"}
            self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, *args):  # silence request logging
        return


def results_calls() -> list[dict]:
    return [
        call
        for call in CAPTURED
        if call["path"] == "/emails"
        and str(call["body"].get("subject", "")).startswith(RESULTS_SUBJECT)
    ]


def login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"authorization": f"Bearer {response.json()['access_token']}"}


def cast_one_ballot(client: TestClient, election: dict) -> None:
    """Accredit one seeded voter and cast a ballot so the tally has something to count."""
    election_id = election["id"]
    verified = client.post(
        "/api/accreditation/verify-voter",
        json={"election_id": election_id, "voter_id": "SJC/AL/2004/001"},
    )
    assert verified.status_code == 200, verified.text
    data = verified.json()

    modulus, exponent = (
        int(crypto.credential_public_numbers()["n"], 16),
        int(crypto.credential_public_numbers()["e"], 16),
    )
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
    prepared_response = client.post(
        "/api/voting/prepare",
        json={
            "election_id": election_id,
            **credential,
            "selections": {
                position["id"]: position["candidates"][0]["id"]
                for position in election["positions"]
            },
        },
    )
    assert prepared_response.status_code == 200, prepared_response.text
    cast = client.post(
        f"/api/voting/{prepared_response.json()['prepared_id']}/cast", json=credential
    )
    assert cast.status_code == 200, cast.text


def check_result_lines() -> None:
    """A tie must be stated as a tie, and no candidate may be named twice."""
    tie_lines = _result_lines({"positions": [{
        "title": "President", "seats": 1, "winners": ["Amara Obi"],
        "candidates": [
            {"full_name": "Amara Obi", "votes": 4, "is_winner": True},
            {"full_name": "Bola Ade", "votes": 4, "is_winner": False},
            {"full_name": "Chidi Eze", "votes": 1, "is_winner": False},
        ],
    }]})
    assert tie_lines == [(
        "President",
        "Tie: Amara Obi and Bola Ade on 4 votes each - no winner returned. Others: Chidi Eze 1.",
    )], tie_lines
    assert "No candidate returned" not in tie_lines[0][1]
    assert tie_lines[0][1].count("Amara Obi") == 1
    ok("a tied position names the tied candidates instead of reporting no candidate")

    three_way = _result_lines({"positions": [{
        "title": "Secretary General", "seats": 1, "winners": [],
        "candidates": [
            {"full_name": "Amara Obi", "votes": 2, "is_winner": False},
            {"full_name": "Bola Ade", "votes": 2, "is_winner": False},
            {"full_name": "Chidi Eze", "votes": 2, "is_winner": False},
        ],
    }]})[0][1]
    assert three_way == (
        "Tie: Amara Obi, Bola Ade and Chidi Eze on 2 votes each - no winner returned."
    ), three_way
    ok("a three-way tie names every tied candidate")

    win_line = _result_lines({"positions": [{
        "title": "President", "seats": 1, "winners": ["Amara Obi"],
        "candidates": [
            {"full_name": "Amara Obi", "votes": 4, "is_winner": True},
            {"full_name": "Bola Ade", "votes": 3, "is_winner": False},
            {"full_name": "Chidi Eze", "votes": 1, "is_winner": False},
        ],
    }]})[0][1]
    assert win_line == "Amara Obi elected with 4 votes. Others: Bola Ade 3; Chidi Eze 1.", win_line
    assert win_line.count("Amara Obi") == 1, win_line
    ok("a winner is named once with their vote count")

    no_votes = _result_lines({"positions": [{
        "title": "Public Relations Officer", "seats": 1, "winners": [],
        "candidates": [
            {"full_name": "Amara Obi", "votes": 0, "is_winner": False},
            {"full_name": "Bola Ade", "votes": 0, "is_winner": False},
        ],
    }]})[0][1]
    assert no_votes == "No votes were cast for this position.", no_votes
    ok("an uncontested zero-vote position says no votes were cast")


def main() -> None:
    check_result_lines()
    server = ThreadingHTTPServer(("127.0.0.1", 8898), MockEmailProvider)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    with TestClient(app) as client:
        election = client.get("/api/public/election").json()["election"]
        election_id = election["id"]
        reference = election["reference"]
        chair = login(client, "chairman@sjcjos-alumni.org")
        returning = login(client, "returning@sjcjos-alumni.org")

        # ── drive the election to a declared result ─────────────────────────
        cast_one_ballot(client, election)
        for headers, path, payload in (
            (chair, f"/api/elections/{election_id}/status", {"status": "voting_closed"}),
            (chair, f"/api/tally/{election_id}/authorise", None),
            (returning, f"/api/tally/{election_id}/authorise", None),
            (returning, f"/api/tally/{election_id}/run", None),
            (returning, f"/api/results/{election_id}/submit", {"comments": "Ready for approval"}),
        ):
            response = client.post(path, headers=headers, **({"json": payload} if payload else {}))
            assert response.status_code == 200, (path, response.status_code, response.text)

        # ── shape the register: approved/eligible, duplicate, no email, excluded ──
        with SessionLocal() as db:
            voters = db.execute(
                select(Voter)
                .where(Voter.election_id == election_id)
                .order_by(Voter.voter_id)
            ).scalars().all()
            assert len(voters) >= 7, len(voters)
            for voter in voters:
                voter.register_status = "pending"
                voter.is_eligible = True

            sent_ok, rejected, also_sent_ok, duplicate, no_email, ineligible, pending = voters[:7]
            for voter in (sent_ok, rejected, also_sent_ok, duplicate, no_email):
                voter.register_status = "approved"
            sent_ok.email = "Amina.Results@example.test"
            rejected.email = "musa.rejected@example.test"
            also_sent_ok.email = "ngozi.results@example.test"
            duplicate.email = "amina.results@example.test"      # same mailbox, different voter
            no_email.email = None
            ineligible.register_status = "approved"
            ineligible.is_eligible = False
            ineligible.email = "ineligible.results@example.test"
            pending.register_status = "pending"
            pending.email = "pending.results@example.test"
            expected_voter_ids = {sent_ok.id, rejected.id, also_sent_ok.id}
            rejected_voter_id = rejected.id
            db.commit()

        FAIL_ADDRESSES.clear()
        FAIL_ADDRESSES.add("musa.rejected@example.test")
        started_at = len(CAPTURED)
        start_rows = None
        with SessionLocal() as db:
            start_rows = len(
                db.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.election_id == election_id,
                        NotificationDelivery.purpose == "results_declared",
                    )
                ).scalars().all()
            )

        # ── the Chairman approves and declares ──────────────────────────────
        approved = client.post(f"/api/results/{election_id}/approve", headers=chair)
        assert approved.status_code == 200, approved.text
        payload = approved.json()
        summary = payload["voter_notifications"]
        calls = results_calls()

        assert summary == {
            "voters": 5,          # approved + eligible, including duplicate and no-email
            "email_sent": 2,
            "email_failed": 1,
            "email_unavailable": 2,  # duplicate address + missing address
        }, summary
        assert len(calls) == 3, [(call["body"]["to"], call["body"]["subject"]) for call in calls]
        assert all(len(call["recipients"]) == 1 for call in calls), \
            "a voter received a shared recipient list"
        assert {call["recipients"][0] for call in calls} == {
            "amina.results@example.test",
            "musa.rejected@example.test",
            "ngozi.results@example.test",
        }, [call["recipients"] for call in calls]
        ok("only approved eligible voters are emailed, one recipient per message")

        assert all(
            call["recipients"][0] not in {
                "ineligible.results@example.test", "pending.results@example.test"
            }
            for call in calls
        )
        ok("ineligible and unapproved voters receive no result email")

        duplicate_calls = [
            call for call in calls if call["recipients"][0] == "amina.results@example.test"
        ]
        assert len(duplicate_calls) == 1, len(duplicate_calls)
        assert summary["email_sent"] + summary["email_failed"] == len(calls)
        ok("a duplicate address is sent once and reported as unavailable")

        body = next(
            call["body"] for call in calls
            if call["recipients"][0] == "ngozi.results@example.test"
        )
        assert body["subject"] == f"{RESULTS_SUBJECT} - {reference}", body["subject"]
        assert "http://localhost:3000/results" in body["text"], body["text"]
        assert "declaration version 1" in body["text"], body["text"]
        assert "does not include your candidate selections" not in body["text"]
        assert "no record of how any individual voted" in body["html"], body["html"]
        for position in election["positions"]:
            assert position["title"] in body["text"], position["title"]
            winner = position["candidates"][0]["full_name"]
            assert winner in body["text"], winner
        ok("the result email carries the published figures, version and public results link")

        with SessionLocal() as db:
            declaration = db.execute(
                select(ResultDeclaration).where(ResultDeclaration.election_id == election_id)
            ).scalar_one()
            rows = db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.election_id == election_id,
                    NotificationDelivery.purpose == "results_declared",
                )
            ).scalars().all()
            stored_election = db.get(Election, election_id)
            assert start_rows == 0
            assert len(rows) == 3, [(row.status, row.recipient_masked) for row in rows]
            assert {row.voter_row_id for row in rows} == expected_voter_ids
            by_status = {}
            for row in rows:
                by_status.setdefault(row.status, []).append(row)
            assert len(by_status["sent"]) == 2, by_status
            assert len(by_status["failed"]) == 1, by_status
            failed = by_status["failed"][0]
            assert failed.voter_row_id == rejected_voter_id, "wrong delivery row"
            assert failed.recipient_masked == mask_email("musa.rejected@example.test")
            assert failed.error, "a failed delivery must record why"
            assert all(row.channel == "email" and row.challenge_id is None for row in rows)
            assert stored_election.status == "declared", stored_election.status
            assert declaration.version == 1 and declaration.is_current is True
            assert declaration.signature and payload["signature_valid"] is True
        ok("one delivery row is recorded per attempt, with the failure reason")

        assert payload["version"] == 1 and payload["is_current"] is True
        assert payload["figures"]["positions"]
        ok("a rejected recipient does not break or roll back the declaration")

        # ── total provider outage: nothing raises, nothing is rolled back ───
        FAIL_ADDRESSES.clear()
        FAIL_ADDRESSES.update({
            "amina.results@example.test",
            "musa.rejected@example.test",
            "ngozi.results@example.test",
        })
        with SessionLocal() as db:
            stored_election = db.get(Election, election_id)
            declaration = db.execute(
                select(ResultDeclaration).where(ResultDeclaration.election_id == election_id)
            ).scalar_one()
            outage = notify_results_declared(
                db,
                election=stored_election,
                figures=declaration.figures,
                declared_at=declaration.declared_at,
                version=declaration.version,
                request_ip="127.0.0.1",
            )
            assert outage == {
                "voters": 5,
                "email_sent": 0,
                "email_failed": 3,
                "email_unavailable": 2,
            }, outage
        with SessionLocal() as db:
            stored_election = db.get(Election, election_id)
            declaration = db.execute(
                select(ResultDeclaration).where(ResultDeclaration.election_id == election_id)
            ).scalar_one()
            rows = db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.election_id == election_id,
                    NotificationDelivery.purpose == "results_declared",
                )
            ).scalars().all()
            assert stored_election.status == "declared", stored_election.status
            assert declaration.version == 1 and declaration.is_current is True
            assert len(rows) == 6, len(rows)
            assert sum(1 for row in rows if row.status == "failed") == 4
        ok("a total provider outage raises nothing and leaves the declaration intact")

    server.shutdown()
    print("\n" + "=" * 72)
    print(f"DECLARED-RESULT EMAIL TESTS PASSED: {len(PASSED)} checks")
    print("=" * 72)
    for label in PASSED:
        print(f"  • {label}")


if __name__ == "__main__":
    main()
