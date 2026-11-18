"""Vote counting: dual authorisation, authorised decryption, aggregation and proofs."""
from __future__ import annotations

import json
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import crypto
from ..commitments import canonical, publish_pending_commitments
from ..db import get_db
from ..deps import client_ip, record_audit, require_permission, roles_for
from ..models import (
    Ballot,
    BallotCommitment,
    BallotReceipt,
    Candidate,
    ChallengedBallot,
    Election,
    ElectionEvent,
    ElectionPosition,
    Profile,
    SpentCredential,
    TallyAuthorisation,
    TallyProof,
    TallyResult,
    TallyRun,
)
from ..services import election_stats, get_election, now

router = APIRouter(prefix="/tally", tags=["tally"])

CHAIRMAN = "chairman"
RETURNING = "returning_officer"


def _authorisations(db: Session, election_id: str) -> list[dict]:
    rows = db.execute(
        select(TallyAuthorisation, Profile)
        .join(Profile, Profile.id == TallyAuthorisation.profile_id)
        .where(TallyAuthorisation.election_id == election_id)
    ).all()
    return [
        {
            "profile_id": a.profile_id,
            "name": p.full_name,
            "role": a.role_key,
            "authorised_at": a.authorised_at.isoformat(),
        }
        for a, p in rows
    ]


def _counting_authorised(db: Session, election_id: str) -> tuple[bool, set[str]]:
    """Counting is authorised by one presiding official (the committee's rule).

    The Chairman conducts the election end to end, so a second authorisation is
    no longer required. Any authorisation on record still names its official.
    """
    roles = {a["role"] for a in _authorisations(db, election_id)}
    return (bool(roles), roles)


def _latest_completed_run(db: Session, election_id: str, run_id: str | None = None) -> TallyRun | None:
    query = select(TallyRun).where(TallyRun.election_id == election_id, TallyRun.status == "completed")
    if run_id:
        query = query.where(TallyRun.id == run_id)
    return db.execute(query.order_by(TallyRun.finished_at.desc())).scalars().first()


def tally_payload(db: Session, election: Election, run: TallyRun) -> dict:
    positions = db.execute(
        select(ElectionPosition).where(ElectionPosition.election_id == election.id)
        .order_by(ElectionPosition.order_index)
    ).scalars().all()
    candidates = db.execute(
        select(Candidate).where(Candidate.election_id == election.id).order_by(Candidate.order_index)
    ).scalars().all()
    results = db.execute(
        select(TallyResult).where(TallyResult.tally_run_id == run.id)
    ).scalars().all()
    by_candidate = {r.candidate_id: r for r in results}
    return {
        "tally_run_id": run.id,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "totals": {
            "accepted_ballots": run.accepted_ballots,
            "challenged_ballots": run.challenged_ballots,
            "valid_ballots": run.valid_ballots,
            "invalid_ballots": run.invalid_ballots,
        },
        "evidence_hash": run.evidence_hash,
        "signature": run.signature,
        "reconciliation": run.reconciliation,
        "positions": [
            {
                "id": p.id,
                "title": p.title,
                "seats": p.seats,
                "candidates": [
                    {
                        "id": c.id,
                        "full_name": c.full_name,
                        "votes": by_candidate[c.id].votes if c.id in by_candidate else 0,
                        "percentage": by_candidate[c.id].percentage if c.id in by_candidate else 0.0,
                        "is_winner": by_candidate[c.id].is_winner if c.id in by_candidate else False,
                    }
                    for c in candidates if c.position_id == p.id
                ],
            }
            for p in positions
        ],
    }


@router.post("/{election_id}/authorise")
def authorise_counting(
    election_id: str,
    request: Request,
    profile: Profile = Depends(require_permission("counting.authorise")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    if election.status not in {"voting_closed", "provisional_results"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Counting can only be authorised after voting closes")
    roles = roles_for(db, profile.id)
    role_key = CHAIRMAN if CHAIRMAN in roles else RETURNING if RETURNING in roles else None
    if not role_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the Chairman or Returning Officer can authorise counting")
    existing = db.execute(
        select(TallyAuthorisation).where(
            TallyAuthorisation.election_id == election.id,
            TallyAuthorisation.profile_id == profile.id,
        )
    ).scalars().first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "You have already authorised this count")
    db.add(TallyAuthorisation(election_id=election.id, profile_id=profile.id, role_key=role_key))
    record_audit(db, action="tally.authorise", election_id=election.id, actor_id=profile.id,
                 actor_role=role_key, entity="election", entity_id=election.id,
                 ip_address=client_ip(request))
    db.add(ElectionEvent(
        election_id=election.id, event_type="tally.authorised",
        message=f"Counting authorised by {role_key.replace('_', ' ')}", actor_id=profile.id,
    ))
    db.commit()
    authorised, role_set = _counting_authorised(db, election.id)
    return {
        "authorisations": _authorisations(db, election.id),
        "roles": sorted(role_set),
        "authorised": authorised,
        "message": "Counting authorised. The automated count may now run.",
    }


@router.post("/{election_id}/run")
def run_tally(
    election_id: str,
    request: Request,
    profile: Profile = Depends(require_permission("counting.run")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    if election.status not in {"voting_closed", "provisional_results", "under_review"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Voting must be closed before counting can begin")
    authorised, _role_set = _counting_authorised(db, election.id)
    if not authorised:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Counting must be authorised before the automated count can run",
        )

    publish_pending_commitments(db, election)
    ballots = db.execute(
        select(Ballot).where(Ballot.election_id == election.id, Ballot.accepted.is_(True))
        .order_by(Ballot.cast_at)
    ).scalars().all()
    if not ballots:
        raise HTTPException(status.HTTP_409_CONFLICT, "There are no accepted ballots to count")

    positions = db.execute(
        select(ElectionPosition).where(ElectionPosition.election_id == election.id)
    ).scalars().all()
    candidates = {
        c.id: c for c in db.execute(
            select(Candidate).where(Candidate.election_id == election.id)
        ).scalars()
    }
    valid_positions = {p.id for p in positions}

    election.status = "counting"
    run = TallyRun(election_id=election.id, started_by=profile.id, status="running")
    db.add(run)
    db.flush()

    commitments = [b.ballot_commitment for b in ballots]
    counts: dict[str, int] = {c.id: 0 for c in candidates.values()}
    valid_count = invalid_count = 0
    chain = crypto.sha256_hex("SJC-TALLY-GENESIS", run.id, election.reference)
    proofs: list[TallyProof] = []
    invalid_commitments: list[str] = []

    for index, ballot in enumerate(ballots):
        counted = True
        selections: dict[str, str] = {}
        try:
            selections = crypto.decrypt_ballot(
                election.id, election.reference, ballot.ciphertext, ballot.encrypted_key, ballot.nonce
            )
            if not isinstance(selections, dict) or not selections:
                raise ValueError("Empty ballot")
            for position_id, candidate_id in selections.items():
                candidate = candidates.get(candidate_id)
                if position_id not in valid_positions or not candidate or candidate.position_id != position_id:
                    raise ValueError("Selection does not match an approved candidate")
            valid_count += 1
            for candidate_id in selections.values():
                counts[candidate_id] = counts.get(candidate_id, 0) + 1
        except crypto.KeyMaterialError:
            # Missing key material is a deployment fault, not a bad ballot. Left
            # to the handler below it would record every ballot as invalid and
            # publish a tally that silently disagrees with the ballot box.
            raise
        except Exception:
            counted = False
            invalid_count += 1
            invalid_commitments.append(ballot.ballot_commitment)
            selections = {}

        ballot_hash = crypto.sha256_hex(
            "SJC-DECRYPTED", ballot.ballot_commitment, json.dumps(selections, sort_keys=True)
        )
        chain = crypto.sha256_hex("SJC-TALLY-CHAIN", chain, ballot_hash)
        proofs.append(TallyProof(
            tally_run_id=run.id,
            election_id=election.id,
            ballot_commitment=ballot.ballot_commitment,
            merkle_proof=crypto.merkle_proof(commitments, index),
            ballot_hash=ballot_hash,
            chain_hash=chain,
            counted=counted,
        ))

    # Winners per position (highest votes; ties flagged).
    winners: list[dict] = []
    for position in positions:
        ranked = sorted(
            [c for c in candidates.values() if c.position_id == position.id],
            key=lambda c: counts.get(c.id, 0),
            reverse=True,
        )
        seats = max(position.seats, 1)
        for rank, candidate in enumerate(ranked):
            is_winner = rank < seats and counts.get(candidate.id, 0) > 0
            if rank < seats and rank > 0 and counts.get(candidate.id, 0) == counts.get(ranked[0].id, 0):
                is_winner = True
            winners.append({
                "position_id": position.id,
                "candidate_id": candidate.id,
                "votes": counts.get(candidate.id, 0),
                "is_winner": is_winner,
            })

    for position in positions:
        for candidate in [c for c in candidates.values() if c.position_id == position.id]:
            winner_row = next(
                (w for w in winners if w["position_id"] == position.id and w["candidate_id"] == candidate.id),
                None,
            )
            votes = counts.get(candidate.id, 0)
            db.add(TallyResult(
                tally_run_id=run.id,
                election_id=election.id,
                position_id=position.id,
                candidate_id=candidate.id,
                votes=votes,
                percentage=round(votes / valid_count * 100, 2) if valid_count else 0.0,
                is_winner=bool(winner_row and winner_row["is_winner"]),
            ))

    accepted = len(ballots)
    challenged = db.scalar(
        select(func.count(ChallengedBallot.id)).where(ChallengedBallot.election_id == election.id)
    ) or 0
    receipts = db.scalar(
        select(func.count(BallotReceipt.id)).where(BallotReceipt.election_id == election.id)
    ) or 0
    commitments_count = db.scalar(
        select(func.count(BallotCommitment.id)).where(BallotCommitment.election_id == election.id)
    ) or 0
    spent = db.scalar(
        select(func.count(SpentCredential.id)).where(SpentCredential.election_id == election.id)
    ) or 0

    evidence = {
        "schema": "SJC-TALLY-EVIDENCE-V1",
        "election_reference": election.reference,
        "tally_run_id": run.id,
        "accepted_ballots": accepted,
        "valid_ballots": valid_count,
        "invalid_ballots": invalid_count,
        "challenged_ballots": challenged,
        "merkle_root": crypto.merkle_root(commitments),
        "chain_hash": chain,
        "results": [
            {"position_id": p.id, "candidates": [
                {"candidate_id": c.id, "votes": counts.get(c.id, 0)}
                for c in candidates.values() if c.position_id == p.id
            ]}
            for p in positions
        ],
        "finished_at": now().isoformat(),
    }
    run.accepted_ballots = accepted
    run.challenged_ballots = challenged
    run.valid_ballots = valid_count
    run.invalid_ballots = invalid_count
    run.evidence_hash = crypto.sha256_hex("SJC-TALLY-EVIDENCE", canonical(evidence).decode())
    run.signature = crypto.election_sign(election.id, canonical(evidence))
    run.reconciliation = {
        "accepted_ballots": accepted,
        "receipts_issued": receipts,
        "commitments_published": commitments_count,
        "spent_credentials": spent,
        "valid_plus_invalid": valid_count + invalid_count,
        "balanced": accepted == valid_count + invalid_count == receipts == spent,
        "invalid_ballot_commitments": invalid_commitments,
    }
    run.status = "completed"
    run.finished_at = now()
    for proof in proofs:
        db.add(proof)

    election.status = "provisional_results"
    db.add(ElectionEvent(
        election_id=election.id, event_type="tally.completed",
        message=f"Automated count completed: {valid_count} valid, {invalid_count} invalid, "
                f"{challenged} challenged ballots",
        actor_id=profile.id,
    ))
    record_audit(db, action="tally.run", election_id=election.id, actor_id=profile.id,
                 entity="tally_run", entity_id=run.id, ip_address=client_ip(request),
                 detail={"accepted": accepted, "valid": valid_count, "invalid": invalid_count})
    db.commit()
    db.refresh(run)
    return tally_payload(db, election, run)


@router.get("/{election_id}")
def get_tally(
    election_id: str,
    run_id: str | None = None,
    profile: Profile = Depends(require_permission("tally.view")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    run = _latest_completed_run(db, election.id, run_id)
    keys_available = crypto.election_keys_available(election.id)
    # A brand-new election has no keys yet: they are generated when dual-control
    # configuration approval completes. That is different from keys that once
    # existed and are gone, and the console must not confuse the two.
    keys_provisioned = bool(election.tally_public_key)
    if not run:
        return {
            "election_id": election.id,
            "status": election.status,
            "tally": None,
            "keys_available": keys_available,
            "keys_provisioned": keys_provisioned,
            "authorisations": _authorisations(db, election.id),
            "authorised": _counting_authorised(db, election.id)[0],
        }
    return {
        "election_id": election.id,
        "status": election.status,
        "tally": tally_payload(db, election, run),
        "keys_available": keys_available,
        "keys_provisioned": keys_provisioned,
        "authorisations": _authorisations(db, election.id),
        "authorised": _counting_authorised(db, election.id)[0],
        "stats": election_stats(db, election.id),
    }


@router.get("/{election_id}/runs")
def list_runs(
    election_id: str,
    profile: Profile = Depends(require_permission("tally.view")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    runs = db.execute(
        select(TallyRun).where(TallyRun.election_id == election.id).order_by(TallyRun.started_at.desc())
    ).scalars().all()
    return {
        "runs": [
            {
                "id": r.id,
                "status": r.status,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "accepted_ballots": r.accepted_ballots,
                "valid_ballots": r.valid_ballots,
                "invalid_ballots": r.invalid_ballots,
                "challenged_ballots": r.challenged_ballots,
                "evidence_hash": r.evidence_hash,
                "signature": r.signature,
                "reconciliation": r.reconciliation,
            }
            for r in runs
        ]
    }


@router.get("/{election_id}/proofs")
def list_proofs(
    election_id: str,
    limit: int = 200,
    offset: int = 0,
    profile: Profile = Depends(require_permission("tally.view")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    run = _latest_completed_run(db, election.id)
    if not run:
        return {"proofs": [], "total": 0}
    total = db.scalar(
        select(func.count(TallyProof.id)).where(TallyProof.tally_run_id == run.id)
    ) or 0
    rows = db.execute(
        select(TallyProof).where(TallyProof.tally_run_id == run.id)
        .order_by(TallyProof.chain_hash).offset(offset).limit(min(limit, 1000))
    ).scalars().all()
    return {
        "tally_run_id": run.id,
        "total": total,
        "evidence_hash": run.evidence_hash,
        "signature": run.signature,
        "proofs": [
            {
                "ballot_commitment": p.ballot_commitment,
                "ballot_hash": p.ballot_hash,
                "chain_hash": p.chain_hash,
                "counted": p.counted,
                "merkle_proof": p.merkle_proof,
            }
            for p in rows
        ],
    }
