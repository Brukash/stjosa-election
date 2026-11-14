"""Public, unauthenticated election information endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Election
from ..schemas import STATUS_LABELS
from ..services import (
    election_summary,
    find_active_election,
    get_settings_row,
    maybe_auto_close,
    public_election_payload,
    public_settings_dict,
    resolve_public_election,
)
from ..security import ROLE_NAMES, PERMISSIONS

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/election")
def current_election(db: Session = Depends(get_db)):
    election = find_active_election(db)
    if not election:
        return {"election": None, "published_results": False}
    maybe_auto_close(db, election)
    settings = get_settings_row(db, election.id)
    return {
        "election": public_election_payload(db, election),
        "verification": public_settings_dict(settings),
        "status_label": STATUS_LABELS.get(election.status, election.status),
    }


@router.get("/elections/{election_id}")
def election_by_id(election_id: str, db: Session = Depends(get_db)):
    election = resolve_public_election(db, election_id)
    maybe_auto_close(db, election)
    return public_election_payload(db, election)


@router.get("/elections")
def elections_index(db: Session = Depends(get_db)):
    rows = db.query(Election).order_by(Election.created_at.desc()).limit(20).all()
    return {
        "elections": [
            {
                **election_summary(db, e),
                "ballot": None,
            }
            for e in rows
        ]
    }


@router.get("/meta")
def meta():
    return {
        "roles": [{"key": k, "name": v, "permissions": sorted(PERMISSIONS.get(k, set()))} for k, v in ROLE_NAMES.items()],
    }
