"""
hotelai.email_router
=====================

Endpoints del canal `email` (simulador en /hotelia/email/).

Dos endpoints:
    POST /api/email/inbound  → mensaje entrante del simulador
    GET  /api/email/inbox    → polling: trae historial de la casilla del huesped

A diferencia del canal web_chat (anonimo, identifica por conversation_id), el
canal email identifica al huesped por su DIRECCION DE EMAIL. Esto permite que
los triggers proactivos del Lifecycle alcancen al huesped sin que tenga la
pestana abierta.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from .canal.handler import process_inbound
from .db import get_supabase
from .schemas import ACTIVE_CHANNELS, Channel

logger = logging.getLogger("hotelai.email")
router = APIRouter()

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class EmailInbound(BaseModel):
    email: str = Field(description="Email del huesped (usado como identidad)")
    subject: str = Field(default="(sin asunto)", max_length=200)
    body: str = Field(min_length=1, max_length=5000)


class EmailOutbound(BaseModel):
    text: str
    trace_id: str
    agent: str


class InboxMessage(BaseModel):
    direction: str
    role: str
    agent: str | None = None
    content: str
    timestamp: str


class InboxResponse(BaseModel):
    email: str
    guest_id: str | None
    conversation_id: str | None
    messages: list[InboxMessage]


# =============================================================================
# Helpers
# =============================================================================


def _validate_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "email invalido")
    return email


def _find_or_create_email_conversation(email: str) -> dict[str, Any]:
    """
    Encuentra o crea la conversación email del huésped.
    Si el guest no existe (sin contacto previo), lo crea con ese email.
    Devuelve {"guest_id", "conversation_id"}.
    """
    sb = get_supabase()

    # 1. Buscar guest por email
    g_resp = sb.table("guests").select("*").eq("email", email).limit(1).execute()
    if g_resp.data:
        guest = g_resp.data[0]
    else:
        # Crear guest minimal con solo email
        g_new = sb.table("guests").insert({
            "email": email,
            "language_pref": "es",
            "consent_marketing": False,
        }).execute()
        guest = g_new.data[0]
        logger.info("creado guest %s para email %s", guest["guest_id"][:8], email)

    # 2. Conversación email activa
    c_resp = sb.table("conversations").select("*") \
        .eq("guest_id", guest["guest_id"]).eq("channel", "email") \
        .in_("state", ["active", "awaiting_payment"]) \
        .order("updated_at", desc=True).limit(1).execute()
    if c_resp.data:
        return {"guest_id": guest["guest_id"],
                "conversation_id": c_resp.data[0]["conversation_id"]}

    conv_id = str(uuid4())
    sb.table("conversations").insert({
        "conversation_id": conv_id,
        "guest_id": guest["guest_id"],
        "external_identifier": email,
        "channel": "email",
        "state": "active",
        "current_phase": "none",
    }).execute()
    logger.info("creada email conversation %s para guest %s",
                 conv_id[:8], guest["guest_id"][:8])
    return {"guest_id": guest["guest_id"], "conversation_id": conv_id}


# =============================================================================
# POST /api/email/inbound
# =============================================================================


@router.post(
    "/inbound",
    response_model=EmailOutbound,
    summary="Recibe un email del simulador (canal email)",
)
async def email_inbound(payload: EmailInbound) -> EmailOutbound:
    if Channel.EMAIL not in ACTIVE_CHANNELS:
        raise HTTPException(503, "Canal email deshabilitado.")

    email = _validate_email(payload.email)
    conv = _find_or_create_email_conversation(email)

    # Incluimos el subject en el texto que ve el Concierge
    full_text = f"{payload.subject.strip()}\n\n{payload.body}".strip()

    result = process_inbound(
        channel=Channel.EMAIL,
        conversation_id=conv["conversation_id"],
        text=full_text,
        external_identifier=email,
    )
    return EmailOutbound(**result)


# =============================================================================
# GET /api/email/inbox?email=...
# =============================================================================


@router.get(
    "/inbox",
    response_model=InboxResponse,
    summary="Trae el historial de la casilla email del huesped",
)
async def email_inbox(email: str) -> InboxResponse:
    email_clean = _validate_email(email)
    sb = get_supabase()

    g_resp = sb.table("guests").select("guest_id").eq("email", email_clean).limit(1).execute()
    if not g_resp.data:
        return InboxResponse(email=email_clean, guest_id=None, conversation_id=None, messages=[])
    guest_id = g_resp.data[0]["guest_id"]

    # Buscar la conversación email más reciente del guest
    c_resp = sb.table("conversations").select("conversation_id") \
        .eq("guest_id", guest_id).eq("channel", "email") \
        .order("updated_at", desc=True).limit(1).execute()
    if not c_resp.data:
        return InboxResponse(email=email_clean, guest_id=guest_id, conversation_id=None, messages=[])
    conv_id = c_resp.data[0]["conversation_id"]

    m_resp = sb.table("messages").select("direction, role, agent_name, content, created_at") \
        .eq("conversation_id", conv_id).order("created_at").execute()
    msgs = [
        InboxMessage(
            direction=m["direction"],
            role=m["role"],
            agent=m.get("agent_name"),
            content=m["content"],
            timestamp=m["created_at"],
        )
        for m in (m_resp.data or [])
    ]
    return InboxResponse(
        email=email_clean,
        guest_id=guest_id,
        conversation_id=conv_id,
        messages=msgs,
    )
