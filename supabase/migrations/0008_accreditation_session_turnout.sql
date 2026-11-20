-- The turnout marker belongs to the verification session, not to the voter row.
-- Verifying the same Voter ID twice previously rotated the marker on the voter,
-- which invalidated a credential that had already been issued from the earlier
-- verification. The marker is now copied to the voter only when a credential is
-- issued. Apply after 0005_voter_turnout.sql. The application also adds the
-- column defensively on startup.

ALTER TABLE accreditation_sessions
    ADD COLUMN IF NOT EXISTS turnout_token_hash VARCHAR(128);
