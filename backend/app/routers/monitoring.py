"""Election monitoring, counting/results dashboards, audit logs and reports."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import crypto
from ..config import settings
from ..db import get_db
from ..deps import client_ip, record_audit, require_any_permission, require_permission, roles_for
from ..models import (
    AccreditationRecord,
    AuditLog,
    Ballot,
    BallotCommitment,
    BallotReceipt,
    ChallengedBallot,
    CredentialIssuance,
    Election,
    ElectionConfigurationApproval,
    ElectionVerificationSetting,
    NotificationDelivery,
    OtpChallenge,
    Profile,
    ResultDeclaration,
    TallyRun,
    Voter,
)
from ..notifications import provider_status
from ..reports import audit_pdf, audit_report, audit_xlsx, result_certificate_pdf
from ..schemas import STATUS_LABELS
from ..security import has_permission
from ..services import election_stats, election_summary, get_election, get_settings_row, now
from .results import _public_results, declaration_dict

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

# The Accreditation Officer's limited audit view covers the parts of the process they work in.
LIMITED_AUDIT_ACTIONS = (
    "otp.request", "otp.deliver", "otp.verify",
    "credential.issued", "credential.revoked",
    "register.import", "register.voter_added", "register.eligibility", "register.consent",
    "register.approve",
)

HIDDEN_RESULT_STATUSES = {"draft", "configured", "approved", "accreditation_open", "voting_open"}


def _hourly_ballots(db: Session, election_id: str, hours: int = 24) -> list[dict]:
    since = now() - timedelta(hours=hours)
    stamps = db.execute(
        select(Ballot.cast_at).where(Ballot.election_id == election_id, Ballot.cast_at >= since)
    ).scalars().all()
    buckets: dict[str, int] = defaultdict(int)
    for stamp in stamps:
        value = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        buckets[value.strftime("%Y-%m-%dT%H:00")] += 1
    current = now().replace(minute=0, second=0, microsecond=0)
    series = []
    for offset in range(hours - 1, -1, -1):
        key = (current - timedelta(hours=offset)).strftime("%Y-%m-%dT%H:00")
        series.append({"hour": key, "ballots": buckets.get(key, 0)})
    return series


def _security_alerts(db: Session, election_id: str, limit: int = 10) -> list[dict]:
    rows = db.execute(
        select(AuditLog).where(AuditLog.election_id == election_id, AuditLog.outcome == "failure")
        .order_by(AuditLog.created_at.desc()).limit(limit)
    ).scalars().all()
    return [
        {
            "action": row.action,
            "at": row.created_at.isoformat(),
            "ip": row.ip_address,
            "detail": row.detail,
        }
        for row in rows
    ]


def _counting_dashboard(db: Session, election: Election) -> dict:
    hidden = election.status in HIDDEN_RESULT_STATUSES
    if hidden:
        return {"hidden": True, "message": "Candidate results remain hidden during the voting period."}
    run = db.execute(
        select(TallyRun).where(TallyRun.election_id == election.id, TallyRun.status == "completed")
        .order_by(TallyRun.finished_at.desc())
    ).scalars().first()
    base = {
        "hidden": False,
        "accepted_ballots": 0,
        "challenged_ballots": db.scalar(
            select(func.count(ChallengedBallot.id)).where(ChallengedBallot.election_id == election.id)
        ) or 0,
        "valid_ballots": 0,
        "invalid_ballots": 0,
        "counting_status": "not started",
        "reconciliation": None,
        "evidence_hash": None,
        "signature": None,
        "positions": [],
    }
    if run:
        from .tally import tally_payload

        payload = tally_payload(db, election, run)
        base.update({
            "accepted_ballots": run.accepted_ballots,
            "valid_ballots": run.valid_ballots,
            "invalid_ballots": run.invalid_ballots,
            "counting_status": "completed",
            "reconciliation": run.reconciliation,
            "evidence_hash": run.evidence_hash,
            "signature": run.signature,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "positions": payload["positions"],
        })
    return base


@router.get("/{election_id}/overview")
def overview(
    election_id: str,
    profile: Profile = Depends(require_permission("monitor.view")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    settings_row = get_settings_row(db, election.id)
    stats = election_stats(db, election.id)
    recent_accreditations = db.scalar(
        select(func.count(AccreditationRecord.id)).where(
            AccreditationRecord.election_id == election.id,
            AccreditationRecord.accredited_at >= now() - timedelta(hours=1),
        )
    ) or 0
    failed_otp = db.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.election_id == election.id, AuditLog.action == "otp.verify",
            AuditLog.outcome == "failure",
        )
    ) or 0
    duplicate_attempts = db.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.election_id == election.id, AuditLog.action == "ballot.cast",
            AuditLog.outcome == "failure",
        )
    ) or 0
    otp_sent = db.scalar(
        select(func.count(NotificationDelivery.id)).where(
            NotificationDelivery.election_id == election.id,
            NotificationDelivery.purpose == "otp",
            NotificationDelivery.status.in_(["sent", "delivered", "read"]),
        )
    ) or 0
    otp_failed_delivery = db.scalar(
        select(func.count(NotificationDelivery.id)).where(
            NotificationDelivery.election_id == election.id,
            NotificationDelivery.purpose == "otp",
            NotificationDelivery.status == "failed",
        )
    ) or 0
    otp_requests = db.scalar(
        select(func.count(OtpChallenge.id)).where(OtpChallenge.election_id == election.id)
    ) or 0
    channel_rows = db.execute(
        select(
            NotificationDelivery.channel,
            NotificationDelivery.status,
            func.count(NotificationDelivery.id),
        )
        .where(
            NotificationDelivery.election_id == election.id,
            NotificationDelivery.purpose == "otp",
        )
        .group_by(NotificationDelivery.channel, NotificationDelivery.status)
    ).all()
    by_channel: dict[str, dict[str, int]] = {
        channel: {"attempts": 0, "delivered": 0, "failed": 0}
        for channel in ("email", "sms", "whatsapp", "development")
    }
    for channel, delivery_status, count in channel_rows:
        bucket = by_channel.setdefault(
            channel, {"attempts": 0, "delivered": 0, "failed": 0}
        )
        bucket["attempts"] += int(count)
        if delivery_status in {"sent", "delivered", "read", "skipped"}:
            bucket["delivered"] += int(count)
        elif delivery_status == "failed":
            bucket["failed"] += int(count)
    last_delivery_failure = db.execute(
        select(NotificationDelivery).where(
            NotificationDelivery.election_id == election.id,
            NotificationDelivery.purpose == "otp",
            NotificationDelivery.status == "failed",
        ).order_by(NotificationDelivery.created_at.desc())
    ).scalars().first()
    batches = db.scalar(
        select(func.count(BallotCommitment.id)).where(BallotCommitment.election_id == election.id)
    ) or 0
    declaration = db.execute(
        select(ResultDeclaration).where(
            ResultDeclaration.election_id == election.id, ResultDeclaration.is_current.is_(True)
        )
    ).scalars().first()
    return {
        "election": election_summary(db, election),
        "status_label": STATUS_LABELS.get(election.status, election.status),
        "stats": stats,
        "live": {
            "accreditations_last_hour": recent_accreditations,
            "failed_otp_attempts": failed_otp,
            "rejected_duplicate_attempts": duplicate_attempts,
            "hourly_ballots": _hourly_ballots(db, election.id),
            "security_alerts": _security_alerts(db, election.id),
            "otp_delivery": {
                "mode": settings.delivery_mode,
                "requests": otp_requests,
                "sent": otp_sent,
                "failed": otp_failed_delivery,
                "by_channel": [
                    {"channel": channel, **counts}
                    for channel, counts in by_channel.items()
                ],
                "providers": provider_status(),
                "last_failure_at": (
                    last_delivery_failure.created_at.isoformat() if last_delivery_failure else None
                ),
                "last_failure_reason": last_delivery_failure.error if last_delivery_failure else None,
            },
        },
        "availability": {
            "api": "operational",
            "database": "operational",
            "election_keys": "provisioned" if election.tally_public_key else "not provisioned",
            "otp_delivery": settings.delivery_mode,
            "configuration_locked": bool(election.locked_at),
            "checked_at": now().isoformat(),
        },
        "counting": _counting_dashboard(db, election),
        "results": {
            "declared": bool(declaration),
            "version": declaration.version if declaration else None,
            "declared_at": declaration.declared_at.isoformat() if declaration else None,
            "published_commitments": batches,
        },
        "verification_settings": {
            "ballot_inclusion_enabled": settings_row.ballot_inclusion_enabled,
            "private_selection_enabled": settings_row.private_selection_enabled,
            "public_commitment_list_enabled": settings_row.public_commitment_list_enabled,
            "pdf_receipt_enabled": settings_row.pdf_receipt_enabled,
            "locked_at": settings_row.locked_at.isoformat() if settings_row.locked_at else None,
        },
    }


@router.get("/{election_id}/participation")
def participation(
    election_id: str,
    profile: Profile = Depends(require_permission("monitor.view")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    rows = db.execute(
        select(Voter.alumni_set, Voter.id, AccreditationRecord.id)
        .outerjoin(AccreditationRecord, AccreditationRecord.voter_row_id == Voter.id)
        .where(Voter.election_id == election.id, Voter.is_eligible.is_(True))
    ).all()
    sets: dict[str, dict[str, int]] = defaultdict(lambda: {"eligible": 0, "accredited": 0})
    for alumni_set, _voter_id, accreditation_id in rows:
        key = alumni_set or "General"
        sets[key]["eligible"] += 1
        if accreditation_id:
            sets[key]["accredited"] += 1
    return {
        "note": (
            "Participation is measured from accreditation records. Ballots carry no voter identity, "
            "so vote totals can never be attributed to an alumni set."
        ),
        "sets": [
            {
                "alumni_set": key,
                **values,
                "participation_percentage": round(values["accredited"] / values["eligible"] * 100, 2)
                if values["eligible"] else 0.0,
            }
            for key, values in sorted(sets.items())
        ],
    }


@router.get("/{election_id}/audit-logs")
def audit_logs(
    election_id: str,
    limit: int = 100,
    action: str | None = None,
    profile: Profile = Depends(
        require_any_permission("audit.view", "audit.view_technical", "audit.view_limited")
    ),
    db: Session = Depends(get_db),
):
    get_election(db, election_id)
    query = select(AuditLog).where(AuditLog.election_id == election_id)
    roles = roles_for(db, profile.id)
    if not has_permission(roles, "audit.view") and not has_permission(roles, "audit.view_technical"):
        query = query.where(AuditLog.action.in_(LIMITED_AUDIT_ACTIONS))
    if action:
        query = query.where(AuditLog.action == action)
    rows = db.execute(query.order_by(AuditLog.created_at.desc()).limit(min(limit, 500))).scalars().all()
    return {
        "logs": [
            {
                "id": row.id,
                "action": row.action,
                "actor_role": row.actor_role,
                "entity": row.entity,
                "entity_id": row.entity_id,
                "outcome": row.outcome,
                "ip_address": row.ip_address,
                "detail": row.detail,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


@router.get("/{election_id}/audit-report")
def audit_report_json(
    election_id: str,
    profile: Profile = Depends(require_any_permission("audit.view", "audit.view_technical")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    report = audit_report(db, election)
    record_audit(db, action="audit.report", election_id=election.id, actor_id=profile.id,
                 entity="election", entity_id=election.id, detail={"format": "json"})
    db.commit()
    return report


@router.get("/{election_id}/audit-report.pdf")
def audit_report_pdf(
    election_id: str,
    request_ip: str = "",
    profile: Profile = Depends(require_any_permission("audit.view", "audit.view_technical")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    pdf = audit_pdf(audit_report(db, election))
    record_audit(db, action="audit.report", election_id=election.id, actor_id=profile.id,
                 entity="election", entity_id=election.id, detail={"format": "pdf"})
    db.commit()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="audit-report-{election.reference}.pdf"'},
    )


@router.get("/{election_id}/audit-report.xlsx")
def audit_report_excel(
    election_id: str,
    profile: Profile = Depends(require_any_permission("audit.view", "audit.view_technical")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    workbook = audit_xlsx(audit_report(db, election))
    record_audit(db, action="audit.report", election_id=election.id, actor_id=profile.id,
                 entity="election", entity_id=election.id, detail={"format": "xlsx"})
    db.commit()
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="audit-report-{election.reference}.xlsx"'},
    )


@router.get("/{election_id}/result-certificate.pdf")
def result_certificate(
    election_id: str,
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    declaration = db.execute(
        select(ResultDeclaration).where(
            ResultDeclaration.election_id == election.id, ResultDeclaration.is_current.is_(True)
        )
    ).scalars().first()
    if not declaration:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Results have not been declared")
    public = _public_results(db, election)
    pdf = result_certificate_pdf(election, {
        "figures": declaration.figures,
        "declared_at": declaration.declared_at.strftime("%d %b %Y %H:%M UTC"),
        "declared_by": declaration_dict(db, declaration, election)["declared_by"],
        "version": declaration.version,
        "signed_payload_hash": declaration.signed_payload_hash,
        "signature": declaration.signature,
    })
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="result-certificate-{election.reference}.pdf"'},
    )


@router.get("/{election_id}/results-status")
def results_status(
    election_id: str,
    profile: Profile = Depends(require_permission("monitor.view")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    declaration = db.execute(
        select(ResultDeclaration).where(
            ResultDeclaration.election_id == election.id, ResultDeclaration.is_current.is_(True)
        )
    ).scalars().first()
    return {
        "status": election.status,
        "status_label": STATUS_LABELS.get(election.status, election.status),
        "declared": bool(declaration),
        "declaration": declaration_dict(db, declaration, election) if declaration else None,
        "certificate_url": f"/api/monitoring/{election.id}/result-certificate.pdf" if declaration else None,
    }
