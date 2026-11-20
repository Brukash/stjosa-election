"""Authentication, OTP and role-based access control primitives."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone

import jwt

from .config import settings

# ── passwords (scrypt, stdlib) ───────────────────────────────────────────────
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return "scrypt$%d$%d$%d$%s$%s" % (
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(base64.b64decode(digest_b64)),
        )
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


# ── JWT ─────────────────────────────────────────────────────────────────────
def create_access_token(subject: str, roles: list[str]) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "roles": roles,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
        "iss": "sjc-alumni-election",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer="sjc-alumni-election",
        )
    except jwt.PyJWTError:
        return None


# ── TOTP MFA (RFC 6238, SHA-1, 6 digits, 30s step) ──────────────────────────
def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def totp_code(secret: str, at: float | None = None) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int((at or time.time()) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


def verify_totp(secret: str, code: str) -> bool:
    if not code or not code.isdigit():
        return False
    now = time.time()
    return any(hmac.compare_digest(totp_code(secret, now + step * 30), code) for step in (-1, 0, 1))


# ── One-time passwords ──────────────────────────────────────────────────────
def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def otp_digest(challenge_id: str, otp: str) -> str:
    return hmac.new(
        settings.otp_pepper.encode(),
        f"{challenge_id}|{otp}".encode(),
        hashlib.sha256,
    ).hexdigest()


def otp_matches(challenge_id: str, otp: str, stored_hash: str) -> bool:
    return hmac.compare_digest(otp_digest(challenge_id, otp.strip()), stored_hash)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ── roles and permission matrix (SRS §13) ───────────────────────────────────
SUPER_ADMIN = "super_admin"
CHAIRMAN = "chairman"
ACCREDITATION = "accreditation_officer"
OBSERVER = "observer"

ROLE_NAMES = {
    SUPER_ADMIN: "Super Administrator",
    CHAIRMAN: "Electoral Committee Chairman",
    ACCREDITATION: "Accreditation Officer",
    OBSERVER: "Election Observer",
}

ROLE_RANK = {SUPER_ADMIN: 0, CHAIRMAN: 1, ACCREDITATION: 2, OBSERVER: 3}

ROLE_DESCRIPTIONS = {
    SUPER_ADMIN: (
        "Technical custodian. Manages staff accounts and role assignments, monitors system health "
        "and technical audit records. Cannot configure an election, approve results or see ballots."
    ),
    CHAIRMAN: (
        "Electoral Committee Chairman. Conducts the election end to end: creates and configures it, "
        "approves the register and verification settings, authorises and runs the count, and submits, "
        "approves and publishes the result."
    ),
    ACCREDITATION: (
        "Accreditation Officer. Imports the voter register, supports Voter ID accreditation and "
        "credential exceptions, and monitors participation. No ballot, tally, result or account access."
    ),
    OBSERVER: (
        "Election Observer. Read-only oversight of monitoring, published commitments, declared "
        "results and audit records. Cannot change any election data."
    ),
}

PERMISSIONS: dict[str, set[str]] = {
    SUPER_ADMIN: {
        "technical.settings", "election.create", "election.view", "monitor.view",
        "commitments.view", "audit.view_technical", "accounts.manage",
    },
    CHAIRMAN: {
        "election.create", "election.edit", "election.approve", "election.view",
        "register.view", "register.import", "register.approve", "verification.configure",
        "verification.approve", "monitor.view", "ballot.view_public",
        "counting.authorise", "counting.run", "tally.view", "results.review", "results.submit",
        "results.approve",
        "results.publish",
        "audit.view", "accreditation.oversight", "commitments.view", "lifecycle.manage",
    },
    ACCREDITATION: {
        "election.view", "register.view", "register.import", "accreditation.manage",
        "accreditation.oversight", "monitor.view", "commitments.view", "audit.view_limited",
    },
    OBSERVER: {
        "election.view", "monitor.view", "results.review_restricted", "audit.view",
        "commitments.view", "ballot.view_public", "verification.view",
    },
}


def permissions_for(roles: list[str]) -> list[str]:
    granted: set[str] = set()
    for role in roles:
        granted |= PERMISSIONS.get(role, set())
    return sorted(granted)


def has_permission(roles: list[str], permission: str) -> bool:
    return permission in permissions_for(roles)
