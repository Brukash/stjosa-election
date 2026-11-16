"""Approved electoral register: import, approval, eligibility maintenance."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, record_audit, require_permission, roles_for
from ..models import AccreditationRecord, Election, ElectionEvent, Profile, Voter
from ..notifications import notify_registered_voters
from ..schemas import EligibilityUpdate, RegisterImport, VoterCreate, WhatsAppConsentBulk
from ..services import election_stats, get_election

router = APIRouter(prefix="/register", tags=["register"])

REQUIRED_COLUMNS = {"voter_id", "full_name"}
TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def _voter_dict(voter: Voter, accredited: bool) -> dict:
    return {
        "id": voter.id,
        "voter_id": voter.voter_id,
        "full_name": voter.full_name,
        "email": voter.email,
        "phone": voter.phone,
        "whatsapp_consent": voter.whatsapp_consent,
        "alumni_set": voter.alumni_set,
        "graduation_year": voter.graduation_year,
        "is_eligible": voter.is_eligible,
        "register_status": voter.register_status,
        "accredited": accredited,
    }


@router.get("/{election_id}")
def list_register(
    election_id: str,
    profile: Profile = Depends(require_permission("register.view")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    voters = db.execute(
        select(Voter).where(Voter.election_id == election.id).order_by(Voter.voter_id)
    ).scalars().all()
    accredited_ids = {
        row.voter_row_id
        for row in db.execute(
            select(AccreditationRecord).where(AccreditationRecord.election_id == election.id)
        ).scalars()
    }
    return {
        "election": {"id": election.id, "title": election.title, "status": election.status,
                     "register_approved": all(v.register_status == "approved" for v in voters) if voters else False,
                     "locked_at": election.locked_at.isoformat() if election.locked_at else None},
        "stats": election_stats(db, election.id),
        "voters": [_voter_dict(v, v.id in accredited_ids) for v in voters],
    }


@router.post("/{election_id}/import")
def import_register(
    election_id: str,
    payload: RegisterImport,
    request: Request,
    profile: Profile = Depends(require_permission("register.import")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    if election.locked_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "The register is locked: voting has begun")

    reader = csv.DictReader(io.StringIO(payload.csv_text.strip()))
    if not reader.fieldnames or not REQUIRED_COLUMNS.issubset({f.strip().lower() for f in reader.fieldnames}):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "CSV must include at least the columns: voter_id, full_name (optional: email, phone, whatsapp_consent, alumni_set, graduation_year)",
        )

    existing = {
        v.voter_id.lower()
        for v in db.execute(select(Voter).where(Voter.election_id == election.id)).scalars()
    }
    added, skipped, errors = 0, 0, []
    for line_no, raw in enumerate(reader, start=2):
        row = { (k or "").strip().lower(): (v or "").strip() for k, v in raw.items() }
        voter_id = row.get("voter_id", "")
        full_name = row.get("full_name", "")
        if not voter_id or not full_name:
            errors.append({"line": line_no, "error": "voter_id and full_name are required"})
            continue
        if voter_id.lower() in existing:
            skipped += 1
            continue
        graduation_year = None
        if row.get("graduation_year"):
            try:
                graduation_year = int(row["graduation_year"])
            except ValueError:
                graduation_year = None
        db.add(Voter(
            election_id=election.id,
            voter_id=voter_id,
            full_name=full_name,
            email=row.get("email") or None,
            phone=row.get("phone") or None,
            whatsapp_consent=(row.get("whatsapp_consent") or "").lower() in TRUE_VALUES,
            alumni_set=row.get("alumni_set") or "General",
            graduation_year=graduation_year,
            is_eligible=True,
            register_status="imported",
            imported_by=profile.id,
        ))
        existing.add(voter_id.lower())
        added += 1

    if added:
        db.add(ElectionEvent(
            election_id=election.id, event_type="register.imported",
            message=f"{added} voter record(s) imported", actor_id=profile.id,
        ))
    record_audit(
        db, action="register.import", election_id=election.id, actor_id=profile.id,
        actor_role=",".join(roles_for(db, profile.id)), entity="voter_register",
        ip_address=client_ip(request), detail={"added": added, "skipped": skipped, "errors": len(errors)},
    )
    db.commit()
    return {
        "added": added,
        "skipped_duplicates": skipped,
        "errors": errors,
        "requires_approval": True,
        "message": "Register imported. The Electoral Committee Chairman must approve the register before accreditation.",
    }


@router.post("/{election_id}/voters", status_code=201)
def add_voter(
    election_id: str,
    payload: VoterCreate,
    request: Request,
    profile: Profile = Depends(require_permission("register.import")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    if election.locked_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "The register is locked: voting has begun")
    if db.execute(
        select(Voter).where(
            Voter.election_id == election.id,
            func.lower(Voter.voter_id) == payload.voter_id.strip().lower(),
        )
    ).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, "This Voter ID already exists for the election")
    voter = Voter(election_id=election.id, **payload.model_dump(), register_status="imported",
                  imported_by=profile.id)
    db.add(voter)
    record_audit(db, action="register.voter_added", election_id=election.id, actor_id=profile.id,
                 entity="voter", ip_address=client_ip(request), detail={"voter_id": payload.voter_id})
    db.commit()
    db.refresh(voter)
    return _voter_dict(voter, False)


@router.patch("/voters/{voter_id}")
def update_eligibility(
    voter_id: str,
    payload: EligibilityUpdate,
    request: Request,
    profile: Profile = Depends(require_permission("register.approve")),
    db: Session = Depends(get_db),
):
    voter = db.get(Voter, voter_id)
    if not voter:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Voter not found")
    election = get_election(db, voter.election_id)
    if election.locked_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "The register is locked: voting has begun")
    if payload.is_eligible is None and payload.whatsapp_consent is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No register change was supplied")
    if payload.is_eligible is not None:
        voter.is_eligible = payload.is_eligible
        if not payload.is_eligible:
            voter.register_status = "excluded"
    if payload.whatsapp_consent is not None:
        voter.whatsapp_consent = payload.whatsapp_consent
    audit_action = (
        "register.consent"
        if payload.is_eligible is None and payload.whatsapp_consent is not None
        else "register.eligibility"
    )
    record_audit(db, action=audit_action, election_id=election.id, actor_id=profile.id,
                 entity="voter", entity_id=voter.id, ip_address=client_ip(request),
                 detail={"is_eligible": payload.is_eligible,
                         "whatsapp_consent": payload.whatsapp_consent, "note": payload.note})
    db.commit()
    return _voter_dict(voter, False)


@router.post("/{election_id}/whatsapp-consent")
def bulk_whatsapp_consent(
    election_id: str,
    payload: WhatsAppConsentBulk,
    request: Request,
    profile: Profile = Depends(require_permission("register.approve")),
    db: Session = Depends(get_db),
):
    """Record consented WhatsApp numbers in bulk, with one audited source/date per voter."""
    election = get_election(db, election_id)
    if "chairman" not in roles_for(db, profile.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the Chairman can record bulk WhatsApp consent",
        )
    if election.locked_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "The register is locked: voting has begun")

    source = payload.source.strip()
    if not source:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Consent source is required")
    requested_ids = list(dict.fromkeys(payload.voter_ids))
    voters = db.execute(
        select(Voter).where(
            Voter.election_id == election.id,
            Voter.id.in_(requested_ids),
        )
    ).scalars().all()
    by_id = {voter.id: voter for voter in voters}

    recorded = 0
    skipped_already_consented = 0
    skipped_no_phone = 0
    skipped_unknown = 0
    note = (payload.note or "").strip() or None
    audit_note = (
        f"WhatsApp consent source: {source}; consent date: {payload.consent_date.isoformat()}."
    )
    if note:
        audit_note = f"{audit_note} {note}"
    for voter_id in requested_ids:
        voter = by_id.get(voter_id)
        if not voter:
            skipped_unknown += 1
            continue
        if not (voter.phone or "").strip():
            skipped_no_phone += 1
            continue
        if voter.whatsapp_consent:
            skipped_already_consented += 1
            continue
        voter.whatsapp_consent = True
        record_audit(
            db,
            action="register.consent",
            election_id=election.id,
            actor_id=profile.id,
            actor_role="chairman",
            entity="voter",
            entity_id=voter.id,
            ip_address=client_ip(request),
            detail={
                "whatsapp_consent": True,
                "consent_source": source,
                "consent_date": payload.consent_date.isoformat(),
                "note": audit_note,
            },
        )
        recorded += 1

    if recorded:
        db.commit()
    return {
        "recorded": recorded,
        "skipped_already_consented": skipped_already_consented,
        "skipped_no_phone": skipped_no_phone,
        "skipped_unknown": skipped_unknown,
    }


@router.post("/{election_id}/approve")
def approve_register(
    election_id: str,
    request: Request,
    profile: Profile = Depends(require_permission("register.approve")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    if election.locked_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "The register is locked: voting has begun")
    voters = db.execute(select(Voter).where(Voter.election_id == election.id)).scalars().all()
    if not voters:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The register is empty")
    eligible = [v for v in voters if v.is_eligible]
    for voter in eligible:
        voter.register_status = "approved"
    db.add(ElectionEvent(
        election_id=election.id, event_type="register.approved",
        message=f"Electoral register approved with {len(eligible)} eligible voters",
        actor_id=profile.id,
    ))
    record_audit(db, action="register.approve", election_id=election.id, actor_id=profile.id,
                 entity="voter_register", ip_address=client_ip(request),
                 detail={"approved": len(eligible), "excluded": len(voters) - len(eligible)})
    db.commit()

    # Approval is the point at which a voter is registered to vote. Send the
    # notice after committing the approval so a provider failure cannot undo it.
    try:
        notifications = notify_registered_voters(
            db, election=election, voters=eligible, request_ip=client_ip(request)
        )
    except Exception as exc:
        db.rollback()
        notifications = {
            "voters": len(eligible),
            "error": f"registration notices failed ({type(exc).__name__})",
        }
    if notifications.get("voters"):
        record_audit(
            db, action="register.notify", election_id=election.id, actor_id=profile.id,
            entity="voter_register", ip_address=client_ip(request), detail=notifications,
        )
        db.commit()
    return {
        "approved": len(eligible),
        "excluded": len(voters) - len(eligible),
        "notifications": notifications,
    }
