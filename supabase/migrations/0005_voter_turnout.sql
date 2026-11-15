-- Private voter turnout markers for aggregate progress reporting.
-- Apply after 0004_registration_notifications.sql. A marker records only that
-- a voter cast an accepted ballot; it is never linked to a ballot or selection.
-- The application also adds these columns defensively on startup.

ALTER TABLE voters
    ADD COLUMN IF NOT EXISTS turnout_token_hash VARCHAR(128),
    ADD COLUMN IF NOT EXISTS has_voted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_voters_turnout_token_hash
    ON voters (turnout_token_hash);
