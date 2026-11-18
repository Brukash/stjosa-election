-- Encrypted election key files kept on the election row.
-- Apply after 0005_voter_turnout.sql. A serverless deployment discards its
-- instance-local key directory, so an election created there lost its private
-- keys and could never be counted. The bundle is the same AES-256-GCM envelope
-- that lives on disk; only MASTER_KEY can open it. The application also adds
-- this column defensively on startup.

ALTER TABLE elections
    ADD COLUMN IF NOT EXISTS key_material TEXT;
