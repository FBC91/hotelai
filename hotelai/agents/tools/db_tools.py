"""
hotelai.agents.tools.db_tools
==============================

Funciones que los agentes invocan contra Supabase. Cada función es una "tool"
en el sentido del threat model: tiene precondiciones, valida inputs, y
retorna estructuras tipadas.

NUNCA aceptan strings libres del huésped como parámetros. Los parámetros
vienen del Concierge (que extrae con LLM y valida) o de scheduler events.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from ...db import get_supabase

logger = logging.getLogger("hotelai.tools")


# =============================================================================
# Static facts (Concierge respond_with_fact)
# =============================================================================


def get_static_fact(fact_key: str, lang: str = "es") -> str | None:
    """Devuelve la versión multi-idioma de un fact o None si no existe."""
    sb = get_supabase()
    resp = sb.table("static_facts").select("values_by_lang").eq("fact_key", fact_key).execute()
    if not resp.data:
        return None
    return resp.data[0]["values_by_lang"].get(lang) or resp.data[0]["values_by_lang"].get("es")


# =============================================================================
# Availability + rates (Reservas)
# =============================================================================


def check_availability(check_in: str, check_out: str, category_id: str) -> list[dict[str, Any]]:
    """Lista de habitaciones disponibles de `category_id` para el rango pedido.

    Usa la vista v_room_availability (días marcados como 'available').
    Una habitación se considera disponible si TODOS los días del rango aparecen
    sin reserva activa.

    Retorna: [{"room_id": uuid, "room_number": str}, ...]
    """
    sb = get_supabase()

    # Generamos una query SQL via PostgREST RPC. Como no tenemos RPC creada,
    # vamos por el camino más simple: pedimos los rooms de la categoría y para
    # cada uno chequeamos si hay overlap con reservas activas.
    # Para una tabla de 80 rooms esto es trivial.

    rooms_resp = sb.table("rooms").select("room_id, room_number").eq("category_id", category_id).eq("active", True).execute()
    if not rooms_resp.data:
        return []

    room_ids = [r["room_id"] for r in rooms_resp.data]

    # Reservas activas que SE SOLAPAN con el rango pedido
    # solapamiento: existing.check_in < check_out AND existing.check_out > check_in
    busy = sb.table("reservations").select("room_id") \
        .in_("room_id", room_ids) \
        .in_("status", ["pending_payment", "confirmed", "checked_in"]) \
        .lt("check_in", check_out) \
        .gt("check_out", check_in) \
        .execute()
    busy_ids = {r["room_id"] for r in (busy.data or [])}

    available = [r for r in rooms_resp.data if r["room_id"] not in busy_ids]
    return available


def get_rate(category_id: str) -> float | None:
    """Tarifa USD por noche para `category_id` (sin temporadas en MVP)."""
    sb = get_supabase()
    resp = sb.table("rates").select("price_usd").eq("category_id", category_id).execute()
    if not resp.data:
        return None
    return float(resp.data[0]["price_usd"])


# =============================================================================
# Guests
# =============================================================================


def find_guest(email: str | None = None, phone: str | None = None) -> dict[str, Any] | None:
    """Busca huésped por email o phone. None si no existe."""
    sb = get_supabase()
    q = sb.table("guests").select("*")
    if email:
        resp = q.eq("email", email.lower()).limit(1).execute()
        if resp.data:
            return resp.data[0]
    if phone:
        resp = sb.table("guests").select("*").eq("phone", phone).limit(1).execute()
        if resp.data:
            return resp.data[0]
    return None


def upsert_guest(
    *,
    full_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    language_pref: str = "es",
) -> dict[str, Any]:
    """Crea o actualiza huésped por email/phone. Retorna fila."""
    existing = find_guest(email=email, phone=phone)
    sb = get_supabase()
    if existing:
        updates = {}
        if full_name and not existing.get("full_name"):
            updates["full_name"] = full_name
        if email and not existing.get("email"):
            updates["email"] = email.lower()
        if phone and not existing.get("phone"):
            updates["phone"] = phone
        if updates:
            sb.table("guests").update(updates).eq("guest_id", existing["guest_id"]).execute()
            existing.update(updates)
        return existing

    payload = {
        "full_name": full_name,
        "language_pref": language_pref,
        "consent_marketing": False,
    }
    if email:
        payload["email"] = email.lower()
    if phone:
        payload["phone"] = phone
    resp = sb.table("guests").insert(payload).execute()
    return resp.data[0]


# =============================================================================
# Reservations
# =============================================================================


def create_reservation(
    *,
    guest_id: str,
    room_id: str,
    check_in: str,
    check_out: str,
    total_amount_usd: float,
    n_adults: int = 1,
    n_children: int = 0,
    payment_hold_hours: int = 24,
) -> dict[str, Any]:
    """Crea reserva en estado pending_payment. Hold de N horas para el cuarto."""
    sb = get_supabase()
    from datetime import datetime, timedelta, timezone

    hold_until = (datetime.now(timezone.utc) + timedelta(hours=payment_hold_hours)).isoformat()
    payload = {
        "guest_id": guest_id,
        "room_id": room_id,
        "check_in": check_in,
        "check_out": check_out,
        "status": "pending_payment",
        "payment_status": "pending",
        "total_amount_usd": total_amount_usd,
        "source": "direct",
        "n_adults": n_adults,
        "n_children": n_children,
        "payment_hold_until": hold_until,
    }
    resp = sb.table("reservations").insert(payload).execute()
    return resp.data[0]


def get_reservation(reservation_id: str, guest_id: str | None = None) -> dict[str, Any] | None:
    """Lee una reserva. Si se pasa guest_id, valida pertenencia."""
    sb = get_supabase()
    q = sb.table("reservations").select("*").eq("reservation_id", reservation_id).limit(1).execute()
    if not q.data:
        return None
    row = q.data[0]
    if guest_id and row["guest_id"] != guest_id:
        # Guard: no devolver reservas de otros guests
        logger.warning("attempt to read reservation of another guest (rid=%s, requested by guest=%s)",
                       reservation_id, guest_id)
        return None
    return row


def list_reservations_for_guest(guest_id: str, limit: int = 5) -> list[dict[str, Any]]:
    sb = get_supabase()
    resp = sb.table("reservations").select(
        "reservation_id, check_in, check_out, status, payment_status, total_amount_usd, room_id"
    ).eq("guest_id", guest_id).order("check_in", desc=False).limit(limit).execute()
    return resp.data or []


def mark_reservation_paid(reservation_id: str) -> dict[str, Any] | None:
    """Marca una reserva como confirmada y paga (flujo manual 'ya pagué')."""
    sb = get_supabase()
    resp = sb.table("reservations").update({
        "status": "confirmed",
        "payment_status": "paid",
    }).eq("reservation_id", reservation_id).eq("status", "pending_payment").execute()
    return (resp.data or [None])[0]


# =============================================================================
# Conversations / messages helpers
# =============================================================================


def get_conversation_history(conversation_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Últimos N mensajes de la conversación, en orden cronológico (más viejo primero)."""
    sb = get_supabase()
    resp = sb.table("messages").select(
        "direction, role, agent_name, content, created_at"
    ).eq("conversation_id", conversation_id).order("created_at", desc=True).limit(limit).execute()
    msgs = list(reversed(resp.data or []))
    return msgs


def get_guest_for_conversation(conversation_id: str) -> dict[str, Any] | None:
    """Devuelve el guest asociado a una conversación, si existe."""
    sb = get_supabase()
    conv = sb.table("conversations").select("guest_id").eq("conversation_id", conversation_id).limit(1).execute()
    if not conv.data or not conv.data[0].get("guest_id"):
        return None
    gid = conv.data[0]["guest_id"]
    g = sb.table("guests").select("*").eq("guest_id", gid).limit(1).execute()
    return g.data[0] if g.data else None


def attach_guest_to_conversation(conversation_id: str, guest_id: str) -> None:
    """Asocia un guest a una conversación (cuando se identifica mid-flow)."""
    sb = get_supabase()
    sb.table("conversations").update({"guest_id": guest_id}).eq("conversation_id", conversation_id).execute()


# =============================================================================
# Escalations
# =============================================================================


def open_escalation(
    *,
    conversation_id: str,
    triggered_by: str,
    reason_code: str,
    severity: str,
    reason_detail: dict[str, Any] | None = None,
    sla_hours: int = 1,
) -> dict[str, Any]:
    """Abre escalation + marca la conversación como escalated_human."""
    from datetime import datetime, timedelta, timezone

    sb = get_supabase()
    sla_due = (datetime.now(timezone.utc) + timedelta(hours=sla_hours)).isoformat()
    payload = {
        "conversation_id": conversation_id,
        "triggered_by_agent": triggered_by,
        "reason_code": reason_code,
        "severity": severity,
        "reason_detail": reason_detail or {},
        "status": "open",
        "sla_due_at": sla_due,
    }
    resp = sb.table("escalations").insert(payload).execute()
    sb.table("conversations").update({
        "state": "escalated_human",
        "last_agent": "human",
    }).eq("conversation_id", conversation_id).execute()
    return resp.data[0]


__all__ = [
    "get_static_fact",
    "check_availability",
    "get_rate",
    "find_guest",
    "upsert_guest",
    "create_reservation",
    "get_reservation",
    "list_reservations_for_guest",
    "mark_reservation_paid",
    "get_conversation_history",
    "get_guest_for_conversation",
    "attach_guest_to_conversation",
    "open_escalation",
]
