"""Election configuration: details, positions, candidates, verification settings,
two-person configuration approval, lifecycle transitions and exceptional changes."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto
from ..db import get_db
from ..deps import client_ip, get_current_profile, record_audit, require_permission, roles_for
from ..models import (
    Candidate,
    ConfigurationChange,
    Election,
    ElectionConfigurationApproval,
    ElectionEvent,
    ElectionPosition,
    ElectionVerificationSetting,
    Profile,
)
from ..schemas import (
    STATUS_LABELS,
    CandidateCreate,
    CandidateUpdate,
    ElectionCreate,
    ElectionUpdate,
    ExceptionalChange,
    PositionCreate,
    PositionUpdate,
    StatusUpdate,
    VerificationSettingsUpdate,
)
from ..services import (
    ALLOWED_TRANSITIONS,
    CONFIG_LOCKED_STATUSES,
    LIFECYCLE_ORDER,
    configuration_hash,
    configuration_payload,
    election_summary,
    get_election,
    get_settings_row,
    now,
    verification_settings_dict,
)

router = APIRouter(prefix="/elections", tags=["elections"])

CHAIRMAN_APPROVAL = "chairman"
SECOND_APPROVAL_ROLE = "returning_officer"


def _ensure_editable(db: Session, election: Election) -> None:
    if election.locked_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Configuration is locked: the first ballot has been accepted. Use the exceptional change process.",
        )
    if election.status in CONFIG_LOCKED_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Configuration is locked for this election stage")
    if election.status in {"counting", "provisional_results", "under_review", "declared", "archived"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Election is past the configuration phase")


def _election_detail(db: Session, election: Election) -> dict:
    settings = get_settings_row(db, election.id)
    positions = db.execute(
        select(ElectionPosition).where(ElectionPosition.election_id == election.id)
        .order_by(ElectionPosition.order_index)
    ).scalars().all()
    candidates = db.execute(
        select(Candidate).where(Candidate.election_id == election.id)
        .order_by(Candidate.order_index)
    ).scalars().all()
    approvals = db.execute(
        select(ElectionConfigurationApproval)
        .where(ElectionConfigurationApproval.election_id == election.id)
        .order_by(ElectionConfigurationApproval.approved_at)
    ).scalars().all()
    changes = db.execute(
        select(ConfigurationChange).where(ConfigurationChange.election_id == election.id)
        .order_by(ConfigurationChange.created_at.desc()).limit(50)
    ).scalars().all()
    events = db.execute(
        select(ElectionEvent).where(ElectionEvent.election_id == election.id)
        .order_by(ElectionEvent.created_at.desc()).limit(50)
    ).scalars().all()
    return {
        **election_summary(db, election),
        "eligibility_rules": election.eligibility_rules,
        "voting_rules": election.voting_rules,
        "approved_at": election.approved_at.isoformat() if election.approved_at else None,
        "positions": [
            {
                "id": p.id, "title": p.title, "description": p.description, "seats": p.seats,
                "order_index": p.order_index, "approved": p.approved,
                "candidates": [
                    {
                        "id": c.id, "full_name": c.full_name, "photo_url": c.photo_url,
                        "bio": c.bio, "manifesto": c.manifesto, "order_index": c.order_index,
                        "approved": c.approved,
                    }
                    for c in candidates if c.position_id == p.id
                ],
            }
            for p in positions
        ],
        "verification": {
            **verification_settings_dict(settings),
            "approved_by": settings.approved_by,
        },
        "configuration_approvals": [
            {
                "id": a.id, "approver_id": a.approver_id, "approver_role": a.approver_role,
                "approval_status": a.approval_status, "settings_hash": a.settings_hash,
                "note": a.note, "approved_at": a.approved_at.isoformat(),
            }
            for a in approvals
        ],
        "change_history": [
            {
                "id": c.id, "reason": c.reason, "status": c.status,
                "changed_fields": c.changed_fields, "previous_hash": c.previous_hash,
                "new_hash": c.new_hash, "approvals": c.approvals,
                "effective_at": c.effective_at.isoformat() if c.effective_at else None,
                "created_at": c.created_at.isoformat(),
            }
            for c in changes
        ],
        "events": [
            {
                "id": e.id, "event_type": e.event_type, "message": e.message,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
        "configuration_hash_now": configuration_hash(db, election),
        "lifecycle": [
            {"status": s, "label": STATUS_LABELS.get(s, s),
             "current": s == election.status,
             "completed": LIFECYCLE_ORDER.index(s) < LIFECYCLE_ORDER.index(election.status)}
            for s in LIFECYCLE_ORDER
        ],
    }


@router.get("")
def list_elections(
    profile: Profile = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(Election).order_by(Election.created_at.desc())).scalars().all()
    return {"elections": [_election_detail(db, e) for e in rows]}


@router.post("", status_code=201)
def create_election(
    payload: ElectionCreate,
    request: Request,
    profile: Profile = Depends(require_permission("election.create")),
    db: Session = Depends(get_db),
):
    reference = (payload.reference or f"SJCJ-{payload.year}-{crypto.receipt_number().split('/')[-1][:6]}").strip().upper()
    if db.execute(select(Election).where(Election.reference == reference)).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An election with this reference already exists")
    election = Election(
        title=payload.title,
        description=payload.description,
        reference=reference,
        year=payload.year,
        opens_at=payload.opens_at,
        closes_at=payload.closes_at,
        timezone=payload.timezone,
        eligibility_rules=payload.eligibility_rules,
        voting_rules=payload.voting_rules,
        status="draft",
        created_by=profile.id,
    )
    db.add(election)
    db.flush()
    db.add(ElectionVerificationSetting(election_id=election.id))
    db.add(ElectionEvent(
        election_id=election.id, event_type="election.created",
        message=f"Election '{election.title}' created", actor_id=profile.id,
    ))
    record_audit(
        db, action="election.create", election_id=election.id, actor_id=profile.id,
        actor_role=",".join(roles_for(db, profile.id)), entity="election",
        entity_id=election.id, ip_address=client_ip(request), detail={"reference": reference},
    )
    db.commit()
    db.refresh(election)
    return _election_detail(db, election)


@router.get("/{election_id}")
def get_election_detail(
    election_id: str,
    profile: Profile = Depends(require_permission("election.view")),
    db: Session = Depends(get_db),
):
    return _election_detail(db, get_election(db, election_id))


@router.patch("/{election_id}")
def update_election(
    election_id: str,
    payload: ElectionUpdate,
    request: Request,
    profile: Profile = Depends(require_permission("election.edit")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    _ensure_editable(db, election)
    fields = payload.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(election, key, value)
    election.configuration_hash = configuration_hash(db, election)
    record_audit(
        db, action="election.update", election_id=election.id, actor_id=profile.id,
        entity="election", entity_id=election.id, ip_address=client_ip(request),
        detail={"fields": list(fields.keys())},
    )
    db.commit()
    return _election_detail(db, election)


# ── positions ────────────────────────────────────────────────────────────────
@router.post("/{election_id}/positions", status_code=201)
def create_position(
    election_id: str,
    payload: PositionCreate,
    request: Request,
    profile: Profile = Depends(require_permission("election.edit")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    _ensure_editable(db, election)
    if db.execute(
        select(ElectionPosition).where(
            ElectionPosition.election_id == election.id, ElectionPosition.title == payload.title
        )
    ).scalars().first():
        raise HTTPException(status.HTTP_409_CONFLICT, "A position with this title already exists")
    position = ElectionPosition(election_id=election.id, **payload.model_dump())
    db.add(position)
    election.configuration_hash = configuration_hash(db, election)
    record_audit(db, action="position.create", election_id=election.id, actor_id=profile.id,
                 entity="position", detail=payload.model_dump(), ip_address=client_ip(request))
    db.commit()
    db.refresh(position)
    return {"id": position.id, **payload.model_dump()}


@router.patch("/positions/{position_id}")
def update_position(
    position_id: str,
    payload: PositionUpdate,
    request: Request,
    profile: Profile = Depends(require_permission("election.edit")),
    db: Session = Depends(get_db),
):
    position = db.get(ElectionPosition, position_id)
    if not position:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
    election = get_election(db, position.election_id)
    _ensure_editable(db, election)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(position, key, value)
    election.configuration_hash = configuration_hash(db, election)
    record_audit(db, action="position.update", election_id=election.id, actor_id=profile.id,
                 entity="position", entity_id=position.id, detail=payload.model_dump(exclude_unset=True),
                 ip_address=client_ip(request))
    db.commit()
    return {"id": position.id, "title": position.title}


@router.delete("/positions/{position_id}")
def delete_position(
    position_id: str,
    request: Request,
    profile: Profile = Depends(require_permission("election.edit")),
    db: Session = Depends(get_db),
):
    position = db.get(ElectionPosition, position_id)
    if not position:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Position not found")
    election = get_election(db, position.election_id)
    _ensure_editable(db, election)
    db.query(Candidate).filter(Candidate.position_id == position.id).delete()
    db.delete(position)
    election.configuration_hash = configuration_hash(db, election)
    record_audit(db, action="position.delete", election_id=election.id, actor_id=profile.id,
                 entity="position", entity_id=position_id, ip_address=client_ip(request))
    db.commit()
    return {"deleted": True}


# ── candidates ───────────────────────────────────────────────────────────────
@router.post("/{election_id}/candidates", status_code=201)
def create_candidate(
    election_id: str,
    payload: CandidateCreate,
    request: Request,
    profile: Profile = Depends(require_permission("election.edit")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    _ensure_editable(db, election)
    position = db.get(ElectionPosition, payload.position_id)
    if not position or position.election_id != election.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid position for this election")
    candidate = Candidate(election_id=election.id, **payload.model_dump())
    db.add(candidate)
    election.configuration_hash = configuration_hash(db, election)
    record_audit(db, action="candidate.create", election_id=election.id, actor_id=profile.id,
                 entity="candidate", detail={"name": payload.full_name}, ip_address=client_ip(request))
    db.commit()
    db.refresh(candidate)
    return {"id": candidate.id, "full_name": candidate.full_name}


@router.patch("/candidates/{candidate_id}")
def update_candidate(
    candidate_id: str,
    payload: CandidateUpdate,
    request: Request,
    profile: Profile = Depends(require_permission("election.edit")),
    db: Session = Depends(get_db),
):
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
    election = get_election(db, candidate.election_id)
    _ensure_editable(db, election)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(candidate, key, value)
    election.configuration_hash = configuration_hash(db, election)
    record_audit(db, action="candidate.update", election_id=election.id, actor_id=profile.id,
                 entity="candidate", entity_id=candidate.id, ip_address=client_ip(request))
    db.commit()
    return {"id": candidate.id, "full_name": candidate.full_name}


@router.delete("/candidates/{candidate_id}")
def delete_candidate(
    candidate_id: str,
    request: Request,
    profile: Profile = Depends(require_permission("election.edit")),
    db: Session = Depends(get_db),
):
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
    election = get_election(db, candidate.election_id)
    _ensure_editable(db, election)
    db.delete(candidate)
    election.configuration_hash = configuration_hash(db, election)
    record_audit(db, action="candidate.delete", election_id=election.id, actor_id=profile.id,
                 entity="candidate", entity_id=candidate_id, ip_address=client_ip(request))
    db.commit()
    return {"deleted": True}


# ── verification settings ────────────────────────────────────────────────────
@router.put("/{election_id}/verification-settings")
def update_verification_settings(
    election_id: str,
    payload: VerificationSettingsUpdate,
    request: Request,
    profile: Profile = Depends(require_permission("verification.configure")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    settings_row = get_settings_row(db, election.id)
    if settings_row.locked_at or election.locked_at:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Verification settings are locked because voting has begun. They cannot be changed.",
        )
    if election.status in {"voting_closed", "counting", "provisional_results", "under_review", "declared", "archived"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Verification settings are locked for this election stage")

    previous = verification_settings_dict(settings_row)
    changes = payload.model_dump()
    for key, value in changes.items():
        setattr(settings_row, key, value)
    settings_row.configured_by = profile.id
    settings_row.approved_at = None
    settings_row.approved_by = None
    election.configuration_hash = configuration_hash(db, election)
    record_audit(
        db, action="verification_settings.update", election_id=election.id, actor_id=profile.id,
        entity="verification_settings", ip_address=client_ip(request),
        detail={"previous": previous, "new": changes},
    )
    db.commit()
    return {"verification": verification_settings_dict(settings_row), "requires_approval": True}


@router.post("/{election_id}/verification-settings/approve")
def approve_verification_settings(
    election_id: str,
    request: Request,
    profile: Profile = Depends(require_permission("verification.approve")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    settings_row = get_settings_row(db, election.id)
    if settings_row.locked_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Verification settings are locked")
    if settings_row.configured_by and settings_row.configured_by == profile.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Verification settings must be approved by a different authorised official",
        )
    settings_row.approved_by = profile.id
    settings_row.approved_at = now()
    record_audit(db, action="verification_settings.approve", election_id=election.id,
                 actor_id=profile.id, entity="verification_settings", ip_address=client_ip(request))
    db.add(ElectionEvent(
        election_id=election.id, event_type="verification.approved",
        message=f"Voter verification settings approved by {profile.full_name}",
        actor_id=profile.id,
    ))
    db.commit()
    return {"approved": True, "approved_at": settings_row.approved_at.isoformat(),
            "verification": verification_settings_dict(settings_row)}


# ── two-person configuration approval ────────────────────────────────────────
@router.post("/{election_id}/configuration/approve")
def approve_configuration(
    election_id: str,
    request: Request,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    roles = roles_for(db, profile.id)
    settings_row = get_settings_row(db, election.id)

    if "chairman" in roles:
        role_key = "chairman"
    elif "returning_officer" in roles:
        role_key = "returning_officer"
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the Chairman or Returning Officer may approve configuration")

    if election.status not in {"draft", "configured", "approved"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Configuration approval is closed")

    existing = db.execute(
        select(ElectionConfigurationApproval).where(
            ElectionConfigurationApproval.election_id == election.id,
            ElectionConfigurationApproval.approver_id == profile.id,
        )
    ).scalars().first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "You have already approved this configuration")

    positions = db.execute(
        select(ElectionPosition).where(ElectionPosition.election_id == election.id)
    ).scalars().all()
    if not positions:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add elective positions before approving configuration")
    candidates = db.execute(
        select(Candidate).where(Candidate.election_id == election.id)
    ).scalars().all()
    if not candidates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add approved candidates before approving configuration")
    if not settings_row.approved_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Approve the voter verification settings first")

    current_hash = configuration_hash(db, election)
    db.add(ElectionConfigurationApproval(
        election_id=election.id, settings_hash=current_hash, approver_id=profile.id,
        approver_role=role_key, approval_status="approved",
        note="Configuration independently confirmed",
    ))
    db.flush()

    approvals = db.execute(
        select(ElectionConfigurationApproval).where(
            ElectionConfigurationApproval.election_id == election.id,
            ElectionConfigurationApproval.approval_status == "approved",
        )
    ).scalars().all()
    role_set = {a.approver_role for a in approvals}
    approved_now = False

    if {"chairman", "returning_officer"}.issubset(role_set):
        for position in positions:
            position.approved = True
        for candidate in candidates:
            candidate.approved = True
        keys = crypto.create_election_keys(election.id)
        election.tally_public_key = keys["tally_public_key"]
        election.signing_public_key = keys["signing_public_key"]
        election.credential_public_key = json.dumps(crypto.credential_public_numbers())
        election.status = "approved"
        election.approved_by = profile.id
        election.approved_at = now()
        election.configuration_hash = current_hash
        settings_row.approved_at = settings_row.approved_at or now()
        approved_now = True
        db.add(ElectionEvent(
            election_id=election.id, event_type="configuration.approved",
            message="Two-person configuration approval completed; election keys provisioned",
            actor_id=profile.id,
        ))

    record_audit(db, action="configuration.approve", election_id=election.id, actor_id=profile.id,
                 actor_role=role_key, entity="election", entity_id=election.id,
                 ip_address=client_ip(request), detail={"configuration_hash": current_hash})
    db.commit()
    return {
        "approved_now": approved_now,
        "approvals": len(approvals),
        "required_roles": sorted(role_set),
        "configuration_hash": current_hash,
        "status": election.status,
        "message": "Configuration approved and keys provisioned." if approved_now
        else "Approval recorded. A second authorised official must confirm the configuration.",
    }


# ── lifecycle ────────────────────────────────────────────────────────────────
STATUS_ROLES = {
    "accreditation_open": {"chairman"},
    "voting_open": {"chairman"},
    "voting_closed": {"chairman", "returning_officer"},
    "archived": {"chairman"},
    "approved": {"chairman"},
    "configured": {"chairman"},
}


@router.post("/{election_id}/status")
def transition_status(
    election_id: str,
    payload: StatusUpdate,
    request: Request,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    target = payload.status
    if target not in STATUS_LABELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown election status")
    if target not in ALLOWED_TRANSITIONS.get(election.status, set()):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot move from {election.status} to {target}. Use the counting/results modules.",
        )
    allowed_roles = STATUS_ROLES.get(target)
    if allowed_roles and not (set(roles_for(db, profile.id)) & allowed_roles):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Only {', '.join(sorted(allowed_roles)).replace('_', ' ')} can move the election to {target}",
        )

    settings_row = get_settings_row(db, election.id)
    if target == "voting_open":
        if election.status != "accreditation_open":
            raise HTTPException(status.HTTP_409_CONFLICT, "Open accreditation before voting")
        if not election.tally_public_key:
            raise HTTPException(status.HTTP_409_CONFLICT, "Election keys are not provisioned")
    if target == "accreditation_open":
        if not election.configuration_hash or election.status != "approved":
            raise HTTPException(status.HTTP_409_CONFLICT, "Configuration must be approved first")
        if not settings_row.approved_at:
            raise HTTPException(status.HTTP_409_CONFLICT, "Verification settings must be approved first")

    previous = election.status
    election.status = target
    db.add(ElectionEvent(
        election_id=election.id, event_type="status.changed",
        message=f"Election status changed from {previous} to {target}" + (f": {payload.note}" if payload.note else ""),
        actor_id=profile.id,
    ))
    record_audit(db, action="election.status", election_id=election.id, actor_id=profile.id,
                 entity="election", entity_id=election.id, ip_address=client_ip(request),
                 detail={"from": previous, "to": target, "note": payload.note})
    db.commit()
    return {"status": election.status, "previous": previous, "label": STATUS_LABELS.get(target)}


# ── exceptional changes ──────────────────────────────────────────────────────
CHANGEABLE_FIELDS = {"title", "description", "opens_at", "closes_at", "eligibility_rules", "voting_rules"}


def _change_value(field: str, value):
    """Exceptional changes arrive as JSON; restore native types the model expects."""
    if field in {"opens_at", "closes_at"} and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


@router.post("/{election_id}/changes")
def request_exceptional_change(
    election_id: str,
    payload: ExceptionalChange,
    request: Request,
    profile: Profile = Depends(require_permission("verification.approve")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    unknown = set(payload.changes) - CHANGEABLE_FIELDS
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"These settings cannot be changed after voting starts: {', '.join(sorted(unknown))}",
        )
    roles = roles_for(db, profile.id)
    requester_role = CHAIRMAN_APPROVAL if CHAIRMAN_APPROVAL in roles else SECOND_APPROVAL_ROLE
    change = ConfigurationChange(
        election_id=election.id,
        changed_fields=payload.changes,
        previous_hash=election.configuration_hash,
        reason=payload.reason,
        requested_by=profile.id,
        approvals=[{"profile_id": profile.id, "role": requester_role, "at": now().isoformat()}],
        status="pending",
        effective_at=None,
    )
    db.add(change)
    record_audit(db, action="configuration.change_requested", election_id=election.id,
                 actor_id=profile.id, entity="configuration_change", detail={"reason": payload.reason},
                 ip_address=client_ip(request))
    db.add(ElectionEvent(
        election_id=election.id, event_type="configuration.change_requested",
        message=f"Exceptional configuration change requested: {payload.reason[:180]}",
        actor_id=profile.id,
    ))
    db.commit()
    return {
        "id": change.id, "status": change.status, "approvals": change.approvals,
        "message": "Change recorded. A second authorised official must approve it before it takes effect.",
    }


@router.post("/changes/{change_id}/approve")
def approve_exceptional_change(
    change_id: str,
    request: Request,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
):
    change = db.get(ConfigurationChange, change_id)
    if not change:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found")
    if change.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Change request is not pending")
    if any(a["profile_id"] == profile.id for a in change.approvals):
        raise HTTPException(status.HTTP_409_CONFLICT, "You have already approved this change")
    roles = roles_for(db, profile.id)
    if SECOND_APPROVAL_ROLE in roles:
        role_key = SECOND_APPROVAL_ROLE
    elif CHAIRMAN_APPROVAL in roles:
        role_key = CHAIRMAN_APPROVAL
    else:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the Chairman or Returning Officer may approve an exceptional change",
        )
    election = get_election(db, change.election_id)
    approvals = list(change.approvals) + [
        {"profile_id": profile.id, "role": role_key, "at": now().isoformat()}
    ]
    change.approvals = approvals
    if len(approvals) >= 2:
        for key, value in change.changed_fields.items():
            if key in CHANGEABLE_FIELDS:
                setattr(election, key, _change_value(key, value))
        change.status = "approved"
        change.effective_at = change.effective_at or now()
        change.new_hash = configuration_hash(db, election)
        election.configuration_hash = change.new_hash
        db.add(ElectionEvent(
            election_id=election.id, event_type="configuration.changed",
            message=f"Exceptional configuration change approved. Reason: {change.reason[:180]}",
            actor_id=profile.id,
        ))
    record_audit(db, action="configuration.change_approved", election_id=election.id,
                 actor_id=profile.id, entity="configuration_change", entity_id=change.id,
                 ip_address=client_ip(request), detail={"approvals": len(approvals)})
    db.commit()
    return {"status": change.status, "approvals": change.approvals, "new_hash": change.new_hash}
