"""Unit tests for WhatsApp delivery through Termii's template endpoint.

Runs the real notification helpers against a local mock of Termii's
``/api/send/template`` endpoint. No real credentials are used, no message is
sent and no database is touched.

Run:  .venv/Scripts/python.exe scripts/test_whatsapp_termii.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="sjc-termii-whatsapp-test-"))
MOCK_BASE = "http://127.0.0.1:8898"

os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{TMP / 'test.db'}",
        "KEYS_DIR": str(TMP / "keys"),
        "ENVIRONMENT": "development",
        "APP_ORIGIN": "http://localhost:3000",
        "API_ORIGIN": "http://localhost:8000",
        "WHATSAPP_PROVIDER": "termii",
        "TERMII_API_KEY": "test-termii-key",
        "TERMII_API_BASE": MOCK_BASE,
        "TERMII_WHATSAPP_DEVICE_ID": "device-abc-123",
        "TERMII_WHATSAPP_OTP_TEMPLATE_ID": "tpl-otp-1",
        "TERMII_WHATSAPP_REGISTRATION_TEMPLATE_ID": "tpl-reg-2",
        "TERMII_WHATSAPP_VOTE_CONFIRMATION_TEMPLATE_ID": "tpl-vote-3",
        "TERMII_WHATSAPP_RESULTS_TEMPLATE_ID": "tpl-results-4",
        # Meta credentials stay unset: the Termii path must not need them.
        "WHATSAPP_ACCESS_TOKEN": "",
        "WHATSAPP_PHONE_NUMBER_ID": "",
        "WHATSAPP_REGISTRATION_TEMPLATE_NAME": "",
        "WHATSAPP_REGISTRATION_TEMPLATE_LANGUAGE": "",
        "WHATSAPP_VOTE_CONFIRMATION_TEMPLATE_NAME": "",
        "WHATSAPP_RESULTS_TEMPLATE_NAME": "",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.notifications import (  # noqa: E402
    _send_termii_whatsapp,
    _send_whatsapp,
    _termii_whatsapp_result,
    provider_status,
    send_registration_whatsapp,
    send_results_whatsapp,
    send_vote_confirmation_whatsapp,
    whatsapp_template_language,
)

CAPTURED: list[dict] = []
PASSED: list[str] = []

VOTER = "Adaeze Okafor"
ELECTION = "SJC Jos Alumni Association Election 2026"
VOTER_ID = "SJC/AL/2004/001"
SUBMITTED = "19 Nov 2026, 21:42"
RESULTS_URL = "http://localhost:3000/results"
DESTINATION = "+2348012345678"
DIGITS = "2348012345678"


def ok(label: str) -> None:
    PASSED.append(label)
    print(f"  PASS  {label}")


class MockTermii(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        payload = json.loads(raw or "{}")
        CAPTURED.append(
            {
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "payload": payload,
            }
        )
        if payload.get("template_id") == "tpl-rejected":
            body = json.dumps({"code": "400", "message": "template not approved"}).encode()
            self.send_response(400)
        else:
            body = json.dumps(
                {
                    "code": "ok",
                    "balance": 5013.4,
                    "message_id": f"termii-wa-{len(CAPTURED)}",
                    "message": "Successfully Sent",
                }
            ).encode()
            self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence request logging
        return


def only_call(start: int) -> dict:
    new = CAPTURED[start:]
    assert len(new) == 1, [call["path"] for call in new]
    return new[0]


def whatsapp_status() -> dict:
    matches = [item for item in provider_status() if item["channel"] == "whatsapp"]
    assert len(matches) == 1, matches
    return matches[0]


def test_configuration() -> None:
    assert settings.whatsapp_provider_key == "termii"
    assert settings.whatsapp_configured is True
    assert settings.whatsapp_registration_configured is True
    assert settings.whatsapp_vote_confirmation_configured is True
    assert settings.whatsapp_results_configured is True
    status = whatsapp_status()
    assert status["provider"] == "termii"
    assert status["configured"] is True
    assert status["template"] == "tpl-reg-2"
    assert status["template_language"] == ""
    assert "TERMII_WHATSAPP_DEVICE_ID" in status["required_settings"]
    assert "WHATSAPP_ACCESS_TOKEN" not in status["required_settings"]
    ok("termii reports every purpose configured from its own device and template ids")


def test_otp_template() -> None:
    start = len(CAPTURED)
    message_id, error = _send_whatsapp(DESTINATION, "483920")
    assert error is None, error
    assert message_id == f"termii-wa-{len(CAPTURED)}"
    call = only_call(start)
    assert call["path"] == "/api/send/template"
    assert "authorization" not in call["headers"]
    assert call["payload"] == {
        "api_key": "test-termii-key",
        "phone_number": DIGITS,
        "device_id": "device-abc-123",
        "template_id": "tpl-otp-1",
        "data": {"1": "483920"},
    }
    ok("the OTP uses the Termii template id with the code as its only variable")


def test_registration_template() -> None:
    start = len(CAPTURED)
    result = send_registration_whatsapp(
        voter_name=VOTER,
        voter_id=VOTER_ID,
        election_title=ELECTION,
        destination=DESTINATION,
    )
    assert result.status == "sent", result.error
    assert result.provider == "termii"
    assert result.channel == "whatsapp"
    call = only_call(start)
    assert call["path"] == "/api/send/template"
    assert "authorization" not in call["headers"]
    assert call["payload"]["template_id"] == "tpl-reg-2"
    assert call["payload"]["phone_number"] == DIGITS
    assert call["payload"]["device_id"] == "device-abc-123"
    assert call["payload"]["data"] == {"1": VOTER, "2": ELECTION, "3": VOTER_ID}
    ok("registration sends the approved template with name, election and Voter ID in order")


def test_vote_confirmation_template() -> None:
    start = len(CAPTURED)
    result = send_vote_confirmation_whatsapp(
        voter_name=VOTER,
        election_title=ELECTION,
        submitted_label=SUBMITTED,
        destination=DESTINATION,
    )
    assert result.status == "sent", result.error
    assert result.provider == "termii"
    call = only_call(start)
    assert call["payload"]["template_id"] == "tpl-vote-3"
    assert call["payload"]["data"] == {"1": VOTER, "2": ELECTION, "3": SUBMITTED}
    ok("vote confirmation sends its own template with the submission time")


def test_results_template() -> None:
    start = len(CAPTURED)
    result = send_results_whatsapp(
        voter_name=VOTER,
        election_title=ELECTION,
        results_url=RESULTS_URL,
        destination=DESTINATION,
    )
    assert result.status == "sent", result.error
    assert result.provider == "termii"
    call = only_call(start)
    assert call["payload"]["template_id"] == "tpl-results-4"
    assert call["payload"]["data"] == {"1": VOTER, "2": ELECTION, "3": RESULTS_URL}
    ok("declared results send their own template with the results link")


def test_rejected_template() -> None:
    original = settings.termii_whatsapp_registration_template_id
    settings.termii_whatsapp_registration_template_id = "tpl-rejected"
    start = len(CAPTURED)
    try:
        result = _termii_whatsapp_result("registration", [VOTER], DESTINATION)
    finally:
        settings.termii_whatsapp_registration_template_id = original
    assert result.status == "failed", result
    assert result.error == "whatsapp provider rejected the message (400)"
    assert len(CAPTURED) == start + 1, "a 4xx rejection must not be retried"
    ok("a rejected template is reported as failed without retrying")


def test_missing_template_id() -> None:
    start = len(CAPTURED)
    message_id, error = _send_termii_whatsapp(DESTINATION, "", [VOTER])
    assert message_id is None
    assert error == "whatsapp template id is not configured for this notice"
    assert len(CAPTURED) == start, "a missing template id must not call Termii"
    ok("a missing template id fails before any HTTP call")


def test_meta_template_languages_stay_per_purpose() -> None:
    original_provider = settings.whatsapp_provider
    original = (
        settings.whatsapp_registration_template_language,
        settings.whatsapp_vote_confirmation_template_language,
        settings.whatsapp_results_template_language,
    )
    settings.whatsapp_provider = "meta"
    settings.whatsapp_registration_template_language = "en_US"
    settings.whatsapp_vote_confirmation_template_language = "en_GB"
    settings.whatsapp_results_template_language = "fr"
    try:
        assert whatsapp_template_language("registration") == "en_US"
        assert whatsapp_template_language("vote_confirmation") == "en_GB"
        assert whatsapp_template_language("results") == "fr"
    finally:
        settings.whatsapp_provider = original_provider
        (
            settings.whatsapp_registration_template_language,
            settings.whatsapp_vote_confirmation_template_language,
            settings.whatsapp_results_template_language,
        ) = original
    assert whatsapp_template_language("results") == ""
    ok("each Meta template keeps its own language and Termii reports none")


def test_missing_device_id() -> None:
    original = settings.termii_whatsapp_device_id
    settings.termii_whatsapp_device_id = ""
    try:
        assert settings.whatsapp_configured is False
        assert settings.whatsapp_registration_configured is False
        assert whatsapp_status()["configured"] is False
    finally:
        settings.termii_whatsapp_device_id = original
    assert settings.whatsapp_configured is True
    ok("WhatsApp is not ready until the Termii device id is set")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8898), MockTermii)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        test_configuration()
        test_otp_template()
        test_registration_template()
        test_vote_confirmation_template()
        test_results_template()
        test_rejected_template()
        test_missing_template_id()
        test_meta_template_languages_stay_per_purpose()
        test_missing_device_id()
    finally:
        server.shutdown()
    print(f"\n{len(PASSED)} checks passed")


if __name__ == "__main__":
    main()
