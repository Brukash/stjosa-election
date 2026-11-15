"""Add pre-approved test voters to one election.

This is a development utility only. It refuses to run when ENVIRONMENT is a
production environment, because the electoral register is frozen after voting
starts. Use it against a local database only.

Examples:
    .venv/Scripts/python.exe scripts/add_test_voters.py --allow-locked
    .venv/Scripts/python.exe scripts/add_test_voters.py --per-set 5 --allow-locked
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Election, ElectionEvent, Voter  # noqa: E402


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", "-", value.upper()).strip("-")
    return cleaned or "GENERAL"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--election-id", help="Election ID; defaults to the newest election")
    parser.add_argument("--per-set", type=int, default=3, help="Test voters per alumni set")
    parser.add_argument(
        "--allow-locked",
        action="store_true",
        help="Allow test insertion after voting has begun (local testing only)",
    )
    args = parser.parse_args()

    if settings.is_production:
        print("Refusing to add test voters in a production environment.", file=sys.stderr)
        return 2
    if args.per_set < 1 or args.per_set > 20:
        print("--per-set must be between 1 and 20.", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        if args.election_id:
            election = db.get(Election, args.election_id)
        else:
            election = db.execute(
                select(Election).order_by(Election.created_at.desc())
            ).scalars().first()
        if not election:
            print("No election found.", file=sys.stderr)
            return 1
        if election.locked_at and not args.allow_locked:
            print(
                "The register is locked because voting has begun. "
                "Pass --allow-locked for local testing.",
                file=sys.stderr,
            )
            return 1

        alumni_sets = sorted(
            {
                row[0] or "General"
                for row in db.execute(
                    select(Voter.alumni_set).where(Voter.election_id == election.id)
                ).all()
            }
        )
        if not alumni_sets:
            alumni_sets = ["General"]

        existing = {
            row[0].lower()
            for row in db.execute(
                select(Voter.voter_id).where(Voter.election_id == election.id)
            ).all()
        }
        added: list[tuple[str, str, str]] = []
        skipped = 0
        for alumni_set in alumni_sets:
            set_slug = _slug(alumni_set)
            for index in range(1, args.per_set + 1):
                voter_id = f"TEST/AL/{set_slug}/{index:02d}"
                if voter_id.lower() in existing:
                    skipped += 1
                    continue
                full_name = f"Test {alumni_set} Voter {index}"
                db.add(
                    Voter(
                        election_id=election.id,
                        voter_id=voter_id,
                        full_name=full_name,
                        email=f"test+{set_slug.lower()}.{index}@example.test",
                        whatsapp_consent=False,
                        alumni_set=alumni_set,
                        graduation_year=election.year,
                        is_eligible=True,
                        register_status="approved",
                    )
                )
                existing.add(voter_id.lower())
                added.append((voter_id, full_name, alumni_set))

        if added:
            db.add(
                ElectionEvent(
                    election_id=election.id,
                    event_type="register.test_voters_added",
                    message=f"{len(added)} pre-approved test voter(s) added for local testing",
                )
            )
        db.commit()

        print(f"Election: {election.reference} ({election.id})")
        print(f"Added: {len(added)}; skipped existing: {skipped}")
        for voter_id, full_name, alumni_set in added:
            print(f"  {voter_id}  {full_name}  [{alumni_set}]")
        if added:
            print("Test voters are approved and can accredit immediately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
