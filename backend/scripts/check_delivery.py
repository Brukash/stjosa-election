"""Verify OTP delivery configuration, and optionally send a live test message.

No secrets or one-time passwords are printed. Run without arguments for a
configuration check; pass --to-email or --to-phone to send a live test.

    python scripts/check_delivery.py
    python scripts/check_delivery.py --to-email official@example.org
    python scripts/check_delivery.py --to-phone +2348012345678
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.notifications import _send_resend, _send_smtp, _send_twilio, mask_email, mask_phone  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check OTP delivery configuration")
    parser.add_argument("--to-email", help="Send a live test email to this address")
    parser.add_argument("--to-phone", help="Send a live test SMS to this E.164 number")
    args = parser.parse_args()

    print(f"environment:       {settings.environment}")
    print(f"delivery channels: {', '.join(settings.delivery_channels) or 'none'}")
    print(f"email provider:    {settings.email_provider or 'none'}")
    print(f"sms provider:      {settings.sms_provider or 'none'}")
    print(f"on-screen OTP:     {'enabled (local development only)' if settings.expose_dev_otp else 'disabled'}")
    if settings.production_issues:
        print("\nProduction issues:")
        for issue in settings.production_issues:
            print(f" - {issue}")

    failures = 0
    if args.to_email:
        subject = "SJC Alumni Election delivery test"
        body = "This is a delivery test from the St. John's College Jos Alumni Election system. No OTP is included."
        if settings.email_provider.strip().lower() == "smtp":
            message_id, error = _send_smtp(args.to_email, subject, body)
        else:
            message_id, error = _send_resend(args.to_email, subject, body, f"<p>{body}</p>")
        print(f"\nemail -> {mask_email(args.to_email)}: {'sent ' + (message_id or '') if message_id else 'FAILED: ' + (error or 'unknown error')}")
        failures += 0 if message_id else 1

    if args.to_phone:
        message_id, error = _send_twilio(
            args.to_phone,
            "SJC Alumni Election delivery test. No OTP is included.",
        )
        print(f"sms -> {mask_phone(args.to_phone)}: {'sent ' + (message_id or '') if message_id else 'FAILED: ' + (error or 'unknown error')}")
        failures += 0 if message_id else 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
