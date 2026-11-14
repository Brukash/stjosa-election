"""FastAPI application entry point."""
from __future__ import annotations

import base64
import io
import os
import tarfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .config import settings
from .db import Base, SessionLocal, engine, get_db
from .routers import (
    accreditation,
    accounts,
    auth,
    elections,
    monitoring,
    public,
    receipts,
    register,
    results,
    settings as settings_router,
    tally,
    verification,
    voting,
    webhooks,
)
from .seed import seed_database


def _ensure_compatibility_columns() -> None:
    """Apply additive schema changes that create_all cannot add to old tables."""
    inspector = inspect(engine)
    if "voters" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("voters")}
    if "whatsapp_consent" not in columns:
        statement = (
            "ALTER TABLE voters ADD COLUMN IF NOT EXISTS whatsapp_consent "
            "BOOLEAN NOT NULL DEFAULT FALSE"
            if engine.dialect.name == "postgresql"
            else "ALTER TABLE voters ADD COLUMN whatsapp_consent BOOLEAN NOT NULL DEFAULT FALSE"
        )
        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
        except Exception:
            # A concurrent serverless instance may have added it first.
            refreshed = {
                column["name"] for column in inspect(engine).get_columns("voters")
            }
            if "whatsapp_consent" not in refreshed:
                raise


def _materialize_keys() -> None:
    """Restore encrypted key files on hosts with an ephemeral filesystem."""
    archive = os.getenv("KEYS_ARCHIVE_B64", "").strip()
    if not archive:
        return
    marker = settings.keys_dir / "credential_issuer_private.pem"
    if marker.exists():
        return
    settings.keys_dir.mkdir(parents=True, exist_ok=True)
    try:
        raw = base64.b64decode(archive, validate=True)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as bundle:
            for member in bundle.getmembers():
                parts = Path(member.name).parts
                if member.name.startswith(("/", "\\")) or ".." in parts:
                    raise RuntimeError("Unsafe path in key archive")
            bundle.extractall(settings.keys_dir)
    except Exception as exc:  # pragma: no cover - deployment infrastructure
        raise RuntimeError("Could not restore the election key archive") from exc


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _materialize_keys()
    issues = settings.production_issues
    if issues:
        raise RuntimeError(
            "Production configuration is incomplete: " + "; ".join(issues)
        )
    Base.metadata.create_all(bind=engine)
    _ensure_compatibility_columns()
    demo_seed = os.getenv("DEMO_SEED")
    if demo_seed is None:
        demo_seed = "false" if settings.is_production else "true"
    if demo_seed.strip().lower() in {"1", "true", "yes"}:
        with SessionLocal() as db:
            seed_database(db)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.1.0",
    description=(
        "End-to-end verifiable remote electronic voting: voter ID + OTP accreditation, blind-signature "
        "anonymous credentials, encrypted ballots, cast-as-intended verification, signed anonymous "
        "commitment lists, verifiable counting and audited results declaration."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_origin, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

for router in (
    accounts.router,
    auth.router,
    public.router,
    elections.router,
    register.router,
    accreditation.router,
    voting.router,
    verification.router,
    receipts.router,
    tally.router,
    results.router,
    monitoring.router,
    settings_router.router,
    webhooks.router,
):
    app.include_router(router, prefix="/api")


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "application": settings.app_name,
        "database": "supabase-postgresql" if "postgresql" in settings.database_url else "sqlite-local",
        "time": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }


@app.get("/")
def root():
    return {
        "application": settings.app_name,
        "docs": "/docs",
        "health": "/api/health",
        "public_election": "/api/public/election",
    }
