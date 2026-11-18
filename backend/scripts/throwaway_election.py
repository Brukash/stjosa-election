"""Create, list or close a throwaway election for exercising the voter flow.

This writes to whatever database ``DATABASE_URL`` points at, so it is built to be
explicit: it needs ``--yes``, it labels everything it creates as a test, and it
refuses to reuse a reference. Use ``close`` to archive it the moment the check is
finished, which takes it off every voter-facing page while keeping its records.

    # against production (secrets come from the environment, never the command)
    .venv/Scripts/python.exe scripts/throwaway_election.py create --yes
    .venv/Scripts/python.exe scripts/throwaway_election.py close --reference SJCJ-TEST-...
    .venv/Scripts/python.exe scripts/throwaway_election.py list
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app import crypto  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Candidate,
    Election,
    ElectionEvent,
    ElectionPosition,
    ElectionVerificationSetting,
    Voter,
)
from app.services import configuration_hash  # noqa: E402

POSITIONS = (
    ("Test Position One", "Throwaway position for the voter-flow check."),
    ("Test Position Two", "Throwaway position for the voter-flow check."),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create(db, args: argparse.Namespace) -> dict:
    now = _now()
    reference = args.reference or f"SJCJ-TEST-{now:%Y%m%d%H%M%S}"
    if db.execute(select(Election).where(Election.reference == reference)).scalar_one_or_none():
        raise SystemExit(f"An election with reference {reference} already exists.")

    election = Election(
        title=f"TEST — {args.title}",
        description=(
            "Throwaway election used to check the voter flow end to end. It is not a real "
            "contest and carries no real candidates."
        ),
        reference=reference,
        year=now.year,
        opens_at=now - timedelta(minutes=10),
        closes_at=now + timedelta(hours=args.hours),
        timezone="Africa/Lagos",
        status="voting_open",
        eligibility_rules="Test register only. This election is a technical check.",
        voting_rules="One test ballot per test voter. Selections cannot be changed after casting.",
        voter_visible=True,
        approved_at=now,
        locked_at=now,
    )
    db.add(election)
    db.flush()

    db.add(ElectionVerificationSetting(election_id=election.id, approved_at=now))

    for index, (title, description) in enumerate(POSITIONS):
        position = ElectionPosition(
            election_id=election.id,
            title=title,
            description=description,
            seats=1,
            order_index=index,
            approved=True,
        )
        db.add(position)
        db.flush()
        for candidate_index, suffix in enumerate(("A", "B")):
            db.add(
                Candidate(
                    election_id=election.id,
                    position_id=position.id,
                    full_name=f"Test Candidate {index + 1}{suffix}",
                    bio="Placeholder candidate for a throwaway election.",
                    manifesto="This candidate exists only so the ballot has something to mark.",
                    order_index=candidate_index,
                    approved=True,
                )
            )

    db.add(
        Voter(
            election_id=election.id,
            voter_id=args.voter_id,
            full_name=args.voter_name,
            email="test.voter@example.test",
            alumni_set="Test",
            is_eligible=True,
            register_status="approved",
        )
    )
    db.flush()

    # Public keys only. The private bundle is wrapped with the deployment's
    # MASTER_KEY, which this script does not hold, so storing one here would look
    # provisioned while being undecryptable there. A throwaway check never needs
    # to be counted; the console shows the keys as missing, which is the truth.
    keys = crypto.create_election_keys(election.id)
    election.tally_public_key = keys["tally_public_key"]
    election.signing_public_key = keys["signing_public_key"]
    try:
        election.credential_public_key = json.dumps(crypto.credential_public_numbers())
    except Exception as exc:  # noqa: BLE001 - the deployment publishes its own credential key
        print(f"note: no credential public key stored ({type(exc).__name__}); the API publishes its own")

    election.configuration_hash = configuration_hash(db, election)
    for event_type, message in (
        ("configuration.approved", "Throwaway election created for a voter-flow check"),
        ("status.changed", "Voting opened for the throwaway election"),
    ):
        db.add(ElectionEvent(election_id=election.id, event_type=event_type, message=message))
    db.commit()

    return {
        "created": True,
        "election_id": election.id,
        "reference": election.reference,
        "title": election.title,
        "status": election.status,
        "voter_id": args.voter_id,
        "closes_at": election.closes_at.isoformat(),
        "positions": len(POSITIONS),
    }


def close(db, args: argparse.Namespace) -> dict:
    election = db.execute(
        select(Election).where(Election.reference == args.reference)
    ).scalar_one_or_none()
    if not election:
        raise SystemExit(f"No election with reference {args.reference}.")
    if not election.title.startswith("TEST"):
        raise SystemExit("Refusing to close an election that is not marked TEST.")
    previous = election.status
    election.status = "archived"
    election.voter_visible = False
    db.add(
        ElectionEvent(
            election_id=election.id,
            event_type="status.changed",
            message="Throwaway election archived after the voter-flow check",
        )
    )
    db.commit()
    return {"closed": True, "reference": election.reference, "from": previous, "to": election.status}


def show(db) -> dict:
    rows = db.execute(select(Election).order_by(Election.created_at)).scalars()
    return {
        "elections": [
            {
                "reference": row.reference,
                "status": row.status,
                "title": row.title,
                "voter_visible": row.voter_visible,
                "test": row.reference.startswith("SJCJ-TEST-"),
            }
            for row in rows
        ]
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create_parser = sub.add_parser("create")
    create_parser.add_argument("--reference", help="Reference to use (default SJCJ-TEST-<timestamp>)")
    create_parser.add_argument("--title", default="Voter flow check")
    create_parser.add_argument("--voter-id", default="TEST/AL/0001")
    create_parser.add_argument("--voter-name", default="Test Voter")
    create_parser.add_argument("--hours", type=int, default=2, help="Hours before it closes itself")
    create_parser.add_argument("--yes", action="store_true", help="Confirm writing to this database")

    close_parser = sub.add_parser("close")
    close_parser.add_argument("--reference", required=True)

    sub.add_parser("list")

    args = parser.parse_args()
    database = os.getenv("DATABASE_URL", "")
    if not database:
        raise SystemExit("DATABASE_URL is not set.")
    host = database.split("@")[-1].split("/")[0] if "@" in database else database.split("://")[0]
    print(f"database: {host}")

    with SessionLocal() as db:
        if args.command == "create":
            if not args.yes:
                raise SystemExit("Refusing to create an election without --yes.")
            print(json.dumps(create(db, args), indent=2))
        elif args.command == "close":
            print(json.dumps(close(db, args), indent=2))
        else:
            print(json.dumps(show(db), indent=2))


if __name__ == "__main__":
    main()
