"""Staff authentication: password login, optional TOTP MFA, session profile."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, current_roles, get_current_profile, record_audit, roles_for, utcnow
from ..models import Profile
from ..schemas import LoginRequest, MfaActivateRequest
from ..security import (
    ROLE_NAMES,
    create_access_token,
    hash_password,
    new_totp_secret,
    permissions_for,
    verify_password,
    verify_totp,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def profile_payload(db: Session, profile: Profile) -> dict:
    roles = roles_for(db, profile.id)
    return {
        "id": profile.id,
        "email": profile.email,
        "full_name": profile.full_name,
        "roles": roles,
        "role_names": [ROLE_NAMES.get(r, r) for r in roles],
        "permissions": permissions_for(roles),
        "mfa_enabled": profile.mfa_enabled,
        "last_login_at": profile.last_login_at.isoformat() if profile.last_login_at else None,
    }


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    profile = db.execute(
        select(Profile).where(Profile.email == payload.email.strip().lower())
    ).scalar_one_or_none()
    if not profile or not verify_password(payload.password, profile.password_hash):
        record_audit(
            db, action="auth.login", outcome="failure", ip_address=client_ip(request),
            detail={"email": payload.email[:120], "reason": "invalid_credentials"},
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not profile.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been disabled")
    if profile.mfa_enabled:
        if not payload.totp_code:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA code required")
        if not verify_totp(profile.mfa_secret or "", payload.totp_code):
            record_audit(
                db, action="auth.mfa", outcome="failure", actor_id=profile.id,
                ip_address=client_ip(request), detail={"reason": "invalid_totp"},
            )
            db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA code")

    profile.last_login_at = utcnow()
    roles = roles_for(db, profile.id)
    record_audit(
        db, action="auth.login", actor_id=profile.id, actor_role=",".join(roles),
        ip_address=client_ip(request), entity="profile", entity_id=profile.id,
    )
    db.commit()
    return {
        "access_token": create_access_token(profile.id, roles),
        "token_type": "bearer",
        "profile": profile_payload(db, profile),
    }


@router.get("/me")
def me(profile: Profile = Depends(get_current_profile), db: Session = Depends(get_db)):
    return profile_payload(db, profile)


@router.post("/mfa/enroll")
def mfa_enroll(profile: Profile = Depends(get_current_profile)):
    secret = new_totp_secret()
    return {
        "secret": secret,
        "otpauth_url": (
            f"otpauth://totp/SJC%20Alumni%20Election:{profile.email}"
            f"?secret={secret}&issuer=SJC%20Alumni%20Election&digits=6&period=30"
        ),
        "instructions": "Scan or enter the secret in an authenticator app, then activate with a code.",
    }


@router.post("/mfa/activate")
def mfa_activate(
    payload: MfaActivateRequest,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
):
    if not verify_totp(payload.secret, payload.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid authenticator code")
    profile.mfa_secret = payload.secret
    profile.mfa_enabled = True
    record_audit(db, action="auth.mfa_enabled", actor_id=profile.id, entity="profile", entity_id=profile.id)
    db.commit()
    return {"mfa_enabled": True}


@router.get("/permissions")
def permissions(roles: list[str] = Depends(current_roles)):
    return {"roles": roles, "role_names": [ROLE_NAMES.get(r, r) for r in roles],
            "permissions": permissions_for(roles)}
