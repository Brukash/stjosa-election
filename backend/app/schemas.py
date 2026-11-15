"""Pydantic request/response models."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

ELECTION_STATUSES = [
    "draft",
    "configured",
    "approved",
    "accreditation_open",
    "voting_open",
    "voting_closed",
    "counting",
    "provisional_results",
    "under_review",
    "declared",
    "archived",
]

STATUS_LABELS = {
    "draft": "Draft",
    "configured": "Configured",
    "approved": "Approved",
    "accreditation_open": "Accreditation Open",
    "voting_open": "Voting Open",
    "voting_closed": "Voting Closed",
    "counting": "Counting",
    "provisional_results": "Provisional Results",
    "under_review": "Under Review",
    "declared": "Declared",
    "archived": "Archived",
}


class LoginRequest(BaseModel):
    email: str
    password: str
    totp_code: str | None = None


class MfaActivateRequest(BaseModel):
    secret: str
    code: str


class ElectionCreate(BaseModel):
    title: str
    description: str = ""
    reference: str | None = None
    year: int
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    timezone: str = "Africa/Lagos"
    eligibility_rules: str = "Voters must appear on the approved alumni register."
    voting_rules: str = "One ballot per accredited voter. One candidate per position."


class ElectionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    year: int | None = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    timezone: str | None = None
    eligibility_rules: str | None = None
    voting_rules: str | None = None


class StatusUpdate(BaseModel):
    status: str
    note: str | None = None


class PositionCreate(BaseModel):
    title: str
    description: str = ""
    seats: int = 1
    order_index: int = 0


class PositionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    seats: int | None = None
    order_index: int | None = None


class CandidateCreate(BaseModel):
    position_id: str
    full_name: str
    photo_url: str | None = None
    bio: str = ""
    manifesto: str = ""
    order_index: int = 0


class CandidateUpdate(BaseModel):
    full_name: str | None = None
    photo_url: str | None = None
    bio: str | None = None
    manifesto: str | None = None
    order_index: int | None = None


class VerificationSettingsUpdate(BaseModel):
    ballot_inclusion_enabled: bool
    private_selection_enabled: bool
    public_commitment_list_enabled: bool
    pdf_receipt_enabled: bool


class RegisterImport(BaseModel):
    csv_text: str


class VoterCreate(BaseModel):
    voter_id: str
    full_name: str
    email: str | None = None
    phone: str | None = None
    whatsapp_consent: bool = False
    alumni_set: str = "General"
    graduation_year: int | None = None
    is_eligible: bool = True


class EligibilityUpdate(BaseModel):
    is_eligible: bool | None = None
    whatsapp_consent: bool | None = None
    note: str | None = None


class VoterVerifyRequest(BaseModel):
    election_id: str | None = None
    voter_id: str


class CredentialRequest(BaseModel):
    accreditation_token: str
    blinded_message: str = Field(min_length=8, max_length=2048)


class BallotPrepare(BaseModel):
    election_id: str
    token: str
    signature: str
    selections: dict[str, str]


class CredentialProof(BaseModel):
    token: str
    signature: str
    # Required for casting (not challenging). Proves the voter's turnout marker without
    # identifying which anonymous ballot was cast.
    turnout_token: str | None = None


class ExceptionalChange(BaseModel):
    changes: dict
    reason: str = Field(min_length=10)
    change_type: str = "configuration"


class ApprovalNote(BaseModel):
    note: str | None = None


class ResultSubmit(BaseModel):
    comments: str | None = None


class CorrectionRequest(BaseModel):
    reason: str = Field(min_length=10)
