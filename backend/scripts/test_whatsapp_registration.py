"""Send one registration WhatsApp utility notice without touching the register.

Usage:
    python scripts/test_whatsapp_registration.py --to +2348012345678 --consented

The command reads WHATSAPP_* credentials from the process environment or the
backend ``.env`` file. It uses the exact same payload builder as registration
approval, but it opens no database session and writes no voter or delivery
records. Only a masked recipient and the provider message id are printed.

Only pass ``--consented`` after confirming the destination has a recorded
WhatsApp opt-in. This sends a real, billable WhatsApp message.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.notifications import (  # noqa: E402
    _normalise_phone,
    mask_phone,
    send_registration_whatsapp,
    whatsapp_template_reference,
)

EXPECTED_TEMPLATE = "sjc_registration_confirmation"
EXPECTED_LANGUAGE = "en_US"


def _missing_settings() -> list[str]:
    """Termii needs its own device and template ids; Meta needs its token pair."""
    missing: list[str] = []
    if settings.whatsapp_provider_key == "termii":
        if not settings.termii_api_key:
            missing.append("TERMII_API_KEY")
        if not settings.termii_whatsapp_device_id:
            missing.append("TERMII_WHATSAPP_DEVICE_ID")
        if not settings.termii_whatsapp_registration_template_id:
            missing.append("TERMII_WHATSAPP_REGISTRATION_TEMPLATE_ID")
        return missing
    if settings.whatsapp_provider_key != "meta":
        missing.append("WHATSAPP_PROVIDER=meta or termii")
    if not settings.whatsapp_access_token:
        missing.append("WHATSAPP_ACCESS_TOKEN")
    if not settings.whatsapp_phone_number_id:
        missing.append("WHATSAPP_PHONE_NUMBER_ID")
    if not settings.whatsapp_registration_template_name:
        missing.append("WHATSAPP_REGISTRATION_TEMPLATE_NAME")
    if not settings.whatsapp_registration_template_language:
        missing.append("WHATSAPP_REGISTRATION_TEMPLATE_LANGUAGE")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Send the registration utility template to one consented number. "
            "This does not approve the register or write delivery records."
        )
    )
    parser.add_argument(
        "--to",
        required=True,
        help="Destination number in E.164 form, for example +2348012345678",
    )
    parser.add_argument(
        "--consented",
        action="store_true",
        help="Confirm this destination has a recorded WhatsApp opt-in",
    )
    parser.add_argument("--name", default="SJC Test Voter", help="Sample {{1}} value")
    parser.add_argument(
        "--election-title",
        default="SJC Jos Alumni Association Election 2026",
        help="Sample {{2}} value",
    )
    parser.add_argument(
        "--voter-id",
        default="SJC/AL/TEST/001",
        help="Sample {{3}} value",
    )
    args = parser.parse_args()

    if not args.consented:
        print(
            "Refusing to send: pass --consented only after confirming this number "
            "has recorded WhatsApp consent.",
            file=sys.stderr,
        )
        return 2

    destination = _normalise_phone(args.to)
    if not destination:
        print(
            "Invalid --to value. Use an international E.164 number, for example "
            "+2348012345678.",
            file=sys.stderr,
        )
        return 2

    missing = _missing_settings()
    if missing:
        print("WhatsApp registration delivery is not configured. Missing:", file=sys.stderr)
        for name in missing:
            print(f" - {name}", file=sys.stderr)
        return 2

    uses_meta = settings.whatsapp_provider_key == "meta"
    if uses_meta and settings.whatsapp_registration_template_name != EXPECTED_TEMPLATE:
        print(
            f"This test only uses {EXPECTED_TEMPLATE!r}; the configured template is "
            f"{settings.whatsapp_registration_template_name!r}.",
            file=sys.stderr,
        )
        return 2

    if uses_meta and settings.whatsapp_registration_template_language != EXPECTED_LANGUAGE:
        print(
            f"This test expects {EXPECTED_TEMPLATE!r} in {EXPECTED_LANGUAGE!r}; "
            f"the configured language is {settings.whatsapp_registration_template_language!r}.",
            file=sys.stderr,
        )
        return 2

    print("Registration WhatsApp test")
    print(f"provider: {settings.whatsapp_provider_key or 'none'}")
    print(f"template: {whatsapp_template_reference('registration')}")
    if uses_meta:
        print(f"language: {settings.whatsapp_registration_template_language}")
    print(f"recipient: {mask_phone(destination)}")

    result = send_registration_whatsapp(
        voter_name=args.name,
        voter_id=args.voter_id,
        election_title=args.election_title,
        destination=destination,
    )
    if result.status == "sent":
        suffix = f" message_id={result.provider_message_id}" if result.provider_message_id else ""
        print(f"result: sent{suffix}")
        return 0

    print(f"result: FAILED: {result.error or 'unknown error'}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
