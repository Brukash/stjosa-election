"""Deployment preflight: configuration, database reachability and schema.

    python scripts/preflight.py

Exits non-zero when a production deployment would fail closed or the database
does not contain the election schema. Safe to run against staging/production;
it only reads configuration and performs SELECT/EXISTS checks.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import engine  # noqa: E402

REQUIRED_TABLES = {
    "profiles",
    "elections",
    "election_verification_settings",
    "voters",
    "accreditation_records",
    "credential_issuances",
    "ballots",
    "ballot_receipts",
    "challenged_ballots",
    "ballot_commitments",
    "published_commitment_batches",
    "tally_runs",
    "tally_results",
    "result_declarations",
    "audit_logs",
    "notification_deliveries",
    "configuration_changes",
}


def main() -> int:
    failures = 0
    print(f"environment:       {settings.environment}")
    print(f"app origin:        {settings.app_origin}")
    print(f"api origin:        {settings.api_origin}")
    print(f"database:          {'postgresql' if 'postgresql' in settings.database_url else settings.database_url.split(':')[0]}")
    print(f"OTP delivery:      {settings.delivery_mode}")
    print(f"on-screen OTP:     {'enabled' if settings.expose_dev_otp else 'disabled'}")
    print(f"keys directory:    {settings.keys_dir} ({'writable' if settings.keys_dir.exists() else 'MISSING'})")
    print(f"production issues: {len(settings.production_issues)}")
    for issue in settings.production_issues:
        print(f" - {issue}")
    failures += len(settings.production_issues)

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            tables = set(inspect(connection).get_table_names())
        missing = sorted(REQUIRED_TABLES - tables)
        print(f"database reachable: yes ({len(tables)} tables)")
        if missing:
            print(f"missing tables: {', '.join(missing)}")
            failures += 1
        with engine.connect() as connection:
            active = connection.execute(
                text("SELECT reference, status FROM elections ORDER BY created_at DESC LIMIT 3")
            ).fetchall()
        if active:
            print("recent elections: " + ", ".join(f"{row[0]} ({row[1]})" for row in active))
        else:
            print("recent elections: none (register and configure the election before opening)")
    except Exception as exc:
        print(f"database check FAILED: {type(exc).__name__}: {exc}")
        failures += 1

    if settings.is_production and "sqlite" in settings.database_url:
        print("WARNING: production is pointed at local SQLite")

    print("\npreflight:", "READY" if failures == 0 else f"{failures} issue(s) to resolve")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
