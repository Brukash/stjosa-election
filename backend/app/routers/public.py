"""Public, unauthenticated election information endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import STATUS_LABELS
from ..services import (
    VOTER_FACING_STATUSES,
    find_voter_election,
    get_settings_row,
    maybe_auto_close,
    public_election_payload,
    public_settings_dict,
    resolve_public_election,
    voter_facing_elections,
)
from ..security import ROLE_NAMES, PERMISSIONS

router = APIRouter(prefix="/public", tags=["public"])

ACTIVE_PUBLIC_STATUSES = ("accreditation_open", "voting_open")


@router.get("/election")
def current_election(db: Session = Depends(get_db)):
    election = find_voter_election(db)
    if election:
        maybe_auto_close(db, election)
    if not election or election.status not in VOTER_FACING_STATUSES:
        # The closing time may just have passed; nothing may be on offer now.
        election = find_voter_election(db)
    if not election:
        return {"election": None, "published_results": False}
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


@router.get("/active-elections")
def active_elections(db: Session = Depends(get_db)):
    """Elections a member can currently accredit or vote in."""
    rows = voter_facing_elections(db)
    for election in rows:
        maybe_auto_close(db, election)
    rows = [election for election in rows if election.status in ACTIVE_PUBLIC_STATUSES]
    # Once the Chairman names the election voters should see, the chooser offers only it.
    chosen = [election for election in rows if election.voter_visible]
    if chosen:
        rows = chosen
    return {
        "elections": [
            {
                "id": election.id,
                "title": election.title,
                "reference": election.reference,
                "year": election.year,
                "status": election.status,
                "status_label": STATUS_LABELS.get(election.status, election.status),
                "opens_at": election.opens_at.isoformat() if election.opens_at else None,
                "closes_at": election.closes_at.isoformat() if election.closes_at else None,
                "can_accredit": election.status in ACTIVE_PUBLIC_STATUSES,
                "can_vote": election.status == "voting_open",
            }
            for election in rows
        ]
    }


@router.get("/elections")
def elections_index(db: Session = Depends(get_db)):
    """The voter-facing index: only elections a voter can act on.

    Closed elections are never listed here. They stay visible to officials in the
    admin workspace and, once declared, on the public results and record pages.
    """
    rows = voter_facing_elections(db)
    for election in rows:
        maybe_auto_close(db, election)
    rows = [election for election in rows if election.status in VOTER_FACING_STATUSES]
    chosen = [election for election in rows if election.voter_visible]
    if chosen:
        rows = chosen
    return {
        "elections": [
            {
                "id": election.id,
                "title": election.title,
                "reference": election.reference,
                "year": election.year,
                "status": election.status,
                "status_label": STATUS_LABELS.get(election.status, election.status),
                "opens_at": election.opens_at.isoformat() if election.opens_at else None,
                "closes_at": election.closes_at.isoformat() if election.closes_at else None,
                "can_accredit": election.status in ACTIVE_PUBLIC_STATUSES,
                "can_vote": election.status == "voting_open",
                "ballot": None,
            }
            for election in rows
        ]
    }


@router.get("/meta")
def meta():
    return {
        "roles": [{"key": k, "name": v, "permissions": sorted(PERMISSIONS.get(k, set()))} for k, v in ROLE_NAMES.items()],
    }
