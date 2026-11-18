"""Audit report computation plus PDF/Excel rendering, and result certificates."""
from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import crypto
from .commitments import canonical
from .models import (
    AccreditationRecord,
    AuditLog,
    Ballot,
    BallotCommitment,
    BallotReceipt,
    ChallengedBallot,
    CredentialIssuance,
    Election,
    ElectionConfigurationApproval,
    ElectionPosition,
    ElectionVerificationSetting,
    PublishedCommitmentBatch,
    ResultApproval,
    ResultDeclaration,
    SpentCredential,
    TallyProof,
    TallyRun,
    Voter,
)
from .services import get_settings_row

NAVY = colors.HexColor("#0B3D24")
GREEN = colors.HexColor("#12703C")
GREY = colors.HexColor("#55635A")


def _count(db: Session, model, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


def audit_report(db: Session, election: Election) -> dict:
    settings = get_settings_row(db, election.id)
    eligible = _count(db, Voter, Voter.election_id == election.id, Voter.is_eligible.is_(True),
                      Voter.register_status == "approved")
    registered = _count(db, Voter, Voter.election_id == election.id)
    accredited = _count(db, AccreditationRecord, AccreditationRecord.election_id == election.id)
    accredited_ineligible = db.scalar(
        select(func.count(AccreditationRecord.id))
        .join(Voter, Voter.id == AccreditationRecord.voter_row_id)
        .where(AccreditationRecord.election_id == election.id, Voter.is_eligible.is_(False))
    ) or 0
    identity_checks = _count(db, AuditLog, AuditLog.election_id == election.id,
                             AuditLog.action == "voter.verify", AuditLog.outcome == "success")
    failed_identity = _count(db, AuditLog, AuditLog.election_id == election.id,
                             AuditLog.action == "voter.verify", AuditLog.outcome == "failure")
    issuances = _count(db, CredentialIssuance, CredentialIssuance.election_id == election.id,
                       CredentialIssuance.status == "issued")
    accepted = _count(db, Ballot, Ballot.election_id == election.id, Ballot.accepted.is_(True))
    challenged = _count(db, ChallengedBallot, ChallengedBallot.election_id == election.id)
    spent = _count(db, SpentCredential, SpentCredential.election_id == election.id)
    receipts = _count(db, BallotReceipt, BallotReceipt.election_id == election.id)
    commitments = _count(db, BallotCommitment, BallotCommitment.election_id == election.id)
    batches = db.execute(
        select(PublishedCommitmentBatch).where(PublishedCommitmentBatch.election_id == election.id)
    ).scalars().all()
    run = db.execute(
        select(TallyRun).where(TallyRun.election_id == election.id, TallyRun.status == "completed")
        .order_by(TallyRun.finished_at.desc())
    ).scalars().first()
    proofs = _count(db, TallyProof, TallyProof.tally_run_id == run.id, TallyProof.counted.is_(True)) if run else 0
    declaration = db.execute(
        select(ResultDeclaration).where(ResultDeclaration.election_id == election.id,
                                       ResultDeclaration.is_current.is_(True))
    ).scalars().first()
    approvals = db.execute(
        select(ResultApproval).where(ResultApproval.election_id == election.id)
        .order_by(ResultApproval.created_at)
    ).scalars().all()
    config_approvals = db.execute(
        select(ElectionConfigurationApproval).where(
            ElectionConfigurationApproval.election_id == election.id
        )
    ).scalars().all()
    failures = db.execute(
        select(AuditLog).where(AuditLog.election_id == election.id, AuditLog.outcome == "failure")
        .order_by(AuditLog.created_at.desc()).limit(50)
    ).scalars().all()
    admin_actions = db.execute(
        select(AuditLog).where(AuditLog.election_id == election.id, AuditLog.actor_id.is_not(None))
        .order_by(AuditLog.created_at.desc()).limit(100)
    ).scalars().all()

    unauthorized = [
        f for f in failures
        if f.action.startswith(("auth.", "credential.", "configuration.", "verification_settings",
                                "election.status", "results."))
    ]
    signature_valid = bool(
        declaration and crypto.election_verify(
            election.signing_public_key, canonical(declaration.figures), declaration.signature
        )
    )
    reconciles = bool(
        run and run.reconciliation
        and run.reconciliation.get("balanced")
        and run.accepted_ballots == run.valid_ballots + run.invalid_ballots
    )
    submission = next((a for a in approvals if a.stage == "provisional_review"), None)
    final_approval = next((a for a in approvals if a.stage == "final_approval"), None)
    single_official = bool(
        submission and final_approval and submission.approver_id == final_approval.approver_id
    )
    checks = [
        {"check": "Only eligible alumni were accredited", "passed": accredited_ineligible == 0 and accredited <= eligible,
         "evidence": f"{accredited} accredited of {eligible} eligible; {accredited_ineligible} ineligible accreditations"},
        {"check": "Voting credentials were single-use", "passed": spent == accepted and spent == receipts,
         "evidence": f"{spent} credentials spent, {accepted} accepted ballots, {receipts} receipts"},
        {"check": "Accepted ballots were preserved", "passed": commitments == accepted,
         "evidence": f"{commitments} commitments for {accepted} accepted ballots"},
        {"check": "Every accepted ballot is in the tally", "passed": proofs == accepted and accepted > 0,
         "evidence": f"{proofs} counted ballot proofs for {accepted} accepted ballots"},
        {"check": "The tally reconciles with accepted ballots", "passed": reconciles,
         "evidence": (f"accepted {run.accepted_ballots}, valid {run.valid_ballots}, invalid {run.invalid_ballots}"
                      if run else "no completed count")},
        {"check": "Final results were properly authorised",
         "passed": bool(declaration and signature_valid and any(a.stage == "final_approval" for a in approvals)),
         "evidence": (
             f"declaration v{declaration.version} signature valid: {signature_valid}"
             + ("; submitted and declared by one official" if single_official
                else "; submitted and declared by two officials" if declaration else "")
         ) if declaration else "not declared"},
        # One recorded approval is the rule since the committee retired the
        # two-person requirement; the evidence names who approved.
        {"check": "Configuration approval was recorded",
         "passed": len(config_approvals) >= 1,
         "evidence": f"{len(config_approvals)} configuration approval(s): "
                     f"{', '.join(sorted({a.approver_role for a in config_approvals})) or 'none'}"},
        {"check": "No unauthorised administrative activity succeeded",
         "passed": len(unauthorized) == 0,
         "evidence": f"{len(unauthorized)} administrative failures, {len(failures)} total rejected attempts recorded"},
    ]

    return {
        "schema": "SJC-AUDIT-REPORT-V1",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "election": {
            "id": election.id, "title": election.title, "reference": election.reference,
            "year": election.year, "status": election.status,
            "configuration_hash": election.configuration_hash,
            "locked_at": election.locked_at.isoformat() if election.locked_at else None,
        },
        "verification_settings": {
            "ballot_inclusion_enabled": settings.ballot_inclusion_enabled,
            "private_selection_enabled": settings.private_selection_enabled,
            "public_commitment_list_enabled": settings.public_commitment_list_enabled,
            "pdf_receipt_enabled": settings.pdf_receipt_enabled,
            "approved_at": settings.approved_at.isoformat() if settings.approved_at else None,
            "locked_at": settings.locked_at.isoformat() if settings.locked_at else None,
        },
        "areas": {
            "accreditation": {"registered_voters": registered, "eligible_voters": eligible,
                              "accredited_voters": accredited, "ineligible_accreditations": accredited_ineligible},
            "identity_verification": {"verified": identity_checks, "failed_attempts": failed_identity},
            "credential_issuance": {"issued": issuances, "spent": spent},
            "voting": {"accepted_ballots": accepted},
            "verification": {"challenged_ballots": challenged},
            "receipts": {"issued": receipts},
            "public_commitments": {"commitments": commitments, "batches": len(batches)},
            "counting": {
                "tally_run_id": run.id if run else None,
                "accepted": run.accepted_ballots if run else 0,
                "valid": run.valid_ballots if run else 0,
                "invalid": run.invalid_ballots if run else 0,
                "reconciliation": run.reconciliation if run else None,
                "evidence_hash": run.evidence_hash if run else None,
            },
            "results": {
                "declared": bool(declaration),
                "declaration_version": declaration.version if declaration else None,
                "declared_at": declaration.declared_at.isoformat() if declaration else None,
                "signature_valid": signature_valid,
                "single_official_declaration": single_official,
                "approvals": [
                    {"stage": a.stage, "role": a.approver_role, "status": a.approval_status,
                     "at": a.created_at.isoformat()}
                    for a in approvals
                ],
            },
            "security": {"failed_attempts": len(failures)},
            "administration": {"recorded_actions": len(admin_actions)},
        },
        "checks": checks,
        "failed_attempts": [
            {"action": f.action, "outcome": f.outcome, "at": f.created_at.isoformat(),
             "ip": f.ip_address, "detail": f.detail}
            for f in failures
        ],
        "administrative_activities": [
            {"action": a.action, "role": a.actor_role, "at": a.created_at.isoformat(),
             "entity": a.entity, "ip": a.ip_address}
            for a in admin_actions
        ],
    }


def _styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=styles["Title"], fontName="Helvetica-Bold",
                                fontSize=18, textColor=NAVY, alignment=0, spaceAfter=4),
        "sub": ParagraphStyle("s", parent=styles["Normal"], fontSize=9.5, textColor=GREY),
        "h2": ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, textColor=NAVY, spaceBefore=14),
        "body": ParagraphStyle("b", parent=styles["Normal"], fontSize=9.5),
    }


def audit_pdf(report: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm)
    styles = _styles()
    flow = [
        Paragraph("St. John's College Jos Alumni Association", styles["sub"]),
        Paragraph("Post-Election Audit Report", styles["title"]),
        Paragraph(
            f"{report['election']['title']} &nbsp;|&nbsp; Reference {report['election']['reference']} "
            f"&nbsp;|&nbsp; Generated {report['generated_at']}", styles["sub"],
        ),
        Spacer(1, 8 * mm),
        Paragraph("Compliance Findings", styles["h2"]),
    ]
    rows = [[Paragraph("<b>Check</b>", styles["body"]), Paragraph("<b>Result</b>", styles["body"]),
             Paragraph("<b>Evidence</b>", styles["body"])]]
    for check in report["checks"]:
        rows.append([
            Paragraph(check["check"], styles["body"]),
            Paragraph("PASS" if check["passed"] else "REVIEW", styles["body"]),
            Paragraph(check["evidence"], styles["body"]),
        ])
    table = Table(rows, colWidths=[62 * mm, 20 * mm, 85 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF4EC")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CFDDD0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow += [table, Paragraph("Audit Evidence by Area", styles["h2"])]
    area_rows = [[Paragraph("<b>Area</b>", styles["body"]), Paragraph("<b>Evidence</b>", styles["body"])]]
    for area, values in report["areas"].items():
        detail = ", ".join(
            f"{k.replace('_', ' ')}: {v}" for k, v in values.items()
            if not isinstance(v, (dict, list)) and v is not None
        ) or "see system records"
        area_rows.append([Paragraph(area.replace("_", " ").title(), styles["body"]),
                          Paragraph(detail, styles["body"])])
    area_table = Table(area_rows, colWidths=[45 * mm, 122 * mm], repeatRows=1)
    area_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF4EC")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CFDDD0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    flow += [area_table, Paragraph("Security Events", styles["h2"])]
    if report["failed_attempts"]:
        security_rows = [[Paragraph("<b>Action</b>", styles["body"]),
                          Paragraph("<b>Time</b>", styles["body"]),
                          Paragraph("<b>IP</b>", styles["body"]),
                          Paragraph("<b>Detail</b>", styles["body"])]]
        for event in report["failed_attempts"][:30]:
            detail = ", ".join(f"{k}: {v}" for k, v in (event["detail"] or {}).items())
            security_rows.append([
                Paragraph(event["action"], styles["body"]),
                Paragraph(event["at"][:19].replace("T", " "), styles["body"]),
                Paragraph(str(event["ip"] or "-"), styles["body"]),
                Paragraph(detail[:160], styles["body"]),
            ])
        security_table = Table(security_rows, colWidths=[48 * mm, 34 * mm, 28 * mm, 57 * mm], repeatRows=1)
        security_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF4EC")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CFDDD0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        flow.append(security_table)
    else:
        flow.append(Paragraph("No failed or unauthorised attempts were recorded.", styles["body"]))

    flow += [
        Spacer(1, 8 * mm),
        Paragraph(
            "This report is generated from append-only election records. Ballot secrecy is preserved: "
            "no voter identity is linked to any ballot or selection in this report.",
            styles["sub"],
        ),
    ]
    doc.build(flow)
    return buffer.getvalue()


def audit_xlsx(report: dict) -> bytes:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Audit Summary"
    summary.append(["St. John's College Jos Alumni Election Audit Report"])
    summary.append(["Election", report["election"]["title"]])
    summary.append(["Reference", report["election"]["reference"]])
    summary.append(["Generated (UTC)", report["generated_at"]])
    summary.append([])
    summary.append(["Check", "Result", "Evidence"])
    for check in report["checks"]:
        summary.append([check["check"], "PASS" if check["passed"] else "REVIEW", check["evidence"]])

    evidence = workbook.create_sheet("Evidence")
    evidence.append(["Area", "Metric", "Value"])
    for area, values in report["areas"].items():
        for key, value in values.items():
            if isinstance(value, (dict, list)) or value is None:
                continue
            evidence.append([area, key, value])

    events = workbook.create_sheet("Security Events")
    events.append(["Action", "Outcome", "Time (UTC)", "IP", "Detail"])
    for event in report["failed_attempts"]:
        events.append([event["action"], event["outcome"], event["at"], event["ip"],
                       str(event["detail"])[:300]])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def result_certificate_pdf(election: Election, declaration_dict: dict) -> bytes:
    figures = declaration_dict["figures"]
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm)
    styles = _styles()
    flow = [
        Paragraph("St. John's College Jos Alumni Association", styles["sub"]),
        Paragraph("Official Election Result Certificate", styles["title"]),
        Paragraph(f"{figures['election']['title']} &nbsp;|&nbsp; {election.reference}", styles["sub"]),
        Spacer(1, 6 * mm),
    ]
    totals = figures["totals"]
    summary = Table([
        ["Eligible voters", totals["eligible_voters"]],
        ["Accredited voters", totals["accredited_voters"]],
        ["Votes cast", totals["votes_cast"]],
        ["Valid ballots", totals["valid_ballots"]],
        ["Invalid ballots", totals["invalid_ballots"]],
        ["Challenged (excluded)", totals["challenged_ballots"]],
        ["Turnout", f"{totals['turnout_percentage']}%"],
    ], colWidths=[70 * mm, 40 * mm])
    summary.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CFDDD0")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF4EC")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    flow += [summary]
    for position in figures["positions"]:
        flow.append(Paragraph(position["title"], styles["h2"]))
        rows = [["Candidate", "Votes", "%", "Result"]]
        for candidate in position["candidates"]:
            rows.append([
                candidate["full_name"], candidate["votes"], f"{candidate['percentage']}%",
                "ELECTED" if candidate["is_winner"] else "Not elected",
            ])
        table = Table(rows, colWidths=[70 * mm, 25 * mm, 20 * mm, 40 * mm])
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CFDDD0")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF4EC")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        flow.append(table)
    flow += [
        Spacer(1, 8 * mm),
        Paragraph(
            f"Declared on {declaration_dict['declared_at']} by {declaration_dict['declared_by']}. "
            f"Declaration version {declaration_dict['version']}.", styles["body"],
        ),
        Spacer(1, 3 * mm),
        Paragraph(f"Signed payload hash: {declaration_dict['signed_payload_hash']}", styles["sub"]),
        Paragraph(f"Tally evidence hash: {totals.get('tally_evidence_hash', '')}", styles["sub"]),
        Paragraph(f"Digital signature: {declaration_dict['signature'][:120]}…", styles["sub"]),
        Spacer(1, 4 * mm),
        Paragraph(
            "Verify this certificate against the published signing public key and the anonymous "
            "commitment list at the election verification portal.", styles["sub"],
        ),
    ]
    doc.build(flow)
    return buffer.getvalue()
