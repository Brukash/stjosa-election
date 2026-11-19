-- Every notice sent by email is also sent by SMS and WhatsApp, so the
-- registration notice needs its own SMS timestamp. Apply after
-- 0004_registration_notifications.sql. The application also adds the column
-- defensively on startup for deployments that have not yet run migrations.

ALTER TABLE voters
    ADD COLUMN IF NOT EXISTS registration_sms_sent_at TIMESTAMPTZ;
