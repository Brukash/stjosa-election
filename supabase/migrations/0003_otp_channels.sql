-- OTP delivery channels: email, SMS and WhatsApp.
-- Apply after 0001_init.sql and 0002_security.sql.
--
-- Voter consent is required before WhatsApp authentication messages are sent.
-- The application also adds this column defensively on startup for deployments
-- that have not yet run migrations.

ALTER TABLE voters
    ADD COLUMN IF NOT EXISTS whatsapp_consent BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_notification_deliveries_channel
    ON notification_deliveries (channel);
