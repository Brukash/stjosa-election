-- One voter may hold exactly one live credential at a time.
--
-- Two simultaneous credential requests could both observe "no active issuance"
-- and each sign a credential, leaving one Voter ID holding two. Revoked rows keep
-- their history, so the index is partial: only issued rows must be unique.
-- Apply after 0008_accreditation_session_turnout.sql. The application also
-- creates the same index defensively on startup.

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_issuance_per_accreditation
    ON credential_issuances (accreditation_id)
    WHERE status = 'issued';
