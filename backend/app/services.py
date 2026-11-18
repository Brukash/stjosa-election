"""Shared domain services used by multiple routers."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import crypto
from .models import (
    AccreditationRecord,
    Ballot,
    BallotCommitment,
    BallotReceipt,
    Candidate,
    ChallengedBallot,
    Election,
    ElectionPosition,
    ElectionVerificationSetting,
    SpentCredential,
    Voter,
)
from .schemas import STATUS_LABELS

PUBLIC_STATUSES = {"accreditation_open", "voting_open", "voting_closed", "counting",
                   "provisional_results", "under_review", "declared"}

LIFECYCLE_ORDER = [
    "draft", "configured", "approved", "accreditation_open", "voting_open",
    "voting_closed", "counting", "provisional_results", "under_review", "declared", "archived",
]

ALLOWED_TRANSITIONS = {
    "draft": {"configured"},
    "configured": {"draft", "approved"},
    "approved": {"accreditation_open", "configured"},
    "accreditation_open": {"voting_open", "approved"},
    "voting_open": {"voting_closed"},
    "voting_closed": {"counting", "voting_open"},
    "counting": {"provisional_results", "voting_closed"},
    "provisional_results": {"under_review", "counting"},
    "under_review": {"declared", "counting"},
    "declared": {"archived"},
    "archived": set(),
}

CONFIG_LOCKED_STATUSES = {"voting_closed", "counting", "provisional_results", "under_review", "declared", "archived"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def get_election(db: Session, election_id: str) -> Election:
    election = db.get(Election, election_id)
    if not election:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Election not found")
    return election


def get_settings_row(db: Session, election_id: str) -> ElectionVerificationSetting:
    row = db.execute(
        select(ElectionVerificationSetting).where(
            ElectionVerificationSetting.election_id == election_id
        )
    ).scalar_one_or_none()
    if not row:
        row = ElectionVerificationSetting(election_id=election_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def find_active_election(db: Session) -> Election | None:
    preferred = ["voting_open", "accreditation_open", "voting_closed", "counting",
                 "provisional_results", "under_review", "approved"]
    for state in preferred:
        election = db.execute(
            select(Election).where(Election.status == state).order_by(Election.created_at.desc())
        ).scalars().first()
        if election:
            return election
    return db.execute(select(Election).order_by(Election.created_at.desc())).scalars().first()


# The public results page is about counted and declared figures, so the election
# furthest through the count wins. find_active_election prefers voting_open,
# which is right for the ballot entry point but would hand the results page a
# rehearsal election that has never been counted.
RESULTS_STATUS_ORDER = ("declared", "under_review", "provisional_results", "counting", "voting_closed")


def find_results_election(db: Session) -> Election | None:
    for state in RESULTS_STATUS_ORDER:
        election = db.execute(
            select(Election).where(Election.status == state).order_by(Election.created_at.desc())
        ).scalars().first()
        if election:
            return election
    return find_active_election(db)


# A voter may only act on an election that is open for accreditation or voting.
# Everything past voting_open is closed: officials still see it in the admin
# workspace, but the public pages must never offer it.
VOTER_FACING_STATUSES = ("accreditation_open", "voting_open")
CLOSED_STATUSES = ("voting_closed", "counting", "provisional_results", "under_review",
                   "declared", "archived")


def voter_facing_elections(db: Session) -> list[Election]:
    rows = db.execute(
        select(Election).where(Election.status.in_(VOTER_FACING_STATUSES))
        .order_by(Election.created_at.desc())
    ).scalars().all()
    return list(rows)


def find_voter_election(db: Session) -> Election | None:
    """The election voters see: the Chairman's choice when it is open, else the newest open one."""
    rows = voter_facing_elections(db)
    for election in rows:
        if election.voter_visible:
            return election
    return rows[0] if rows else None


def resolve_public_election(db: Session, election_id: str | None) -> Election:
    election = get_election(db, election_id) if election_id else find_voter_election(db)
    if not election:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No election is available")
    if election.status in CLOSED_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "This election is closed and is no longer shown to voters")
    return election


def maybe_auto_close(db: Session, election: Election) -> Election:
    """Close voting automatically when the configured closing time has passed."""
    if election.status == "voting_open" and election.closes_at:
        if aware(election.closes_at) <= now():
            election.status = "voting_closed"
            db.commit()
            db.refresh(election)
    return election


def ensure_voting_window(db: Session, election: Election) -> None:
    maybe_auto_close(db, election)
    if election.status != "voting_open":
        raise HTTPException(status.HTTP_409_CONFLICT, "Voting is not open for this election")
    current = now()
    if election.opens_at and aware(election.opens_at) > current:
        raise HTTPException(status.HTTP_409_CONFLICT, "Voting has not started yet")
    if election.closes_at and aware(election.closes_at) <= current:
        raise HTTPException(status.HTTP_409_CONFLICT, "Voting has closed")


def configuration_payload(db: Session, election: Election) -> dict:
    settings = get_settings_row(db, election.id)
    positions = db.execute(
        select(ElectionPosition).where(ElectionPosition.election_id == election.id)
        .order_by(ElectionPosition.order_index)
    ).scalars().all()
    candidates = db.execute(
        select(Candidate).where(Candidate.election_id == election.id).order_by(Candidate.order_index)
    ).scalars().all()
    return {
        "election": {
            "title": election.title,
            "reference": election.reference,
            "year": election.year,
            "opens_at": election.opens_at.isoformat() if election.opens_at else None,
            "closes_at": election.closes_at.isoformat() if election.closes_at else None,
            "timezone": election.timezone,
            "eligibility_rules": election.eligibility_rules,
            "voting_rules": election.voting_rules,
        },
        "verification": {
            "ballot_inclusion_enabled": settings.ballot_inclusion_enabled,
            "private_selection_enabled": settings.private_selection_enabled,
            "public_commitment_list_enabled": settings.public_commitment_list_enabled,
            "pdf_receipt_enabled": settings.pdf_receipt_enabled,
        },
        "positions": [
            {"id": p.id, "title": p.title, "seats": p.seats, "order": p.order_index} for p in positions
        ],
        "candidates": [
            {"id": c.id, "position_id": c.position_id, "name": c.full_name, "order": c.order_index}
            for c in candidates
        ],
    }


def configuration_hash(db: Session, election: Election) -> str:
    canonical = json.dumps(configuration_payload(db, election), sort_keys=True, separators=(",", ":"))
    return crypto.sha256_hex("SJC-CONFIG-V1", election.reference, canonical)


def verification_settings_dict(settings: ElectionVerificationSetting) -> dict:
    return {
        "ballot_inclusion_enabled": settings.ballot_inclusion_enabled,
        "private_selection_enabled": settings.private_selection_enabled,
        "public_commitment_list_enabled": settings.public_commitment_list_enabled,
        "pdf_receipt_enabled": settings.pdf_receipt_enabled,
        "configured_by": settings.configured_by,
        "approved_at": settings.approved_at.isoformat() if settings.approved_at else None,
        "locked_at": settings.locked_at.isoformat() if settings.locked_at else None,
    }


def public_settings_dict(settings: ElectionVerificationSetting) -> dict:
    return {
        "ballot_inclusion_enabled": settings.ballot_inclusion_enabled,
        "private_selection_enabled": settings.private_selection_enabled,
        "public_commitment_list_enabled": settings.public_commitment_list_enabled,
        "pdf_receipt_enabled": settings.pdf_receipt_enabled,
    }


def election_summary(db: Session, election: Election) -> dict:
    settings = get_settings_row(db, election.id)
    eligible = db.scalar(
        select(func.count(Voter.id)).where(
            Voter.election_id == election.id, Voter.is_eligible.is_(True),
            Voter.register_status == "approved",
        )
    ) or 0
    accredited = db.scalar(
        select(func.count(AccreditationRecord.id)).where(AccreditationRecord.election_id == election.id)
    ) or 0
    ballots = db.scalar(
        select(func.count(Ballot.id)).where(Ballot.election_id == election.id, Ballot.accepted.is_(True))
    ) or 0
    return {
        "id": election.id,
        "title": election.title,
        "description": election.description,
        "reference": election.reference,
        "year": election.year,
        "status": election.status,
        "status_label": STATUS_LABELS.get(election.status, election.status),
        "opens_at": election.opens_at.isoformat() if election.opens_at else None,
        "closes_at": election.closes_at.isoformat() if election.closes_at else None,
        "timezone": election.timezone,
        "configuration_hash": election.configuration_hash,
        "locked_at": election.locked_at.isoformat() if election.locked_at else None,
        "voter_visible": election.voter_visible,
        "voter_facing": election.status in VOTER_FACING_STATUSES,
        "verification": verification_settings_dict(settings),
        "totals": {
            "eligible_voters": eligible,
            "accredited_voters": accredited,
            "votes_cast": ballots,
            "yet_to_vote": max(eligible - ballots, 0),
            "turnout_percentage": round((ballots / eligible * 100), 2) if eligible else 0.0,
        },
    }


def public_key_material(election: Election) -> dict:
    """The public key material published for an election.

    The credential key is read from the running key material first, because a
    browser blinds its credential with the value published here and the service
    signs that credential with its own key. Publishing the copy stored on the
    election row, which is a snapshot from whenever keys were generated, meant
    a host whose key files had been replaced signed with a key the browser never
    saw, and every credential failed to unblind. The row stays as the fallback
    for a host that holds no key files at all, so the public page still renders.
    """
    credential = None
    try:
        credential = crypto.credential_public_numbers()
    except crypto.KeyMaterialError:
        credential = None
    if credential is None:
        stored = (election.credential_public_key or "").strip()
        if stored.startswith("{"):
            try:
                credential = json.loads(stored)
            except ValueError:
                credential = None
    return {
        "tally_public_key": election.tally_public_key,
        "signing_public_key": crypto.signing_public_b64_from_pem(election.signing_public_key),
        "credential_public_key": credential,
    }


def public_election_payload(db: Session, election: Election) -> dict:
    settings = get_settings_row(db, election.id)
    positions = db.execute(
        select(ElectionPosition).where(ElectionPosition.election_id == election.id)
        .order_by(ElectionPosition.order_index)
    ).scalars().all()
    candidates = db.execute(
        select(Candidate).where(Candidate.election_id == election.id)
        .where(Candidate.approved.is_(True)).order_by(Candidate.order_index)
    ).scalars().all()
    return {
        "id": election.id,
        "title": election.title,
        "description": election.description,
        "reference": election.reference,
        "year": election.year,
        "status": election.status,
        "status_label": STATUS_LABELS.get(election.status, election.status),
        "opens_at": election.opens_at.isoformat() if election.opens_at else None,
        "closes_at": election.closes_at.isoformat() if election.closes_at else None,
        "timezone": election.timezone,
        "voting_rules": election.voting_rules,
        "can_accredit": election.status in {"accreditation_open", "voting_open"},
        "can_vote": election.status == "voting_open",
        "verification": public_settings_dict(settings),
        "positions": [
            {
                "id": p.id,
                "title": p.title,
                "description": p.description,
                "seats": p.seats,
                "candidates": [
                    {
                        "id": c.id,
                        "full_name": c.full_name,
                        "photo_url": c.photo_url,
                        "bio": c.bio,
                        "manifesto": c.manifesto,
                    }
                    for c in candidates
                    if c.position_id == p.id
                ],
            }
            for p in positions
        ],
        "keys": public_key_material(election),
    }


def election_stats(db: Session, election_id: str) -> dict:
    eligible = db.scalar(
        select(func.count(Voter.id)).where(
            Voter.election_id == election_id, Voter.is_eligible.is_(True),
            Voter.register_status == "approved",
        )
    ) or 0
    registered = db.scalar(select(func.count(Voter.id)).where(Voter.election_id == election_id)) or 0
    accredited = db.scalar(
        select(func.count(AccreditationRecord.id)).where(AccreditationRecord.election_id == election_id)
    ) or 0
    accepted = db.scalar(
        select(func.count(Ballot.id)).where(Ballot.election_id == election_id, Ballot.accepted.is_(True))
    ) or 0
    challenged = db.scalar(
        select(func.count(ChallengedBallot.id)).where(ChallengedBallot.election_id == election_id)
    ) or 0
    commitments = db.scalar(
        select(func.count(BallotCommitment.id)).where(BallotCommitment.election_id == election_id)
    ) or 0
    receipts = db.scalar(
        select(func.count(BallotReceipt.id)).where(BallotReceipt.election_id == election_id)
    ) or 0
    spent = db.scalar(
        select(func.count(SpentCredential.id)).where(SpentCredential.election_id == election_id)
    ) or 0
    return {
        "registered_voters": registered,
        "eligible_voters": eligible,
        "accredited_voters": accredited,
        "accreditation_rate": round(accredited / eligible * 100, 2) if eligible else 0.0,
        "votes_cast": accepted,
        "yet_to_vote": max(eligible - accepted, 0),
        "turnout_percentage": round(accepted / eligible * 100, 2) if eligible else 0.0,
        "challenged_ballots": challenged,
        "commitments": commitments,
        "receipts": receipts,
        "spent_credentials": spent,
    }
