"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class Settings:
    app_name: str = os.getenv(
        "APP_NAME", "St. John's College Jos Alumni Election Management System"
    )
    # `environment` is the single switch that decides whether development-only
    # behaviour (such as displaying an OTP on screen) is permitted at all.
    environment: str = os.getenv("ENVIRONMENT", "development")
    app_origin: str = os.getenv("APP_ORIGIN", "http://localhost:3000")
    api_origin: str = os.getenv("API_ORIGIN", "http://localhost:8000")

    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./election.db")

    secret_key: str = os.getenv("SECRET_KEY", "dev-only-change-me-please-32-bytes-minimum")
    master_key: str = os.getenv("MASTER_KEY", "dev-only-master-key-change-me-32-bytes-minimum")
    otp_pepper: str = os.getenv("OTP_HASH_PEPPER", "dev-only-otp-pepper-change-me")

    otp_ttl_seconds: int = _int("OTP_TTL_SECONDS", 300)
    otp_max_attempts: int = _int("OTP_MAX_ATTEMPTS", 5)
    otp_resend_seconds: int = _int("OTP_RESEND_SECONDS", 60)
    otp_max_requests_per_hour: int = _int("OTP_MAX_REQUESTS_PER_HOUR", 10)
    access_token_ttl_minutes: int = _int("ACCESS_TOKEN_TTL_MINUTES", 480)

    # Requesting the on-screen OTP is only honoured when the deployment is local
    # development. It can never be enabled in production by this flag alone.
    dev_expose_otp: bool = _bool("DEV_EXPOSE_OTP", True)

    # ── OTP delivery ────────────────────────────────────────────────────────
    email_provider: str = os.getenv("EMAIL_PROVIDER", "none")  # resend | smtp | none
    resend_api_key: str = os.getenv("RESEND_API_KEY", "")
    email_from: str = os.getenv(
        "EMAIL_FROM", "SJC Jos Alumni Election <no-reply@elections.sjcjos-alumni.org>"
    )
    email_api_base: str = os.getenv("EMAIL_API_BASE", "https://api.resend.com").rstrip("/")

    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = _int("SMTP_PORT", 587)
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_starttls: bool = _bool("SMTP_STARTTLS", True)

    # Termii is the required SMS gateway. Twilio remains available only as a
    # legacy fallback for deployments that have not migrated yet.
    sms_provider: str = os.getenv("SMS_PROVIDER", "termii")  # termii | twilio | none
    termii_api_key: str = os.getenv("TERMII_API_KEY", "")
    termii_sender_id: str = os.getenv("TERMII_SENDER_ID", "")
    termii_channel: str = os.getenv("TERMII_CHANNEL", "dnd")  # dnd is required for OTPs
    termii_api_base: str = os.getenv("TERMII_API_BASE", "https://api.ng.termii.com").rstrip("/")

    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_from_number: str = os.getenv("TWILIO_FROM_NUMBER", "")
    sms_api_base: str = os.getenv("SMS_API_BASE", "https://api.twilio.com").rstrip("/")

    # WhatsApp uses the official Meta WhatsApp Business Platform / Cloud API.
    # A personal WhatsApp account or browser automation is never used.
    whatsapp_provider: str = os.getenv("WHATSAPP_PROVIDER", "none")  # meta | none
    whatsapp_access_token: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    whatsapp_phone_number_id: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    whatsapp_business_account_id: str = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
    whatsapp_api_base: str = os.getenv(
        "WHATSAPP_API_BASE", "https://graph.facebook.com/v27.0"
    ).rstrip("/")
    whatsapp_template_name: str = os.getenv("WHATSAPP_TEMPLATE_NAME", "sjc_election_otp")
    whatsapp_template_language: str = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US")
    # Registration notices are utility templates, separate from the OTP
    # authentication template. Parameters: {{1}} name, {{2}} election title,
    # {{3}} Voter ID.
    whatsapp_registration_template_name: str = os.getenv(
        "WHATSAPP_REGISTRATION_TEMPLATE_NAME", "sjc_registration_confirmation"
    )
    whatsapp_registration_template_language: str = os.getenv(
        "WHATSAPP_REGISTRATION_TEMPLATE_LANGUAGE", "en_US"
    )
    whatsapp_app_secret: str = os.getenv("WHATSAPP_APP_SECRET", "")
    whatsapp_verify_token: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

    otp_delivery_timeout_seconds: int = _int("OTP_DELIVERY_TIMEOUT_SECONDS", 10)

    seed_password: str = os.getenv("SEED_DEFAULT_PASSWORD", "ChangeMe!2026")
    keys_dir: Path = Path(os.getenv("KEYS_DIR", str(BASE_DIR / "keys")))
    jwt_algorithm: str = "HS256"

    # Ballot preparation lifetime: an uncast prepared ballot expires.
    prepared_ballot_ttl_seconds: int = 30 * 60

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() not in {"development", "dev", "local", "test"}

    @property
    def app_origin_is_loopback(self) -> bool:
        host = (urlparse(self.app_origin).hostname or "").lower()
        return host in {"localhost", "127.0.0.1", "::1"}

    @property
    def expose_dev_otp(self) -> bool:
        """True only for a local development deployment that explicitly opted in.

        Production, staging, any non-loopback origin, or a false DEV_EXPOSE_OTP
        value all disable on-screen OTP display.
        """
        return bool(self.dev_expose_otp) and not self.is_production and self.app_origin_is_loopback

    @property
    def email_configured(self) -> bool:
        provider = self.email_provider.strip().lower()
        if provider == "resend":
            return bool(self.resend_api_key)
        if provider == "smtp":
            return bool(self.smtp_host)
        return False

    @property
    def sms_configured(self) -> bool:
        provider = self.sms_provider.strip().lower()
        if provider == "termii":
            return bool(self.termii_api_key and self.termii_sender_id)
        if provider == "twilio":
            return bool(
                self.twilio_account_sid
                and self.twilio_auth_token
                and self.twilio_from_number
            )
        return False

    @property
    def whatsapp_configured(self) -> bool:
        if self.whatsapp_provider.strip().lower() != "meta":
            return False
        return bool(
            self.whatsapp_access_token
            and self.whatsapp_phone_number_id
            and self.whatsapp_template_name
        )

    @property
    def whatsapp_registration_configured(self) -> bool:
        return bool(
            self.whatsapp_provider.strip().lower() == "meta"
            and self.whatsapp_access_token
            and self.whatsapp_phone_number_id
            and self.whatsapp_registration_template_name
        )

    @property
    def delivery_channels(self) -> list[str]:
        channels: list[str] = []
        if self.email_configured:
            channels.append("email")
        if self.sms_configured:
            channels.append("sms")
        if self.whatsapp_configured:
            channels.append("whatsapp")
        return channels

    @property
    def delivery_mode(self) -> str:
        if self.delivery_channels:
            return "+".join(self.delivery_channels)
        if self.expose_dev_otp:
            return "development-on-screen"
        return "not configured"

    @property
    def production_issues(self) -> list[str]:
        """Configuration that must be resolved before running a real election.

        Empty for development. In production, any entry blocks startup so a
        misconfigured deployment fails closed instead of issuing unusable OTPs.
        """
        if not self.is_production:
            return []
        issues: list[str] = []
        if self.secret_key.startswith("dev-only"):
            issues.append("SECRET_KEY still uses the development default")
        if self.master_key.startswith("dev-only"):
            issues.append("MASTER_KEY still uses the development default")
        if self.otp_pepper.startswith("dev-only"):
            issues.append("OTP_HASH_PEPPER still uses the development default")
        if self.seed_password == "ChangeMe!2026":
            issues.append("SEED_DEFAULT_PASSWORD still uses the demo default")
        if not self.delivery_channels:
            issues.append("no OTP delivery channel is configured (email, SMS or WhatsApp)")
        if not self.app_origin.lower().startswith("https://"):
            issues.append("APP_ORIGIN must be an https origin in production")
        if "sqlite" in self.database_url:
            issues.append("DATABASE_URL must point at PostgreSQL in production")
        if os.getenv("DEMO_SEED", "").strip().lower() in {"1", "true", "yes"}:
            issues.append("DEMO_SEED must be disabled in production")
        return issues


settings = Settings()

if settings.database_url.startswith("postgres://"):
    settings.database_url = settings.database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif settings.database_url.startswith("postgresql://"):
    settings.database_url = settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)

settings.keys_dir.mkdir(parents=True, exist_ok=True)

ELECTION_REFERENCE_PREFIX = "SJCJ-ALUMNI"
