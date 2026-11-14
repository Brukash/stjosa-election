"""FastAPI dependencies: database session, current staff account, RBAC, auditing."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, Profile, Role, UserRole
from .security import decode_access_token, has_permission


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def roles_for(db: Session, profile_id: str) -> list[str]:
    rows = db.execute(
        select(Role.key).join(UserRole, UserRole.role_id == Role.id).where(
            UserRole.profile_id == profile_id
        )
    ).scalars().all()
    return sorted(set(rows))


def get_current_profile(request: Request, db: Session = Depends(get_db)) -> Profile:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    payload = decode_access_token(auth.split(" ", 1)[1].strip())
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    profile = db.get(Profile, payload.get("sub"))
    if not profile or not profile.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is not active")
    return profile


def current_roles(profile: Profile = Depends(get_current_profile), db: Session = Depends(get_db)) -> list[str]:
    return roles_for(db, profile.id)


def require_permission(permission: str) -> Callable:
    def dependency(
        profile: Profile = Depends(get_current_profile),
        roles: list[str] = Depends(current_roles),
    ) -> Profile:
        if not has_permission(roles, permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role {', '.join(roles) or 'none'} cannot perform '{permission}'",
            )
        return profile

    return dependency


def require_any_permission(*permissions: str) -> Callable:
    def dependency(
        profile: Profile = Depends(get_current_profile),
        roles: list[str] = Depends(current_roles),
    ) -> Profile:
        if not any(has_permission(roles, permission) for permission in permissions):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this resource")
        return profile

    return dependency


def record_audit(
    db: Session,
    *,
    action: str,
    election_id: str | None = None,
    actor_id: str | None = None,
    actor_role: str | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    outcome: str = "success",
    ip_address: str | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            election_id=election_id,
            actor_id=actor_id,
            actor_role=actor_role,
            entity=entity,
            entity_id=entity_id,
            outcome=outcome,
            ip_address=ip_address,
            detail=detail or {},
        )
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value):
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
