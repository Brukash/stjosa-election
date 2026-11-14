-- Registration notices sent after the electoral register is approved.
-- Apply after 0003_otp_channels.sql. The application also adds these columns
-- defensively on startup for deployments that have not yet run migrations.

ALTER TABLE voters
    ADD COLUMN IF NOT EXISTS registration_email_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS registration_whatsapp_sent_at TIMESTAMPTZ;

ALTER TABLE notification_deliveries
    ADD COLUMN IF NOT EXISTS purpose VARCHAR(20) NOT NULL DEFAULT 'otp';

CREATE INDEX IF NOT EXISTS ix_notification_deliveries_purpose
    ON notification_deliveries (purpose);
