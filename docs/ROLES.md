# Staff roles and access control

The system has five offices. A person may hold more than one role, and effective permissions are the
union of their roles. Roles are global (not per-election); every API call re-checks the caller's
current roles, so a change takes effect immediately.

Defined in `backend/app/security.py` (`PERMISSIONS`, `ROLE_DESCRIPTIONS`). Enforced by
`require_permission` in `backend/app/deps.py`. The catalogue is exposed at `GET /api/accounts/roles`
and rendered in **Admin → Team & roles** (Super Administrator only).

## Office definitions

### Super Administrator — `super_admin`
**Duty:** technical custodian of the platform, not an electoral decision-maker.

Can:
- Create accounts, assign/remove roles, disable accounts, reset passwords.
- View elections, monitoring, commitments and technical audit records.
- Create an election shell.

Cannot:
- Configure positions, candidates, register or verification settings.
- Approve verification settings, authorise counting, approve/publish/declare results.
- Read voter identities, ballots or tally plaintext.

### Electoral Committee Chairman — `chairman`
**Duty:** owns the conduct and configuration of the election.

Can:
- Create and edit elections, positions and candidates.
- Import and approve the voter register.
- Configure and approve verification settings.
- Authorise counting and run the automated count.
- Review results, approve the declaration, publish results.
- Oversee accreditation, lifecycle and audit.

Cannot:
- Manage staff accounts.

### Returning Officer — `returning_officer`
**Duty:** optional second official. On 2026-11-18 the committee retired the two-person rule and
asked the Chairman to conduct the election from start to finish, so no step requires this office.

Can:
- Approve verification settings.
- Authorise and run counting, in the Chairman's place.
- Submit provisional results and publish the declared result.
- Manage election lifecycle within its permitted transitions; view audit and commitments.

Cannot:
- Create or configure elections, approve the register, approve results, or manage accounts.

### Accreditation Officer — `accreditation_officer`
**Duty:** voter roll and accreditation support.

Can:
- Import the register, review accreditation and Voter ID verification records, reset a failed issuance.
- Monitor participation, commitments and limited audit records.
- Use **Admin → Accreditation** to search accredited voters, see each voter's credential status
  (active / revoked / not issued) and revoke a lost credential with a recorded reason. The old
  issuance is retained and audited; a re-accreditation shows as active again with its issuance count.

Cannot:
- Approve the register, configure the election, view ballots or tally, see results before
  publication, or manage accounts.

### Election Observer — `observer`
**Duty:** independent, read-only oversight.

Can:
- View elections, monitoring, published commitment lists, declared results and audit records.
- View public verification information.

Cannot:
- Change any election data, accredit voters, count, declare results or manage accounts.

## Enforcement summary

| Capability | Super Admin | Chairman | Returning | Accreditation | Observer |
| --- | :-: | :-: | :-: | :-: | :-: |
| Manage staff accounts/roles | ✅ | — | — | — | — |
| Create/configure election | create only | ✅ | — | — | — |
| View voter register (identities) | — | ✅ | — | ✅ | — |
| Import register | — | ✅ | — | ✅ | — |
| Approve register | — | ✅ | — | — | — |
| Configure verification | — | ✅ | — | — | — |
| Approve verification | — | ✅ | ✅ | — | — |
| Authorise counting | — | ✅ | ✅ | — | — |
| Run counting | — | ✅ | ✅ | — | — |
| Submit/publish results | — | ✅ | ✅ | — | — |
| Approve/declare results | — | ✅ | — | — | — |

When no Returning Officer submission has been made, the Chairman can complete both the submission
and the declaration in one session. Both `result_approvals` rows name the same account, and the
comments, audit log detail (`single_official: true`) and election events state that one official
did both.
| View tally and count proofs | — | ✅ | ✅ | — | — |
| View monitoring/audit | ✅ | ✅ | ✅ | limited | ✅ |
| Accreditation console / exceptions | — | view | — | ✅ | — |
| Manage fields/accounts | accounts | all election | lifecycle | register | none |

Two integrity rules apply regardless of role:

1. **Verification settings** are approved as a recorded act (`approved_by`, `approved_at`), and the
   approval is audited, including when one official both saves and approves them.
2. **Counting** runs only after an authorisation is recorded in `tally_authorisations`. One
   authorisation is enough; the Chairman's is the normal case.

Read boundaries are enforced with dedicated permissions, not just hidden menus:

- `register.view` — voter identities: Chairman and Accreditation Officer only.
- `tally.view` — tally runs and count proofs: Chairman and Returning Officer only.
- `results.review` — full provisional/approval view; `results.review_restricted` (Observer) returns
  signed declarations only, with provisional counts and approval comments removed.
- `audit.view_limited` — Accreditation Officer sees only Voter ID, credential and register audit events;
  full audit logs and reports require `audit.view` or `audit.view_technical`.

## Account administration

`GET /api/accounts/roles` — role catalogue (any authenticated staff).
`GET /api/accounts` — list staff (Super Administrator).
`POST /api/accounts` — create staff with one or more roles.
`PATCH /api/accounts/{id}` — change name, active state, roles or password.

Safeguards:
- Only `accounts.manage` (Super Administrator) may call the management endpoints.
- Unknown roles are rejected; at least one role is required.
- The last active Super Administrator cannot be demoted or deactivated.
- You cannot deactivate your own account.
- Every create/update/password reset is written to `audit_logs`; passwords and MFA secrets are never
  returned.
- Disabling an account blocks its existing tokens on the next request (`get_current_profile` checks
  `is_active`). Password resets do **not** revoke already-issued tokens; they expire normally.

## Demo accounts

Password for all seeded accounts: `ChangeMe!2026` (override with `SEED_DEFAULT_PASSWORD`).

| Office | Email |
| --- | --- |
| Super Administrator | `superadmin@sjcjos-alumni.org` |
| Chairman | `chairman@sjcjos-alumni.org` |
| Returning Officer | `returning@sjcjos-alumni.org` |
| Accreditation Officer | `accreditation@sjcjos-alumni.org` |
| Observer | `observer@sjcjos-alumni.org` |

Change these passwords and create named accounts for real officials before an election. MFA can be
enrolled per account at **Admin → Security**; enrolment is optional today but required by the
go-live checklist.
