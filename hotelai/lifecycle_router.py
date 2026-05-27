"""
hotelai.lifecycle_router
==========================

Endpoint para disparar triggers proactivos del agente Lifecycle.

Lo invoca un scheduler externo (cron de Render, GitHub Actions, etc.) con un
shared secret en el header `X-Trigger-Secret`. En esta etapa MVP no hay
scheduler interno — los triggers se disparan desde afuera.

Uso:
    POST /api/lifecycle/trigger
    X-Trigger-Secret: <WEB_CHAT_HMAC_SECRET>
    {
      "trigger": "pre_stay_t7",
      "guest_id": "uuid",
      "reservation_id": "uuid",
      "phase": "pre_stay"
    }
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .agents import lifecycle
from .schemas import GuestPhase, LifecycleTrigger, LifecycleTriggerKind
from .settings import settings

logger = logging.getLogger("hotelai.lifecycle_router")
router = APIRouter()


class TriggerRequest(BaseModel):
    trigger: str = Field(description="LifecycleTriggerKind value")
    guest_id: str
    reservation_id: str
    phase: str = Field(default="none")


@router.post(
    "/trigger",
    summary="Dispara un trigger proactivo del Lifecycle (scheduler externo)",
)
async def trigger_endpoint(
    payload: TriggerRequest,
    x_trigger_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    expected = settings.web_chat_hmac_secret.get_secret_value()
    if expected:
        if not x_trigger_secret or x_trigger_secret != expected:
            raise HTTPException(401, "X-Trigger-Secret invalid")
    # Si no hay secret configurado, dejamos pasar (modo dev). Es responsabilidad
    # del operador setear el secret en env vars antes de exponer públicamente.

    try:
        kind = LifecycleTriggerKind(payload.trigger)
    except ValueError:
        raise HTTPException(400, f"trigger inválido: {payload.trigger!r}")
    try:
        phase = GuestPhase(payload.phase)
    except ValueError:
        phase = GuestPhase.NONE

    try:
        envelope = LifecycleTrigger(
            trigger=kind,
            guest_id=UUID(payload.guest_id),
            reservation_id=UUID(payload.reservation_id),
            phase=phase,
        )
    except ValueError as exc:
        raise HTTPException(400, f"UUID inválido: {exc}") from exc

    try:
        result = lifecycle.handle_trigger(envelope)
    except Exception as exc:
        logger.exception("trigger %s falló: %s", kind.value, exc)
        raise HTTPException(500, f"trigger error: {type(exc).__name__}") from exc

    return {"trigger": kind.value, "trace_id": str(envelope.trace_id), **result}
