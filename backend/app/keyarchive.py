"""Restore the encrypted election key archive on hosts with an ephemeral disk.

Serverless hosts load the ASGI application to answer requests, and not every
runtime sends the lifespan startup event. Restoring the keys only from startup
left the deployed API reporting that its key material was never provisioned
even when ``KEYS_ARCHIVE_B64`` was configured. Unpacking therefore happens when
this module is imported, and startup calls it again harmlessly.
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


def _archive_b64() -> str:
    return os.getenv("KEYS_ARCHIVE_B64", "").strip()


def archive_error() -> str | None:
    """The reason the configured archive could not be restored, if it failed."""
    return _LAST_ERROR


def ensure_keys_materialized() -> None:
    """Unpack ``KEYS_ARCHIVE_B64`` into the key directory once per process."""
    global _LAST_ERROR
    archive = _archive_b64()
    if not archive:
        return
    marker = settings.keys_dir / "credential_issuer_private.pem"
    if marker.exists():
        return
    with _LOCK:
        if marker.exists():
            return
        settings.keys_dir.mkdir(parents=True, exist_ok=True)
        try:
            raw = base64.b64decode(archive, validate=True)
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as bundle:
                for member in bundle.getmembers():
                    parts = Path(member.name).parts
                    if member.name.startswith(("/", "\\")) or ".." in parts:
                        raise RuntimeError("unsafe path in the key archive")
                bundle.extractall(settings.keys_dir)
        except Exception as exc:  # noqa: BLE001 - reported wherever a key is needed
            _LAST_ERROR = f"{type(exc).__name__}: {exc}"
            raise
        _LAST_ERROR = None


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
