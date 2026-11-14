# Operations, Deployment and Recovery

## 1. Environments

| Environment | Database | Keys | Demo seed |
| --- | --- | --- | --- |
| Local development | SQLite (`backend/election.db`) | `backend/keys/` | `DEMO_SEED=true` |
| Staging | Supabase project (separate) | dedicated `keys/` volume | `DEMO_SEED=false` |
| Production | Supabase project | HSM/KMS-backed (see §5) | `DEMO_SEED=false` |

Required backend variables are documented in `backend/.env.example`. Minimum production changes:

```
DATABASE_URL=postgresql+psycopg://…@…pooler.supabase.com:5432/postgres
SECRET_KEY=<32+ random bytes>
MASTER_KEY=<32+ random bytes, stored in a secret manager>
OTP_HASH_PEPPER=<32+ random bytes>
DEV_EXPOSE_OTP=false
DEMO_SEED=false
APP_ORIGIN=https://elections.your-domain.org
API_ORIGIN=https://api.elections.your-domain.org
KEYS_DIR=/var/lib/sjc-election/keys
```

Frontend: `NEXT_PUBLIC_API_URL=https://api.elections.your-domain.org`.

## 2. Supabase setup

1. Create a project and note the connection string (Session pooler).
2. Apply migrations in order:
   - `supabase/migrations/0001_init.sql` — 30 tables (schema generated from the ORM).
   - `supabase/migrations/0002_security.sql` — RLS, grants, append-only audit trigger, ballot
     immutability, receipt/commitment integrity check.
3. Confirm RLS is enabled on all sensitive tables (`Supabase → Database → Tables`).
4. Create staff accounts through the application (or seed then change every password).
5. Never expose the database connection string to the browser; the Next.js app talks only to FastAPI.

`0001_init.sql` can be regenerated after model changes:

```bash
cd backend
.venv/Scripts/python.exe scripts/export_postgres_schema.py > ../supabase/migrations/0001_init.sql
```

## 2a. OTP delivery provider setup

OTPs must reach the contact on the approved register. Configure one or both channels; the backend
fails closed (`503`) outside development if neither is configured.

### Email — Resend (recommended)

1. Create a Resend account and add the sending domain (for example `elections.sjcjos-alumni.org`).
2. Add the SPF and DKIM records Resend provides, wait for domain verification, then set a DMARC
   policy for the subdomain.
3. Set `EMAIL_PROVIDER=resend`, `RESEND_API_KEY` (server-side secret only) and
   `EMAIL_FROM="SJC Jos Alumni Election <no-reply@elections.sjcjos-alumni.org>"`.
4. Send a test accreditation OTP to a committee mailbox and confirm inbox placement.

### Email — SMTP fallback

`EMAIL_PROVIDER=smtp` plus `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
`SMTP_STARTTLS=true`. Works with the association's existing mail host.

### SMS — Twilio

1. Buy or port a sender that can deliver to Nigerian (+234) numbers; confirm pricing and sender ID
   rules with Twilio.
2. Set `SMS_PROVIDER=twilio`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`.
3. Trial accounts can only message verified numbers: upgrade before the election.
4. SMS is used when a voter has no email address or no email provider is configured; numbers must be
   E.164 (`+234…`) on the register.

### Production guard and preflight

In production the backend refuses to start when a critical setting is missing or still on a
development default: weak `SECRET_KEY`/`MASTER_KEY`/`OTP_HASH_PEPPER`, the demo password, no OTP
channel, a non-https `APP_ORIGIN`, SQLite, or `DEMO_SEED=true`. Fix the reported setting and restart.

Run the read-only checks before opening the election:

```bash
cd backend
.venv/Scripts/python.exe scripts/preflight.py
.venv/Scripts/python.exe scripts/check_delivery.py --to-email you@example.org
.venv/Scripts/python.exe scripts/check_delivery.py --to-phone +2348012345678
```

`preflight.py` reports configuration, database reachability, missing tables and recent elections;
it exits non-zero when production would fail closed. `check_delivery.py` prints the active channels
and sends a live test only when you pass a destination (no OTP or secret is printed).

### Production guard (details)

- Set `ENVIRONMENT=production` (anything other than `development` counts as non-development).
- Keep `DEV_EXPOSE_OTP=false`. Even if set true, on-screen OTP requires a loopback `APP_ORIGIN`
  **and** a development environment, so production can never display a code.
- Check the monitoring dashboard: delivery mode, sent and failed OTP counts, and the last failure
  reason. Investigate any spike in failures before opening voting.

## 3. Backend deployment

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

Put it behind TLS (reverse proxy or platform load balancer). Health endpoint: `GET /api/health`.
Notes:

- Multiple workers are safe: all state is in PostgreSQL; SQLite is for single-process development only.
- `backend/keys/` must be on persistent storage shared by all workers, and excluded from backups that
  leave the trusted environment unless encrypted.
- Restrict CORS to the real frontend origin (`APP_ORIGIN`).

## 4. Frontend deployment

```bash
cd frontend
npm ci
NEXT_PUBLIC_API_URL=https://api.elections.your-domain.org npm run build
npm run start
```

## 5. Cryptographic key custody

| Key | Location | Protection | Required controls |
| --- | --- | --- | --- |
| Credential issuer (RSA-FDH) | `keys/credential_issuer_private.pem` | AES-256-GCM under scrypt(`MASTER_KEY`) | Offline backup, restricted file permissions |
| Tally key per election | `keys/elections/<id>/tally_private.enc` | Same envelope | HSM/KMS for production, dual-control release |
| Signing key per election | `keys/elections/<id>/signing_private.enc` | Same envelope | Public key published with results |

Rotating `MASTER_KEY` requires re-encrypting the key files before restarting (decrypt with old key,
encrypt with new). Removing an election's key directory destroys the ability to decrypt its ballots —
archive it under dual control for the retention period.

## 6. Backup and recovery

### What to back up

1. PostgreSQL database (all tables, especially `ballots`, `ballot_commitments`,
   `published_commitment_batches`, `tally_*`, `result_*`, `audit_logs`).
2. `keys/` directory (encrypted private keys).
3. `MASTER_KEY`, `SECRET_KEY`, `OTP_HASH_PEPPER` in the secret manager.
4. Published commitment manifests (`GET /api/commitments/{id}` and batch downloads) and declared
   result certificates.

### Backup procedure (Supabase)

```bash
pg_dump "$DATABASE_URL" --format=custom --file=sjc-election-$(date +%F).dump
tar -czf sjc-keys-$(date +%F).tgz backend/keys
```

Use Supabase's daily automated backups as the baseline and take an additional dump immediately before
opening voting, after voting closes, and after declaration. Store off-site, encrypted, with access
logs.

### Recovery procedure

1. Provision the database and restore the dump (`pg_restore --clean --if-exists`).
2. Restore `keys/` to `KEYS_DIR` and confirm `MASTER_KEY` matches (decrypt one file to test).
3. Start the backend; check `GET /api/health`.
4. Verify integrity:
   - `GET /api/verify/<known receipt>` → receipt found, merkle verified, counted in tally.
   - `GET /api/commitments/<election_id>` → signature verified for each batch.
   - `GET /api/results/public/<election_id>` → signature valid.
   - Run the audit report and confirm all checks still pass.
5. Record the recovery event in the election log.

**Recovery test is mandatory before production** (SRS criterion 19). It has not been executed
against a Supabase project yet.

## 7. Election-day runbook

| Time | Action | Role |
| --- | --- | --- |
| T-14 days | Configure election, positions, candidates, verification settings | Chairman |
| T-10 days | Import register, exclude ineligible records, approve register | Chairman |
| T-7 days | Two-person configuration approval; confirm keys provisioned | Chairman + Returning Officer |
| T-1 day | Check monitoring, OTP delivery, backups; enrol MFA for all staff | All |
| T-0 | Open accreditation, then voting | Chairman |
| During voting | Monitor turnout, OTP failures, duplicate attempts; resolve accreditation exceptions | All |
| Close | Close voting; publish commitments; dual authorise count; run count | Chairman + Returning Officer |
| T+ | Submit provisional results, approve and declare, download audit reports | Returning Officer + Chairman |
| T+30 days | Archive election, retain records and keys | Chairman |

## 8. Incident procedures

**OTP delivery outage:** voters see a generic failure and no code is issued. Switch provider
credentials, confirm the sender domain/number, then retry. Delivery failures are recorded in
`notification_deliveries` without OTPs; keep `DEV_EXPOSE_OTP=false` — never fall back to displaying
codes in production.

**Suspected credential compromise:** revoke the issuance via the accreditation exception endpoint,
audit the action, notify the committee. Never delete audit records.

**Suspicious duplicate attempts / attack traffic:** capture audit details, apply edge rate limiting,
inform observers. The unique spent-credential constraint still prevents double counting.

**Counting failure or mismatch:** do not declare. Preserve the failed run, investigate invalid
ballot commitments, re-run counting after both officials re-authorise. Previous runs remain visible.

**Key loss:** the election cannot be decrypted. Restore keys from backup. If unrecoverable, the
election must be re-run; publish the incident and evidence.

**Suspension:** the Chairman may close voting early and record the reason; public commitment batches
already published must never be removed.

## 9. Monitoring

- `/api/health` for liveness and database connectivity.
- Election dashboard for availability, failed attempts, duplicates and turnout.
- Application logs must never contain OTPs, passwords, credentials or decrypted selections; the
  backend only logs counts and audit metadata.
- Alert on: credential issuance failures, OTP failure spikes, reconciliation imbalance, signature
  verification failures, audit-report check failures.

## 10. Retention

Retain ballots, commitments, receipts (hashed references), tally evidence, declarations, audit logs
and key archives for the retention period approved by the Electoral Committee. Ballot secrecy applies
after the election: no report or interface may link a voter to a ballot.
