"""Anonymous ballot commitment publication (Merkle tree + Ed25519 signature)."""
from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import crypto
from .models import BallotCommitment, Election, PublishedCommitmentBatch
from .services import now


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def batch_header(election: Election, batch_reference: str, count: int, root: str, published_at: str) -> dict:
    return {
        "schema": "SJC-COMMITMENT-BATCH-V1",
        "election_id": election.id,
        "election_reference": election.reference,
        "batch_reference": batch_reference,
        "commitment_count": count,
        "merkle_root": root,
        "published_at": published_at,
    }


def publish_pending_commitments(db: Session, election: Election) -> PublishedCommitmentBatch | None:
    rows = db.execute(
        select(BallotCommitment)
        .where(BallotCommitment.election_id == election.id, BallotCommitment.batch_id.is_(None))
        .where(BallotCommitment.commitment_status == "accepted")
        .order_by(BallotCommitment.created_at)
    ).scalars().all()
    if not rows:
        return None

    commitments = [row.ballot_commitment for row in rows]
    root = crypto.merkle_root(commitments)
    count = db.scalar(
        select(func.count(PublishedCommitmentBatch.id)).where(
            PublishedCommitmentBatch.election_id == election.id
        )
    ) or 0
    batch_reference = f"{election.reference}-B{count + 1:02d}"
    published_at = now().isoformat()
    header = batch_header(election, batch_reference, len(commitments), root, published_at)
    signature = crypto.election_sign(election.id, canonical(header))

    batch = PublishedCommitmentBatch(
        election_id=election.id,
        batch_reference=batch_reference,
        commitment_count=len(commitments),
        merkle_root=root,
        digital_signature=signature,
        signed_payload=header,
        published_at=now(),
    )
    db.add(batch)
    db.flush()

    for row in rows:
        row.batch_id = batch.id
        row.ballot_proof = {
            **(row.ballot_proof or {}),
            "batch_reference": batch_reference,
            "merkle_index": commitments.index(row.ballot_commitment),
        }
    db.commit()
    db.refresh(batch)
    return batch


def batch_manifest(db: Session, election: Election, batch: PublishedCommitmentBatch) -> dict:
    rows = db.execute(
        select(BallotCommitment)
        .where(BallotCommitment.batch_id == batch.id)
        .order_by(BallotCommitment.created_at)
    ).scalars().all()
    commitments = [row.ballot_commitment for row in rows]
    entries = [
        {
            "index": index,
            "ballot_commitment": commitment,
            "merkle_proof": crypto.merkle_proof(commitments, index),
        }
        for index, commitment in enumerate(commitments)
    ]
    header = batch.signed_payload or batch_header(
        election, batch.batch_reference, batch.commitment_count, batch.merkle_root,
        (batch.published_at or now()).isoformat(),
    )
    return {
        "header": header,
        "merkle_root": batch.merkle_root,
        "digital_signature": batch.digital_signature,
        "signing_public_key": crypto.signing_public_b64_from_pem(election.signing_public_key),
        "verification_instructions": (
            "Recompute the Merkle root from the commitments using SHA-256 with the "
            "'SJC-LEAF|' and 'SJC-NODE|' domain prefixes, then verify the Ed25519 signature "
            "over the canonical JSON header (sorted keys, compact separators)."
        ),
        "commitments": entries,
    }
