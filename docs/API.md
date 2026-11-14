# API Reference

Base URL: `http://127.0.0.1:8000/api` (interactive OpenAPI docs at `/docs`).

Staff endpoints require `Authorization: Bearer <JWT>` from `POST /auth/login`. RBAC is enforced by
the backend on every route, not by the interface.

## Public / voter endpoints

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| GET | `/health` | Service + database health | |
| GET | `/public/election` | Active election, ballot, verification settings, public keys | FR105–FR111 |
| GET | `/public/elections/{id}` | Public configuration of one election | |
| POST | `/accreditation/request-otp` | Send OTP for a Voter ID | Rate limited, hashed storage; delivers by email/SMS; `503` if no channel configured, `502` on provider failure |
| POST | `/accreditation/verify-otp` | Validate OTP, create accreditation + short session | Attempt-limited, audited |
| POST | `/accreditation/credential` | Sign a **blinded** credential request | One active issuance per voter/election |
| POST | `/voting/prepare` | Validate credential, encrypt selections, store prepared ballot | Not yet counted |
| POST | `/voting/{prepared_id}/challenge` | Reveal challenge material; spoil ballot | FR097–FR104, permanently excluded |
| POST | `/voting/{prepared_id}/cast` | Spend credential, accept ballot, issue receipt | Idempotent replay |
| GET | `/verify/{reference}` | Receipt verification and inclusion evidence | FR092–FR096 |
| GET | `/receipts/{reference}` | Receipt metadata | |
| GET | `/receipts/{reference}/pdf` | PDF receipt with QR | FR112–FR118 |
| GET | `/commitments/{election_id}` | Published commitment batches | FR105–FR111 |
| GET | `/commitments/{election_id}/batches/{ref}/download` | Signed manifest with Merkle proofs | |
| GET | `/crypto/{election_id}` | Tally, signing and credential public keys | |
| GET | `/results/public/current` | Current declared results | |
| GET | `/results/public/{election_id}` | Declared results for an election | |
| GET | `/monitoring/{election_id}/result-certificate.pdf` | Signed result certificate | |

`POST /accreditation/request-otp` response includes `delivery_channel` (`email`, `sms` or
`development`), the masked `delivery` destination, `expires_in` and `max_attempts`. `dev_otp` is
present only when the backend is in local development, `APP_ORIGIN` is loopback and
`DEV_EXPOSE_OTP=true`; it is never returned in production or staging.

`POST /voting/prepare` body:

```json
{
  "election_id": "…",
  "token": "<64 hex chars — client-generated secret>",
  "signature": "<unblinded RSA-FDH signature hex>",
  "selections": { "<position_id>": "<candidate_id>" }
}
```

`POST /voting/{id}/cast` body: `{ "token": "…", "signature": "…" }`. Repeating a cast for the same
prepared ballot returns the same receipt (no duplicate ballot).

Challenge response `verification_material` contains: ciphertext, encrypted key, nonce, revealed data
key, key commitment, ballot commitment and the revealed selections. The voter's browser checks that
the AES-GCM ciphertext decrypts to those selections and that both commitments match.

## Staff endpoints

### Authentication

| Method | Path | Permission |
| --- | --- | --- |
| POST | `/auth/login` | public (password + optional TOTP) |
| GET | `/auth/me` | authenticated |
| POST | `/auth/mfa/enroll` | authenticated |
| POST | `/auth/mfa/activate` | authenticated |

### Staff accounts and roles

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/accounts/roles` | authenticated (role definitions and permission matrix) |
| GET | `/accounts` | `accounts.manage` |
| POST | `/accounts` | `accounts.manage` |
| PATCH | `/accounts/{id}` | `accounts.manage` (last active Super Administrator protected) |

### Elections and configuration

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/elections` | `election.view` |
| POST | `/elections` | `election.create` |
| GET | `/elections/{id}` | `election.view` |
| PATCH | `/elections/{id}` | `election.edit` (blocked when frozen) |
| POST | `/elections/{id}/positions` | `election.edit` |
| PATCH/DELETE | `/elections/positions/{id}` | `election.edit` |
| POST | `/elections/{id}/candidates` | `election.edit` |
| PATCH/DELETE | `/elections/candidates/{id}` | `election.edit` |
| PUT | `/elections/{id}/verification-settings` | `verification.configure` |
| POST | `/elections/{id}/verification-settings/approve` | `verification.approve`, by a different official from the one who saved the settings |
| POST | `/elections/{id}/configuration/approve` | Chairman or Returning Officer (two-person) |
| POST | `/elections/{id}/status` | role-checked lifecycle transition |
| POST | `/elections/{id}/changes` | `verification.approve` + reason (exceptional change) |
| POST | `/elections/changes/{change_id}/approve` | second authorised official (Chairman or Returning Officer, distinct from the requester); applies the change at two approvals |

Frozen configuration returns `409` with an explanation. Lifecycle transitions allowed by the API:
`draft → configured`, `configured → approved` (via two-person approval), `approved →
accreditation_open`, `accreditation_open → voting_open`, `voting_open → voting_closed`,
`declared → archived`. Counting and declaration move status through their own modules.

### Voter register

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/register/{election_id}` | `register.view` |
| POST | `/register/{election_id}/import` | `register.import` |
| POST | `/register/{election_id}/voters` | `register.import` |
| PATCH | `/register/voters/{voter_id}` | `register.approve` |
| POST | `/register/{election_id}/approve` | `register.approve` |
| GET | `/accreditation/exceptions/accreditations` | `accreditation.oversight` |
| POST | `/accreditation/exceptions/reset-issuance` | `accreditation.manage` (audited) |

### Counting, results, monitoring

| Method | Path | Permission |
| --- | --- | --- |
| POST | `/tally/{id}/authorise` | `counting.authorise` (Chairman or Returning Officer) |
| POST | `/tally/{id}/run` | `counting.run` + both authorisations |
| GET | `/tally/{id}` | `tally.view` |
| GET | `/tally/{id}/runs`, `/proofs` | `tally.view` |
| GET | `/results/{id}` | `results.review` (full) / `results.review_restricted` (declared only) |
| POST | `/results/{id}/submit` | `results.submit` |
| POST | `/results/{id}/approve` | `results.approve` |
| POST | `/results/{id}/corrections` | `results.approve` + reason |
| GET | `/monitoring/{id}/overview` | `monitor.view` |
| GET | `/monitoring/{id}/participation` | `monitor.view` |
| GET | `/monitoring/{id}/audit-logs` | `audit.view` / `_technical`; `_limited` is filtered to OTP, credential and register events |
| GET | `/monitoring/{id}/audit-report[.pdf\|.xlsx]` | `audit.view` or `audit.view_technical` |
| GET | `/monitoring/{id}/results-status` | `monitor.view` |
| POST | `/commitments/{id}/publish` | `counting.authorise`, after closure |

## Permission matrix implementation

`backend/app/security.py` encodes the SRS §13 matrix as permission sets per role; `require_permission`
guards every staff route. Examples:

- Super Administrator cannot approve elections, configure verification settings, or declare results.
- Chairman cannot cast ballots, run the count alone, or change declared results without the
  versioned correction workflow.
- Observer has read-only monitoring, results, commitments and audit access.
- Accreditation Officer cannot view ballots or modify verification settings.

## Requirement coverage

| Requirement | Endpoint / component |
| --- | --- |
| FR089–FR096 ballot inclusion verification | `POST /voting/{id}/cast`, `GET /verify/{reference}`, `GET /commitments/…` |
| FR097–FR104 selection verification | `POST /voting/{id}/prepare`, `POST /voting/{id}/challenge`, browser verifier |
| FR105–FR111 commitment list | `POST /commitments/{id}/publish`, `GET /commitments/{id}`, manifest download |
| FR112–FR118 PDF receipt | `GET /receipts/{ref}/pdf`, receipt hash storage, no selections |
| §14 configuration freeze | settings lock on first ballot, `409` on later changes, change request records |
