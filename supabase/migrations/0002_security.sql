-- Security hardening for the Supabase PostgreSQL deployment (SRS §11.7, §12).
-- Apply after 0001_init.sql.
--
-- The FastAPI backend uses a server-side connection string and is responsible
-- for every authorisation decision. Browser clients never query Postgres
-- directly, so RLS is used as defence in depth: it denies everything except the
-- intentionally public, already-approved verification records.

-- ── Row Level Security ───────────────────────────────────────────────────────
ALTER TABLE profiles                              ENABLE ROW LEVEL SECURITY;
ALTER TABLE roles                                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_roles                            ENABLE ROW LEVEL SECURITY;
ALTER TABLE elections                             ENABLE ROW LEVEL SECURITY;
ALTER TABLE election_positions                    ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidates                            ENABLE ROW LEVEL SECURITY;
ALTER TABLE voters                                ENABLE ROW LEVEL SECURITY;
ALTER TABLE otp_challenges                        ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_deliveries               ENABLE ROW LEVEL SECURITY;
ALTER TABLE accreditation_records                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE accreditation_sessions                ENABLE ROW LEVEL SECURITY;
ALTER TABLE credential_issuances                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE spent_credentials                     ENABLE ROW LEVEL SECURITY;
ALTER TABLE prepared_ballots                      ENABLE ROW LEVEL SECURITY;
ALTER TABLE ballots                               ENABLE ROW LEVEL SECURITY;
ALTER TABLE challenged_ballots                    ENABLE ROW LEVEL SECURITY;
ALTER TABLE ballot_receipts                       ENABLE ROW LEVEL SECURITY;
ALTER TABLE ballot_commitments                    ENABLE ROW LEVEL SECURITY;
ALTER TABLE published_commitment_batches          ENABLE ROW LEVEL SECURITY;
ALTER TABLE election_verification_settings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE election_configuration_approvals      ENABLE ROW LEVEL SECURITY;
ALTER TABLE configuration_changes                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE tally_authorisations                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE tally_runs                            ENABLE ROW LEVEL SECURITY;
ALTER TABLE tally_results                         ENABLE ROW LEVEL SECURITY;
ALTER TABLE tally_proofs                          ENABLE ROW LEVEL SECURITY;
ALTER TABLE result_approvals                      ENABLE ROW LEVEL SECURITY;
ALTER TABLE result_declarations                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs                            ENABLE ROW LEVEL SECURITY;
ALTER TABLE election_events                       ENABLE ROW LEVEL SECURITY;
ALTER TABLE election_documents                    ENABLE ROW LEVEL SECURITY;

-- No policy is created for voter identity, accreditation, credential, ballot,
-- tally, approval or audit tables: with RLS enabled, anon/authenticated have no
-- access at all. Only the server-side role (which bypasses RLS) may read/write.

-- ── Public verification read-only access ────────────────────────────────────
DROP POLICY IF EXISTS public_read_published_batches ON published_commitment_batches;
CREATE POLICY public_read_published_batches
    ON published_commitment_batches
    FOR SELECT
    USING (published_at IS NOT NULL);

DROP POLICY IF EXISTS public_read_published_commitments ON ballot_commitments;
CREATE POLICY public_read_published_commitments
    ON ballot_commitments
    FOR SELECT
    USING (commitment_status = 'accepted' AND batch_id IS NOT NULL);

DROP POLICY IF EXISTS public_read_declared_results ON result_declarations;
CREATE POLICY public_read_declared_results
    ON result_declarations
    FOR SELECT
    USING (is_current = TRUE);

-- ── Role grants (Supabase only) ─────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
        GRANT SELECT (election_id, batch_reference, commitment_count, merkle_root,
                      digital_signature, signed_payload, published_at)
            ON published_commitment_batches TO anon;
        GRANT SELECT (election_id, ballot_commitment, commitment_status, batch_id)
            ON ballot_commitments TO anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM authenticated;
        GRANT SELECT (election_id, batch_reference, commitment_count, merkle_root,
                      digital_signature, signed_payload, published_at)
            ON published_commitment_batches TO authenticated;
        GRANT SELECT (election_id, ballot_commitment, commitment_status, batch_id)
            ON ballot_commitments TO authenticated;
    END IF;
END $$;

-- ── Append-only audit trail ─────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION prevent_audit_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs;
CREATE TRIGGER audit_logs_no_update
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();

-- Accepted ballots are immutable: no update or delete of ballot ciphertext.
CREATE OR REPLACE FUNCTION prevent_ballot_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'accepted ballots are immutable';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ballots_no_mutation ON ballots;
CREATE TRIGGER ballots_no_mutation
    BEFORE UPDATE OR DELETE ON ballots
    FOR EACH ROW EXECUTE FUNCTION prevent_ballot_mutation();

-- Credential issuance records must not store the credential serial: enforce the
-- column contract at the database level.
ALTER TABLE credential_issuances
    DROP COLUMN IF EXISTS credential_serial;

-- ── Integrity helpers ───────────────────────────────────────────────────────
-- A receipt row must never point at a commitment that is not an accepted ballot.
CREATE OR REPLACE FUNCTION check_receipt_commitment() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ballot_commitments c
        WHERE c.election_id = NEW.election_id
          AND c.ballot_commitment = NEW.ballot_commitment
          AND c.commitment_status = 'accepted'
    ) THEN
        RAISE EXCEPTION 'receipt references an unknown ballot commitment';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ballot_receipts_commitment_check ON ballot_receipts;
CREATE TRIGGER ballot_receipts_commitment_check
    BEFORE INSERT ON ballot_receipts
    FOR EACH ROW EXECUTE FUNCTION check_receipt_commitment();
