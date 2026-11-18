"""End-to-end mock election against a running backend.

Exercises: accreditation (Voter ID + blinded credential), cast-as-intended challenge,
ballot casting and idempotent retry, credential reuse rejection, receipt + PDF,
commitment publication, dual-control counting, results declaration, audit report
and configuration freeze.

Run:  .venv/Scripts/python.exe scripts/smoke_test.py
"""
from __future__ import annotations

import json
import math
import os
import secrets
import sys

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, ".")
from app import crypto  # noqa: E402

# Point the run at another instance with SMOKE_BASE, so a throwaway database can
# be exercised without disturbing the development one.
BASE = os.getenv("SMOKE_BASE", "http://127.0.0.1:8000/api")
PASSED: list[str] = []


def ok(label: str) -> None:
    PASSED.append(label)
    print(f"  PASS  {label}")


def call(method: str, path: str, expected: int = 200, **kwargs):
    response = httpx.request(method, BASE + path, timeout=120, **kwargs)
    if response.status_code != expected:
        raise AssertionError(
            f"{method} {path} expected {expected}, got {response.status_code}: {response.text[:800]}"
        )
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return response


def login(email: str, password: str = "ChangeMe!2026") -> dict:
    data = call("POST", "/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {data['access_token']}"}


def public_election() -> dict:
    data = call("GET", "/public/election")
    assert data["election"], "no active election"
    return data["election"]


def published_credential_key(election_id: str) -> tuple[int, int]:
    """The key a browser blinds with: what the API publishes, never a local file.

    Reading the key from this machine would hide the failure this test exists to
    catch, because a credential key that differs between processes is what
    makes an unblinded credential fail to verify.
    """
    data = call("GET", f"/crypto/{election_id}")
    key = data.get("credential")
    assert key, "the API published no credential issuer key"
    return int(key["n"], 16), int(key["e"], 16)


def issue_credential(election: dict, voter_id: str) -> dict:
    verified = call("POST", "/accreditation/verify-voter", json={
        "election_id": election["id"], "voter_id": voter_id,
    })
    assert verified["voter"]["voter_id"] == voter_id, "Voter ID verification returned another voter"
    reference = election["reference"]
    token_hex = secrets.token_hex(32)
    n, e = published_credential_key(election["id"])
    message_hash = crypto.fdh(crypto.credential_message(reference, token_hex), n)
    while True:
        blinding = secrets.randbelow(n - 2) + 2
        if math.gcd(blinding, n) == 1:
            break
    blinded = (message_hash * pow(blinding, e, n)) % n
    signed = call("POST", "/accreditation/credential", json={
        "accreditation_token": verified["accreditation_token"],
        "blinded_message": format(blinded, "x"),
    })
    issued = signed.get("credential_public_key") or {}
    assert issued.get("n") == format(n, "x"), (
        "the API signed the credential with a different key than the one it published"
    )
    unblinded = (int(signed["blind_signature"], 16) * pow(blinding, -1, n)) % n
    assert pow(unblinded, e, n) == message_hash, (
        "unblinded credential does not verify: the API signed with a different "
        "credential key than the one it published"
    )
    return {
        "token": token_hex,
        "signature": format(unblinded, "x"),
        "turnout_token": verified["turnout_token"],
    }


def selections_for(election: dict) -> dict:
    return {position["id"]: position["candidates"][0]["id"] for position in election["positions"]}


def prepare(election: dict, credential: dict, selections: dict) -> dict:
    return call("POST", "/voting/prepare", json={
        "election_id": election["id"], **credential, "selections": selections,
    })


def main() -> None:
    health = call("GET", "/health")
    ok(f"health check ({health['database']})")

    election = public_election()
    assert election["positions"] and election["positions"][0]["candidates"], "ballot is empty"
    ok(f"public election '{election['title']}' with {len(election['positions'])} positions")

    headers = {
        "chairman": login("chairman@sjcjos-alumni.org"),
        "returning": login("returning@sjcjos-alumni.org"),
        "observer": login("observer@sjcjos-alumni.org"),
        "accreditation": login("accreditation@sjcjos-alumni.org"),
        "super": login("superadmin@sjcjos-alumni.org"),
    }
    ok("all five staff roles authenticate")

    # ── 1. cast-as-intended challenge, then a fresh cast ballot ──────────────
    voter_a = "SJC/AL/2004/001"
    credential_a = issue_credential(election, voter_a)
    selections_a = selections_for(election)
    prepared_a = prepare(election, credential_a, selections_a)

    challenged = call("POST", f"/voting/{prepared_a['prepared_id']}/challenge", json=credential_a)
    material = challenged["verification_material"]
    data_key = crypto.b64d(material["data_key"])
    plaintext = AESGCM(data_key).decrypt(
        crypto.b64d(material["nonce"]), crypto.b64d(material["ciphertext"]),
        election["reference"].encode(),
    )
    revealed = json.loads(plaintext)["selections"]
    assert revealed == selections_a, "challenge proof decrypts to different selections"
    assert crypto.sha256_hex("SJC-KEY", election["reference"], material["data_key"]) == material["key_commitment"]
    assert crypto.ballot_commitment(
        election["reference"], material["nonce"], material["encrypted_key"], material["ciphertext"]
    ) == material["commitment"]
    ok("challenged ballot reveals cryptographic proof of the exact selections")

    blocked = httpx.post(f"{BASE}/voting/{prepared_a['prepared_id']}/cast", json=credential_a, timeout=60)
    assert blocked.status_code == 409, f"challenged ballot was cast: {blocked.status_code}"
    ok("challenged ballot is permanently excluded and cannot be cast")

    fresh = prepare(election, credential_a, selections_a)
    receipt_a = call("POST", f"/voting/{fresh['prepared_id']}/cast", json=credential_a)
    ok(f"fresh ballot cast; receipt {receipt_a['receipt_number']}")

    replay = call("POST", f"/voting/{fresh['prepared_id']}/cast", json=credential_a)
    assert replay["receipt_reference"] == receipt_a["receipt_reference"], "retry created a second receipt"
    ok("cast retry is idempotent (no duplicate accepted ballot)")

    duplicate_prepare = httpx.post(f"{BASE}/voting/prepare", json={
        "election_id": election["id"], **credential_a, "selections": selections_a,
    }, timeout=60)
    assert duplicate_prepare.status_code == 409, "spent credential was reusable"
    ok("credential reuse rejected")

    verification = call("GET", f"/verify/{receipt_a['receipt_reference']}")
    assert verification["found"] and verification["checks"]["ballot_recorded"]
    ok("receipt verification confirms the ballot is recorded")

    pdf = call("GET", f"/receipts/{receipt_a['receipt_reference']}/pdf")
    assert pdf.content[:4] == b"%PDF"
    ok("PDF receipt with QR code downloads")

    # ── 2. more voters cast ballots ──────────────────────────────────────────
    cast_receipts = [receipt_a["receipt_reference"]]
    for voter_id in ("SJC/AL/2005/003", "SJC/AL/2006/005"):
        credential = issue_credential(election, voter_id)
        prepared = prepare(election, credential, selections_for(election))
        receipt = call("POST", f"/voting/{prepared['prepared_id']}/cast", json=credential)
        cast_receipts.append(receipt["receipt_reference"])
    ok("multiple accredited voters cast encrypted ballots")

    # ── 3. configuration freeze ──────────────────────────────────────────────
    detail = call("GET", f"/elections/{election['id']}", headers=headers["chairman"])
    assert detail["locked_at"], "configuration did not lock after the first ballot"
    locked = httpx.put(f"{BASE}/elections/{election['id']}/verification-settings", json={
        "ballot_inclusion_enabled": False, "private_selection_enabled": False,
        "public_commitment_list_enabled": False, "pdf_receipt_enabled": False,
    }, headers=headers["chairman"], timeout=60)
    assert locked.status_code == 409, "verification settings changed after voting began"
    ok("verification settings are locked once voting starts")

    forbidden = httpx.post(f"{BASE}/elections/{election['id']}/status",
                           json={"status": "voting_closed"}, headers=headers["observer"], timeout=60)
    assert forbidden.status_code == 403, "observer could change the lifecycle"
    ok("observer is read-only (lifecycle change rejected)")

    # ── 4. close voting and publish commitments ──────────────────────────────
    call("POST", f"/elections/{election['id']}/status", json={"status": "voting_closed"},
         headers=headers["returning"])
    batches = call("GET", f"/commitments/{election['id']}")
    if not batches["batches"]:
        published = call("POST", f"/commitments/{election['id']}/publish", headers=headers["returning"])
        assert published["published"]
    batches = call("GET", f"/commitments/{election['id']}")
    assert batches["batches"] and batches["batches"][0]["signature_verified"]
    manifest = call("GET", batches["batches"][0]["download_url"].replace("/api", ""))
    assert len(manifest["commitments"]) >= len(cast_receipts)
    ok("signed anonymous commitment list published with Merkle proofs")

    # ── 5. counting authorisation ───────────────────────────────────────────
    premature = httpx.post(f"{BASE}/tally/{election['id']}/run", headers=headers["chairman"], timeout=60)
    assert premature.status_code == 403, "counting ran without authorisation"
    ok("counting blocked until it is authorised")

    call("POST", f"/tally/{election['id']}/authorise", headers=headers["chairman"])
    tally = call("POST", f"/tally/{election['id']}/run", headers=headers["chairman"])
    assert tally["totals"]["accepted_ballots"] == len(cast_receipts)
    assert tally["totals"]["accepted_ballots"] == tally["totals"]["valid_ballots"] + tally["totals"]["invalid_ballots"]
    assert tally["signature"] and tally["evidence_hash"]
    ok(f"count completed over {tally['totals']['accepted_ballots']} accepted ballots with signed evidence")

    inclusion = call("GET", f"/verify/{receipt_a['receipt_reference']}")
    assert inclusion["checks"]["merkle_verified"] and inclusion["checks"]["counted_in_tally"]
    assert inclusion["checks"]["signature_verified"]
    ok("voter verification shows Merkle inclusion and inclusion in the count")

    # ── 6. results declaration ──────────────────────────────────────────────
    call("POST", f"/results/{election['id']}/submit", headers=headers["returning"],
         json={"comments": "Provisional figures reconciled"})
    declared = call("POST", f"/results/{election['id']}/approve", headers=headers["chairman"])
    assert declared["signature_valid"] and declared["version"] == 1
    public = call("GET", f"/results/public/{election['id']}")
    assert public["published"] and public["signature_valid"]
    ok("official results declared, digitally signed and published")

    certificate = call("GET", f"/monitoring/{election['id']}/result-certificate.pdf")
    assert certificate.content[:4] == b"%PDF"
    ok("result certificate PDF generated")

    # ── 7. audit report ─────────────────────────────────────────────────────
    report = call("GET", f"/monitoring/{election['id']}/audit-report", headers=headers["observer"])
    failed = [check for check in report["checks"] if not check["passed"]]
    assert not failed, f"audit checks failed: {failed}"
    ok(f"post-election audit report passes {len(report['checks'])} checks")

    audit_pdf = call("GET", f"/monitoring/{election['id']}/audit-report.pdf", headers=headers["observer"])
    assert audit_pdf.content[:4] == b"%PDF"
    audit_xlsx = call("GET", f"/monitoring/{election['id']}/audit-report.xlsx", headers=headers["observer"])
    assert audit_xlsx.content[:2] == b"PK"
    ok("audit report exports to PDF and Excel")

    # ── 8. configuration module on a second election ────────────────────────
    new_election = call("POST", "/elections", headers=headers["chairman"], expected=201, json={
        "title": "St. John's College Jos Alumni Association Election 2027",
        "year": 2027,
        "reference": "SJCJ-ALUMNI-2027",
        "opens_at": "2027-03-01T08:00:00Z",
        "closes_at": "2027-03-15T20:00:00Z",
    })
    position = call("POST", f"/elections/{new_election['id']}/positions", headers=headers["chairman"],
                    expected=201, json={"title": "President", "seats": 1})
    call("POST", f"/elections/{new_election['id']}/candidates", headers=headers["chairman"],
         expected=201, json={"position_id": position["id"], "full_name": "Test Candidate"})
    call("PUT", f"/elections/{new_election['id']}/verification-settings", headers=headers["chairman"], json={
        "ballot_inclusion_enabled": True, "private_selection_enabled": True,
        "public_commitment_list_enabled": True, "pdf_receipt_enabled": True,
    })
    call("POST", f"/elections/{new_election['id']}/verification-settings/approve", headers=headers["chairman"])
    ok("verification settings approved by the presiding official")
    approved = call("POST", f"/elections/{new_election['id']}/configuration/approve", headers=headers["chairman"])
    assert approved["approved_now"] and approved["status"] == "approved"
    ok("second election configured and approved by the Chairman alone")

    # ── 9. roles and account administration ──────────────────────────────────
    superadmin = login("superadmin@sjcjos-alumni.org")
    headers["superadmin"] = superadmin
    catalogue = call("GET", "/accounts/roles", headers=superadmin)
    assert len(catalogue["roles"]) == 5
    assert {role["key"] for role in catalogue["roles"]} == {
        "super_admin", "chairman", "accreditation_officer", "returning_officer", "observer"
    }
    ok("role catalogue defines all five offices")

    accounts = call("GET", "/accounts", headers=superadmin)
    assert len(accounts["accounts"]) >= 5
    created = call("POST", "/accounts", expected=201, headers=superadmin, json={
        "email": "pilot.observer@sjcjos-alumni.org",
        "full_name": "Pilot Observer",
        "password": "PilotPass!2026x",
        "roles": ["observer"],
    })
    assert created["roles"] == ["observer"]
    observer_headers = login("pilot.observer@sjcjos-alumni.org", "PilotPass!2026x")
    assert "accounts.manage" not in call("GET", "/auth/me", headers=observer_headers)["permissions"]
    assert httpx.get(BASE + "/accounts", headers=observer_headers, timeout=60).status_code == 403
    assert httpx.get(BASE + "/accounts", headers=headers["chairman"], timeout=60).status_code == 403
    ok("Super Administrator creates accounts; other roles cannot manage them")

    updated = call("PATCH", f"/accounts/{created['id']}", headers=superadmin, json={
        "roles": ["observer", "accreditation_officer"]
    })
    assert set(updated["roles"]) == {"observer", "accreditation_officer"}
    super_id = call("GET", "/auth/me", headers=superadmin)["id"]
    last_super = httpx.patch(BASE + f"/accounts/{super_id}", headers=superadmin,
                             json={"roles": ["observer"]}, timeout=60)
    assert last_super.status_code == 409, last_super.text
    self_off = httpx.patch(BASE + f"/accounts/{super_id}", headers=superadmin,
                           json={"is_active": False}, timeout=60)
    assert self_off.status_code == 400, self_off.text
    ok("role changes are audited and the last Super Administrator is protected")

    # ── 10. read-side role boundaries ───────────────────────────────────────
    def status(path: str, who: str) -> int:
        return httpx.get(BASE + path, headers=headers[who], timeout=60).status_code

    assert status(f"/register/{election['id']}", "chairman") == 200
    assert status(f"/register/{election['id']}", "accreditation") == 200
    for who in ("superadmin", "returning", "observer"):
        assert status(f"/register/{election['id']}", who) == 403, who

    assert status(f"/tally/{election['id']}", "chairman") == 200
    assert status(f"/tally/{election['id']}", "returning") == 200
    for who in ("superadmin", "accreditation", "observer"):
        assert status(f"/tally/{election['id']}", who) == 403, who

    assert status(f"/results/{election['id']}", "chairman") == 200
    assert status(f"/results/{election['id']}", "returning") == 200
    assert status(f"/results/{election['id']}", "observer") == 200
    for who in ("superadmin", "accreditation"):
        assert status(f"/results/{election['id']}", who) == 403, who
    restricted = call("GET", f"/results/{election['id']}", headers=headers["observer"])
    assert restricted["provisional"] is None and restricted["approvals"] == []
    assert restricted["declarations"], "observer must still see declared results"
    full = call("GET", f"/results/{election['id']}", headers=headers["chairman"])
    assert full["provisional"] is not None and full["approvals"]

    limited_actions = {
        "voter.verify", "otp.request", "otp.deliver", "otp.verify",
        "credential.issued", "credential.revoked",
        "register.import", "register.voter_added", "register.eligibility", "register.approve",
    }
    limited = call("GET", f"/monitoring/{election['id']}/audit-logs?limit=200",
                   headers=headers["accreditation"])
    assert all(log["action"] in limited_actions for log in limited["logs"])
    full_logs = call("GET", f"/monitoring/{election['id']}/audit-logs?limit=200",
                     headers=headers["observer"])
    assert any(log["action"] not in limited_actions for log in full_logs["logs"])
    ok("read boundaries enforced across all five roles")

    print("\n" + "=" * 66)
    print(f"MOCK ELECTION PASSED: {len(PASSED)} checks")
    print("=" * 66)
    for label in PASSED:
        print(f"  • {label}")


if __name__ == "__main__":
    main()
