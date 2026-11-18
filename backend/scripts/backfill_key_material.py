"""Copy encrypted election key files onto their election rows.

An election created on a serverless deployment generates its keys in a directory
that does not outlive the instance, so counting later failed with "the election
signing private key is not provisioned". Keys are now saved with the election;
this backfills elections whose key files still exist on the machine running it.

    .venv/Scripts/python.exe scripts/backfill_key_material.py --env-file .env.supabase
    .venv/Scripts/python.exe scripts/backfill_key_material.py --env-file .env.supabase --apply

Without --apply it only reports what it would store.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--env-file", help="dotenv file holding the target DATABASE_URL")
parser.add_argument("--apply", action="store_true", help="write the bundles (default: report only)")
args = parser.parse_args()

if args.env_file:
    from dotenv import load_dotenv

    # Loaded before app.config so the database in this file wins over backend/.env.
    load_dotenv(BACKEND_DIR / args.env_file, override=True)

from sqlalchemy import select, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.crypto import ELECTION_KEY_FILES, election_key_dir  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Election  # noqa: E402


def _ensure_column() -> None:
    """Add the bundle column if the deployment has not started since it was added."""
    statement = "ALTER TABLE elections ADD COLUMN IF NOT EXISTS key_material TEXT"
    if engine.dialect.name == "sqlite":
        statement = "ALTER TABLE elections ADD COLUMN key_material TEXT"
    try:
        with engine.begin() as connection:
            connection.execute(text(statement))
    except Exception:  # noqa: BLE001 - an existing column raises on SQLite
        pass


def _bundle(election_id: str) -> dict[str, str]:
    directory = election_key_dir(election_id)
    material: dict[str, str] = {}
    for name in ELECTION_KEY_FILES:
        path = directory / name
        if path.exists():
            material[name] = path.read_text(encoding="utf-8")
    return material


_ensure_column()

stored = already = unrecoverable = 0
database = settings.database_url.split("@")[-1]
print(f"database: {database}")
print(f"key directory: {settings.keys_dir}")

with SessionLocal() as db:
    for election in db.execute(select(Election).order_by(Election.created_at)).scalars():
        if election.key_material:
            already += 1
            print(f"present      {election.id}  {election.reference}")
            continue
        material = _bundle(election.id)
        if len(material) != len(ELECTION_KEY_FILES):
            unrecoverable += 1
            print(
                f"NO KEY FILES {election.id}  {election.reference}  "
                f"({len(material)}/{len(ELECTION_KEY_FILES)} files on disk)"
            )
            continue
        if args.apply:
            election.key_material = json.dumps(material)
            db.commit()
            print(f"stored       {election.id}  {election.reference}")
        else:
            print(f"would store  {election.id}  {election.reference}")
        stored += 1

verb = "stored" if args.apply else "would store"
print(f"\n{verb}={stored} already-present={already} unrecoverable={unrecoverable}")
if unrecoverable:
    print(
        "Elections without local key files cannot be recovered: recreate them so they "
        "get keys saved on the election row."
    )
