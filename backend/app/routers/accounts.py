"""Staff accounts and role assignment (Super Administrator)."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip, get_current_profile, record_audit, roles_for, require_permission
from ..models import Profile, Role, UserRole
from ..security import (
    PERMISSIONS,
    ROLE_DESCRIPTIONS,
    ROLE_NAMES,
    SUPER_ADMIN,
    hash_password,
    permissions_for,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class StaffCreate(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=12, max_length=128)
    roles: list[str] = Field(min_length=1)


class StaffUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    password: str | None = Field(default=None, min_length=12, max_length=128)
    is_active: bool | None = None
    roles: list[str] | None = None


def _validate_roles(db: Session, keys: list[str]) -> list[Role]:
    unique = sorted(set(keys))
    unknown = [key for key in unique if key not in ROLE_NAMES]
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown role(s): {', '.join(unknown)}",
        )
    if not unique:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one role is required")
    rows = db.execute(select(Role).where(Role.key.in_(unique))).scalars().all()
    if len(rows) != len(unique):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Role catalogue is incomplete")
    return list(rows)


def _active_super_admins(db: Session, exclude: str | None = None) -> int:
    statement = (
        select(func.count(func.distinct(Profile.id)))
        .select_from(Profile)
        .join(UserRole, UserRole.profile_id == Profile.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.key == SUPER_ADMIN, Profile.is_active.is_(True))
    )
    if exclude:
        statement = statement.where(Profile.id != exclude)
    return int(db.scalar(statement) or 0)


def _payload(db: Session, profile: Profile) -> dict:
    keys = roles_for(db, profile.id)
    return {
        "id": profile.id,
        "email": profile.email,
        "full_name": profile.full_name,
        "roles": keys,
        "role_names": [ROLE_NAMES.get(key, key) for key in keys],
        "permissions": permissions_for(keys),
        "is_active": profile.is_active,
        "mfa_enabled": profile.mfa_enabled,
        "last_login_at": profile.last_login_at.isoformat() if profile.last_login_at else None,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
    }


@router.get("/roles")
def role_catalogue(profile: Profile = Depends(get_current_profile)):
    """Role definitions and the permission matrix (authenticated staff)."""
    return {
        "roles": [
            {
                "key": key,
                "name": name,
                "description": ROLE_DESCRIPTIONS.get(key, ""),
                "permissions": sorted(PERMISSIONS.get(key, set())),
            }
            for key, name in ROLE_NAMES.items()
        ]
    }


@router.get("")
def list_accounts(
    profile: Profile = Depends(require_permission("accounts.manage")),
    db: Session = Depends(get_db),
):
    profiles = db.execute(select(Profile).order_by(Profile.created_at)).scalars().all()
    return {"accounts": [_payload(db, item) for item in profiles]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_account(
    payload: StaffCreate,
    request: Request,
    profile: Profile = Depends(require_permission("accounts.manage")),
    db: Session = Depends(get_db),
):
    email = payload.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a valid email address")
    existing = db.execute(select(Profile).where(Profile.email == email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists")
    role_rows = _validate_roles(db, payload.roles)

    account = Profile(
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(account)
    db.flush()
    for role in role_rows:
        db.add(UserRole(profile_id=account.id, role_id=role.id))
    record_audit(
        db,
        action="account.create",
        actor_id=profile.id,
        entity="profile",
        entity_id=account.id,
        ip_address=client_ip(request),
        detail={"email": email, "roles": [role.key for role in role_rows]},
    )
    db.commit()
    return _payload(db, account)


@router.patch("/{account_id}")
def update_account(
    account_id: str,
    payload: StaffUpdate,
    request: Request,
    profile: Profile = Depends(require_permission("accounts.manage")),
    db: Session = Depends(get_db),
):
    account = db.get(Profile, account_id)
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")

    current_roles = roles_for(db, account.id)
    role_rows: list[Role] | None = None
    if payload.roles is not None:
        role_rows = _validate_roles(db, payload.roles)

    if account.id == profile.id and payload.is_active is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate your own account")
    removing_super_admin = (
        SUPER_ADMIN in current_roles
        and (
            payload.is_active is False
            or (role_rows is not None and SUPER_ADMIN not in {role.key for role in role_rows})
        )
    )
    if removing_super_admin and _active_super_admins(db, exclude=account.id) == 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "At least one active Super Administrator must remain",
        )

    if payload.full_name is not None:
        account.full_name = payload.full_name.strip()
    if payload.is_active is not None:
        account.is_active = payload.is_active
    if payload.password is not None:
        account.password_hash = hash_password(payload.password)
    if role_rows is not None:
        db.execute(delete(UserRole).where(UserRole.profile_id == account.id))
        for role in role_rows:
            db.add(UserRole(profile_id=account.id, role_id=role.id))

    changes: dict = {}
    if payload.full_name is not None:
        changes["full_name"] = account.full_name
    if payload.is_active is not None:
        changes["is_active"] = account.is_active
    if payload.password is not None:
        changes["password"] = "reset"
    if role_rows is not None:
        changes["roles"] = sorted(role.key for role in role_rows)
    record_audit(
        db,
        action="account.update",
        actor_id=profile.id,
        entity="profile",
        entity_id=account.id,
        ip_address=client_ip(request),
        detail=changes,
    )
    db.commit()
    return _payload(db, account)
