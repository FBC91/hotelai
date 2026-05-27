"""
hotelai.canal.router
=====================

Endpoint del canal `web_chat` (simulador de WhatsApp en facundobolani.com).

Flujo:
    1. POST /api/web-chat/inbound recibe el mensaje del simulador.
    2. Sanitiza el texto (strip, length cap, HTML escape básico).
    3. Resuelve/crea conversación en Supabase.
    4. Persiste mensaje entrante en `messages`.
    5. (Sprint 3+) Llama al Concierge real. Por ahora: mock determinístico.
    6. Persiste respuesta saliente en `messages`.
    7. Devuelve la respuesta al simulador.

Threat model relevante (ver 02-agente-canal/README.md):
    · K2: HTML/JS injection → `_sanitize_text` strip HTML.
    · K8: floods → rate limit (TODO Sprint 3).
    · K10: confusion attack → siempre respondemos por el mismo canal de origen.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..db import get_supabase
from ..schemas import ACTIVE_CHANNELS, Channel

logger = logging.getLogger("hotelai.canal")
router = APIRouter()


# =============================================================================
# Schemas request/response
# =============================================================================


class WebChatInbound(BaseModel):
    """Payload que envía el simulador en facundobolani.com/hotelia/."""

    conversation_id: str = Field(min_length=8, max_length=64)
    channel: str = Field(default="web_chat")
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("conversation_id")
    @classmethod
    def must_be_uuid(cls, v: str) -> str:
        try:
            UUID(v)
        except ValueError as exc:
            raise ValueError("conversation_id debe ser un UUID válido") from exc
        return v


class WebChatOutbound(BaseModel):
    """Respuesta del backend al simulador."""

    text: str
    trace_id: str
    agent: str = Field(default="canal", description="Agente que generó la respuesta.")


# =============================================================================
# Sanitización
# =============================================================================

_HTML_TAG = re.compile(r"<[^>]+>")
_MULTI_WS = re.compile(r"\s+")


def _sanitize_text(raw: str) -> str:
    """Strip HTML, normaliza whitespace, recorta a límite duro."""
    text = _HTML_TAG.sub("", raw)
    text = _MULTI_WS.sub(" ", text).strip()
    return text[:2000]


# =============================================================================
# Persistencia
# =============================================================================


def _ensure_conversation(conversation_id: str) -> None:
    """Crea la conversación si no existe (upsert idempotente).

    Para `web_chat` anónimo usamos el propio conversation_id como
    `external_identifier` (no tenemos phone/email todavía).
    """
    sb = get_supabase()
    sb.table("conversations").upsert(
        {
            "conversation_id": conversation_id,
            "external_identifier": conversation_id,
            "channel": Channel.WEB_CHAT.value,
            "state": "active",
            "current_phase": "none",
            "last_agent": "canal",
        },
        on_conflict="conversation_id",
        ignore_duplicates=True,
    ).execute()


def _persist_inbound(conversation_id: str, trace_id: str, text: str, raw_payload: dict) -> None:
    sb = get_supabase()
    sb.table("messages").insert(
        {
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "direction": "inbound",
            "role": "guest",
            "content": text,
            "raw_payload": raw_payload,
        }
    ).execute()


def _persist_outbound(conversation_id: str, trace_id: str, text: str, agent: str) -> None:
    sb = get_supabase()
    sb.table("messages").insert(
        {
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "direction": "outbound",
            "role": "agent",
            "agent_name": agent,
            "content": text,
        }
    ).execute()


# =============================================================================
# Concierge mock (placeholder — Sprint 3 lo reemplaza por Claude real)
# =============================================================================


def _mock_concierge(text: str) -> str:
    """Respuesta scripted hasta tener el Concierge LLM conectado.

    Lee `static_facts` cuando puede para responder con la versión persistida
    (no inventada). Demuestra que la cadena DB → backend → simulador funciona.
    """
    t = text.lower()
    sb = get_supabase()

    def fact(key: str, lang: str = "es") -> str | None:
        resp = sb.table("static_facts").select("values_by_lang").eq("fact_key", key).execute()
        if resp.data:
            return resp.data[0]["values_by_lang"].get(lang)
        return None

    if re.search(r"\b(hola|holaa|buenas|buen ?dia|buenos ?dias|hi|hello)\b", t):
        return "¡Hola! Soy el asistente del Hotel Bahía Serena. ¿En qué te puedo ayudar?"
    if re.search(r"\b(wifi|pass|clave|red)\b", t):
        ssid = fact("wifi_ssid") or "BahiaSerena_Guest"
        pwd = fact("wifi_password") or "BahiaSerena2026"
        return f"La red WiFi es **{ssid}** y la clave es **{pwd}** 📶"
    if re.search(r"check.?in|ingreso|llegada", t):
        return fact("checkin_time") or "El check-in es desde las 15:00 hs."
    if re.search(r"check.?out|salida", t):
        return fact("checkout_time") or "El check-out es hasta las 11:00 hs."
    if re.search(r"desayuno|breakfast", t):
        return fact("breakfast_hours") or "Desayuno de 7:00 a 10:30 hs."
    if re.search(r"direccion|donde|ubicacion|address", t):
        return fact("hotel_address") or "Av. Roosevelt y Parada 5, Punta del Este."
    if re.search(r"\b(reservar|reserva|disponibilidad|habitacion)\b", t):
        return (
            "¡Genial! Por ahora estoy en modo demo, pero te puedo confirmar que "
            "tenemos habitaciones desde USD 90/noche. Cuando el agente Reservas "
            "esté conectado (Sprint 4) vas a poder reservar directo desde acá."
        )
    return (
        "✅ Backend live. Recibí tu mensaje, lo guardé en Supabase y te respondo "
        "desde el endpoint real. El agente Concierge con Claude Sonnet 4.6 se "
        "conecta en Sprint 3 — por ahora soy un router básico."
    )


# =============================================================================
# Endpoint
# =============================================================================


@router.post(
    "/inbound",
    response_model=WebChatOutbound,
    summary="Recibe un mensaje del simulador web (canal web_chat)",
)
async def inbound(payload: WebChatInbound) -> WebChatOutbound:
    if payload.channel != Channel.WEB_CHAT.value:
        raise HTTPException(
            status_code=400,
            detail=f"Canal {payload.channel!r} no soportado por este endpoint.",
        )

    if Channel.WEB_CHAT not in ACTIVE_CHANNELS:
        raise HTTPException(status_code=503, detail="Canal web_chat deshabilitado.")

    trace_id = str(uuid4())
    clean_text = _sanitize_text(payload.text)
    if not clean_text:
        raise HTTPException(status_code=400, detail="Texto vacío tras sanitización.")

    raw_payload = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "user_agent": "web_chat_simulator",
        "original_length": len(payload.text),
        "sanitized_length": len(clean_text),
    }

    try:
        _ensure_conversation(payload.conversation_id)
        _persist_inbound(payload.conversation_id, trace_id, clean_text, raw_payload)
    except Exception as exc:
        logger.exception("error persistiendo entrante (trace_id=%s): %s", trace_id, exc)
        raise HTTPException(status_code=502, detail="Error persistiendo mensaje.") from exc

    # Sprint 3+ : reemplazar por Concierge real (LangGraph + Claude Sonnet 4.6)
    reply = _mock_concierge(clean_text)

    try:
        _persist_outbound(payload.conversation_id, trace_id, reply, agent="concierge")
    except Exception as exc:
        # Si falla la persistencia del outbound, devolvemos igual al user (no perder UX).
        logger.exception("error persistiendo saliente (trace_id=%s): %s", trace_id, exc)

    logger.info(
        "web_chat OK · trace=%s · conv=%s · in=%dch · out=%dch",
        trace_id, payload.conversation_id, len(clean_text), len(reply),
    )

    return WebChatOutbound(text=reply, trace_id=trace_id, agent="concierge")
