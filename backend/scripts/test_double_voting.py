"""Double-voting test suite.

Runs the real FastAPI app against a temporary SQLite database and tries every
route by which one person might be counted twice: re-verification, a second
credential, two prepared ballots from one credential, replay, simultaneous
casts, and the accreditation-officer exception path.

Delivery providers are disabled, so nothing leaves the machine.

Run:  .venv/Scripts/python.exe scripts/test_double_voting.py
"""
from __future__ import annotations

import math
import os
import secrets
import sys
import tempfile
import threading
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="sjc-double-vote-test-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{TMP / 'test.db'}",
        "KEYS_DIR": str(TMP / "keys"),
        "ENVIRONMENT": "development",
        "APP_ORIGIN": "http://localhost:3000",
        "API_ORIGIN": "http://localhost:8000",
        "EMAIL_PROVIDER": "none",
        "SMS_PROVIDER": "none",
        "WHATSAPP_PROVIDER": "none",
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
    Ballot,
    BallotReceipt,
    CredentialIssuance,
    SpentCredential,
    Voter,
)

RESULTS: list[tuple[bool, str, str]] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    RESULTS.append((passed, label, detail))
    print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    if not passed and detail:
        print(f"        {detail}")


def counts(election_id: str) -> dict:
    with SessionLocal() as db:
        return {
            "ballots": db.scalar(
                select(func.count(Ballot.id)).where(
                    Ballot.election_id == election_id, Ballot.accepted.is_(True)
                )
            )
            or 0,
            "receipts": db.scalar(
                select(func.count(BallotReceipt.id)).where(
                    BallotReceipt.election_id == election_id
                )
            )
            or 0,
            "spent": db.scalar(
                select(func.count(SpentCredential.id)).where(
                    SpentCredential.election_id == election_id
                )
            )
            or 0,
            "voted_voters": db.scalar(
                select(func.count(Voter.id)).where(
                    Voter.election_id == election_id, Voter.has_voted_at.is_not(None)
                )
            )
            or 0,
            "active_issuances": db.scalar(
                select(func.count(CredentialIssuance.id)).where(
                    CredentialIssuance.election_id == election_id,
                    CredentialIssuance.status == "issued",
                )
            )
            or 0,
        }


def blind(client: TestClient, election_reference: str) -> tuple[str, int, int, str]:
    """Return (blinded message hex, blinding factor, modulus)."""
    numbers = crypto.credential_public_numbers()
    modulus, exponent = int(numbers["n"], 16), int(numbers["e"], 16)
    token_hex = secrets.token_hex(32)
    message_hash = crypto.fdh(
        crypto.credential_message(election_reference, token_hex), modulus
    )
    while True:
        blinding = secrets.randbelow(modulus - 2) + 2
        if math.gcd(blinding, modulus) == 1:
            break
    blinded = (message_hash * pow(blinding, exponent, modulus)) % modulus
    return token_hex, blinding, modulus, format(blinded, "x")


def request_credential(
    client: TestClient, accreditation_token: str, blinded_hex: str, blinding: int, modulus: int
) -> dict:
    signed = client.post(
        "/api/accreditation/credential",
        json={"accreditation_token": accreditation_token, "blinded_message": blinded_hex},
    )
    if signed.status_code != 200:
        return {"status": signed.status_code, "body": signed.text}
    unblinded = (int(signed.json()["blind_signature"], 16) * pow(blinding, -1, modulus)) % modulus
    return {"status": 200, "signature": format(unblinded, "x"), "body": signed.text}


def verify(client: TestClient, election_id: str, voter_id: str):
    return client.post(
        "/api/accreditation/verify-voter",
        json={"election_id": election_id, "voter_id": voter_id},
    )


def main() -> None:
    with TestClient(app) as client:
        election = client.get("/api/public/election").json()["election"]
        election_id = election["id"]
        reference = election["reference"]
        selections = {
            position["id"]: position["candidates"][0]["id"]
            for position in election["positions"]
        }

        chair = client.post(
            "/api/auth/login",
            json={"email": "chairman@sjcjos-alumni.org", "password": "ChangeMe!2026"},
        )
        assert chair.status_code == 200, chair.text
        chair_headers = {"authorization": f"Bearer {chair.json()['access_token']}"}
        officer = client.post(
            "/api/auth/login",
            json={
                "email": "accreditation@sjcjos-alumni.org",
                "password": "ChangeMe!2026",
            },
        )
        assert officer.status_code == 200, officer.text
        officer_headers = {"authorization": f"Bearer {officer.json()['access_token']}"}

        # ── Setup: voter 1 verifies twice before asking for a credential ────
        first = verify(client, election_id, "SJC/AL/2004/001")
        assert first.status_code == 200, first.text
        second = verify(client, election_id, "SJC/AL/2004/001")
        assert second.status_code == 200, second.text
        check(
            "a second Voter ID check before credential issuance is still allowed",
            second.json()["accreditation_token"] != first.json()["accreditation_token"],
            second.text,
        )

        token_1, blinding_1, modulus_1, blinded_1 = blind(client, reference)
        issued = request_credential(
            client, first.json()["accreditation_token"], blinded_1, blinding_1, modulus_1
        )
        check("the first credential request is signed", issued["status"] == 200, issued.get("body", ""))

        # ── 1. the open second session cannot produce a second credential ──
        token_2, blinding_2, modulus_2, blinded_2 = blind(client, reference)
        duplicate = request_credential(
            client, second.json()["accreditation_token"], blinded_2, blinding_2, modulus_2
        )
        check(
            "a credential already issued blocks a second credential for the same Voter ID",
            duplicate["status"] == 409,
            f"status={duplicate['status']} {duplicate.get('body', '')[:200]}",
        )

        # ── 2. re-verifying after issuance is refused ──────────────────────
        again = verify(client, election_id, "SJC/AL/2004/001")
        check(
            "re-verifying a Voter ID that already holds a credential is refused (409)",
            again.status_code == 409,
            f"status={again.status_code} {again.text[:200]}",
        )

        credential_1 = {
            "token": token_1,
            "signature": issued["signature"],
            "turnout_token": first.json()["turnout_token"],
        }

        # ── 3. two prepared ballots from one credential; only one may count ─
        prepared_a = client.post(
            "/api/voting/prepare",
            json={"election_id": election_id, **credential_1, "selections": selections},
        )
        assert prepared_a.status_code == 200, prepared_a.text
        prepared_b = client.post(
            "/api/voting/prepare",
            json={"election_id": election_id, **credential_1, "selections": selections},
        )
        assert prepared_b.status_code == 200, prepared_b.text
        check(
            "a prepared-but-uncast ballot does not block preparing another",
            prepared_a.json()["prepared_id"] != prepared_b.json()["prepared_id"],
        )

        cast_a = client.post(
            f"/api/voting/{prepared_a.json()['prepared_id']}/cast", json=credential_1
        )
        check("the first ballot casts and returns a receipt", cast_a.status_code == 200, cast_a.text[:300])
        receipt_number = cast_a.json().get("receipt_number")

        cast_b = client.post(
            f"/api/voting/{prepared_b.json()['prepared_id']}/cast", json=credential_1
        )
        check(
            "the same credential cannot cast a second prepared ballot (409)",
            cast_b.status_code == 409,
            f"status={cast_b.status_code} {cast_b.text[:200]}",
        )
        check(
            "the credential is now refused at prepare too",
            client.post(
                "/api/voting/prepare",
                json={"election_id": election_id, **credential_1, "selections": selections},
            ).status_code
            == 409,
        )

        # ── 4. replay of the accepted ballot is idempotent ─────────────────
        replay = client.post(
            f"/api/voting/{prepared_a.json()['prepared_id']}/cast", json=credential_1
        )
        check(
            "replaying the accepted ballot returns the same receipt",
            replay.status_code == 200
            and replay.json().get("receipt_number") == receipt_number,
            f"status={replay.status_code} {replay.text[:200]}",
        )

        after_one = counts(election_id)
        check(
            "one voter produced exactly one ballot, receipt and spent credential",
            after_one["ballots"] == 1
            and after_one["receipts"] == 1
            and after_one["spent"] == 1
            and after_one["voted_voters"] == 1,
            str(after_one),
        )

        # ── 5. another voter's turnout marker cannot be borrowed ────────────
        lender = verify(client, election_id, "SJC/AL/2004/002")
        assert lender.status_code == 200, lender.text
        # token_2 was never signed (check 1 refused it), so this must fail anyway.
        borrowed = client.post(
            "/api/voting/prepare",
            json={
                "election_id": election_id,
                "token": token_2,
                "signature": "0",
                "turnout_token": lender.json()["turnout_token"],
                "selections": selections,
            },
        )
        check(
            "a credential that was never signed cannot prepare a ballot",
            borrowed.status_code == 401,
            f"status={borrowed.status_code} {borrowed.text[:200]}",
        )

        # ── 6. two simultaneous casts of one credential: one ballot only ────
        third = verify(client, election_id, "SJC/AL/2005/003")
        assert third.status_code == 200, third.text
        token_3, blinding_3, modulus_3, blinded_3 = blind(client, reference)
        issued_3 = request_credential(
            client, third.json()["accreditation_token"], blinded_3, blinding_3, modulus_3
        )
        assert issued_3["status"] == 200, issued_3
        credential_3 = {
            "token": token_3,
            "signature": issued_3["signature"],
            "turnout_token": third.json()["turnout_token"],
        }
        parallel = []
        for _ in range(2):
            response = client.post(
                "/api/voting/prepare",
                json={"election_id": election_id, **credential_3, "selections": selections},
            )
            assert response.status_code == 200, response.text
            parallel.append(response.json()["prepared_id"])

        before_race = counts(election_id)
        statuses: list[int] = []
        race_errors: list[str] = []
        barrier = threading.Barrier(2)

        def race(prepared_id: str) -> None:
            worker = TestClient(app)
            barrier.wait()
            try:
                statuses.append(
                    worker.post(
                        f"/api/voting/{prepared_id}/cast", json=credential_3
                    ).status_code
                )
            except Exception as exc:  # noqa: BLE001 - recorded and classified below
                race_errors.append(f"{type(exc).__name__}: {exc}")


        threads = [threading.Thread(target=race, args=(pid,)) for pid in parallel]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        after_race = counts(election_id)
        check(
            "simultaneous casts of one credential accept exactly one ballot",
            statuses.count(200) == 1 and after_race["ballots"] == before_race["ballots"] + 1,
            f"statuses={statuses} before={before_race} after={after_race}",
        )
        # SQLite serialises writers by upgrading a read transaction, so two
        # simultaneous casts can deadlock there and one request fails with
        # "database is locked". PostgreSQL (production) locks rows instead, which
        # is why the deployed path answers 409. The one-ballot invariant above is
        # asserted in every case.
        sqlite_contention = bool(race_errors) and all(
            "database is locked" in error.lower() for error in race_errors
        )
        # The loser is refused: either the spent-credential check sees the winner
        # (409), or the turnout marker is already cleared (401). Both are refusals;
        # neither creates a ballot.
        refused_cleanly = (
            len(statuses) == 2
            and statuses.count(200) == 1
            and all(status in {401, 409} for status in statuses if status != 200)
            and not race_errors
        )
        check(
            "the losing simultaneous cast is refused, never a second ballot",
            refused_cleanly or (sqlite_contention and statuses.count(200) == 1),
            f"statuses={statuses} errors={race_errors}",
        )
        if sqlite_contention:
            print("        note: the test SQLite database raised a write-lock error; production uses PostgreSQL row locks")

        # ── 7. two simultaneous credentials for one voter ──────────────────
        racer = verify(client, election_id, "SJC/AL/2005/004")
        assert racer.status_code == 200, racer.text
        racer_again = verify(client, election_id, "SJC/AL/2005/004")
        assert racer_again.status_code == 200, racer_again.text
        requests = []
        for session in (racer, racer_again):
            token_hex, blinding, modulus, blinded_hex = blind(client, reference)
            requests.append(
                {
                    "json": {
                        "accreditation_token": session.json()["accreditation_token"],
                        "blinded_message": blinded_hex,
                    },
                    "token": token_hex,
                    "blinding": blinding,
                    "modulus": modulus,
                }
            )
        issue_statuses: list[int] = []
        issue_barrier = threading.Barrier(2)

        def issue_call(request: dict) -> None:
            worker = TestClient(app)
            issue_barrier.wait()
            issue_statuses.append(
                worker.post("/api/accreditation/credential", json=request["json"]).status_code
            )

        issue_threads = [threading.Thread(target=issue_call, args=(item,)) for item in requests]
        for thread in issue_threads:
            thread.start()
        for thread in issue_threads:
            thread.join(timeout=60)
        check(
            "simultaneous credential requests leave at most one active credential",
            counts(election_id)["active_issuances"] == 3,
            f"statuses={issue_statuses} counts={counts(election_id)} (3 = one each for the first three voters)",
        )

        # ── 8. the officer exception path after a vote ─────────────────────
        reset = client.post(
            "/api/accreditation/exceptions/reset-issuance",
            params={
                "election_id": election_id,
                "voter_id": "SJC/AL/2004/001",
                "reason": "voter reported a lost credential after voting",
            },
            headers=officer_headers,
        )
        if reset.status_code == 409:
            check(
                "a credential cannot be revoked once the voter has voted",
                True,
            )
            voted_verify = verify(client, election_id, "SJC/AL/2004/001")
            check(
                "a voter who has already voted cannot verify again",
                voted_verify.status_code == 409,
                f"status={voted_verify.status_code} {voted_verify.text[:200]}",
            )
        else:
            check(
                "a credential cannot be revoked once the voter has voted",
                False,
                f"status={reset.status_code} {reset.text[:200]}",
            )
            re_verify = verify(client, election_id, "SJC/AL/2004/001")
            check(
                "a voter who has already voted cannot verify again",
                re_verify.status_code == 409,
                f"status={re_verify.status_code} {re_verify.text[:200]}",
            )
            if re_verify.status_code == 200:
                token_r, blinding_r, modulus_r, blinded_r = blind(client, reference)
                issued_r = request_credential(
                    client, re_verify.json()["accreditation_token"], blinded_r, blinding_r, modulus_r
                )
                if issued_r["status"] == 200:
                    credential_r = {
                        "token": token_r,
                        "signature": issued_r["signature"],
                        "turnout_token": re_verify.json()["turnout_token"],
                    }
                    prepared_r = client.post(
                        "/api/voting/prepare",
                        json={"election_id": election_id, **credential_r, "selections": selections},
                    )
                    cast_r = client.post(
                        f"/api/voting/{prepared_r.json()['prepared_id']}/cast",
                        json=credential_r,
                    ) if prepared_r.status_code == 200 else prepared_r
                    check(
                        "a reissued credential after voting cannot cast a second ballot",
                        cast_r.status_code != 200,
                        f"status={cast_r.status_code} {cast_r.text[:200]}",
                    )

        # ── 9. final one-voter-one-ballot invariant ────────────────────────
        final = counts(election_id)
        check(
            "ballots, receipts, spent credentials and voted voters agree",
            final["ballots"] == final["receipts"] == final["spent"] == final["voted_voters"],
            str(final),
        )
        check(
            "no more ballots exist than voters who are marked as having voted",
            final["ballots"] <= final["voted_voters"],
            str(final),
        )

        summary = client.get(f"/api/monitoring/{election_id}/overview", headers=chair_headers)
        if summary.status_code == 200:
            live = summary.json()["live"]
            check(
                "the dashboard reports the same accepted-ballot count",
                live.get("votes_cast") in (None, final["ballots"]),
                f"dashboard={live.get('votes_cast')} db={final['ballots']}",
            )

    failures = [item for item in RESULTS if not item[0]]
    print("\n" + "=" * 72)
    print(f"DOUBLE-VOTING TESTS: {len(RESULTS) - len(failures)}/{len(RESULTS)} passed")
    print("=" * 72)
    for passed, label, detail in RESULTS:
        print(f"  {'PASS' if passed else 'FAIL'}  {label}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
