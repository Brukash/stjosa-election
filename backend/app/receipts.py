"""Receipt payloads and PDF rendering."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas

from . import crypto
from .config import settings
from .models import BallotReceipt, Election

NAVY = (0.043, 0.239, 0.141)
GREEN = (0.906, 0.824, 0.110)
GREY = (0.33, 0.39, 0.35)


def receipt_reference(receipt: BallotReceipt) -> str:
    return crypto.decrypt_secret(receipt.receipt_ref_encrypted).decode()


def receipt_payload(election: Election, receipt: BallotReceipt, *, verification_enabled: bool = True) -> dict:
    reference = receipt_reference(receipt)
    return {
        "receipt_number": receipt.receipt_number,
        "receipt_reference": reference,
        "ballot_commitment": receipt.ballot_commitment,
        "issued_at": receipt.issued_at.isoformat(),
        "accepted": True,
        "election": {
            "id": election.id,
            "title": election.title,
            "reference": election.reference,
            "year": election.year,
        },
        "verify_url": f"{settings.app_origin}/verify?ref={reference}",
        "pdf_url": f"{settings.api_origin}/api/receipts/{reference}/pdf",
        "note": (
            "This receipt confirms that your ballot was accepted. It deliberately does not "
            "record or reveal your candidate selections."
        ),
        "verification_enabled": verification_enabled,
    }


def build_receipt_pdf(election: Election, receipt: BallotReceipt, verify_url: str) -> bytes:
    reference = receipt_reference(receipt)
    buffer = io.BytesIO()
    page = pdfcanvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Header band
    page.setFillColorRGB(*NAVY)
    page.rect(0, height - 130, width, 130, stroke=0, fill=1)
    page.setFillColorRGB(1, 1, 1)
    page.setFont("Helvetica-Bold", 16)
    page.drawString(50, height - 58, "ST. JOHN'S COLLEGE JOS")
    page.setFont("Helvetica-Bold", 12)
    page.drawString(50, height - 78, "Alumni Association Election Management System")
    page.setFont("Helvetica", 9)
    page.drawString(50, height - 96, "Official Electronic Voting Receipt")

    page.setFillColorRGB(*GREEN)
    page.rect(0, height - 136, width, 6, stroke=0, fill=1)

    crest_path = Path(__file__).resolve().parent.parent / "assets" / "crest.png"
    if crest_path.exists():
        page.drawImage(
            ImageReader(str(crest_path)),
            width - 50 - 58,
            height - 122,
            width=58,
            height=74,
            preserveAspectRatio=True,
            mask="auto",
        )

    content_top = height - 180
    page.setFillColorRGB(*NAVY)
    page.setFont("Helvetica-Bold", 14)
    page.drawString(50, content_top, election.title)
    page.setFillColorRGB(*GREY)
    page.setFont("Helvetica", 9)
    page.drawString(50, content_top - 16, f"Election reference: {election.reference}   |   Year: {election.year}")

    rows = [
        ("Receipt number", receipt.receipt_number),
        ("Verification reference", reference),
        ("Ballot acceptance status", "ACCEPTED"),
        ("Submitted (UTC)", receipt.issued_at.strftime("%d %b %Y, %H:%M:%S")),
        ("Ballot commitment", receipt.ballot_commitment),
    ]
    y = content_top - 52
    page.setFont("Helvetica", 9.5)
    for label, value in rows:
        page.setFillColorRGB(*GREY)
        page.drawString(50, y, label.upper())
        page.setFillColorRGB(*NAVY)
        page.setFont("Helvetica-Bold", 10)
        text = value
        while page.stringWidth(text, "Helvetica-Bold", 10) > 360 and len(text) > 12:
            text = text[:-2]
        page.drawString(200, y, text)
        page.setFont("Helvetica", 9.5)
        page.setStrokeColorRGB(0.85, 0.87, 0.9)
        page.line(50, y - 8, width - 50, y - 8)
        y -= 30

    # QR code
    qr = qrcode.QRCode(version=None, box_size=6, border=2)
    qr.add_data(verify_url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#0B3D24", back_color="white")
    qr_buffer = io.BytesIO()
    image.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    page.drawImage(ImageReader(qr_buffer), 50, y - 160, width=130, height=130)
    page.setFillColorRGB(*GREY)
    page.setFont("Helvetica", 8)
    page.drawString(50, y - 174, "Scan to verify this ballot's inclusion")

    page.setFillColorRGB(*NAVY)
    page.setFont("Helvetica-Bold", 9)
    page.drawString(200, y - 40, "How to verify")
    page.setFont("Helvetica", 9)
    lines = [
        "1. Open the verification portal at the address below.",
        "2. Enter your verification reference or scan the QR code.",
        "3. The portal confirms whether your ballot commitment",
        "   appears in the published election record and tally.",
        "",
        "This receipt proves acceptance only. It does not contain,",
        "and cannot be used to reveal, your voting selections.",
    ]
    for offset, line in enumerate(lines):
        page.setFillColorRGB(*GREY)
        page.drawString(200, y - 58 - offset * 14, line)

    page.setFillColorRGB(*NAVY)
    page.setFont("Helvetica-Bold", 8.5)
    page.drawString(200, y - 178, verify_url)

    page.setStrokeColorRGB(0.85, 0.87, 0.9)
    page.line(50, 90, width - 50, 90)
    page.setFillColorRGB(*GREY)
    page.setFont("Helvetica", 7.5)
    page.drawString(
        50, 74,
        "Issued automatically on ballot commitment. Retain this receipt for post-election verification.",
    )
    page.drawString(
        50, 62,
        "St. John's College Jos Alumni Association - Electoral Committee. Document generated by the election system.",
    )
    page.showPage()
    page.save()
    return buffer.getvalue()


def fmt(value: datetime | None) -> str:
    return value.strftime("%d %b %Y %H:%M UTC") if value else "-"
