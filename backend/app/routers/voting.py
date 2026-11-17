"""Anonymous electronic voting: prepare, challenge (cast-as-intended) or cast."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import crypto
from ..config import settings
from ..db import get_db
from ..deps import client_ip, record_audit
from ..models import (
    Ballot,
    BallotCommitment,
    BallotReceipt,
    Candidate,
    ChallengedBallot,
    Election,
    ElectionEvent,
    ElectionPosition,
    ElectionVerificationSetting,
    PreparedBallot,
    SpentCredential,
    Voter,
)
from ..notifications import notify_vote_submitted_by_id
from ..receipts import receipt_payload
from ..schemas import BallotPrepare, CredentialProof
from ..services import ensure_voting_window, get_election, get_settings_row, now

router = APIRouter(prefix="/voting", tags=["voting"])


def token_hash(token: str) -> str:
    return hashlib.sha256(token.strip().encode()).hexdigest()


def _validate_selections(db: Session, election: Election, selections: dict[str, str]) -> dict[str, str]:
    if not selections:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Select at least one candidate")
    if len(selections) > 60:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Too many selections")
    positions = {
        p.id: p for p in db.execute(
            select(ElectionPosition).where(ElectionPosition.election_id == election.id)
        ).scalars()
    }
    candidates = {
        c.id: c for c in db.execute(
            select(Candidate).where(Candidate.election_id == election.id, Candidate.approved.is_(True))
        ).scalars()
    }
    normalized: dict[str, str] = {}
    for position_id, candidate_id in selections.items():
        position = positions.get(str(position_id))
        if not position:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ballot contains an unknown position")
        candidate = candidates.get(str(candidate_id))
        if not candidate or candidate.position_id != position.id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Selection for '{position.title}' is not an approved candidate for that position",
            )
        normalized[str(position.id)] = str(candidate.id)
    return normalized


def _issue_receipt(db: Session, election: Election, ballot: Ballot, prepared: PreparedBallot) -> BallotReceipt:
    reference = crypto.new_receipt_reference()
    receipt = BallotReceipt(
        election_id=election.id,
        receipt_number=crypto.receipt_number(),
        receipt_hash=crypto.receipt_hash(reference),
        ballot_commitment=ballot.ballot_commitment,
        receipt_ref_encrypted=crypto.encrypt_secret(reference.encode()),
    )
    db.add(receipt)
    db.flush()
    prepared.receipt_id = receipt.id
    prepared.ballot_id = ballot.id
    prepared.status = "cast"
    prepared.selections = None
    prepared.data_key = None
    prepared.cleared_at = now()
    return receipt


@router.post("/prepare")
def prepare_ballot(payload: BallotPrepare, request: Request, db: Session = Depends(get_db)):
    election = get_election(db, payload.election_id)
    ensure_voting_window(db, election)

    if not crypto.verify_credential(election.reference, payload.token, payload.signature):
        record_audit(
            db, action="ballot.prepare", outcome="failure", election_id=election.id,
            ip_address=client_ip(request), detail={"reason": "invalid_credential"},
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your voting credential is not valid for this election")

    digest = token_hash(payload.token)
    if db.execute(
        select(SpentCredential).where(
            SpentCredential.election_id == election.id, SpentCredential.token_hash == digest
        )
    ).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, "This voting credential has already been used")

    selections = _validate_selections(db, election, payload.selections)
    encrypted = crypto.encrypt_ballot(election.reference, selections, election.tally_public_key)

    prepared = PreparedBallot(
        election_id=election.id,
        token_hash=digest,
        ciphertext=encrypted["ciphertext"],
        encrypted_key=encrypted["encrypted_key"],
        nonce=encrypted["nonce"],
        commitment=encrypted["commitment"],
        key_commitment=encrypted["key_commitment"],
        selections=selections,
        data_key=encrypted["data_key"],
        status="prepared",
        expires_at=now() + timedelta(seconds=settings.prepared_ballot_ttl_seconds),
    )
    db.add(prepared)
    record_audit(
        db, action="ballot.prepare", election_id=election.id, entity="prepared_ballot",
        entity_id=prepared.id, ip_address=client_ip(request),
    )
    db.commit()

    return {
        "prepared_id": prepared.id,
        "commitment": encrypted["commitment"],
        "key_commitment": encrypted["key_commitment"],
        "ciphertext": encrypted["ciphertext"],
        "encrypted_key": encrypted["encrypted_key"],
        "nonce": encrypted["nonce"],
        "election_id": election.id,
        "election_reference": election.reference,
        "private_verification_enabled": get_settings_row(db, election.id).private_selection_enabled,
        "message": "Your ballot is encrypted. Verify it, or cast it now.",
    }


@router.post("/{prepared_id}/challenge")
def challenge_ballot(
    prepared_id: str,
    payload: CredentialProof,
    request: Request,
    db: Session = Depends(get_db),
):
    prepared = db.get(PreparedBallot, prepared_id)
    if not prepared:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prepared ballot not found")
    election = get_election(db, prepared.election_id)
    settings_row = get_settings_row(db, election.id)
    if not settings_row.private_selection_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Private selection verification is disabled")

    if prepared.token_hash != token_hash(payload.token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This prepared ballot belongs to another credential")
    if not crypto.verify_credential(election.reference, payload.token, payload.signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid voting credential")
    expires = prepared.expires_at if prepared.expires_at.tzinfo else prepared.expires_at.replace(tzinfo=timezone.utc)
    if prepared.status != "prepared" or expires <= now():
        raise HTTPException(status.HTTP_409_CONFLICT, "This ballot can no longer be challenged")

    if prepared.selections is None or prepared.data_key is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Verification material is no longer available")

    proof = {
        "protocol": "AES-256-GCM ballot with RSA-OAEP wrapped key",
        "election_reference": election.reference,
        "ciphertext": prepared.ciphertext,
        "encrypted_key": prepared.encrypted_key,
        "nonce": prepared.nonce,
        "data_key": prepared.data_key,
        "key_commitment": prepared.key_commitment,
        "commitment": prepared.commitment,
        "ballot_hash": crypto.sha256_hex("SJC-CHALLENGED", prepared.commitment),
        "revealed_selections": prepared.selections,
        "revealed_at": now().isoformat(),
    }
    db.add(
        ChallengedBallot(
            election_id=election.id,
            ballot_hash=proof["ballot_hash"],
            ciphertext=prepared.ciphertext,
            encrypted_key=prepared.encrypted_key,
            nonce=prepared.nonce,
            revealed_selections=prepared.selections,
            proof=proof,
        )
    )
    prepared.status = "challenged"
    prepared.selections = None
    prepared.data_key = None
    prepared.cleared_at = now()
    record_audit(
        db, action="ballot.challenged", election_id=election.id, entity="prepared_ballot",
        entity_id=prepared.id, ip_address=client_ip(request),
    )
    db.add(ElectionEvent(
        election_id=election.id, event_type="ballot.challenged",
        message="A voter challenged a prepared ballot for private verification (excluded from tally)",
    ))
    db.commit()

    return {
        "status": "challenged",
        "excluded_from_tally": True,
        "verification_material": proof,
        "message": "Challenge accepted. This ballot is permanently excluded from the count. Prepare a fresh ballot to vote.",
    }


@router.post("/{prepared_id}/cast")
def cast_ballot(
    prepared_id: str,
    payload: CredentialProof,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    prepared = db.get(PreparedBallot, prepared_id)
    if not prepared:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prepared ballot not found")
    election = get_election(db, prepared.election_id)
    settings_row = get_settings_row(db, election.id)

    if prepared.token_hash != token_hash(payload.token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This prepared ballot belongs to another credential")

    # Idempotent replay: network retry returns the same receipt, never a second ballot.
    if prepared.status == "cast" and prepared.receipt_id:
        receipt = db.get(BallotReceipt, prepared.receipt_id)
        if receipt:
            return receipt_payload(election, receipt, verification_enabled=settings_row.ballot_inclusion_enabled)

    if prepared.status == "challenged":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This ballot was challenged for verification and can never be cast. Prepare a fresh ballot.",
        )
    ensure_voting_window(db, election)

    if not crypto.verify_credential(election.reference, payload.token, payload.signature):
        record_audit(
            db, action="ballot.cast", outcome="failure", election_id=election.id,
            ip_address=client_ip(request), detail={"reason": "invalid_credential"},
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid voting credential")

    turnout_hash = token_hash(payload.turnout_token or "")
    voter = db.execute(
        select(Voter).where(
            Voter.election_id == election.id,
            Voter.turnout_token_hash == turnout_hash,
        )
    ).scalar_one_or_none()
    if not voter:
        record_audit(
            db, action="ballot.cast", outcome="failure", election_id=election.id,
            ip_address=client_ip(request), detail={"reason": "invalid_turnout_token"},
        )
        db.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Turnout verification is missing or invalid. Verify your Voter ID again to vote.",
        )

    digest = prepared.token_hash
    if db.execute(
        select(SpentCredential).where(
            SpentCredential.election_id == election.id, SpentCredential.token_hash == digest
        )
    ).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, "This voting credential has already been used")

    ballot = Ballot(
        election_id=election.id,
        ciphertext=prepared.ciphertext,
        encrypted_key=prepared.encrypted_key,
        nonce=prepared.nonce,
        ballot_commitment=prepared.commitment,
        selection_count=len(prepared.selections or {}),
        accepted=True,
    )
    db.add(ballot)
    db.flush()
    db.add(
        BallotCommitment(
            election_id=election.id,
            ballot_commitment=prepared.commitment,
            commitment_status="accepted",
            ballot_proof={
                "nonce": prepared.nonce,
                "encrypted_key": prepared.encrypted_key,
                "ciphertext_hash": crypto.sha256_hex(prepared.ciphertext),
                "algorithm": "RSA-OAEP-SHA256 + AES-256-GCM",
            },
        )
    )
    db.add(SpentCredential(election_id=election.id, token_hash=digest))
    voted_at = now()
    voter.has_voted_at = voted_at
    voter.turnout_token_hash = None
    receipt = _issue_receipt(db, election, ballot, prepared)

    # Freeze configuration on the first accepted ballot (SRS §14.3).
    if not election.locked_at:
        election.locked_at = now()
        settings_row.locked_at = now()
        db.add(ElectionEvent(
            election_id=election.id, event_type="configuration.locked",
            message="Configuration and verification settings locked after the first accepted ballot",
        ))

    record_audit(
        db, action="ballot.cast", election_id=election.id, entity="ballot", entity_id=ballot.id,
        ip_address=client_ip(request), detail={"commitment": prepared.commitment},
    )
    db.add(ElectionEvent(
        election_id=election.id, event_type="ballot.accepted",
        message="An encrypted ballot was accepted and committed",
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        record_audit(
            db, action="ballot.cast", outcome="failure", election_id=election.id,
            ip_address=client_ip(request), detail={"reason": "duplicate_credential"},
        )
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "This voting credential has already been used")

    db.refresh(receipt)
    # Confirmation runs after the response is sent. Slow or failing providers
    # therefore cannot delay or invalidate an accepted ballot.
    background_tasks.add_task(
        notify_vote_submitted_by_id,
        election_id=election.id,
        voter_id=voter.id,
        submitted_at=voted_at,
        request_ip=client_ip(request),
    )
    return receipt_payload(election, receipt, verification_enabled=settings_row.ballot_inclusion_enabled)


@router.get("/availability")
def availability(db: Session = Depends(get_db)):
    row = db.execute(select(ElectionVerificationSetting)).scalars().first()
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat(),
            "private_verification_supported": True}
