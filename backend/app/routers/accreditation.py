"""Voter accreditation: Voter ID verification, then blinded anonymous credential issuance."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import crypto
from ..db import get_db
from ..deps import client_ip, record_audit, require_permission
from ..models import (
    AccreditationRecord,
    AccreditationSession,
    CredentialIssuance,
    Election,
    ElectionEvent,
    Profile,
    Voter,
)
from ..schemas import CredentialRequest, VoterVerifyRequest
from ..services import get_settings_row, maybe_auto_close, now, public_settings_dict, resolve_public_election

router = APIRouter(prefix="/accreditation", tags=["accreditation"])

ACCREDITATION_STATUSES = {"accreditation_open", "voting_open"}


def _voter_by_id(db: Session, election: Election, voter_id: str) -> Voter | None:
    return db.execute(
        select(Voter).where(
            Voter.election_id == election.id,
            func.lower(Voter.voter_id) == voter_id.strip().lower(),
        )
    ).scalar_one_or_none()


def _active_issuance(db: Session, accreditation_id: str) -> CredentialIssuance | None:
    return db.execute(
        select(CredentialIssuance).where(
            CredentialIssuance.accreditation_id == accreditation_id,
            CredentialIssuance.status == "issued",
        )
    ).scalars().first()


def _eligible_voter(db: Session, election: Election, voter_id: str) -> Voter:
    voter = _voter_by_id(db, election, voter_id)
    if not voter or not voter.is_eligible or voter.register_status != "approved":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "That Voter ID is not on the approved electoral register",
        )
    return voter


def _ensure_not_issued(db: Session, election: Election, voter: Voter) -> None:
    accreditation = db.execute(
        select(AccreditationRecord).where(
            AccreditationRecord.election_id == election.id,
            AccreditationRecord.voter_row_id == voter.id,
        )
    ).scalar_one_or_none()
    if accreditation and _active_issuance(db, accreditation.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A voting credential has already been issued to this Voter ID. "
            "Contact an Accreditation Officer if it was lost.",
        )


@router.post("/verify-voter")
def verify_voter(payload: VoterVerifyRequest, request: Request, db: Session = Depends(get_db)):
    """Verify a Voter ID against the approved register and open an accreditation session.

    Accreditation is deliberately Voter ID-only. The Voter ID is sent to the member
    when the register is approved, so no OTP is generated or delivered here.
    """
    election = resolve_public_election(db, payload.election_id)
    maybe_auto_close(db, election)
    if election.status not in ACCREDITATION_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Accreditation is not open for this election")

    try:
        voter = _eligible_voter(db, election, payload.voter_id)
    except HTTPException:
        record_audit(
            db, action="voter.verify", outcome="failure", election_id=election.id,
            ip_address=client_ip(request), detail={"reason": "not_on_register"},
        )
        db.commit()
        raise

    _ensure_not_issued(db, election, voter)

    # Serialise concurrent verification for the same voter. The second check
    # prevents two simultaneous requests from both opening an issuance window.
    db.execute(select(Voter.id).where(Voter.id == voter.id).with_for_update())
    _ensure_not_issued(db, election, voter)

    accreditation = db.execute(
        select(AccreditationRecord).where(
            AccreditationRecord.election_id == election.id,
            AccreditationRecord.voter_row_id == voter.id,
        )
    ).scalar_one_or_none()
    if not accreditation:
        accreditation = AccreditationRecord(
            election_id=election.id,
            voter_row_id=voter.id,
            ip_address=client_ip(request),
            method="voter_id",
            note="Voter ID matched the approved register",
        )
        db.add(accreditation)
        db.flush()

    session_token = secrets.token_hex(32)
    turnout_token = secrets.token_hex(32)
    voter.turnout_token_hash = hashlib.sha256(turnout_token.encode()).hexdigest()
    db.add(AccreditationSession(
        election_id=election.id,
        voter_row_id=voter.id,
        token_hash=hashlib.sha256(session_token.encode()).hexdigest(),
        expires_at=now() + timedelta(minutes=20),
    ))
    db.add(ElectionEvent(
        election_id=election.id, event_type="voter.accredited",
        message="Voter ID matched the approved register",
    ))
    record_audit(
        db, action="voter.verify", election_id=election.id, entity="voter", entity_id=voter.id,
        ip_address=client_ip(request), detail={"outcome": "accredited"},
    )
    db.commit()

    settings_row = get_settings_row(db, election.id)
    return {
        "accreditation_token": session_token,
        "turnout_token": turnout_token,
        "expires_in": 20 * 60,
        "election_id": election.id,
        "election_reference": election.reference,
        "election_title": election.title,
        "voter": {
            "voter_id": voter.voter_id,
            "full_name": voter.full_name,
            "alumni_set": voter.alumni_set,
        },
        "already_issued": bool(_active_issuance(db, accreditation.id)),
        "verification": public_settings_dict(settings_row),
        "message": (
            "Voter ID verified against the approved register. "
            "Request your anonymous voting credential next."
        ),
    }


@router.post("/credential")
def request_credential(payload: CredentialRequest, request: Request, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(payload.accreditation_token.encode()).hexdigest()
    session = db.execute(
        select(AccreditationSession).where(AccreditationSession.token_hash == token_hash)
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid accreditation session")
    expires = session.expires_at if session.expires_at.tzinfo else session.expires_at.replace(tzinfo=now().tzinfo)
    if session.consumed_at or expires <= now():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Accreditation session expired. Verify your Voter ID again.")

    election = db.get(Election, session.election_id)
    if not election or election.status not in ACCREDITATION_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Accreditation is not open")

    accreditation = db.execute(
        select(AccreditationRecord).where(
            AccreditationRecord.election_id == election.id,
            AccreditationRecord.voter_row_id == session.voter_row_id,
        )
    ).scalar_one_or_none()
    if not accreditation:
        raise HTTPException(status.HTTP_409_CONFLICT, "No accreditation record found")

    if _active_issuance(db, accreditation.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A credential has already been issued for this Voter ID in this election.",
        )

    blinded_hash = crypto.sha256_hex("blinded", payload.blinded_message)
    try:
        blind_signature = crypto.blind_sign(payload.blinded_message, election.reference)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    db.add(CredentialIssuance(
        election_id=election.id,
        accreditation_id=accreditation.id,
        blinded_request_hash=blinded_hash,
    ))
    session.consumed_at = now()
    record_audit(
        db, action="credential.issued", election_id=election.id, entity="accreditation",
        entity_id=accreditation.id, ip_address=client_ip(request),
    )
    db.commit()

    return {
        "blind_signature": blind_signature,
        "election_id": election.id,
        "election_reference": election.reference,
        "credential_public_key": crypto.credential_public_numbers(),
        "message": "Credential signed. Unblind and verify it locally, then proceed to vote.",
    }


@router.post("/exceptions/reset-issuance")
def reset_issuance(
    election_id: str,
    voter_id: str,
    reason: str,
    request: Request,
    profile: Profile = Depends(require_permission("accreditation.manage")),
    db: Session = Depends(get_db),
):
    """Controlled manual exception: allow a lost credential to be replaced.

    The previous issuance is revoked, never deleted, and the action is audited.
    """
    election = db.get(Election, election_id)
    if not election:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Election not found")
    voter = _voter_by_id(db, election, voter_id)
    if not voter:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Voter not found")
    accreditation = db.execute(
        select(AccreditationRecord).where(
            AccreditationRecord.election_id == election.id,
            AccreditationRecord.voter_row_id == voter.id,
        )
    ).scalar_one_or_none()
    if not accreditation:
        raise HTTPException(status.HTTP_409_CONFLICT, "Voter has not been accredited")
    issuance = _active_issuance(db, accreditation.id)
    if not issuance:
        raise HTTPException(status.HTTP_409_CONFLICT, "No active credential issuance to revoke")
    issuance.status = "revoked"
    record_audit(
        db, action="credential.revoked", election_id=election.id, actor_id=profile.id,
        actor_role="accreditation_officer", entity="credential_issuance",
        entity_id=issuance.id, ip_address=client_ip(request), detail={"reason": reason},
    )
    db.add(ElectionEvent(
        election_id=election.id, event_type="credential.exception",
        message=f"Credential issuance revoked by accreditation officer: {reason[:160]}",
        actor_id=profile.id,
    ))
    db.commit()
    return {"status": "revoked", "issuance_id": issuance.id, "reason": reason}


@router.get("/exceptions/accreditations")
def accreditation_log(
    election_id: str,
    profile: Profile = Depends(require_permission("accreditation.oversight")),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(AccreditationRecord).where(AccreditationRecord.election_id == election_id)
        .order_by(AccreditationRecord.accredited_at.desc()).limit(500)
    ).scalars().all()
    voters = {v.id: v for v in db.execute(select(Voter).where(Voter.election_id == election_id)).scalars()}

    issuances: dict[str, list[CredentialIssuance]] = {}
    if rows:
        records = db.execute(
            select(CredentialIssuance)
            .where(CredentialIssuance.accreditation_id.in_([row.id for row in rows]))
            .order_by(CredentialIssuance.issued_at.desc())
        ).scalars().all()
        for issuance in records:
            issuances.setdefault(issuance.accreditation_id, []).append(issuance)

    def credential_state(accreditation_id: str) -> dict:
        history = issuances.get(accreditation_id, [])
        active = next((item for item in history if item.status == "issued"), None)
        latest = active or (history[0] if history else None)
        return {
            "credential_status": "active" if active else ("revoked" if history else "not_issued"),
            "credential_issued_at": latest.issued_at.isoformat() if latest else None,
            "credential_issuance_count": len(history),
        }

    return {
        "accreditations": [
            {
                "id": r.id,
                "voter_id": voters[r.voter_row_id].voter_id if r.voter_row_id in voters else None,
                "full_name": voters[r.voter_row_id].full_name if r.voter_row_id in voters else None,
                "accredited_at": r.accredited_at.isoformat(),
                "method": r.method,
                **credential_state(r.id),
            }
            for r in rows
        ]
    }
