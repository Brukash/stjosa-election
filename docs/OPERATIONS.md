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
   - `supabase/migrations/0003_otp_channels.sql` — voter WhatsApp consent and delivery-channel history.
   - `supabase/migrations/0004_registration_notifications.sql` — registration notice timestamps and
     purpose tracking.
   - `supabase/migrations/0005_voter_turnout.sql` — private turnout marker for aggregate progress
     reporting.
3. Confirm RLS is enabled on all sensitive tables (`Supabase → Database → Tables`).
4. Create staff accounts through the application (or seed then change every password).
5. Never expose the database connection string to the browser; the Next.js app talks only to FastAPI.

`0001_init.sql` can be regenerated after model changes:

```bash
cd backend
.venv/Scripts/python.exe scripts/export_postgres_schema.py > ../supabase/migrations/0001_init.sql
```

## 2a. Registration notice delivery

Accreditation is Voter ID-only: the voter enters the Voter ID from the approved register, and a match
opens the credential flow. No OTP is generated or delivered.

When the Chairman approves the register, the backend sends one registration notice by email and one
by WhatsApp to each eligible voter. The email includes the voter's **Voter ID**, which is the identifier
used for accreditation. Successful channels are recorded on the voter so a repeat approval only retries
the missing channel. Approval commits before delivery; provider failures do not cancel the approval.

The additive migration `supabase/migrations/0003_otp_channels.sql` adds the voter WhatsApp consent
column and remains part of the schema history. Registration notices use
`supabase/migrations/0004_registration_notifications.sql` for per-channel sent timestamps and a
`purpose` column on `notification_deliveries`; the API adds those columns defensively as well.

### Email — cPanel SMTP (recommended for this election)

The association's cPanel mailbox replaces Resend. A cPanel account has no 100-per-day API cap, so
150 registration notices plus 150 vote confirmations fit in one day; the only limits are the host's
hourly message cap and its simultaneous-connection cap.

1. **Create the sending mailbox.** cPanel → *Email Accounts* → *Create*. Use an address on the
   election domain, for example `no-reply@elections.cbncoopng.com`. Keep the password in cPanel and
   in the Vercel environment only — never in the repository or in chat.
2. **Read the outgoing server settings.** cPanel → *Email Accounts* → *Connect Devices* (or *Mail
   Client Manual Settings*) shows the outgoing server. It is normally `mail.<your-domain>` plus:
   **465** for SSL/TLS (implicit TLS, recommended) or **587** for STARTTLS. Port 25 is blocked by
   Vercel and must not be used.
3. **Set the Vercel environment variables** (Project → Settings → Environment Variables →
   Production) and redeploy:

   | Variable | Value |
   | --- | --- |
   | `EMAIL_PROVIDER` | `smtp` |
   | `EMAIL_FROM` | `SJC Jos Alumni Election <no-reply@elections.cbncoopng.com>` |
   | `SMTP_HOST` | exact host from step 2, e.g. `mail.elections.cbncoopng.com` |
   | `SMTP_PORT` | `465` |
   | `SMTP_USERNAME` | the **full** mailbox address |
   | `SMTP_PASSWORD` | the mailbox password |
   | `SMTP_SSL` | `true` on port 465. On 587 set `SMTP_STARTTLS=true` and leave `SMTP_SSL` unset |
   | `SMTP_MAX_CONNECTIONS` | `3` (default); cPanel blocks mailboxes that open too many connections |

   `EMAIL_FROM` must be that mailbox, or an alias on the same domain: cPanel refuses a sender it
   does not host. Remove `RESEND_API_KEY` once SMTP works so the deployment cannot fall back
   silently.
4. **Authenticate the domain.** cPanel → *Email Deliverability* → *Repair* for the domain. Confirm
   SPF and DKIM are **Valid**. DKIM must be enabled before the rehearsal, or Gmail and Outlook will
   junk bulk notices.
5. **Verify before election day.** With the same variables in `backend/.env`:

   ```bash
   cd backend
   .venv/Scripts/python.exe scripts/check_delivery.py --to-email you@example.org
   ```

   The report must say `sent <Message-ID>`. Then open `/admin/delivery` on the deployed API as the
   Super Administrator: Email must show the `smtp` provider and `configured: true`.

**Ask the host for two numbers.** The per-hour message limit for the domain (commonly 200–500/hour
on shared hosting) and the simultaneous SMTP connection cap. 150 registration notices plus 150 vote
confirmations is 300 messages: if the hourly cap is 200 or lower, approve the register in batches of
about 50, since the app records each voter's sent channel and only retries the missing ones.

**Troubleshooting.**

| Symptom | Cause |
| --- | --- |
| `smtp delivery failed: SMTPAuthenticationError` | Wrong mailbox or password; `SMTP_USERNAME` must be the full address |
| `smtp delivery failed: SMTPSenderRefused` | `EMAIL_FROM` is not a mailbox or alias on this cPanel account |
| `smtp delivery failed: SMTPServerDisconnected` or timeout | Wrong host/port pairing — 465 with `SMTP_SSL=true`, or 587 with `SMTP_STARTTLS=true` |
| Delivered but lands in spam | DKIM disabled or SPF missing in *Email Deliverability* |
| `smtp delivery failed: SMTPRecipientsRefused` | The recipient's server rejected the address on the register |

### Email — Resend (optional)

1. Create a Resend account and add the sending domain (for example `elections.sjcjos-alumni.org`).
2. Add the SPF and DKIM records Resend provides, wait for domain verification, then set a DMARC
   policy for the subdomain.
3. Set `EMAIL_PROVIDER=resend`, `RESEND_API_KEY` (server-side secret only) and
   `EMAIL_FROM="SJC Jos Alumni Election <no-reply@elections.sjcjos-alumni.org>"`.
4. Send a test registration notice to a committee mailbox and confirm inbox placement.


### WhatsApp — Meta WhatsApp Business Platform / Cloud API

1. Create a Meta Business account, a WhatsApp Business Account and a system-user access token with
   `whatsapp_business_messaging` permission. Never use a personal WhatsApp account or automation.
2. Create an approved **Utility** template (for example `sjc_registration_confirmation`, language
   `en_US`) whose body uses three parameters in this order: `{{1}}` voter full name, `{{2}}` election
   title and `{{3}}` Voter ID. This is not an authentication/OTP template.
3. Create a second approved **Utility** template (for example `sjc_vote_confirmation`, language
   `en_US`) for the post-vote confirmation. Its body uses three parameters in this order: `{{1}}`
   voter full name, `{{2}}` election title and `{{3}}` submission time. It must say the ballot was
   received and submitted successfully and must not request or reveal selections.
4. Set `WHATSAPP_PROVIDER=meta`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
   `WHATSAPP_REGISTRATION_TEMPLATE_NAME`, `WHATSAPP_REGISTRATION_TEMPLATE_LANGUAGE`,
   `WHATSAPP_VOTE_CONFIRMATION_TEMPLATE_NAME` and `WHATSAPP_VOTE_CONFIRMATION_TEMPLATE_LANGUAGE`.
   Keep the token in the server-side environment/secret store only.
5. Record each voter's `whatsapp_consent` in the register CSV/import or via the register screen.
   WhatsApp is reported as unavailable and skipped without consent; email still proceeds.
6. Set `WHATSAPP_APP_SECRET` and `WHATSAPP_VERIFY_TOKEN`, then subscribe the Meta app to
   `https://<api-host>/api/webhooks/whatsapp`. Signed delivery/read/failure callbacks update
   `notification_deliveries`; message contents are not stored.
7. Send a test registration and vote-confirmation template to a consented committee number and
   confirm delivery before the election. The Super Administrator can inspect readiness at
   `/admin/delivery`.

### Local WhatsApp registration-delivery test

To send one registration notice without approving the register or writing voter/delivery records:

```bash
cd backend
.venv/Scripts/python.exe scripts/test_whatsapp_registration.py --to +2348012345678 --consented
```

`--consented` is required and must only be passed after confirming the destination has a recorded
WhatsApp opt-in. The command reads `WHATSAPP_*` from the environment or `backend/.env`, reuses the
exact registration-notice payload, and prints only the template, masked recipient and provider
message id. It opens no database session and sends one real billable message.

### Production guard and preflight

In production the backend refuses to start when a critical setting is missing or still on a
development default: weak `SECRET_KEY`/`MASTER_KEY`, the demo password, no notification delivery
channel, a non-https `APP_ORIGIN`, SQLite, or `DEMO_SEED=true`. Fix the reported setting and restart.

Run the read-only checks before opening the election:

```bash
cd backend
.venv/Scripts/python.exe scripts/preflight.py
.venv/Scripts/python.exe scripts/test_notifications.py
```

`preflight.py` reports configuration, database reachability, missing tables and recent elections; it
exits non-zero when production would fail closed. It does not send messages or expose secrets.

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

Election keys are also kept as an encrypted bundle on the election row (`elections.key_material`),
because Vercel discards the instance-local key directory. It is the same AES-256-GCM envelope as the
files on disk; back up the row with the database and `MASTER_KEY` separately. Key files that still
exist on the machine that created them can be copied onto their rows with:

```bash
cd backend
.venv/Scripts/python.exe scripts/backfill_key_material.py --env-file .env.supabase --apply
```

An election created on a serverless deployment before this column existed has no recoverable keys:
its ballots cannot be decrypted and the election must be recreated.

Rotating `MASTER_KEY` requires re-encrypting the key files before restarting (decrypt with old key,
encrypt with new). Removing an election's key directory destroys the ability to decrypt its ballots —
archive it under dual control for the retention period.

## 6. Backup and recovery

### What to back up

1. PostgreSQL database (all tables, especially `ballots`, `ballot_commitments`,
   `published_commitment_batches`, `tally_*`, `result_*`, `audit_logs`).
2. `keys/` directory (encrypted private keys).
3. `MASTER_KEY`, `SECRET_KEY` and provider credentials in the secret manager.
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

**Recovery test was executed on 14 Nov 2026**: a custom-format dump of the Supabase database was
restored into a local PostgreSQL 17 instance. The restored database contained 5 profiles, 1 election
and 24 voters, and the application passed health, public-election and Chairman-login checks against
it. This proves the logical restore path; a production failover drill and encrypted off-site backup
schedule are still required before go-live.

## 7. Election-day runbook

| Time | Action | Role |
| --- | --- | --- |
| T-14 days | Configure election, positions, candidates, verification settings | Chairman |
| T-10 days | Import register, exclude ineligible records, approve register | Chairman |
| T-7 days | Approve the configuration; confirm keys provisioned | Chairman |
| T-1 day | Check monitoring, email/WhatsApp delivery, backups; enrol MFA for all staff | All |
| T-0 | Open accreditation, then voting | Chairman |
| During voting | Monitor turnout, failed Voter ID checks, duplicate attempts; resolve accreditation exceptions | All |
| Close | Close voting; publish commitments; authorise count; run count | Chairman |
| T+ | Submit provisional results, approve and declare, download audit reports | Chairman |
| T+30 days | Archive election, retain records and keys | Chairman |

## 8. Incident procedures

**Email or WhatsApp notice outage:** registration approval still succeeds, but the affected channel
is recorded as failed and can be retried by approving the register again. Fix the provider credentials
or sender domain, then retry only the missing channel. Message contents are never written to delivery
records.

**Suspected credential compromise:** revoke the issuance via the accreditation exception endpoint,
audit the action, notify the committee. Never delete audit records.

**Suspicious duplicate attempts / attack traffic:** capture audit details, apply edge rate limiting,
inform observers. The unique spent-credential constraint still prevents double counting.

**Counting failure or mismatch:** do not declare. Preserve the failed run, investigate invalid
ballot commitments, re-run counting after authorising the count again. Previous runs remain visible.

**Key loss:** the election cannot be decrypted. Restore keys from backup. If unrecoverable, the
election must be re-run; publish the incident and evidence.

**Suspension:** the Chairman may close voting early and record the reason; public commitment batches
already published must never be removed.

## 9. Monitoring

- `/api/health` for liveness and database connectivity.
- Election dashboard for availability, failed attempts, duplicates and turnout.
- Application logs must never contain passwords, credentials or decrypted selections; the
  backend only logs counts and audit metadata.
- Alert on: credential issuance failures, failed Voter ID check spikes, reconciliation imbalance, signature
  verification failures, audit-report check failures.

## 10. Retention

Retain ballots, commitments, receipts (hashed references), tally evidence, declarations, audit logs
and key archives for the retention period approved by the Electoral Committee. Ballot secrecy applies
after the election: no report or interface may link a voter to a ballot.
