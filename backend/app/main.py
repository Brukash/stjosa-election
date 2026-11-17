"""FastAPI application entry point."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .config import settings
from .crypto import KeyMaterialError
from .db import Base, SessionLocal, engine, get_db
from .keyarchive import ensure_keys_materialized, materialize_on_import
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


def _ensure_column(table: str, column: str, postgres_type: str, sqlite_type: str) -> None:
    """Add one additive column when an older database lacks it."""
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    if column in {item["name"] for item in inspector.get_columns(table)}:
        return
    if engine.dialect.name == "postgresql":
        statement = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {postgres_type}"
    else:
        statement = f"ALTER TABLE {table} ADD COLUMN {column} {sqlite_type}"
    try:
        with engine.begin() as connection:
            connection.execute(text(statement))
    except Exception:
        # A concurrent serverless instance may have added it first.
        refreshed = {item["name"] for item in inspect(engine).get_columns(table)}
        if column not in refreshed:
            raise


def _ensure_compatibility_columns() -> None:
    """Apply additive schema changes that create_all cannot add to old tables."""
    _ensure_column("voters", "whatsapp_consent", "BOOLEAN NOT NULL DEFAULT FALSE",
                   "BOOLEAN NOT NULL DEFAULT FALSE")
    _ensure_column("voters", "registration_email_sent_at", "TIMESTAMPTZ", "DATETIME")
    _ensure_column("voters", "registration_whatsapp_sent_at", "TIMESTAMPTZ", "DATETIME")
    _ensure_column("voters", "turnout_token_hash", "VARCHAR(128)", "VARCHAR(128)")
    _ensure_column("voters", "has_voted_at", "TIMESTAMPTZ", "DATETIME")
    _ensure_column("notification_deliveries", "purpose",
                   "VARCHAR(20) NOT NULL DEFAULT 'otp'", "VARCHAR(20) NOT NULL DEFAULT 'otp'")


# Serverless hosts may never send the ASGI startup event, so the archive is
# restored while this module is imported and again at startup for long-running
# servers, where an unusable archive must stop the process.
materialize_on_import()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        ensure_keys_materialized()
    except Exception as exc:  # pragma: no cover - deployment infrastructure
        raise RuntimeError("Could not restore the election key archive") from exc
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
        "End-to-end verifiable remote electronic voting: Voter ID accreditation, blind-signature "
        "anonymous credentials, encrypted ballots, cast-as-intended verification, signed anonymous "
        "commitment lists, verifiable counting and audited results declaration."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    GZipMiddleware,
    # JSON payloads of a few KB compress to a fraction of their size; tiny
    # responses stay uncompressed because the header costs more than it saves.
    minimum_size=500,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
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


@app.exception_handler(KeyMaterialError)
async def key_material_problem(_request: Request, exc: KeyMaterialError) -> JSONResponse:
    """Report missing key material as a provisioning problem, not a crash.

    Without this the ballot endpoints answered a bare 500 and the cause was
    invisible from the outside.
    """
    return JSONResponse(status_code=503, content={"detail": str(exc)})


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
