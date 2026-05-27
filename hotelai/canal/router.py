"""
hotelai.canal.router
=====================

Endpoint del canal `web_chat` (simulador en facundobolani.com).

Flujo (Sprint 3+):
    1. POST /api/web-chat/inbound recibe payload del simulador.
    2. Sanitiza el texto.
    3. Resuelve/crea conversación.
    4. Persiste mensaje entrante.
    5. Construye envelope InboundMessage y llama al Concierge real (Claude).
    6. El Concierge decide y devuelve un OutboundMessage.
    7. Persistimos el saliente y respondemos al simulador.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..agents import concierge
from ..db import get_supabase
from ..schemas import (
    ACTIVE_CHANNELS,
    Channel,
    InboundMessage,
    TrustSignals,
)

logger = logging.getLogger("hotelai.canal")
router = APIRouter()


class WebChatInbound(BaseModel):
    conversation_id: str = Field(min_length=8, max_length=64)
    channel: str = Field(default="web_chat")
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("conversation_id")
    @classmethod
    def must_be_uuid(cls, v: str) -> str:
        try:
            UUID(v)
        except ValueError as exc:
            raise ValueError("conversation_id debe ser un UUID valido") from exc
        return v


class WebChatOutbound(BaseModel):
    text: str
    trace_id: str
    agent: str = Field(default="concierge")


_HTML_TAG = re.compile(r"<[^>]+>")
_MULTI_WS = re.compile(r"\s+")


def _sanitize_text(raw: str) -> str:
    text = _HTML_TAG.sub("", raw)
    text = _MULTI_WS.sub(" ", text).strip()
    return text[:2000]


def _ensure_conversation(conversation_id: str) -> None:
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
    get_supabase().table("messages").insert({
        "conversation_id": conversation_id,
        "trace_id": trace_id,
        "direction": "inbound",
        "role": "guest",
        "content": text,
        "raw_payload": raw_payload,
    }).execute()


def _persist_outbound(conversation_id: str, trace_id: str, text: str, agent: str) -> None:
    get_supabase().table("messages").insert({
        "conversation_id": conversation_id,
        "trace_id": trace_id,
        "direction": "outbound",
        "role": "agent",
        "agent_name": agent,
        "content": text,
    }).execute()


@router.post(
    "/inbound",
    response_model=WebChatOutbound,
    summary="Recibe un mensaje del simulador web (canal web_chat)",
)
async def inbound(payload: WebChatInbound) -> WebChatOutbound:
    if payload.channel != Channel.WEB_CHAT.value:
        raise HTTPException(400, f"Canal {payload.channel!r} no soportado por este endpoint.")
    if Channel.WEB_CHAT not in ACTIVE_CHANNELS:
        raise HTTPException(503, "Canal web_chat deshabilitado.")

    trace_id = uuid4()
    clean_text = _sanitize_text(payload.text)
    if not clean_text:
        raise HTTPException(400, "Texto vacio tras sanitizacion.")

    raw_payload = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "user_agent": "web_chat_simulator",
        "original_length": len(payload.text),
        "sanitized_length": len(clean_text),
    }

    try:
        _ensure_conversation(payload.conversation_id)
        _persist_inbound(payload.conversation_id, str(trace_id), clean_text, raw_payload)
    except Exception as exc:
        logger.exception("error persistiendo entrante (trace_id=%s): %s", trace_id, exc)
        raise HTTPException(502, "Error persistiendo mensaje.") from exc

    try:
        envelope = InboundMessage(
            trace_id=trace_id,
            conversation_id=UUID(payload.conversation_id),
            guest_id=None,
            channel=Channel.WEB_CHAT,
            raw_text=clean_text,
            metadata=raw_payload,
            trust=TrustSignals(
                channel_authenticated=True,
                identity_verified=False,
                matches_known_guest=False,
            ),
        )
        outbound = concierge.handle(envelope)
        reply_text = outbound.text
        agent_name = "concierge"
    except Exception as exc:
        logger.exception("concierge fallo trace=%s: %s", trace_id, exc)
        reply_text = (
            "Disculpa, tuve un problema procesando tu mensaje. "
            "Proba de nuevo en un momento."
        )
        agent_name = "system"

    try:
        _persist_outbound(payload.conversation_id, str(trace_id), reply_text, agent_name)
    except Exception as exc:
        logger.exception("error persistiendo saliente (trace_id=%s): %s", trace_id, exc)

    logger.info(
        "web_chat OK · trace=%s · conv=%s · in=%dch · out=%dch",
        trace_id, payload.conversation_id, len(clean_text), len(reply_text),
    )

    return WebChatOutbound(text=reply_text, trace_id=str(trace_id), agent=agent_name)
