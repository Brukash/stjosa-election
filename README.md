# St. John's College Jos Alumni Election Management System

End-to-end verifiable remote electronic voting for the St. John's College Jos Alumni
Association, built to the SRS v1.1 baseline.

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 14 (App Router), React 18, Tailwind CSS |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 |
| Database | Supabase PostgreSQL (local SQLite fallback for development) |
| Cryptography | RSA-FDH blind signatures, RSA-OAEP + AES-256-GCM, SHA-256 Merkle trees, Ed25519 signatures |

## What is implemented

- **Voter accreditation** — Voter ID checked against the approved register, one credential issuance
  per voter per election,
  audited exception handling.
- **Anonymous credentials** — The browser blinds a secret token, the accreditation service signs it,
  and the voter unblinds locally. The service never sees the credential and cannot link it to a
  ballot. Credentials are single-use (`spent_credentials`).
- **Encrypted ballots** — Hybrid encryption to the election tally key (AES-256-GCM data key wrapped
  with RSA-OAEP-SHA256). Ballot tables hold no voter identifier.
- **Cast-as-intended verification** — Voters can challenge a prepared ballot. The system reveals the
  data key and randomisers; the *browser* re-decrypts and re-checks the commitment. Challenged
  ballots are permanently excluded and the voter prepares a fresh ballot.
- **Receipts** — Unique 160-bit verification reference (stored only as a hash), receipt number,
  downloadable PDF with QR code, no selections.
- **Public commitment list** — Signed Merkle-root batches of anonymous ballot commitments with
  per-ballot inclusion proofs and downloadable manifests.
- **Verification portal** — Receipt lookup returning acceptance, publication, Merkle proof, signature
  validity and inclusion in the count; never reveals identity or selections.
- **Monitoring dashboard** — Turnout, accreditation, failed identity checks, rejected duplicates, hourly
  activity, security alerts, availability, counting and results status.
- **Counting** — Requires dual authorisation (Chairman + Returning Officer); decrypts under the
  tally key, validates ballots, aggregates per position, writes per-ballot proofs, a hash-chained
  evidence record and an Ed25519 signature. Results stay hidden during voting.
- **Results** — Provisional → submitted → approved/declared, signed figures, versioned corrections
  that preserve earlier declarations, result certificate PDF.
- **Audit** — Append-only audit log, eight automated compliance checks, PDF and Excel reports.
- **Configuration integrity** — Four verification controls enabled by default; two-person
  configuration approval; automatic lock on the first accepted ballot; exceptional change workflow
  with reason, second approval and preserved history.

## Repository layout

```
backend/
  app/            FastAPI application, routers, crypto, reporting
  scripts/        smoke_test.py, export_postgres_schema.py
  keys/           generated election keys (gitignored, encrypted at rest)
  .env.example
frontend/
  app/            public voter pages + /admin staff portal
  lib/            API client and browser credential/verification crypto
  components/
supabase/
  migrations/     0001_init.sql (schema), 0002_security.sql (RLS, audit protection),
                  0003_otp_channels.sql (WhatsApp consent history),
                  0004_registration_notifications.sql (per-channel notice timestamps)
docs/             API reference, admin manual, voter guide, security report, operations
```

## Running locally

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows (source .venv/bin/activate on Unix)
pip install -r requirements.txt
cp .env.example .env            # change SECRET_KEY and MASTER_KEY
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On first start the database schema is created and a demo election is seeded
(`DEMO_SEED=true`). API docs: <http://127.0.0.1:8000/docs>.

### 2. Frontend

```bash
cd frontend
npm install
printf 'NEXT_PUBLIC_API_URL=http://127.0.0.1:8000\n' > .env.local
npm run dev
```

Open <http://localhost:3000>.

### 3. Demo accounts

Password for all seeded accounts: `ChangeMe!2026` (override with `SEED_DEFAULT_PASSWORD`).

| Role | Email |
| --- | --- |
| Super Administrator | `superadmin@sjcjos-alumni.org` |
| Electoral Committee Chairman | `chairman@sjcjos-alumni.org` |
| Accreditation Officer | `accreditation@sjcjos-alumni.org` |
| Returning Officer | `returning@sjcjos-alumni.org` |
| Election Observer | `observer@sjcjos-alumni.org` |

Demo Voter IDs: `SJC/AL/2004/001` … `SJC/AL/2015/024`. Accreditation checks the Voter ID directly
against the approved register; no OTP is involved. Registration notices are sent by email and
WhatsApp when the register is approved.

### 4. Registration notices (email and WhatsApp)

Accreditation is **Voter ID-only**. A voter enters the Voter ID from the approved register; if it
matches, the system opens an accreditation session and the browser creates the anonymous credential.
No OTP is generated or delivered during accreditation.

When the Chairman approves the register, every eligible voter receives a registration notice:

- **Email** includes the voter's full name, **Voter ID**, election title and a link to the
  accreditation page. The subject line also includes the Voter ID. An address on the register is
  required.
- **WhatsApp** uses the separate approved **Utility** template `sjc_registration_confirmation` with
  three body parameters: `{{1}}` voter name, `{{2}}` election title and `{{3}}` Voter ID. Recorded
  `whatsapp_consent` is required. The OTP authentication template is not used.

| Channel | Provider | Required settings |
| --- | --- | --- |
| Email | Resend | `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, `EMAIL_FROM` (verified domain) |
| Email | cPanel / any authenticated SMTP relay | `EMAIL_PROVIDER=smtp`, `EMAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SSL=true` (465) or `SMTP_STARTTLS=true` (587), optional `SMTP_MAX_CONNECTIONS` |
| WhatsApp registration notices | Meta WhatsApp Business Platform (Cloud API) | `WHATSAPP_PROVIDER=meta`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_REGISTRATION_TEMPLATE_NAME`, `WHATSAPP_REGISTRATION_TEMPLATE_LANGUAGE` |
| WhatsApp vote confirmations | Meta WhatsApp Business Platform (Cloud API) | `WHATSAPP_PROVIDER=meta`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VOTE_CONFIRMATION_TEMPLATE_NAME`, `WHATSAPP_VOTE_CONFIRMATION_TEMPLATE_LANGUAGE` |
| WhatsApp status webhook | Meta | `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` |

Successful channels are timestamped on the voter (`registration_email_sent_at`,
`registration_whatsapp_sent_at`). Approving the register again retries only channels that have not
succeeded, so repeated approval does not spam members. Approval is committed before notifications,
and a provider failure never cancels the approval or the other channel. Delivery attempts are recorded
in `notification_deliveries` with `purpose="registration"`; message contents and full contacts are not
stored.

After a ballot is accepted, the voter also receives a confirmation by email and, where recorded
`whatsapp_consent` is present, by WhatsApp. The message says the ballot was received and submitted
successfully, includes the election title and submission time, and never includes the voter's
selections. Email is sent only when an address and provider are configured; WhatsApp uses the
separate approved **Utility** template `sjc_vote_confirmation` with `{{1}}` voter name, `{{2}}`
election title and `{{3}}` submission time. Confirmation delivery is best effort: a provider failure
never invalidates or fails the accepted vote, and it runs after the cast response has been sent so a
slow provider cannot delay the voter. Idempotent cast retries do not resend messages. Delivery
attempts are recorded with `purpose="vote_confirmation"`. Each confirmation provider attempt is
limited by `VOTE_CONFIRMATION_TIMEOUT_SECONDS` (default 4 seconds) and is not retried.

Run the delivery and accreditation tests without real credentials:

```bash
cd backend
.venv/Scripts/python.exe scripts/test_notifications.py
```

### 5. Mock election test

```bash
cd backend
.venv/Scripts/python.exe scripts/smoke_test.py
```

The script exercises the full mock-election suite: accreditation, blinded credential verification,
challenge verification, idempotent casting, credential reuse rejection, receipts/PDF, commitment
publication, dual-control counting, voter inclusion verification, declaration, audit reports and a
second election through the two-person configuration flow. Run it against a fresh database.

## Supabase deployment

1. Create a Supabase project.
2. Apply `supabase/migrations/0001_init.sql`, `0002_security.sql`, `0003_otp_channels.sql` and
   `0004_registration_notifications.sql` (SQL editor or `supabase db push`).
3. Set `DATABASE_URL` to the Supabase connection string (the backend rewrites `postgres://` /
   `postgresql://` to the `psycopg` driver).
4. Set strong `SECRET_KEY`, `MASTER_KEY` and `SEED_DEFAULT_PASSWORD` values.
5. Run the backend with `DEMO_SEED=false` for production and create staff accounts deliberately.

Detailed steps, backup/recovery and election-day procedures: `docs/OPERATIONS.md`.

## Security model (summary)

- The database has no join path from a voter to a ballot, a selection, or a credential serial.
  Receipts store only `sha256(reference)`; verification references are 160-bit random values.
- Tally private keys never enter the database: they are encrypted with a key derived from
  `MASTER_KEY` and stored under `backend/keys/`.
- Passwords use scrypt; staff JWTs are HS256 and expire; TOTP MFA can be enrolled per account.
- Every administrative action is audited; audit logs are append-only (enforced by trigger on
  PostgreSQL).
- Verification settings are locked by the system when the first ballot is accepted, not by
  administrator preference.

### Known limitations (read before production)

- Registration notices are implemented by email (Resend/SMTP) and WhatsApp (Meta utility template),
  but must be configured with the committee's verified sender domain, approved WhatsApp template and
  recorded voter consent, then tested for deliverability before a real election. No provider
  credential is committed.
- Accreditation is Voter ID-only. The Voter ID is sent by email and therefore acts as a bearer
  credential: it must be issued privately, and members must not forward their registration email.
- The blind-signature construction is textbook RSA-FDH on a 2048-bit key. It must be reviewed by an
  independent cryptographer (SRS §12.4) before production; key rotation and HSM-backed key custody
  are not implemented.
- Tally keys are file-based with a software master key. Production requires an HSM or KMS with
  dual-control access.
- The browser verifies the challenge material against the tally public key; independent
  client-side verification tooling for the published Merkle batch (outside this app) is provided as
  a JSON manifest and documented hashing rules, not as a separate audited verifier binary.
- Rate limiting is per-voter in the database; edge/WAF rate limiting and load testing
  (2,500 voters, 500 concurrent users) still need to be performed on the target infrastructure.
- Staff sessions are held in `localStorage`; a production deployment should move to
  `HttpOnly; Secure; SameSite` cookies with CSRF protection.

## Acceptance-criteria mapping

See `docs/SECURITY.md` for the crypto protocol and test evidence, `docs/ROLES.md` for every staff
office and its permissions, `docs/OPERATIONS.md` for
provider setup and key custody, and `docs/API.md` for the endpoint-to-requirement mapping
(FR089–FR118, §13 permissions, §14 freeze rules).
