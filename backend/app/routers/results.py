"""Provisional results, authorised declaration and versioned corrections."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import crypto
from ..commitments import canonical
from ..db import get_db
from ..deps import client_ip, record_audit, require_any_permission, require_permission, roles_for
from ..models import (
    BallotCommitment,
    BallotReceipt,
    Candidate,
    ChallengedBallot,
    Election,
    ElectionDocument,
    ElectionEvent,
    ElectionPosition,
    Profile,
    ResultApproval,
    ResultDeclaration,
    TallyProof,
    TallyRun,
)
from ..schemas import CorrectionRequest, ResultSubmit, STATUS_LABELS
from ..notifications import notify_results_declared
from ..security import has_permission
from ..services import election_stats, find_results_election, get_election, now
from ..receipts import fmt

router = APIRouter(prefix="/results", tags=["results"])


def _latest_run(db: Session, election_id: str) -> TallyRun | None:
    return db.execute(
        select(TallyRun).where(TallyRun.election_id == election_id, TallyRun.status == "completed")
        .order_by(TallyRun.finished_at.desc())
    ).scalars().first()


def _tally_rows(db: Session, election_id: str, run_id: str):
    positions = db.execute(
        select(ElectionPosition).where(ElectionPosition.election_id == election_id)
        .order_by(ElectionPosition.order_index)
    ).scalars().all()
    candidates = db.execute(
        select(Candidate).where(Candidate.election_id == election_id).order_by(Candidate.order_index)
    ).scalars().all()
    from ..models import TallyResult

    results = {
        r.candidate_id: r
        for r in db.execute(select(TallyResult).where(TallyResult.tally_run_id == run_id)).scalars()
    }
    return positions, candidates, results


def build_figures(db: Session, election: Election, run: TallyRun) -> dict:
    positions, candidates, tallies = _tally_rows(db, election.id, run.id)
    stats = election_stats(db, election.id)
    approvals = db.execute(
        select(ResultApproval).where(ResultApproval.election_id == election.id)
        .order_by(ResultApproval.created_at)
    ).scalars().all()
    challenger = db.scalar(
        select(func.count(ChallengedBallot.id)).where(ChallengedBallot.election_id == election.id)
    ) or 0
    receipts = db.scalar(
        select(func.count(BallotReceipt.id)).where(BallotReceipt.election_id == election.id)
    ) or 0
    commitments = db.scalar(
        select(func.count(BallotCommitment.id)).where(BallotCommitment.election_id == election.id)
    ) or 0
    proofs = db.scalar(
        select(func.count(TallyProof.id)).where(TallyProof.tally_run_id == run.id, TallyProof.counted.is_(True))
    ) or 0

    position_rows = []
    for position in positions:
        entries = sorted(
            [c for c in candidates if c.position_id == position.id],
            key=lambda c: tallies[c.id].votes if c.id in tallies else 0,
            reverse=True,
        )
        top_votes = (tallies[entries[0].id].votes if entries and entries[0].id in tallies else 0)
        position_rows.append({
            "id": position.id,
            "title": position.title,
            "seats": position.seats,
            "candidates": [
                {
                    "id": c.id,
                    "full_name": c.full_name,
                    "votes": tallies[c.id].votes if c.id in tallies else 0,
                    "percentage": tallies[c.id].percentage if c.id in tallies else 0.0,
                    "is_winner": tallies[c.id].is_winner if c.id in tallies else False,
                    "tie": bool(
                        entries and entries[0].id in tallies
                        and (tallies[c.id].votes if c.id in tallies else 0) == top_votes
                        and sum(1 for e in entries if e.id in tallies and tallies[e.id].votes == top_votes) > 1
                    ),
                }
                for c in entries
            ],
            "winners": [
                c.full_name for c in entries
                if c.id in tallies and tallies[c.id].is_winner
            ],
        })

    return {
        "election": {
            "id": election.id,
            "title": election.title,
            "reference": election.reference,
            "year": election.year,
            "timezone": election.timezone,
        },
        "totals": {
            "eligible_voters": stats["eligible_voters"],
            "accredited_voters": stats["accredited_voters"],
            "votes_cast": run.accepted_ballots,
            "valid_ballots": run.valid_ballots,
            "invalid_ballots": run.invalid_ballots,
            "challenged_ballots": challenger,
            "turnout_percentage": stats["turnout_percentage"],
        },
        "positions": position_rows,
        "verification": {
            "receipts_issued": receipts,
            "published_commitments": commitments,
            "challenged_ballots": challenger,
            "counted_ballot_proofs": proofs,
            "tally_evidence_hash": run.evidence_hash,
            "tally_signature": run.signature,
            "reconciliation": run.reconciliation,
        },
        "approvals": [
            {
                "stage": a.stage,
                "approver_role": a.approver_role,
                "status": a.approval_status,
                "comments": a.comments,
                "at": a.created_at.isoformat(),
            }
            for a in approvals
        ],
        "tally_run_id": run.id,
    }


def declaration_dict(db: Session, declaration: ResultDeclaration, election: Election) -> dict:
    signer = db.get(Profile, declaration.declared_by)
    signature_valid = crypto.election_verify(
        election.signing_public_key, canonical(declaration.figures), declaration.signature
    ) if declaration.signature else False
    return {
        "id": declaration.id,
        "version": declaration.version,
        "is_current": declaration.is_current,
        "figures": declaration.figures,
        "signature": declaration.signature,
        "signed_payload_hash": declaration.signed_payload_hash,
        "signature_valid": signature_valid,
        "correction_reason": declaration.correction_reason,
        "declared_at": declaration.declared_at.isoformat(),
        "declared_by": signer.full_name if signer else "Electoral Committee Chairman",
        "signing_public_key": crypto.signing_public_b64_from_pem(election.signing_public_key),
        "tally_run_id": declaration.tally_run_id,
    }


def _declare(
    db: Session, election: Election, run: TallyRun, profile: Profile, reason: str | None = None
) -> ResultDeclaration:
    figures = build_figures(db, election, run)
    figures["declaration"] = {
        "declared_at": now().isoformat(),
        "correction_reason": reason,
    }
    version = (db.scalar(
        select(func.max(ResultDeclaration.version)).where(ResultDeclaration.election_id == election.id)
    ) or 0) + 1
    db.query(ResultDeclaration).filter(
        ResultDeclaration.election_id == election.id
    ).update({ResultDeclaration.is_current: False}, synchronize_session=False)
    signature = crypto.election_sign(election.id, canonical(figures))
    declaration = ResultDeclaration(
        election_id=election.id,
        tally_run_id=run.id,
        version=version,
        is_current=True,
        figures=figures,
        signature=signature,
        signed_payload_hash=crypto.sha256_hex("SJC-DECLARATION", canonical(figures).decode()),
        correction_reason=reason,
        declared_by=profile.id,
        declared_at=now(),
    )
    db.add(declaration)
    db.flush()
    db.add(ElectionDocument(
        election_id=election.id,
        kind="result_declaration",
        title=f"Official results declaration v{version}",
        content_hash=declaration.signed_payload_hash,
        signature=signature,
        payload=figures,
    ))
    return declaration


@router.get("/{election_id}")
def get_results(
    election_id: str,
    profile: Profile = Depends(
        require_any_permission("results.review", "results.review_restricted")
    ),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    run = _latest_run(db, election.id)
    declarations = db.execute(
        select(ResultDeclaration).where(ResultDeclaration.election_id == election.id)
        .order_by(ResultDeclaration.version.desc())
    ).scalars().all()
    approvals = db.execute(
        select(ResultApproval).where(ResultApproval.election_id == election.id)
        .order_by(ResultApproval.created_at)
    ).scalars().all()

    # Observers hold results.review_restricted: they see only signed, declared results,
    # never the provisional tally or internal approval comments.
    restricted = not has_permission(roles_for(db, profile.id), "results.review")
    provisional = None if restricted else (build_figures(db, election, run) if run else None)
    visible_declarations = declarations
    visible_approvals = [] if restricted else approvals
    if restricted and election.status not in {"declared", "archived"}:
        visible_declarations = []

    return {
        "election": {"id": election.id, "title": election.title, "status": election.status,
                     "status_label": election.status.replace("_", " ").title()},
        "provisional": provisional,
        "declarations": [declaration_dict(db, d, election) for d in visible_declarations],
        "approvals": [
            {"stage": a.stage, "approver_role": a.approver_role, "status": a.approval_status,
             "comments": a.comments, "at": a.created_at.isoformat()}
            for a in visible_approvals
        ],
    }


@router.post("/{election_id}/submit")
def submit_results(
    election_id: str,
    payload: ResultSubmit,
    request: Request,
    profile: Profile = Depends(require_permission("results.submit")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    run = _latest_run(db, election.id)
    if not run:
        raise HTTPException(status.HTTP_409_CONFLICT, "Counting has not been completed")
    if election.status != "provisional_results":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Provisional results are not awaiting submission (this election is "
            f"{STATUS_LABELS.get(election.status, election.status).lower()})",
        )
    # One office now conducts the count and the declaration, so the trail always
    # names the Chairman.
    role_key = "chairman"
    single_official = True
    comments = (payload.comments or "").strip()
    if single_official:
        comments = (
            f"{comments} Single-official path: the Chairman submitted the provisional "
            "figures and will also approve and declare the result."
        ).strip()
    db.add(ResultApproval(
        election_id=election.id, tally_run_id=run.id, stage="provisional_review",
        approver_id=profile.id, approver_role=role_key,
        approval_status="submitted", comments=comments,
    ))
    election.status = "under_review"
    record_audit(db, action="results.submit", election_id=election.id, actor_id=profile.id,
                 actor_role=role_key, entity="tally_run", entity_id=run.id,
                 ip_address=client_ip(request),
                 detail={"role": role_key, "single_official": single_official,
                         "submitted_by": profile.id})
    db.add(ElectionEvent(
        election_id=election.id, event_type="results.submitted",
        message=(
            f"Provisional results submitted for approval by the {role_key.replace('_', ' ')}"
            + (" (single-official completion: the same account will declare them)"
               if single_official else "")
        ),
        actor_id=profile.id,
    ))
    db.commit()
    return {"status": election.status, "message": "Provisional results submitted for Chairman approval"}


@router.post("/{election_id}/approve")
def approve_and_declare(
    election_id: str,
    request: Request,
    profile: Profile = Depends(require_permission("results.approve")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    if election.status != "under_review":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Results must be submitted for review before approval (this election is "
            f"{STATUS_LABELS.get(election.status, election.status).lower()})",
        )
    run = _latest_run(db, election.id)
    if not run:
        raise HTTPException(status.HTTP_409_CONFLICT, "Counting has not been completed")
    submission = db.execute(
        select(ResultApproval).where(
            ResultApproval.election_id == election.id,
            ResultApproval.stage == "provisional_review",
        ).order_by(ResultApproval.created_at.desc())
    ).scalars().first()
    single_official = bool(submission and submission.approver_id == profile.id)
    comments = (
        "Official results approved and declared by the same official who submitted the "
        "provisional figures. Single-official completion: the two-official control was "
        "not exercised."
        if single_official else "Official results approved and declared"
    )
    db.add(ResultApproval(
        election_id=election.id, tally_run_id=run.id, stage="final_approval",
        approver_id=profile.id, approver_role="chairman", approval_status="approved",
        comments=comments,
    ))
    declaration = _declare(db, election, run, profile)
    election.status = "declared"
    record_audit(db, action="results.declare", election_id=election.id, actor_id=profile.id,
                 entity="result_declaration", entity_id=declaration.id, ip_address=client_ip(request),
                 detail={"version": declaration.version, "hash": declaration.signed_payload_hash,
                         "single_official": single_official,
                         "submitted_by": submission.approver_id if submission else None})
    db.add(ElectionEvent(
        election_id=election.id, event_type="results.declared",
        message=(
            f"Official results declared (version {declaration.version})"
            + (" by one official: the same account submitted and declared the result"
               if single_official else "")
        ),
        actor_id=profile.id,
    ))
    db.commit()
    db.refresh(declaration)
    payload = declaration_dict(db, declaration, election)
    payload["single_official_declaration"] = single_official
    # The declaration is already committed, so voters' result notices can never
    # delay or roll it back. The delivery summary is reported back to the admin.
    try:
        payload["voter_notifications"] = notify_results_declared(
            db,
            election=election,
            figures=declaration.figures,
            declared_at=declaration.declared_at,
            version=declaration.version,
            request_ip=client_ip(request),
        )
    except Exception:
        db.rollback()
        payload["voter_notifications"] = {"error": "result notices could not be sent"}
    return payload


@router.post("/{election_id}/corrections")
def correct_declaration(
    election_id: str,
    payload: CorrectionRequest,
    request: Request,
    profile: Profile = Depends(require_permission("results.approve")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    if election.status != "declared":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only declared results can be corrected")
    run = _latest_run(db, election.id)
    if not run:
        raise HTTPException(status.HTTP_409_CONFLICT, "No completed count found")
    declaration = _declare(db, election, run, profile, reason=payload.reason)
    record_audit(db, action="results.correction", election_id=election.id, actor_id=profile.id,
                 entity="result_declaration", entity_id=declaration.id, ip_address=client_ip(request),
                 detail={"reason": payload.reason, "version": declaration.version})
    db.add(ElectionEvent(
        election_id=election.id, event_type="results.corrected",
        message=f"Official results corrected (version {declaration.version}): {payload.reason[:180]}",
        actor_id=profile.id,
    ))
    db.commit()
    db.refresh(declaration)
    return declaration_dict(db, declaration, election)


@router.get("/public/current")
def public_current(db: Session = Depends(get_db)):
    election = find_results_election(db)
    if not election:
        return {"published": False, "election": None}
    return _public_results(db, election)


@router.get("/public/{election_id}")
def public_results(election_id: str, db: Session = Depends(get_db)):
    return _public_results(db, get_election(db, election_id))


def _public_results(db: Session, election: Election) -> dict:
    declaration = db.execute(
        select(ResultDeclaration).where(
            ResultDeclaration.election_id == election.id,
            ResultDeclaration.is_current.is_(True),
        )
    ).scalars().first()
    stats = election_stats(db, election.id)
    base = {
        "published": bool(declaration),
        "election": {
            "id": election.id, "title": election.title, "reference": election.reference,
            "year": election.year, "status": election.status,
            "status_label": election.status.replace("_", " ").title(),
        },
        "turnout": {
            "eligible_voters": stats["eligible_voters"],
            "accredited_voters": stats["accredited_voters"],
            "votes_cast": stats["votes_cast"],
            "turnout_percentage": stats["turnout_percentage"],
        },
    }
    if not declaration:
        base["message"] = "Official results have not been declared yet."
        return base
    data = declaration_dict(db, declaration, election)
    base.update({
        "declared_at": data["declared_at"],
        "declared_by": data["declared_by"],
        "signature": data["signature"],
        "signature_valid": data["signature_valid"],
        "signed_payload_hash": data["signed_payload_hash"],
        "signing_public_key": data["signing_public_key"],
        "version": data["version"],
        "correction_reason": data["correction_reason"],
        "figures": data["figures"],
        "verification_statistics": data["figures"].get("verification"),
        "message": "Official results declared and digitally signed.",
    })
    return base
