"""
hotelai.canal.handler
======================

Lógica compartida entre los canales activos (web_chat y email).

Auto-captura inteligente de contacto: si el mensaje contiene un email
(formato RFC), upsertea el guest y lo asocia a la conversación.
Esto permite que un mismo guest sea reconocido entre canales.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from ..agents import concierge
from ..agents.tools import db_tools as t
from ..db import get_supabase
from ..schemas import Channel, InboundMessage, TrustSignals

logger = logging.getLogger("hotelai.handler")


_HTML_TAG = re.compile(r"<[^>]+>")
_MULTI_WS = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# E.164 ish — opcional +, 8 a 15 dígitos
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,18}\d")


def sanitize_text(raw: str) -> str:
    text = _HTML_TAG.sub("", raw)
    text = _MULTI_WS.sub(" ", text).strip()
    return text[:2000]


def extract_contact(text: str) -> dict[str, str | None]:
    """Devuelve {'email': str|None, 'phone': str|None} extraído del texto."""
    email_m = _EMAIL_RE.search(text)
    phone_m = _PHONE_RE.search(text)
    email = email_m.group(0).lower() if email_m else None
    # Limpiar phone (sacar espacios y guiones internos)
    phone = None
    if phone_m:
        raw_phone = phone_m.group(0)
        cleaned = re.sub(r"[\s\-()]", "", raw_phone)
        # Filtros: descartar números que parecen códigos de reserva o años
        if 8 <= len(cleaned.lstrip("+")) <= 15 and not cleaned.startswith("19") and not cleaned.startswith("20"):
            phone = cleaned
    return {"email": email, "phone": phone}


def ensure_conversation(
    conversation_id: str,
    channel: Channel,
    external_identifier: str | None = None,
) -> None:
    """Upsert idempotente de la conversación."""
    sb = get_supabase()
    sb.table("conversations").upsert(
        {
            "conversation_id": conversation_id,
            "external_identifier": external_identifier or conversation_id,
            "channel": channel.value,
            "state": "active",
            "current_phase": "none",
            "last_agent": "canal",
        },
        on_conflict="conversation_id",
        ignore_duplicates=True,
    ).execute()


def auto_capture_contact(conversation_id: str, text: str) -> dict | None:
    """
    Si el texto contiene email/phone:
    - Si la conversación no tiene guest asociado: upsert_guest + attach.
    - Si lo tiene pero al guest le falta email/phone: completa el dato.
    Devuelve el guest actualizado o None.
    """
    contact = extract_contact(text)
    email, phone = contact["email"], contact["phone"]
    if not email and not phone:
        return None

    sb = get_supabase()
    conv = sb.table("conversations").select("guest_id", "external_identifier") \
        .eq("conversation_id", conversation_id).limit(1).execute()
    if not conv.data:
        return None
    current_guest_id = conv.data[0].get("guest_id")

    if current_guest_id:
        # Completar campos faltantes
        g = sb.table("guests").select("*").eq("guest_id", current_guest_id).limit(1).execute()
        if not g.data:
            return None
        guest = g.data[0]
        updates = {}
        if email and not guest.get("email"):
            updates["email"] = email
        if phone and not guest.get("phone"):
            updates["phone"] = phone
        if updates:
            sb.table("guests").update(updates).eq("guest_id", current_guest_id).execute()
            guest.update(updates)
            logger.info("auto_capture · guest %s actualizado con %s",
                         current_guest_id[:8], list(updates.keys()))
        return guest

    # No hay guest. Crear/encontrar por email o phone.
    guest = t.upsert_guest(email=email, phone=phone)
    t.attach_guest_to_conversation(conversation_id, guest["guest_id"])
    logger.info("auto_capture · guest %s asociado a conv %s",
                 guest["guest_id"][:8], conversation_id[:8])
    return guest


def persist_inbound(conversation_id: str, trace_id: str, text: str,
                     raw_payload: dict) -> None:
    get_supabase().table("messages").insert({
        "conversation_id": conversation_id,
        "trace_id": trace_id,
        "direction": "inbound",
        "role": "guest",
        "content": text,
        "raw_payload": raw_payload,
    }).execute()


def persist_outbound(conversation_id: str, trace_id: str, text: str, agent: str) -> None:
    get_supabase().table("messages").insert({
        "conversation_id": conversation_id,
        "trace_id": trace_id,
        "direction": "outbound",
        "role": "agent",
        "agent_name": agent,
        "content": text,
    }).execute()


def process_inbound(
    channel: Channel,
    conversation_id: str,
    text: str,
    external_identifier: str | None = None,
) -> dict:
    """
    Pipeline unificado para cualquier canal entrante:
        sanitize → ensure_conversation → persist inbound → auto_capture
        → Concierge → persist outbound → return reply

    Devuelve {"text": str, "trace_id": str, "agent": str}.
    """
    trace_id = uuid4()
    clean_text = sanitize_text(text)
    if not clean_text:
        return {"text": "(mensaje vacío tras sanitización)", "trace_id": str(trace_id), "agent": "system"}

    raw_payload = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "channel": channel.value,
        "original_length": len(text),
        "sanitized_length": len(clean_text),
    }

    try:
        ensure_conversation(conversation_id, channel, external_identifier)
        persist_inbound(conversation_id, str(trace_id), clean_text, raw_payload)
        auto_capture_contact(conversation_id, clean_text)
    except Exception as exc:
        logger.exception("error pre-concierge trace=%s: %s", trace_id, exc)
        return {
            "text": "Disculpa, tuve un problema guardando tu mensaje. Proba de nuevo.",
            "trace_id": str(trace_id),
            "agent": "system",
        }

    try:
        envelope = InboundMessage(
            trace_id=trace_id,
            conversation_id=UUID(conversation_id),
            guest_id=None,
            channel=channel,
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
        persist_outbound(conversation_id, str(trace_id), reply_text, agent_name)
    except Exception as exc:
        logger.exception("error persistiendo outbound trace=%s: %s", trace_id, exc)

    logger.info(
        "%s OK · trace=%s · conv=%s · in=%dch · out=%dch",
        channel.value, trace_id, conversation_id, len(clean_text), len(reply_text),
    )
    return {"text": reply_text, "trace_id": str(trace_id), "agent": agent_name}
