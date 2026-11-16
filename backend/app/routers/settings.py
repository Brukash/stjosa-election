"""Technical delivery configuration visibility (Super Administrator)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import settings
from ..models import Profile
from ..deps import require_permission
from ..notifications import provider_status

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/delivery")
def delivery_settings(profile: Profile = Depends(require_permission("technical.settings"))):
    """Report provider readiness without returning credentials.

    Credentials remain backend environment variables by design. The Super
    Administrator configures them in the deployment secret store; this endpoint
    and the admin page expose only whether each provider is ready.
    """
    return {
        "providers": provider_status(),
        "delivery_mode": settings.delivery_mode,
        "environment": settings.environment,
        "whatsapp": {
            "official_platform": "Meta WhatsApp Business Platform (Cloud API)",
            "consent_required": True,
            "registration_template_name": settings.whatsapp_registration_template_name,
            "registration_template_language": settings.whatsapp_registration_template_language,
            "vote_confirmation_template_name": settings.whatsapp_vote_confirmation_template_name,
            "vote_confirmation_template_language": settings.whatsapp_vote_confirmation_template_language,
            "webhook_url": f"{settings.api_origin}/api/webhooks/whatsapp",
            "webhook_signed": bool(settings.whatsapp_app_secret),
        },
        "security_note": (
            "Provider secrets are read only from server-side environment variables. They are never "
            "returned by this endpoint, stored in the browser or written to delivery records."
        ),
    }
