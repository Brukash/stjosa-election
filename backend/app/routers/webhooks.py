"""Provider callbacks.

The WhatsApp webhook receives Meta delivery-status updates and matches them to
the provider message id stored on a delivery attempt. It never receives or
returns an OTP. Requests are authenticated with Meta's HMAC signature.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import record_audit
from ..models import NotificationDelivery

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

WHATSAPP_STATUSES = {"sent", "delivered", "read", "failed"}
FAILURE_STATUSES = {"failed"}


@router.get("/whatsapp")
def verify_whatsapp_webhook(request: Request):
    """Meta's subscription handshake."""
    if not settings.whatsapp_verify_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp webhook is not configured")
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge", "")
    if mode == "subscribe" and token and hmac.compare_digest(token, settings.whatsapp_verify_token):
        return PlainTextResponse(challenge)
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Webhook verification failed")


def _valid_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not settings.whatsapp_app_secret or not signature_header:
        return False
    expected = "sha256=" + hmac.new(
        settings.whatsapp_app_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header.strip())


@router.post("/whatsapp")
async def whatsapp_status(
    request: Request,
    db: Session = Depends(get_db),
):
    """Apply delivery/read/failure statuses reported by Meta.

    The endpoint responds 200 for valid events that do not match a local row so
    Meta does not retry historical or unrelated messages indefinitely.
    """
    if not settings.whatsapp_app_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp webhook is not configured")
    raw_body = await request.body()
    if not _valid_signature(raw_body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid webhook signature")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid webhook payload") from exc

    updated = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for item in value.get("statuses") or []:
                provider_message_id = str(item.get("id") or "")
                reported = str(item.get("status") or "").lower()
                if not provider_message_id or reported not in WHATSAPP_STATUSES:
                    continue
                delivery = db.execute(
                    select(NotificationDelivery)
                    .where(
                        NotificationDelivery.provider_message_id == provider_message_id,
                        NotificationDelivery.channel == "whatsapp",
                    )
                    .order_by(NotificationDelivery.created_at.desc())
                ).scalars().first()
                if not delivery:
                    continue
                delivery.status = reported
                if reported in FAILURE_STATUSES:
                    errors = item.get("errors") or []
                    title = "WhatsApp delivery failed"
                    if errors and isinstance(errors[0], dict):
                        # Provider details can sometimes echo the recipient;
                        # store only the generic error title.
                        title = str(errors[0].get("title") or title)
                    delivery.error = title[:300]
                else:
                    delivery.error = None
                record_audit(
                    db,
                    action="otp.delivery_status",
                    election_id=delivery.election_id,
                    actor_role="whatsapp",
                    entity="notification_delivery",
                    entity_id=delivery.id,
                    outcome="failure" if reported in FAILURE_STATUSES else "success",
                    detail={"channel": "whatsapp", "status": reported},
                )
                updated += 1

    db.commit()
    return {"status": "ok", "updated": updated}
