"""FastAPI application entry point."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
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
    tally,
    verification,
    voting,
)
from .seed import seed_database


@asynccontextmanager
async def lifespan(_app: FastAPI):
    issues = settings.production_issues
    if issues:
        raise RuntimeError(
            "Production configuration is incomplete: " + "; ".join(issues)
        )
    Base.metadata.create_all(bind=engine)
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
