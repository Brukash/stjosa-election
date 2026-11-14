"""SQLAlchemy models.

Design rules enforced here (SRS §11.7):
  * Voter identity records and ballot records live in separate tables.
  * No ballot/challenged-ballot table has a voter foreign key.
  * Credential issuance rows never store the anonymous credential serial.
  * Tally private keys are never stored in the database (see crypto.py / keys dir).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# ── Accounts and roles ───────────────────────────────────────────────────────
class Profile(Base, TimestampMixin):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("profile_id", "role_id", name="uq_user_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False, index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), nullable=False, index=True)
    election_id: Mapped[str | None] = mapped_column(ForeignKey("elections.id"))


# ── Election configuration ───────────────────────────────────────────────────
class Election(Base, TimestampMixin):
    __tablename__ = "elections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reference: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Lagos", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False, index=True)
    eligibility_rules: Mapped[str] = mapped_column(Text, default="Approved alumni register only.", nullable=False)
    voting_rules: Mapped[str] = mapped_column(Text, default="One vote per position. One ballot per voter.", nullable=False)
    ballot_style: Mapped[str] = mapped_column(String(40), default="single_choice", nullable=False)

    created_by: Mapped[str | None] = mapped_column(ForeignKey("profiles.id"))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("profiles.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    configuration_hash: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tally_public_key: Mapped[str | None] = mapped_column(Text)
    signing_public_key: Mapped[str | None] = mapped_column(Text)
    credential_public_key: Mapped[str | None] = mapped_column(Text)


class ElectionPosition(Base, TimestampMixin):
    __tablename__ = "election_positions"
    __table_args__ = (UniqueConstraint("election_id", "title", name="uq_position_title"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    seats: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Candidate(Base, TimestampMixin):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    position_id: Mapped[str] = mapped_column(
        ForeignKey("election_positions.id"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    photo_url: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str] = mapped_column(Text, default="", nullable=False)
    manifesto: Mapped[str] = mapped_column(Text, default="", nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Voter(Base, TimestampMixin):
    __tablename__ = "voters"
    __table_args__ = (UniqueConstraint("election_id", "voter_id", name="uq_voter_per_election"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    voter_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    # WhatsApp authentication messages require an opt-in recorded against the voter.
    whatsapp_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    alumni_set: Mapped[str] = mapped_column(String(64), default="General", nullable=False)
    graduation_year: Mapped[int | None] = mapped_column(Integer)
    is_eligible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    register_status: Mapped[str] = mapped_column(String(20), default="imported", nullable=False)
    imported_by: Mapped[str | None] = mapped_column(ForeignKey("profiles.id"))


# ── Accreditation ────────────────────────────────────────────────────────────
class OtpChallenge(Base):
    __tablename__ = "otp_challenges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    voter_row_id: Mapped[str] = mapped_column(ForeignKey("voters.id"), nullable=False, index=True)
    otp_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class NotificationDelivery(Base):
    """OTP delivery attempt audit. Never contains the OTP itself."""

    __tablename__ = "notification_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    voter_row_id: Mapped[str | None] = mapped_column(ForeignKey("voters.id"))
    challenge_id: Mapped[str | None] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_masked: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(160))
    error: Mapped[str | None] = mapped_column(Text)
    request_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class AccreditationRecord(Base):
    __tablename__ = "accreditation_records"
    __table_args__ = (UniqueConstraint("election_id", "voter_row_id", name="uq_accreditation"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    voter_row_id: Mapped[str] = mapped_column(ForeignKey("voters.id"), nullable=False, index=True)
    accredited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(40), default="voter_id_otp", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class CredentialIssuance(Base):
    """Anonymous credential issuance.

    Deliberately does not store the credential serial or the unblinded signature.
    Only a hash of the blinded request is kept (for single-issuance enforcement) and
    a reference to the accreditation record for audit purposes.
    """

    __tablename__ = "credential_issuances"
    __table_args__ = (
        UniqueConstraint("election_id", "blinded_request_hash", name="uq_blinded_request"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    accreditation_id: Mapped[str] = mapped_column(
        ForeignKey("accreditation_records.id"), nullable=False, index=True
    )
    blinded_request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="issued", nullable=False)


class AccreditationSession(Base):
    """Short-lived proof that OTP verification succeeded, used to request a signature."""

    __tablename__ = "accreditation_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    voter_row_id: Mapped[str] = mapped_column(ForeignKey("voters.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SpentCredential(Base):
    """Single-use anonymous credential registry. Stores only a token hash."""

    __tablename__ = "spent_credentials"
    __table_args__ = (UniqueConstraint("election_id", "token_hash", name="uq_spent_token"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    spent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# ── Voting ───────────────────────────────────────────────────────────────────
class PreparedBallot(Base):
    """A ballot encrypted but not yet cast; may be challenged (revealed) once."""

    __tablename__ = "prepared_ballots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    commitment: Mapped[str] = mapped_column(String(128), nullable=False)
    selections: Mapped[dict | None] = mapped_column(JSON)
    data_key: Mapped[str | None] = mapped_column(String(128))
    key_commitment: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="prepared", nullable=False)
    ballot_id: Mapped[str | None] = mapped_column(ForeignKey("ballots.id"))
    receipt_id: Mapped[str | None] = mapped_column(ForeignKey("ballot_receipts.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Ballot(Base):
    """Accepted encrypted ballot. Contains no voter identifier by design."""

    __tablename__ = "ballots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    ballot_commitment: Mapped[str] = mapped_column(String(128), nullable=False)
    selection_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cast_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("published_commitment_batches.id"))


class ChallengedBallot(Base):
    __tablename__ = "challenged_ballots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    ballot_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    revealed_selections: Mapped[dict] = mapped_column(JSON, nullable=False)
    proof: Mapped[dict] = mapped_column(JSON, nullable=False)
    challenged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    counted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class BallotReceipt(Base):
    __tablename__ = "ballot_receipts"
    __table_args__ = (
        UniqueConstraint("election_id", "receipt_hash", name="uq_receipt_hash"),
        UniqueConstraint("election_id", "ballot_commitment", name="uq_receipt_commitment"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    receipt_number: Mapped[str] = mapped_column(String(40), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    ballot_commitment: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    receipt_ref_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class BallotCommitment(Base):
    __tablename__ = "ballot_commitments"
    __table_args__ = (
        UniqueConstraint("election_id", "ballot_commitment", name="uq_commitment"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    ballot_commitment: Mapped[str] = mapped_column(String(128), nullable=False)
    ballot_proof: Mapped[dict | None] = mapped_column(JSON)
    commitment_status: Mapped[str] = mapped_column(String(20), default="accepted", nullable=False)
    batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("published_commitment_batches.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PublishedCommitmentBatch(Base):
    __tablename__ = "published_commitment_batches"
    __table_args__ = (
        UniqueConstraint("election_id", "batch_reference", name="uq_batch_reference"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    batch_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    commitment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    merkle_root: Mapped[str] = mapped_column(String(128), nullable=False)
    digital_signature: Mapped[str] = mapped_column(Text, nullable=False)
    signed_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ElectionVerificationSetting(Base, TimestampMixin):
    __tablename__ = "election_verification_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(
        ForeignKey("elections.id"), unique=True, nullable=False
    )
    ballot_inclusion_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    private_selection_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    public_commitment_list_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pdf_receipt_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    configured_by: Mapped[str | None] = mapped_column(ForeignKey("profiles.id"))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("profiles.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ElectionConfigurationApproval(Base):
    __tablename__ = "election_configuration_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    settings_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    approver_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False)
    approver_role: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    approval_status: Mapped[str] = mapped_column(String(40), default="approved", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ConfigurationChange(Base):
    """Exceptional change request log (SRS §14.4)."""

    __tablename__ = "configuration_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    changed_fields: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(128))
    new_hash: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False)
    approvals: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# ── Counting, results, audit ─────────────────────────────────────────────────
class TallyAuthorisation(Base):
    __tablename__ = "tally_authorisations"
    __table_args__ = (UniqueConstraint("election_id", "profile_id", name="uq_tally_authoriser"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False)
    role_key: Mapped[str] = mapped_column(String(64), nullable=False)
    authorised_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class TallyRun(Base):
    __tablename__ = "tally_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    started_by: Mapped[str | None] = mapped_column(ForeignKey("profiles.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_ballots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    challenged_ballots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_ballots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_ballots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_hash: Mapped[str | None] = mapped_column(String(128))
    signature: Mapped[str | None] = mapped_column(Text)
    reconciliation: Mapped[dict | None] = mapped_column(JSON)


class TallyResult(Base):
    __tablename__ = "tally_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tally_run_id: Mapped[str] = mapped_column(ForeignKey("tally_runs.id"), nullable=False, index=True)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    position_id: Mapped[str] = mapped_column(ForeignKey("election_positions.id"), nullable=False)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    votes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    percentage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class TallyProof(Base):
    __tablename__ = "tally_proofs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tally_run_id: Mapped[str] = mapped_column(ForeignKey("tally_runs.id"), nullable=False, index=True)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False)
    ballot_commitment: Mapped[str] = mapped_column(String(128), nullable=False)
    merkle_proof: Mapped[dict] = mapped_column(JSON, nullable=False)
    ballot_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    chain_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    counted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ResultApproval(Base):
    __tablename__ = "result_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    tally_run_id: Mapped[str] = mapped_column(ForeignKey("tally_runs.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    approver_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False)
    approver_role: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    approval_status: Mapped[str] = mapped_column(String(30), default="approved", nullable=False)
    comments: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ResultDeclaration(Base):
    __tablename__ = "result_declarations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    tally_run_id: Mapped[str] = mapped_column(ForeignKey("tally_runs.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    figures: Mapped[dict] = mapped_column(JSON, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    signed_payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    correction_reason: Mapped[str | None] = mapped_column(Text)
    declared_by: Mapped[str] = mapped_column(ForeignKey("profiles.id"), nullable=False)
    declared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str | None] = mapped_column(ForeignKey("elections.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("profiles.id"))
    actor_role: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    entity: Mapped[str | None] = mapped_column(String(120))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(20), default="success", nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class ElectionEvent(Base):
    __tablename__ = "election_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("profiles.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ElectionDocument(Base):
    __tablename__ = "election_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    election_id: Mapped[str] = mapped_column(ForeignKey("elections.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    signature: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


Index("ix_ballot_election_cast", Ballot.election_id, Ballot.cast_at)
