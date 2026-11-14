"""Emit the PostgreSQL DDL for the election schema (used for the Supabase migration).

Usage:  .venv/Scripts/python.exe scripts/export_postgres_schema.py > ../supabase/migrations/0001_init.sql
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import Base
from app import models  # noqa: F401  (registers metadata)

HEADER = """-- St. John's College Jos Alumni Election Management System
-- Supabase PostgreSQL schema (SRS v1.1 §11).
-- Apply with: supabase db push   (or paste into the Supabase SQL editor)
--
-- Row Level Security, append-only audit protection and service-role grants live
-- in 0002_security.sql. The FastAPI backend connects with a role that bypasses
-- RLS; browser clients never talk to Postgres directly.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
"""


def main() -> None:
    dialect = postgresql.dialect()
    print(HEADER)
    for table in Base.metadata.sorted_tables:
        print(str(CreateTable(table).compile(dialect=dialect)).strip() + ";\n")
        for index in table.indexes:
            print(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")


if __name__ == "__main__":
    main()
