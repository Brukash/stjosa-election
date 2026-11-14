"""Voter accreditation: Voter ID + OTP, then blinded anonymous credential issuance."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import crypto
from ..config import settings
from ..db import get_db
from ..deps import client_ip, get_current_profile, record_audit, require_permission
from ..models import (
    AccreditationRecord,
    AccreditationSession,
    CredentialIssuance,
    Election,
    ElectionEvent,
    OtpChallenge,
    Profile,
    Voter,
)
from ..notifications import deliver_otp, delivery_available
from ..schemas import CredentialRequest, OtpRequest, OtpVerify
from ..services import get_settings_row, maybe_auto_close, now, public_settings_dict, resolve_public_election
from ..security import generate_otp, otp_digest, otp_matches

router = APIRouter(prefix="/accreditation", tags=["accreditation"])

OTP_ALLOWED_STATUSES = {"accreditation_open", "voting_open"}


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


@router.post("/request-otp")
def request_otp(payload: OtpRequest, request: Request, db: Session = Depends(get_db)):
    election = resolve_public_election(db, payload.election_id)
    maybe_auto_close(db, election)
    if election.status not in OTP_ALLOWED_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Accreditation is not open for this election")

    voter = _voter_by_id(db, election, payload.voter_id)
    if not voter or not voter.is_eligible or voter.register_status != "approved":
        record_audit(
            db, action="otp.request", outcome="failure", election_id=election.id,
            ip_address=client_ip(request), detail={"reason": "not_on_register"},
        )
        db.commit()
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "That Voter ID is not on the approved electoral register",
        )

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

    hour_ago = now() - timedelta(hours=1)
    recent_requests = db.scalar(
        select(func.count(OtpChallenge.id)).where(
            OtpChallenge.voter_row_id == voter.id, OtpChallenge.created_at >= hour_ago
        )
    ) or 0
    if recent_requests >= settings.otp_max_requests_per_hour:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many OTP requests. Try again later.")

    latest = db.execute(
        select(OtpChallenge).where(OtpChallenge.voter_row_id == voter.id)
        .order_by(OtpChallenge.created_at.desc())
    ).scalars().first()
    if latest and (now() - latest.created_at).total_seconds() < settings.otp_resend_seconds:
        wait = int(settings.otp_resend_seconds - (now() - latest.created_at).total_seconds())
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Please wait {max(wait, 1)}s before requesting another OTP.")

    if not delivery_available(voter):
        record_audit(
            db, action="otp.request", outcome="failure", election_id=election.id,
            entity="voter", entity_id=voter.id, ip_address=client_ip(request),
            detail={"reason": "delivery_not_configured"},
        )
        db.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "One-time password delivery is not available. Contact the Electoral Committee.",
        )

    challenge_id = crypto.sha256_hex("challenge", secrets.token_hex(16))[:36]
    otp = generate_otp()
    challenge = OtpChallenge(
        id=challenge_id,
        election_id=election.id,
        voter_row_id=voter.id,
        otp_hash=otp_digest(challenge_id, otp),
        expires_at=now() + timedelta(seconds=settings.otp_ttl_seconds),
        max_attempts=settings.otp_max_attempts,
        request_ip=client_ip(request),
    )
    db.add(challenge)
    db.flush()

    delivery = deliver_otp(
        db,
        election=election,
        voter=voter,
        otp=otp,
        challenge_id=challenge_id,
        request_ip=client_ip(request),
    )

    if not delivery.delivered:
        # Never reveal or keep a usable OTP when delivery failed.
        challenge.expires_at = now()
        record_audit(
            db, action="otp.deliver", outcome="failure", election_id=election.id,
            entity="voter", entity_id=voter.id, ip_address=client_ip(request),
            detail={"channel": delivery.channel, "provider": delivery.provider, "error": delivery.error},
        )
        db.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "We could not deliver your one-time password. Please try again shortly or contact the "
            "Accreditation Officer.",
        )

    record_audit(
        db, action="otp.deliver", election_id=election.id, entity="voter", entity_id=voter.id,
        ip_address=client_ip(request),
        detail={"channel": delivery.channel, "provider": delivery.provider, "status": delivery.status},
    )
    db.commit()

    development_delivery = delivery.channel == "development" and settings.expose_dev_otp
    if delivery.channel == "email":
        message = f"A one-time password has been emailed to {delivery.recipient_masked}."
    elif delivery.channel == "sms":
        message = f"A one-time password has been sent by SMS to {delivery.recipient_masked}."
    else:
        message = "Local development delivery: the one-time password is shown below."

    return {
        "challenge_id": challenge_id,
        "voter_id": voter.voter_id,
        "delivery": delivery.recipient_masked,
        "delivery_channel": delivery.channel,
        "expires_in": settings.otp_ttl_seconds,
        "max_attempts": settings.otp_max_attempts,
        "message": message,
        "dev_otp": otp if development_delivery else None,
        "dev_note": (
            "Displayed only because this backend is running in local development on a loopback "
            "origin. Production requires a configured email or SMS provider."
            if development_delivery else None
        ),
    }


@router.post("/verify-otp")
def verify_otp(payload: OtpVerify, request: Request, db: Session = Depends(get_db)):
    election = resolve_public_election(db, payload.election_id)
    voter = _voter_by_id(db, election, payload.voter_id)
    challenge = db.get(OtpChallenge, payload.challenge_id)
    if not voter or not challenge or challenge.election_id != election.id or challenge.voter_row_id != voter.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OTP challenge")

    if challenge.consumed_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This OTP has already been used. Request a new one.")
    expires = challenge.expires_at
    if expires.tzinfo is None:
        from datetime import timezone

        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The OTP has expired. Request a new one.")
    if challenge.attempts >= challenge.max_attempts:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Maximum verification attempts reached. Request a new OTP.")

    if not otp_matches(challenge.id, payload.otp, challenge.otp_hash):
        challenge.attempts += 1
        record_audit(
            db, action="otp.verify", outcome="failure", election_id=election.id,
            ip_address=client_ip(request),
            detail={"attempt": challenge.attempts, "voter_id": voter.voter_id},
        )
        db.commit()
        remaining = max(challenge.max_attempts - challenge.attempts, 0)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"Incorrect OTP. {remaining} attempt(s) remaining." if remaining else "Maximum attempts reached.",
        )

    challenge.consumed_at = now()
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
            note="Voter ID and OTP verified",
        )
        db.add(accreditation)
        db.flush()

    session_token = secrets.token_hex(32)
    session = AccreditationSession(
        election_id=election.id,
        voter_row_id=voter.id,
        token_hash=hashlib.sha256(session_token.encode()).hexdigest(),
        expires_at=now() + timedelta(minutes=20),
    )
    db.add(session)
    db.add(ElectionEvent(
        election_id=election.id, event_type="voter.accredited",
        message="Voter completed OTP accreditation",
    ))
    record_audit(
        db, action="otp.verify", election_id=election.id, entity="voter", entity_id=voter.id,
        ip_address=client_ip(request), detail={"outcome": "accredited"},
    )
    db.commit()

    settings_row = get_settings_row(db, election.id)
    return {
        "accreditation_token": session_token,
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
        "message": "Identity verified. Request your anonymous voting credential next.",
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
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Accreditation session expired. Verify your OTP again.")

    election = db.get(Election, session.election_id)
    if not election or election.status not in OTP_ALLOWED_STATUSES:
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
