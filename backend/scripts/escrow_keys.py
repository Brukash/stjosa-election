"""Publish the election key directory to the database, sealed with MASTER_KEY.

A serverless deployment has no durable disk, so it restores its keys from this
copy on every cold start. Run it on the machine that holds the key files:

    .venv/Scripts/python.exe scripts/escrow_keys.py

``DATABASE_URL`` in the environment wins over ``.env``, so the archive can be
published to a different database than the local development one. Nothing about
the keys is printed: only the file count and the stored size.
"""
from __future__ import annotations

import base64
import io
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, ".")

from app import crypto  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import KeyArchive  # noqa: E402


def build_archive() -> tuple[str, int]:
    """Pack the key directory the same way KEYS_ARCHIVE_B64 is packed."""
    root = settings.keys_dir
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise SystemExit(f"No key files under {root}")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for path in files:
            if path.name.endswith(".tmp"):
                continue
            bundle.add(path, arcname=str(path.relative_to(root)))
    return base64.b64encode(buffer.getvalue()).decode(), len(files)


def main() -> None:
    archive, count = build_archive()
    sealed = crypto.encrypt_secret(archive.encode())
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        row = db.get(KeyArchive, "primary")
        if row is None:
            db.add(KeyArchive(id="primary", ciphertext=sealed))
        else:
            row.ciphertext = sealed
        db.commit()
    print(f"sealed {count} key files into key_archives.primary ({len(sealed)} chars)")
    print(f"database: {settings.database_url.split('@')[-1]}")


if __name__ == "__main__":
    main()
