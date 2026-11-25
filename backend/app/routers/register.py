"""Approved electoral register: import, approval, eligibility maintenance."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, record_audit, require_permission, roles_for
from ..models import (
    AccreditationRecord,
    Election,
    ElectionEvent,
    NotificationDelivery,
    Profile,
    Voter,
)
from ..notifications import mask_email, notify_registered_voters, resend_registration_email
from ..schemas import (
    EligibilityUpdate,
    EmailCorrection,
    NotificationResend,
    RegisterImport,
    VoterCreate,
    WhatsAppConsentBulk,
)
from ..services import election_stats, get_election
from ..validation import clean_email, email_problem

router = APIRouter(prefix="/register", tags=["register"])

REQUIRED_COLUMNS = {"voter_id", "full_name"}
TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def _voter_dict(
    voter: Voter,
    accredited: bool,
    last_notice: NotificationDelivery | None = None,
    notice_attempts: int = 0,
) -> dict:
    return {
        "id": voter.id,
        "voter_id": voter.voter_id,
        "full_name": voter.full_name,
        "email": voter.email,
        # A readable reason, so an address that cannot receive a notice is
        # visible on the register instead of surfacing at the mail server.
        "email_problem": email_problem(voter.email) if (voter.email or "").strip() else None,
        "phone": voter.phone,
        "whatsapp_consent": voter.whatsapp_consent,
        "alumni_set": voter.alumni_set,
        "graduation_year": voter.graduation_year,
        "is_eligible": voter.is_eligible,
        "register_status": voter.register_status,
        "accredited": accredited,
        # What actually happened on the last registration-email attempt, so the
        # committee can read the delivery record before deciding to resend. The
        # masked recipient and provider error are already the only contact detail
        # stored, so nothing new is exposed.
        "registration_email_sent_at": (
            voter.registration_email_sent_at.isoformat()
            if voter.registration_email_sent_at
            else None
        ),
        "last_notice": (
            {
                "channel": last_notice.channel,
                "status": last_notice.status,
                "provider": last_notice.provider,
                "recipient_masked": last_notice.recipient_masked,
                "error": last_notice.error,
                "at": last_notice.created_at.isoformat() if last_notice.created_at else None,
                "attempts": notice_attempts,
            }
            if last_notice
            else None
        ),
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
    # The latest registration-email attempt per voter, with a count of attempts.
    # Email only: that is the channel the notice and the on-demand resend use, so
    # this answers "what happened to his mail" without a channel that was never
    # configured clouding the answer.
    notice_rows = db.execute(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.election_id == election.id,
            NotificationDelivery.purpose == "registration",
            NotificationDelivery.channel == "email",
        )
        .order_by(NotificationDelivery.created_at.desc())
    ).scalars().all()
    latest_notice: dict[str, NotificationDelivery] = {}
    notice_attempts: dict[str, int] = {}
    for row in notice_rows:
        if not row.voter_row_id:
            continue
        notice_attempts[row.voter_row_id] = notice_attempts.get(row.voter_row_id, 0) + 1
        latest_notice.setdefault(row.voter_row_id, row)

    return {
        "election": {"id": election.id, "title": election.title, "status": election.status,
                     "register_approved": all(v.register_status == "approved" for v in voters) if voters else False,
                     "locked_at": election.locked_at.isoformat() if election.locked_at else None},
        "stats": election_stats(db, election.id),
        "voters": [
            _voter_dict(
                v,
                v.id in accredited_ids,
                latest_notice.get(v.id),
                notice_attempts.get(v.id, 0),
            )
            for v in voters
        ],
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
        # A malformed address is rejected here rather than stored: it fails at
        # the mail server every time, and the register is the only place it
        # lives. The row is reported so the committee fixes the file and imports
        # it again (re-import adds only the records that are missing).
        email = clean_email(row.get("email"))
        if email:
            problem = email_problem(email)
            if problem:
                errors.append({"line": line_no, "error": f"email: {problem}"})
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
            email=email,
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
    email = clean_email(payload.email)
    if email:
        problem = email_problem(email)
        if problem:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"That email address cannot be used: {problem}",
            )
    fields = payload.model_dump()
    fields["email"] = email
    voter = Voter(election_id=election.id, **fields, register_status="imported",
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


@router.post("/{election_id}/notifications/retry")
def retry_registration_notices(
    election_id: str,
    request: Request,
    profile: Profile = Depends(require_permission("register.approve")),
    db: Session = Depends(get_db),
):
    """Resend registration notices that have not been delivered yet.

    Approval sends the notices, but the register locks as soon as the first
    ballot is cast, so a provider outage during approval would otherwise leave
    voters without their Voter ID for the rest of the election. This action is
    allowed after the lock because it never changes the register: it reuses the
    idempotent notifier, which skips every channel that already succeeded and
    retries only the notices still pending or failed.
    """
    election = get_election(db, election_id)
    voters = db.execute(select(Voter).where(Voter.election_id == election.id)).scalars().all()
    eligible = [v for v in voters if v.is_eligible and v.register_status == "approved"]
    if not eligible:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The register has no approved voters to notify",
        )

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
    record_audit(
        db, action="register.notify_retry", election_id=election.id, actor_id=profile.id,
        entity="voter_register", ip_address=client_ip(request), detail=notifications,
    )
    db.commit()
    return {
        "voters": len(eligible),
        "register_locked": bool(election.locked_at),
        "notifications": notifications,
    }


@router.post("/{election_id}/notifications/resend")
def resend_one_registration_notice(
    election_id: str,
    payload: NotificationResend,
    request: Request,
    profile: Profile = Depends(require_permission("register.approve")),
    db: Session = Depends(get_db),
):
    """Resend one member's registration email, on demand.

    A voter may report that the notice never arrived, or a batch send may have
    failed for them, and the register cannot be re-approved once voting starts.
    The committee names the voter by Voter ID or email address and only that
    voter's email is sent, so a single complaint never re-mails the register.
    """
    election = get_election(db, election_id)
    target = payload.voter.strip()
    if not target:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Enter a Voter ID or email address"
        )
    voters = db.execute(select(Voter).where(Voter.election_id == election.id)).scalars().all()
    lowered = target.lower()
    matches = [
        voter
        for voter in voters
        if voter.voter_id.lower() == lowered
        or (voter.email or "").strip().lower() == lowered
    ]
    if not matches:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No voter on this register matches {target}"
        )
    if len(matches) > 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{len(matches)} voters share {target}; resend by Voter ID instead",
        )
    voter = matches[0]
    if not voter.is_eligible or voter.register_status != "approved":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{voter.voter_id} is not an approved voter on this register",
        )
    result = resend_registration_email(
        db, election=election, voter=voter, request_ip=client_ip(request)
    )
    record_audit(
        db, action="register.notify_resend", election_id=election.id, actor_id=profile.id,
        entity="voter", entity_id=voter.voter_id, ip_address=client_ip(request),
        detail={
            "voter_id": voter.voter_id,
            "status": result.status,
            "provider": result.provider,
            "error": result.error,
        },
    )
    db.commit()
    return {
        "voter": {
            "voter_id": voter.voter_id,
            "full_name": voter.full_name,
            "email": result.recipient_masked,
        },
        "register_locked": bool(election.locked_at),
        "delivery": {
            "status": result.status,
            "provider": result.provider,
            "error": result.error,
        },
    }


@router.post("/{election_id}/voters/email")
def correct_voter_email(
    election_id: str,
    payload: EmailCorrection,
    request: Request,
    profile: Profile = Depends(require_permission("register.approve")),
    db: Session = Depends(get_db),
):
    """Correct one voter's email address and record the change.

    A notice fails permanently only when the address itself is wrong, and the
    register is the only place that address lives, so a rejected send cannot be
    fixed by sending again. The committee names the member by Voter ID or current
    address and only that record changes. This is allowed after the register
    locks because an address cannot alter eligibility, a cast ballot or the
    result — and because a member who writes in with the right spelling is
    exactly when voting is under way.
    """
    election = get_election(db, election_id)
    target = payload.voter.strip()
    if not target:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Enter a Voter ID or email address"
        )
    voters = db.execute(select(Voter).where(Voter.election_id == election.id)).scalars().all()
    lowered = target.lower()
    matches = [
        voter
        for voter in voters
        if voter.voter_id.lower() == lowered
        or (voter.email or "").strip().lower() == lowered
    ]
    if not matches:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No voter on this register matches {target}"
        )
    if len(matches) > 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{len(matches)} voters share {target}; correct by Voter ID instead",
        )
    voter = matches[0]

    email = clean_email(payload.email)
    if email is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Enter the corrected email address"
        )
    problem = email_problem(email)
    if problem:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"That email address cannot be used: {problem}",
        )
    previous = (voter.email or "").strip() or None
    if previous is not None and previous.lower() == email.lower():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That is already the address on this record"
        )

    voter.email = email
    record_audit(
        db, action="register.email_corrected", election_id=election.id, actor_id=profile.id,
        entity="voter", entity_id=voter.voter_id, ip_address=client_ip(request),
        detail={
            "voter_id": voter.voter_id,
            "previous": previous,
            "new": email,
            "note": (payload.note or "").strip() or None,
            "register_locked": bool(election.locked_at),
        },
    )
    db.commit()
    return {
        "voter": {
            "voter_id": voter.voter_id,
            "full_name": voter.full_name,
            "email": mask_email(email),
        },
        "previous_email": mask_email(previous) if previous else None,
        "register_locked": bool(election.locked_at),
        "usage": "Send the notice to the new address with Resend to one member.",
    }
