# Security Architecture and Testing Report

## 1. Protocol summary

### 1.1 Anonymous credential (RSA-FDH blind signature)

- Issuer key: RSA 2048-bit, stored encrypted under `MASTER_KEY` (`backend/keys/credential_issuer_private.pem`).
- Client generates a 256-bit secret token `t`, computes `h = FDH("SJC-CRED|<election>|<t>")` where
  `FDH` is SHA-256 + MGF1 mapped into `Z_n` (`shadow` of RSA-FDH).
- Client picks `r` coprime to `n`, sends `h · r^e mod n`.
- Issuer signs with `d`; client unblinds `s = s' · r^-1 mod n` and verifies `s^e = h mod n`.
- The issuer never sees `t` or the unblinded signature, so issuance records cannot be linked to a cast
  ballot. The server records only `sha256(blinded_request)` and the accreditation reference.
- At cast time the server verifies the signature and unconditionally spends `sha256(t)` in
  `spent_credentials` (unique constraint), which prevents double voting even under concurrency.

### 1.2 Ballot encryption

- Tally key: RSA 3072-bit per election, private key encrypted with AES-256-GCM under a scrypt-derived
  master key; public key published in the election record.
- Ballot: JSON `{"election": ref, "selections": {position: candidate}}` encrypted with AES-256-GCM
  (random 256-bit data key, random 96-bit nonce, election reference as AAD).
- Data key wrapped with RSA-OAEP-SHA256.
- Commitment: `SHA-256("SJC-BALLOT-COMMITMENT-V1" | ref | nonce | encrypted_key | ciphertext)`.
- Key commitment: `SHA-256("SJC-KEY" | ref | data_key_b64)` — lets a voter verify the revealed key
  without weakening ballot secrecy.

### 1.3 Cast-as-intended challenge

A prepared ballot is stored encrypted with its plaintext and randomisers retained only until the voter
decides. On challenge:

1. the ballot row is marked `challenged` and plaintext + data key are erased;
2. a `challenged_ballots` record stores the revealed proof (ciphertext, wrapped key, nonce, data key,
   selections, commitments, timestamp);
3. the browser decrypts the ciphertext with WebCrypto and compares the plaintext selections, recomputes
   the key commitment and the ballot commitment;
4. challenged ballots are never eligible for the tally — `POST /cast` returns `409`.

The protocol never produces a transferable proof of the voter's final cast ballot, which limits
coercion and vote-buying risk.

### 1.3a OTP delivery

- OTPs are delivered by email (Resend HTTP API, or SMTP) or by Twilio SMS to the contact held on the
  approved register. The browser cannot choose the destination.
- OTPs are stored only as HMAC-SHA256 digests; delivery records store a masked recipient, provider
  message id, status and a truncated failure reason — never the code or the full address.
- On-screen delivery exists only for local development: `ENVIRONMENT=development`, a loopback
  `APP_ORIGIN` and `DEV_EXPOSE_OTP=true` are all required. Production/staging or a public origin
  disables it regardless of the flag.
- With no channel configured outside development, OTP issuance returns `503` rather than exposing a
  code; a provider failure returns `502` and expires the challenge immediately.

### 1.4 Published commitments and tally

- Commitments are published in batches after closure. Each batch has a Merkle root
  (`SHA-256("SJC-LEAF|commitment")`, `SHA-256("SJC-NODE|left|right")`) and an Ed25519 signature over a
  canonical JSON header.
- Counting runs only with two authorisations (Chairman + Returning Officer), decrypts each accepted
  ballot, validates every selection against the approved candidate set, and writes:
  - one `tally_proofs` row per ballot (Merkle inclusion proof, decrypted-selection hash, hash-chain
    link),
  - a signed `tally_runs` evidence object (`evidence_hash`, `signature`, `reconciliation`).
- Results declarations are signed and versioned; corrections preserve prior declarations.
- Verification recomputes the Merkle proof and verifies the batch signature server-side and returns the
  material needed for independent checking.

## 2. Separation of duties implemented

| Control | Implementation |
| --- | --- |
| No admin can see selections | Ballot tables have no voter FK; decryption requires the tally key (counting service, dual control) |
| No single official can declare results | Returning Officer submits, Chairman approves; `result_approvals` records both |
| No single official can approve configuration | Chairman + Returning Officer approvals required before keys are provisioned |
| Super Admin restrictions | Permission matrix excludes approval, verification configuration, counting and declaration |
| Verification freeze | `elections.locked_at` + `election_verification_settings.locked_at` set atomically on first accepted ballot; settings endpoints reject updates |
| Audit integrity | Append-only audit log; PostgreSQL trigger blocks UPDATE/DELETE |
| Ballot immutability | No update/delete endpoints; PostgreSQL trigger blocks UPDATE/DELETE on `ballots` |
| Credential serial secrecy | Issuance records never store the serial or signature |

## 3. Threat model and mitigations

| Threat | Mitigation |
| --- | --- |
| Ineligible person votes | Approved register + OTP + one credential per Voter ID |
| Double voting | Unique spent-credential constraint; idempotent cast retries return the original receipt |
| Credential theft | Single-use credential, OTP-bound issuance, audited revocation |
| Ballot substitution | Cast-as-intended challenge with browser-side verification |
| Vote buying / coercion | No transferable proof of final selections; receipt contains commitment only |
| Admin reads votes | Ballot ciphertext only; tally key outside database, dual-control use |
| Admin alters results | Signed tally evidence; declarations signed and versioned; corrections audited |
| Commitment list tampering | Merkle root + Ed25519 signature; earlier batches preserved |
| Receipt enumeration | 160-bit random reference stored only as SHA-256 |
| Replay / duplicate submissions | Prepared-ballot binding to credential hash + unique spent credential |
| Verification disabled mid-election | Settings locked on first ballot and at closure |
| Audit tampering | Append-only table plus database trigger |
| OTP brute force | 5 attempts, 5-minute expiry, 60-second resend, 10 requests/hour |

## 4. Test evidence

`backend/scripts/smoke_test.py` runs a complete mock election and asserts 22 properties. Last run
against the delivered code: **22/22 passed**.

1. Health check and public election payload
2. Ballot contains positions and candidates
3. All five staff roles authenticate
4. Challenge reveals cryptographic proof of exact selections
5. Challenged ballot cannot be cast (409)
6. Fresh ballot casts successfully
7. Cast retry returns the same receipt (idempotent)
8. Credential reuse rejected (409)
9. Receipt verification confirms the ballot is recorded
10. PDF receipt downloads and is a valid PDF
11. Multiple accredited voters cast encrypted ballots
12. Configuration locks after the first ballot
13. Verification settings update rejected after lock
14. Verification settings require approval by a different official (tested)
15. MFA enrol/activate and login enforcement (tested)
14. Observer cannot change lifecycle (403)
15. Commitment list published and signature verified
16. Counting blocked without dual authorisation (403)
17. Count completes with signed evidence and balanced reconciliation
18. Voter verification shows Merkle inclusion and count inclusion
19. Results submitted, approved, declared and signature verified
20. Result certificate PDF generated
21. Audit report passes all 8 automated checks; PDF and Excel exports valid
22. Second election configured and approved through the two-person flow

Additionally exercised in a real browser (Chromium): OTP accreditation, in-browser credential
blinding/unblinding and verification, ballot selection, challenge verification (all four browser
checks passed), casting, and receipt issuance.

`backend/scripts/test_otp_delivery.py` exercises real provider HTTP payloads against a local mock
(no credentials required). Last run: **9/9 passed**.

1. OTP delivered by email; no OTP in the API response
2. Provider received the OTP addressed to the registered email only
3. The emailed OTP completes accreditation
4. Delivery recorded without the OTP or full address
5. On-screen OTP refused for non-loopback origin and for production/staging
6. Production without a provider fails closed (503, no OTP)
7. Twilio SMS fallback sends E.164 and the code accredits the voter
8. Provider outage returns 502, records the failure and never leaks the OTP
9. Local development still shows the OTP when explicitly enabled

Also checked manually: authorization failures return 403, invalid credentials 401, locked
configuration 409, and no ballot table row contains a voter identifier.

## 5. Residual risks / required work before production

1. **Independent cryptographic review** of the blind signature and challenge protocol (SRS §12.4) has
   not been performed. Do not run a real election without it.
2. **OTP deliverability**: Resend/SMTP and Twilio are integrated, but the committee must verify its
   sender domain (SPF/DKIM/DMARC) or Twilio sender for Nigeria, set `ENVIRONMENT=production`, and
   monitor `notification_deliveries` failures. No provider credentials are committed.
3. **Key management**: file-based tally keys with a software master key. Use an HSM/KMS with
   dual-control release, documented rotation and split-knowledge custody.
4. **Load and availability testing** at 2,500 voters / 500 concurrent users has not been performed.
5. **Penetration testing** (authentication, API, injection, XSS, OTP abuse, credential reuse, database
   access control) is pending independent execution.
6. **Session storage**: staff JWT is in `localStorage`. Production should use `HttpOnly` cookies, CSRF
   tokens and short session lifetimes with refresh.
7. **MFA enrolment** is available at `/admin/security` and enforced for any account that enrols; it is
   not yet mandatory by role. Enrol every official before the election and consider enforcing it for
   Chairman and Returning Officer.
8. **DoS / edge rate limiting** is database-level per voter only; add WAF/edge limits.

## 6. Acceptance criteria status

| # | Criterion | Status |
| --- | --- | --- |
| 1 | Only eligible voters obtain credentials | Implemented, tested |
| 2 | OTP verification works | Implemented, tested |
| 3 | No multiple credentials | Implemented (one active issuance; audited exception), tested indirectly |
| 4 | Credential single use | Implemented, tested |
| 5 | Selections encrypted | Implemented, tested |
| 6 | No application link voter↔ballot | Implemented by schema and flow |
| 7 | Private selection verification | Implemented, browser-verified |
| 8 | Challenged ballots excluded | Implemented, tested |
| 9 | Accepted ballots immutable | Implemented (API + DB trigger) |
| 10 | Every accepted ballot gets a receipt | Implemented, tested |
| 11 | Voters verify inclusion | Implemented, tested |
| 12 | Commitment list independently checkable | Signed manifest + documented rules |
| 13 | Reproducible verifiable tally | Implemented with signed evidence and proofs |
| 14 | Dashboard accurate | Implemented, tested |
| 15 | Settings locked during voting | Implemented, tested |
| 16 | Results require approval | Implemented, tested |
| 17 | Audit reports | Implemented, tested |
| 18 | Independent security testing | **Not performed** — required |
| 19 | Backup/recovery tested | Documented in OPERATIONS.md; **not executed on Supabase** |
| 20 | Full mock election | Executed (22 checks) |
