"""Restore the election key archive on hosts with an ephemeral disk.

Serverless hosts load the ASGI application to answer requests, and not every
runtime sends the lifespan startup event, so restoring keys only from startup
left the deployed API reporting that its key material was never provisioned.
Unpacking therefore happens when this module is imported, and startup calls it
again harmlessly.

Three sources are tried, in order:

1. the key directory itself, when the host has a durable disk;
2. ``KEYS_ARCHIVE_B64``, an archive supplied through the environment;
3. ``key_archives.primary``, an archive stored in the database sealed with
   MASTER_KEY, which lets a deployment without a disk or an environment secret
   still share one set of keys across every instance.

A host with key files on disk never reads the other two, so local development is
unaffected.
"""
from __future__ import annotations

import base64
import io
import os
import tarfile
import threading
from pathlib import Path

from .config import settings

_LOCK = threading.Lock()
_LAST_ERROR: str | None = None
# The presence of this file is what "the key directory is populated" means.
_MARKER = "credential_issuer_private.pem"


def _archive_b64() -> str:
    return os.getenv("KEYS_ARCHIVE_B64", "").strip()


def archive_error() -> str | None:
    """The reason the configured archive could not be restored, if it failed."""
    return _LAST_ERROR


def _database_archive() -> tuple[str | None, str | None]:
    """The sealed archive published in the database, with any reason it failed."""
    # Imported here because crypto imports this module for its error text.
    from . import crypto
    from .db import SessionLocal
    from .models import KeyArchive

    try:
        with SessionLocal() as db:
            row = db.get(KeyArchive, "primary")
            if row is None:
                return None, None
            return crypto.decrypt_secret(row.ciphertext).decode(), None
    except Exception as exc:  # noqa: BLE001 - a missing table or unreadable row is not fatal
        return None, f"the database key archive: {type(exc).__name__}: {exc}"


def _extract(archive: str) -> None:
    settings.keys_dir.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(archive, validate=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as bundle:
        for member in bundle.getmembers():
            parts = Path(member.name).parts
            if member.name.startswith(("/", "\\")) or ".." in parts:
                raise RuntimeError("unsafe path in the key archive")
        bundle.extractall(settings.keys_dir)


def ensure_keys_materialized() -> None:
    """Populate the key directory from the first archive that restores."""
    global _LAST_ERROR
    marker = settings.keys_dir / _MARKER
    if marker.exists():
        _LAST_ERROR = None
        return

    sources: list[tuple[str, str]] = []
    env_archive = _archive_b64()
    if env_archive:
        sources.append(("KEYS_ARCHIVE_B64", env_archive))
    db_archive, db_error = _database_archive()
    if db_archive:
        sources.append(("the database key archive", db_archive))
    if not sources:
        # Never fatal: a host without key material still starts and answers,
        # and the request that needs a key explains what is missing.
        _LAST_ERROR = db_error
        return

    with _LOCK:
        if marker.exists():
            return
        failures: list[str] = [db_error] if db_error else []
        for label, archive in sources:
            try:
                _extract(archive)
            except Exception as exc:  # noqa: BLE001 - reported below with the source
                failures.append(f"{label}: {type(exc).__name__}: {exc}")
                continue
            _LAST_ERROR = None
            return
        _LAST_ERROR = "; ".join(failures)
        raise RuntimeError("Could not restore the election key archive")


def materialize_on_import() -> None:
    """Restore at import time without taking the whole API down when it fails.

    A failed restore is remembered and repeated in the error a key request
    raises, so the cause is visible instead of looking like a missing secret.
    """
    global _LAST_ERROR
    try:
        ensure_keys_materialized()
    except Exception as exc:  # noqa: BLE001 - surfaced by the key loaders
        _LAST_ERROR = f"{type(exc).__name__}: {exc}"
