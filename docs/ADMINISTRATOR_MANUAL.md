# Administrator Manual

This manual covers the staff portal at `/admin`. Roles are enforced by the backend; a button that is
visible but not permitted will be rejected with `403`.

## 1. Sign in

1. Open `/admin` and sign in with your official email and password.
2. If MFA is enrolled, enter the 6-digit authenticator code when prompted.
3. After sign-in, open **Security** in the admin navigation (`/admin/security`). Choose *Set up
   authenticator*, add the setup key to your authenticator app, and confirm a six-digit code. Enrol
   MFA for every administrator before the
   election.

All sign-in attempts are recorded in the audit log.

## 2. Configure an election (Chairman, Super Administrator)

1. **Elections → Create election**: title, year, optional reference, opening and closing times.
2. **Workspace → Positions & candidates**: add each elective position and its approved candidates
   (name, profile, manifesto, optional photograph URL).
3. **Workspace → Setup & verification**: set eligibility rules and voting rules, then confirm the four
   verification controls:
   - Ballot inclusion verification
   - Private selection verification (challenge before casting)
   - Public anonymous ballot commitment list
   - PDF voting receipt

   All four are enabled by default. Save, then **Approve settings** as Chairman.

## 3. Load and approve the register

1. **Workspace → Voter register**: paste or upload the CSV from the Electoral Committee.
   Required columns: `voter_id`, `full_name`; optional: `email`, `phone`, `alumni_set`,
   `graduation_year`.
2. Remove ineligible records with **Exclude** (recorded in the audit log).
3. Click **Approve register** as Chairman. Only approved, eligible voters can be accredited.

The register and eligibility rules lock permanently when the first ballot is accepted.

## 4. Two-person configuration approval

1. The Chairman records approval under **Configuration approvals**.
2. The Returning Officer independently records the second approval.
3. The system then provisions the election's RSA tally key and Ed25519 signing key, computes the
   configuration hash and moves the election to **Approved**.

A single official cannot complete approval. The configuration hash covers dates, rules, positions,
candidates and verification settings.

## 5. Open the election

1. **Open accreditation** (Chairman): voters can now verify their Voter ID and receive credentials.
2. **Open voting** (Chairman): the ballot becomes available.
3. **Close voting** can be performed by the Chairman or Returning Officer; voting also closes
   automatically at the configured closing time.

Verification settings must be approved by a **different** authorised official from the one who saved
them (for example the Chairman configures, the Returning Officer approves). They freeze automatically
on the first accepted ballot. The dashboard shows the
lock time.

## 6. Monitor the election

**Monitoring** shows eligible/accredited/votes/turnout, hourly ballot submissions, failed Voter ID
checks, rejected duplicate attempts, security alerts, availability and verification lock state. The
**Voted and pending by alumni set** report shows aggregate turnout against a three-voter target for
each set. A private turnout marker records only that a voter has voted; it is never linked to the
anonymous ballot or its selections, and the report never shows voter names. Ballots cast before this
report is enabled have no marker and are therefore excluded from its voted counts.

Candidate totals remain hidden until counting completes.

## 7. Accreditation exceptions

If a voter loses their credential, an Accreditation Officer can revoke the active issuance
(`POST /api/accreditation/exceptions/reset-issuance` with the Voter ID and a reason). The revocation
is audited and the voter can accredit again. Use only for genuine exceptions and record the reason.

## 8. Counting (dual control)

1. Confirm voting is closed.
2. **Counting → Authorise counting** as Chairman; the Returning Officer authorises separately.
3. **Run automated count** (Returning Officer). The system:
   - publishes any unpublished commitment batch,
   - decrypts accepted ballots with the tally key,
   - excludes challenged ballots,
   - aggregates per position, marks winners and percentages,
   - stores a per-ballot proof and a signed evidence hash,
   - produces the reconciliation report.

If reconciliation is not balanced, do not proceed. Record the finding, investigate and re-run from
the preserved records; previous runs remain in the run history.

## 9. Declare results

1. **Results → Submit provisional results** (Returning Officer).
2. The Chairman reviews and clicks **Approve and declare results**.
3. The declaration is signed, published and accompanied by a PDF certificate and verification
   evidence.

Corrections after declaration require a reason and create a new version; earlier declarations are
preserved forever.

## 10. Audit

**Workspace → Audit** shows eight automated compliance checks, evidence by area, failed attempts and
administrative activity. Download PDF and Excel versions for the committee record. The audit report
never links a voter to a ballot.

## 11. Exceptional configuration changes

If an emergency requires a change after the freeze:

1. Record the change request with a mandatory reason.
2. A second authorised official approves it.
3. The previous configuration hash and approval history are preserved and the change appears in the
   election event log.

Voting security controls cannot be disabled; the API rejects attempts to remove verification features
after voting starts.
