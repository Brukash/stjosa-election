# Election clearance: security review, performance and pilot

The proposal states the system is not ready for an official election until testing and an
independent security review are completed. This file records that gate. **It is not a
certification and must be signed off by people outside the development team.**

## 1. Current status

| Gate | Status | Evidence |
| --- | --- | --- |
| Functional mock election | Passed | `backend/scripts/smoke_test.py` — full suite: accreditation, credential, challenge, cast, receipts, commitments, dual-control count, declaration, audit report |
| Registration notices | Passed against mock providers | `backend/scripts/test_notifications.py` — direct Voter ID accreditation with no OTP delivery, retired OTP routes returning 404, unknown Voter ID rejection, registration approval notices by email and WhatsApp utility template, Voter ID included in the email, consent handling, per-channel delivery records, monitoring and repeat-approval idempotency; no live provider credentials used |
| MFA | Passed | Enrol → activate → login without code (401), wrong code (401), correct code (200); UI at `/admin/security` |
| Verification settings independence | Passed | Same official cannot configure and approve; second official approval enforced; smoke check |
| Deployment preflight | Passed locally | `python scripts/preflight.py` → READY (31 tables, no production issues in development) |
| Production configuration guard | Implemented | Startup fails when production secrets, delivery channel, https origin, PostgreSQL or demo seed are wrong |
| Independent penetration test | **Not performed** | External supplier required |
| Performance test at target load | **Not performed** | Only a local indicative run (below) |
| Committee pilot | **Not performed** | Plan below |
| Backup restore drill | **Passed 14 Nov 2026** | Supabase custom dump restored into PostgreSQL 17; 5 profiles, 1 election and 24 voters recovered; `/api/health`, public election and Chairman login verified |

## 2. Independent security review scope

Give the reviewer the `docs/SECURITY.md` protocol description and a staging deployment with
`DEMO_SEED=false`. Minimum scope:

1. Authentication: password hashing, lockout/rate limits, session token forgery, staff MFA bypass,
   role escalation between Chairman / Returning Officer / Accreditation Officer / Observer.
2. Accreditation abuse: enumeration of Voter IDs, guessing or sharing of Voter IDs, reused
   credentials, and concurrent requests for one voter.
3. Ballot secrecy: confirm no API, report or database query links a voter to a ballot; verify
   receipt references cannot decrypt ballots; verify challenge does not leave a castable ballot.
4. Cryptography: blind RSA-FDH credential issuance, AES-256-GCM ballot envelope, RSA-OAEP key wrap,
   Merkle commitment inclusion, Ed25519 signatures, dual-control tally proofs.
5. Application security: injection, XSS in candidate/register fields, CSRF on authenticated mutations,
   permissive CORS, file/path handling, verbose errors leaking secrets, RLS on Supabase.
6. Operational security: key custody and release, secret handling, backup encryption, log redaction
   (no tokens or ballot choices), audit tamper-resistance, denial of service.
7. Election logic: freeze after first accepted ballot, duplicate voting, results hidden while voting,
   declaration only after review, emergency-change authorisation and audit.

Deliverables: findings by severity, reproduction steps, retest evidence, and a signed statement that
no critical/high issue remains open.

## 3. Performance test

Run against a staging deployment with PostgreSQL, the production worker count and notification delivery
disabled or mocked (so provider latency does not dominate):

```bash
cd backend
python scripts/load_test.py --voters 24 --workers 8
```

The script drives full voter flows (Voter ID → credential → prepare → cast) and reports completion,
throughput and p50/p95 latency. It refuses to hide failures.

**Local indicative result (not capacity evidence):** 8 voters / 4 workers → 8/8 completed,
0.55 ballots/s, p50 6.68 s, p95 7.92 s on SQLite with one Uvicorn worker. The single worker and
SQLite serialise writes; this says nothing about the target deployment. The committee should define
the concurrency target (for example, peak voters in the final hour) and require the staging result to
meet it with headroom.

Do not run a load test against the production database during a live election.

## 4. Pilot plan

**Purpose:** prove the operational runbook with real officials before the binding election.

1. **Setup (T-7 days):** staging deployment with production-like email/WhatsApp providers and test senders;
   `DEMO_SEED=false`; create pilot election; import a pilot register of 20–50 consenting alumni;
   configure positions/candidates; provision keys; approve configuration and verification settings
   through the two-person flow; enrol MFA for every official.
2. **Briefing (T-2 days):** walk officials through accreditation, counting authorisation, result
   review/declaration, emergency changes and audit exports. Issue Voter IDs privately.
3. **Pilot voting (60–90 minutes):** open accreditation, then voting; ask at least one voter to use
   challenge verification; confirm one-vote-only with a deliberate retry; test one invalid Voter ID.
4. **Close and count:** close voting, authorise counting with Chairman + Returning Officer, review
   provisional results, declare, publish the commitment list.
5. **Verify:** voters check receipts and inclusion; officials export the audit report (PDF/XLSX);
   compare declared totals with an independent manual count of the pilot ballots.
6. **Restore drill:** restore the staging database and keys into a clean environment and confirm the
   declared result and audit report are readable.
7. **Sign-off:** record defects, fix and retest; only then schedule the official election.

**Pilot exit criteria:** every step completed by the intended role, no unexplained audit gaps, all
receipts verifiable, count matches manual check, restore drill successful, no open critical/high
security finding.

## 5. Production go-live checklist

- [ ] `ENVIRONMENT=production`, `APP_ORIGIN` https
- [ ] Strong `SECRET_KEY`, `MASTER_KEY`; secrets stored outside the repository
- [ ] `DATABASE_URL` PostgreSQL with migrations applied; RLS verified
- [ ] `DEMO_SEED=false`; no demo accounts or sample voters
- [ ] Email/WhatsApp providers verified with live registration notices to committee test accounts
- [ ] `python scripts/preflight.py` → READY
- [ ] MFA enrolled for every official; recovery/reset procedure agreed
- [ ] Independent security review signed off; performance target met; pilot signed off
- [x] Backup restore drill complete (14 Nov 2026); production backup encryption and schedule still to be confirmed
- [ ] Tally key custody (KMS/HSM) and dual-control release agreed
