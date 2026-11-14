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

- **Voter accreditation** — Voter ID + OTP (5-minute expiry, attempt limits, resend cool-down,
  request rate limiting, hashed OTP storage), one credential issuance per voter per election,
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
- **Monitoring dashboard** — Turnout, accreditation, OTP failures, rejected duplicates, hourly
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
                  0003_otp_channels.sql (WhatsApp consent and channel index)
docs/             API reference, admin manual, voter guide, security report, operations
```

## Running locally

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows (source .venv/bin/activate on Unix)
pip install -r requirements.txt
cp .env.example .env            # change SECRET_KEY, MASTER_KEY and OTP_HASH_PEPPER
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

Demo Voter IDs: `SJC/AL/2004/001` … `SJC/AL/2015/024`. In local development with no provider
configured the OTP is shown on the accreditation screen and returned as `dev_otp`; that is only
possible when `ENVIRONMENT=development`, `APP_ORIGIN` is a loopback address and `DEV_EXPOSE_OTP=true`.

### 4. Simultaneous OTP delivery (email, SMS and WhatsApp)

After one Voter ID submission, the backend validates the approved register and generates **one**
cryptographically secure six-digit OTP. It sends that same OTP concurrently through Resend email,
Termii SMS and the official Meta WhatsApp Business API. The voter does not choose a channel; they
enter whichever registered message arrives first. The destination always comes from the approved
register, so the browser cannot supply or change an email address or phone number.

`POST /api/accreditation/otp-options` remains available as a read-only diagnostic view of masked
destinations. The accreditation screen calls `POST /api/accreditation/request-otp` directly.

| Channel | Provider | Required settings |
| --- | --- | --- |
| Email | Resend | `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, `EMAIL_FROM` (verified domain) |
| Email | Any SMTP relay | `EMAIL_PROVIDER=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` |
| SMS | Termii | `SMS_PROVIDER=termii`, `TERMII_API_KEY`, `TERMII_SENDER_ID`, `TERMII_CHANNEL=dnd` |
| WhatsApp | Meta WhatsApp Business Platform (Cloud API) | `WHATSAPP_PROVIDER=meta`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, approved authentication `WHATSAPP_TEMPLATE_NAME`, `WHATSAPP_TEMPLATE_LANGUAGE` |
| WhatsApp status webhook | Meta | `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` |

Twilio remains only as a legacy SMS fallback (`SMS_PROVIDER=twilio`); new deployments should use
Termii's transactional `dnd` channel. WhatsApp requires a recorded `whatsapp_consent` opt-in and an
approved Meta authentication template; it never uses a personal account or browser automation.

Behaviour:

- One challenge and one hashed OTP cover all channels. Verification through any channel consumes the
  same challenge, invalidates the code everywhere and creates at most one accreditation record.
- Delivery attempts run concurrently and are isolated: a failed Resend call does not cancel Termii or
  Meta. The response lists every channel with its masked destination and a confirmed status
  (`sent`, `failed`, `unavailable` or local-development `skipped`).
- Delivery succeeds only if at least one provider returns a confirmation identifier. If every
  attempted provider fails, the API returns `502`, expires the challenge immediately and exposes no
  usable OTP. If no registered channel/provider is available, it returns `503` before generating a
  challenge.
- The same six-digit value is sent to every available channel, but it is never returned by the API,
  written to logs or stored in plain text. Delivery rows store only a masked recipient, provider
  message id, status and a truncated failure reason. Meta callbacks are HMAC-verified and contain no
  OTP.
- OTPs expire after five minutes, allow five incorrect attempts, and are stored only as HMAC digests.
  A resend invalidates the previous active challenge and is subject to the per-voter cooldown and
  hourly cap.
- `dev_otp` is returned **only** when `ENVIRONMENT=development` **and** `APP_ORIGIN` is loopback
  **and** `DEV_EXPOSE_OTP=true`. `ENVIRONMENT=production` or any non-local origin disables it
  regardless of the flag.
- The monitoring dashboard and Super Administrator delivery page show requests, successful and failed
  deliveries by channel and provider readiness. Administrators never see OTP values or full contacts.

Run the delivery tests without real credentials (uses a local mock provider):

```bash
cd backend
.venv/Scripts/python.exe scripts/test_otp_delivery.py
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
2. Apply `supabase/migrations/0001_init.sql`, `0002_security.sql` and
   `0003_otp_channels.sql` (SQL editor or `supabase db push`).
3. Set `DATABASE_URL` to the Supabase connection string (the backend rewrites `postgres://` /
   `postgresql://` to the `psycopg` driver).
4. Set strong `SECRET_KEY`, `MASTER_KEY`, `OTP_HASH_PEPPER` and `SEED_DEFAULT_PASSWORD` values.
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

- OTP delivery is implemented (Resend/SMTP email, Termii SMS and Meta WhatsApp), but must be
  configured with the committee's verified sender domain, Termii sender ID, approved WhatsApp
  authentication template and recorded voter consent, then tested for deliverability before a real
  election. In production the on-screen OTP is disabled automatically; no provider credential is
  committed.
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
