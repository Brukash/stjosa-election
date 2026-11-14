"""Public verification portal: ballot inclusion, commitment list, public keys."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto
from ..commitments import batch_manifest, canonical, publish_pending_commitments
from ..db import get_db
from ..deps import client_ip, record_audit, require_permission
from ..models import (
    Ballot,
    BallotCommitment,
    BallotReceipt,
    Election,
    ElectionVerificationSetting,
    PublishedCommitmentBatch,
    Profile,
    TallyProof,
    TallyRun,
)
from ..services import get_election, get_settings_row, resolve_public_election

router = APIRouter(tags=["verification"])

PUBLISHABLE = {"voting_closed", "counting", "provisional_results", "under_review", "declared", "archived"}


@router.get("/verify/{reference}")
def verify_receipt(reference: str, db: Session = Depends(get_db)):
    digest = crypto.receipt_hash(reference)
    receipt = db.execute(
        select(BallotReceipt).where(BallotReceipt.receipt_hash == digest)
    ).scalar_one_or_none()
    if not receipt:
        return {
            "found": False,
            "message": "No ballot was found for this verification reference. Check the reference and try again.",
        }
    election = db.get(Election, receipt.election_id)
    settings_row = get_settings_row(db, election.id)
    ballot = db.execute(
        select(Ballot).where(
            Ballot.election_id == election.id,
            Ballot.ballot_commitment == receipt.ballot_commitment,
        )
    ).scalars().first()
    commitment = db.execute(
        select(BallotCommitment).where(
            BallotCommitment.election_id == election.id,
            BallotCommitment.ballot_commitment == receipt.ballot_commitment,
        )
    ).scalars().first()

    result = {
        "found": True,
        "receipt_number": receipt.receipt_number,
        "verification_reference": reference.strip().upper(),
        "issued_at": receipt.issued_at.isoformat(),
        "accepted": bool(ballot and ballot.accepted),
        "ballot_commitment": receipt.ballot_commitment,
        "election": {
            "id": election.id,
            "title": election.title,
            "reference": election.reference,
            "year": election.year,
            "status": election.status,
        },
        "checks": {
            "receipt_valid": True,
            "ballot_recorded": bool(ballot),
            "commitment_present": bool(commitment),
            "published": False,
            "merkle_verified": False,
            "counted_in_tally": False,
            "signature_verified": False,
        },
        "batch": None,
        "tally": None,
        "settings": {
            "ballot_inclusion_enabled": settings_row.ballot_inclusion_enabled,
            "public_commitment_list_enabled": settings_row.public_commitment_list_enabled,
        },
    }

    if not settings_row.ballot_inclusion_enabled:
        result["message"] = "Ballot inclusion verification is disabled for this election."
        return result

    if commitment and commitment.batch_id:
        batch = db.get(PublishedCommitmentBatch, commitment.batch_id)
        if batch:
            rows = db.execute(
                select(BallotCommitment)
                .where(BallotCommitment.batch_id == batch.id)
                .order_by(BallotCommitment.created_at)
            ).scalars().all()
            commitments = [row.ballot_commitment for row in rows]
            try:
                index = commitments.index(commitment.ballot_commitment)
                proof = crypto.merkle_proof(commitments, index)
                header = batch.signed_payload or {}
                signature_valid = crypto.election_verify(
                    election.id, canonical(header), batch.digital_signature
                )
            except ValueError:
                proof, signature_valid = None, False
            result["checks"].update(
                published=True,
                merkle_verified=bool(proof and crypto.verify_merkle_proof(commitment.ballot_commitment, proof)),
                signature_verified=signature_valid,
            )
            result["batch"] = {
                "reference": batch.batch_reference,
                "merkle_root": batch.merkle_root,
                "commitment_count": batch.commitment_count,
                "published_at": batch.published_at.isoformat() if batch.published_at else None,
                "digital_signature": batch.digital_signature,
                "merkle_proof": proof,
                "header": header,
                "signing_public_key": crypto.signing_public_key_b64(election.id),
                "download_url": f"/api/commitments/{election.id}/batches/{batch.batch_reference}/download",
            }

    tally_proof = db.execute(
        select(TallyProof).where(TallyProof.ballot_commitment == receipt.ballot_commitment)
        .order_by(TallyProof.id)
    ).scalars().first()
    if tally_proof:
        run = db.get(TallyRun, tally_proof.tally_run_id)
        result["checks"]["counted_in_tally"] = bool(tally_proof.counted and run and run.status == "completed")
        result["tally"] = {
            "tally_run_id": tally_proof.tally_run_id,
            "counted": tally_proof.counted,
            "ballot_hash": tally_proof.ballot_hash,
            "chain_hash": tally_proof.chain_hash,
            "finished_at": run.finished_at.isoformat() if run and run.finished_at else None,
            "evidence_hash": run.evidence_hash if run else None,
            "signature": run.signature if run else None,
        }

    if result["checks"]["published"] and result["checks"]["merkle_verified"]:
        result["message"] = (
            "Your ballot commitment is in the published election record and is covered by the "
            "signed Merkle root."
            + (" It has been included in the final count." if result["checks"]["counted_in_tally"] else "")
        )
    elif receipt and ballot:
        result["message"] = (
            "Your ballot was accepted and recorded. The anonymous commitment list has not been "
            "published yet; check again after voting closes."
        )
    return result


@router.get("/commitments/{election_id}")
def commitment_batches(election_id: str, db: Session = Depends(get_db)):
    election = get_election(db, election_id)
    settings_row = get_settings_row(db, election.id)
    if not settings_row.public_commitment_list_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The public commitment list is disabled for this election")
    batches = db.execute(
        select(PublishedCommitmentBatch).where(PublishedCommitmentBatch.election_id == election.id)
        .order_by(PublishedCommitmentBatch.created_at)
    ).scalars().all()
    return {
        "election": {
            "id": election.id, "title": election.title, "reference": election.reference,
            "status": election.status,
        },
        "settings": {"public_commitment_list_enabled": settings_row.public_commitment_list_enabled},
        "batches": [
            {
                "batch_reference": b.batch_reference,
                "commitment_count": b.commitment_count,
                "merkle_root": b.merkle_root,
                "digital_signature": b.digital_signature,
                "published_at": b.published_at.isoformat() if b.published_at else None,
                "header": b.signed_payload,
                "signature_verified": crypto.election_verify(
                    election.id, canonical(b.signed_payload or {}), b.digital_signature
                ),
                "download_url": f"/api/commitments/{election.id}/batches/{b.batch_reference}/download",
            }
            for b in batches
        ],
        "note": "This list contains anonymous ballot commitments only. It contains no voter identity and no selections.",
    }


@router.get("/commitments/{election_id}/batches/{batch_reference}/download")
def download_batch(election_id: str, batch_reference: str, db: Session = Depends(get_db)):
    election = get_election(db, election_id)
    batch = db.execute(
        select(PublishedCommitmentBatch).where(
            PublishedCommitmentBatch.election_id == election.id,
            PublishedCommitmentBatch.batch_reference == batch_reference,
        )
    ).scalar_one_or_none()
    if not batch:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Batch not found")
    return batch_manifest(db, election, batch)


@router.post("/commitments/{election_id}/publish")
def publish_commitments(
    election_id: str,
    request: Request,
    profile: Profile = Depends(require_permission("counting.authorise")),
    db: Session = Depends(get_db),
):
    election = get_election(db, election_id)
    if election.status not in PUBLISHABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Commitments can only be published after voting closes")
    settings_row = get_settings_row(db, election.id)
    if not settings_row.public_commitment_list_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The public commitment list is disabled for this election")
    batch = publish_pending_commitments(db, election)
    record_audit(db, action="commitments.publish", election_id=election.id, actor_id=profile.id,
                 entity="commitment_batch", entity_id=batch.batch_reference if batch else None,
                 ip_address=client_ip(request))
    db.commit()
    if not batch:
        return {"published": False, "message": "No unpublished commitments remain"}
    return {
        "published": True,
        "batch_reference": batch.batch_reference,
        "commitment_count": batch.commitment_count,
        "merkle_root": batch.merkle_root,
        "digital_signature": batch.digital_signature,
    }


@router.get("/crypto/{election_id}")
def public_keys(election_id: str, db: Session = Depends(get_db)):
    election = get_election(db, election_id)
    return {
        "election_reference": election.reference,
        "credential": crypto.credential_public_numbers(),
        "tally_public_key": election.tally_public_key,
        "signing_public_key": crypto.signing_public_key_b64(election.id) if election.signing_public_key else None,
        "hash": "SHA-256",
        "commitment_scheme": "SHA-256 over election reference, nonce, wrapped key and ciphertext",
    }
