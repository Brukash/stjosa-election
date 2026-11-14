"""Voting receipt retrieval and PDF download."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crypto
from ..config import settings
from ..db import get_db
from ..models import BallotReceipt, Election
from ..receipts import build_receipt_pdf, receipt_payload
from ..services import get_settings_row

router = APIRouter(prefix="/receipts", tags=["receipts"])


def _lookup(db: Session, reference: str) -> tuple[BallotReceipt, Election]:
    receipt = db.execute(
        select(BallotReceipt).where(BallotReceipt.receipt_hash == crypto.receipt_hash(reference))
    ).scalar_one_or_none()
    if not receipt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")
    election = db.get(Election, receipt.election_id)
    if not election:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Election not found")
    return receipt, election


@router.get("/{reference}")
def get_receipt(reference: str, db: Session = Depends(get_db)):
    receipt, election = _lookup(db, reference)
    settings_row = get_settings_row(db, election.id)
    return receipt_payload(election, receipt, verification_enabled=settings_row.pdf_receipt_enabled)


@router.get("/{reference}/pdf")
def download_receipt(reference: str, db: Session = Depends(get_db)):
    receipt, election = _lookup(db, reference)
    settings_row = get_settings_row(db, election.id)
    if not settings_row.pdf_receipt_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "PDF receipts are disabled for this election")
    verify_url = f"{settings.app_origin}/verify?ref={reference}"
    pdf = build_receipt_pdf(election, receipt, verify_url)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="SJCJ-voting-receipt-{receipt.receipt_number.replace("/", "-")}.pdf"',
            "Cache-Control": "no-store",
        },
    )
