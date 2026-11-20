"""Verify notification delivery configuration, and optionally send a live test.

No secrets are printed. Run without arguments for a configuration check; pass
--to-email, --to-phone or --to-whatsapp to send one live test message.

    python scripts/check_delivery.py
    python scripts/check_delivery.py --to-email official@example.org
    python scripts/check_delivery.py --to-phone +2348012345678
    python scripts/check_delivery.py --to-whatsapp +2348012345678
    python scripts/check_delivery.py --to-whatsapp +2348012345678 --whatsapp-template results

The WhatsApp destination must have a recorded opt-in. The test uses the same
payload builders as registration approval, ballot confirmation and results
declaration, so a success here proves that template and parameter order are
approved and deliverable.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.notifications import (  # noqa: E402
    _send_resend,
    _send_smtp,
    _send_termii,
    _send_twilio,
    mask_email,
    mask_phone,
    send_registration_whatsapp,
    send_results_whatsapp,
    send_vote_confirmation_whatsapp,
    whatsapp_template_reference,
)

TEST_VOTER = "Delivery Test"
TEST_ELECTION = "SJC Alumni Election delivery test"
TEST_VOTER_ID = "SJC/AL/0000/000"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check notification delivery configuration")
    parser.add_argument("--to-email", help="Send a live test email to this address")
    parser.add_argument("--to-phone", help="Send a live test SMS to this E.164 number")
    parser.add_argument(
        "--to-whatsapp",
        help="Send a live template test to this opted-in E.164 WhatsApp number",
    )
    parser.add_argument(
        "--whatsapp-template",
        choices=("registration", "vote_confirmation", "results"),
        default="registration",
        help="Which approved Utility template to test (default: registration)",
    )
    args = parser.parse_args()

    print(f"environment:       {settings.environment}")
    print(f"delivery channels: {', '.join(settings.delivery_channels) or 'none'}")
    print(f"email provider:    {settings.email_provider or 'none'}")
    print(f"sms provider:      {settings.sms_provider or 'none'}")
    print(f"whatsapp provider: {settings.whatsapp_provider or 'none'}")
    print(f"registration tmpl: {whatsapp_template_reference('registration') or 'none'}")
    print(f"vote tmpl:         {whatsapp_template_reference('vote_confirmation') or 'none'}")
    print(f"results tmpl:      {whatsapp_template_reference('results') or 'none'}")
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
        text = "SJC Alumni Election delivery test. No OTP is included."
        if settings.sms_provider.strip().lower() == "termii":
            message_id, error = _send_termii(args.to_phone, text)
        else:
            message_id, error = _send_twilio(args.to_phone, text)
        print(f"sms -> {mask_phone(args.to_phone)}: {'sent ' + (message_id or '') if message_id else 'FAILED: ' + (error or 'unknown error')}")
        failures += 0 if message_id else 1

    if args.to_whatsapp:
        if not settings.whatsapp_configured:
            print(f"whatsapp -> {mask_phone(args.to_whatsapp)}: FAILED: provider not configured")
            return 1
        if args.whatsapp_template == "registration":
            if not settings.whatsapp_registration_configured:
                print("whatsapp -> FAILED: registration template is not configured")
                return 1
            result = send_registration_whatsapp(
                voter_name=TEST_VOTER,
                voter_id=TEST_VOTER_ID,
                election_title=TEST_ELECTION,
                destination=args.to_whatsapp,
            )
        elif args.whatsapp_template == "vote_confirmation":
            if not settings.whatsapp_vote_confirmation_configured:
                print("whatsapp -> FAILED: vote confirmation template is not configured")
                return 1
            result = send_vote_confirmation_whatsapp(
                voter_name=TEST_VOTER,
                election_title=TEST_ELECTION,
                submitted_label="delivery test",
                destination=args.to_whatsapp,
            )
        else:
            if not settings.whatsapp_results_configured:
                print("whatsapp -> FAILED: results template is not configured")
                return 1
            result = send_results_whatsapp(
                voter_name=TEST_VOTER,
                election_title=TEST_ELECTION,
                results_url=f"{settings.app_origin.rstrip('/')}/results",
                destination=args.to_whatsapp,
            )
        print(
            f"whatsapp {args.whatsapp_template} -> {mask_phone(args.to_whatsapp)}: "
            f"{'sent ' + (result.provider_message_id or '') if result.status == 'sent' else 'FAILED: ' + (result.error or 'unknown error')}"
        )
        failures += 0 if result.status == "sent" else 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
