"""
hotelai.agents.tools.db_tools
==============================

Tools que los agentes invocan contra Supabase.
v2: agrega find_reservation_by_short_code y rooms_status_overview.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from ...db import get_supabase

logger = logging.getLogger("hotelai.tools")


def get_static_fact(fact_key: str, lang: str = "es") -> str | None:
    sb = get_supabase()
    resp = sb.table("static_facts").select("values_by_lang").eq("fact_key", fact_key).execute()
    if not resp.data:
        return None
    return resp.data[0]["values_by_lang"].get(lang) or resp.data[0]["values_by_lang"].get("es")


def check_availability(check_in: str, check_out: str, category_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    rooms_resp = sb.table("rooms").select("room_id, room_number") \
        .eq("category_id", category_id).eq("active", True).execute()
    if not rooms_resp.data:
        return []
    room_ids = [r["room_id"] for r in rooms_resp.data]
    busy = sb.table("reservations").select("room_id") \
        .in_("room_id", room_ids) \
        .in_("status", ["pending_payment", "confirmed", "checked_in"]) \
        .lt("check_in", check_out).gt("check_out", check_in).execute()
    busy_ids = {r["room_id"] for r in (busy.data or [])}
    return [r for r in rooms_resp.data if r["room_id"] not in busy_ids]


def get_rate(category_id: str) -> float | None:
    sb = get_supabase()
    resp = sb.table("rates").select("price_usd").eq("category_id", category_id).execute()
    if not resp.data:
        return None
    return float(resp.data[0]["price_usd"])


def find_guest(email: str | None = None, phone: str | None = None) -> dict[str, Any] | None:
    sb = get_supabase()
    if email:
        resp = sb.table("guests").select("*").eq("email", email.lower()).limit(1).execute()
        if resp.data:
            return resp.data[0]
    if phone:
        resp = sb.table("guests").select("*").eq("phone", phone).limit(1).execute()
        if resp.data:
            return resp.data[0]
    return None


def upsert_guest(*, full_name: str | None = None, email: str | None = None,
                 phone: str | None = None, language_pref: str = "es") -> dict[str, Any]:
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

    payload: dict[str, Any] = {
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


def create_reservation(*, guest_id: str, room_id: str, check_in: str, check_out: str,
                       total_amount_usd: float, n_adults: int = 1, n_children: int = 0,
                       payment_hold_hours: int = 24) -> dict[str, Any]:
    from datetime import datetime, timedelta, timezone
    sb = get_supabase()
    hold_until = (datetime.now(timezone.utc) + timedelta(hours=payment_hold_hours)).isoformat()
    payload = {
        "guest_id": guest_id, "room_id": room_id,
        "check_in": check_in, "check_out": check_out,
        "status": "pending_payment", "payment_status": "pending",
        "total_amount_usd": total_amount_usd, "source": "direct",
        "n_adults": n_adults, "n_children": n_children,
        "payment_hold_until": hold_until,
    }
    resp = sb.table("reservations").insert(payload).execute()
    return resp.data[0]


def get_reservation(reservation_id: str, guest_id: str | None = None) -> dict[str, Any] | None:
    sb = get_supabase()
    q = sb.table("reservations").select("*").eq("reservation_id", reservation_id).limit(1).execute()
    if not q.data:
        return None
    row = q.data[0]
    if guest_id and row["guest_id"] != guest_id:
        return None
    return row


def find_reservation_by_short_code(short_code: str, guest_id: str | None = None) -> dict[str, Any] | None:
    """
    Busca una reserva por prefijo de UUID (primeros 8+ chars que el huesped suele recordar).
    Si guest_id se pasa, valida pertenencia.

    Ejemplo: short_code='54e2309e' encuentra '54e2309e-1234-...'.
    """
    sb = get_supabase()
    code = (short_code or "").strip().lower()
    if len(code) < 6:
        return None
    # PostgREST no soporta LIKE prefix directamente con UUID, asi que listamos
    # las del guest y matcheamos en cliente. Acotado a 50 resultados.
    if guest_id:
        rows = sb.table("reservations").select("*") \
            .eq("guest_id", guest_id).limit(50).execute().data or []
    else:
        rows = sb.table("reservations").select("*") \
            .order("created_at", desc=True).limit(50).execute().data or []
    for r in rows:
        if r["reservation_id"].lower().startswith(code):
            return r
    return None


def list_reservations_for_guest(guest_id: str, limit: int = 5) -> list[dict[str, Any]]:
    sb = get_supabase()
    resp = sb.table("reservations").select(
        "reservation_id, check_in, check_out, status, payment_status, total_amount_usd, room_id"
    ).eq("guest_id", guest_id).order("check_in").limit(limit).execute()
    return resp.data or []


def mark_reservation_paid(reservation_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    resp = sb.table("reservations").update({
        "status": "confirmed", "payment_status": "paid",
    }).eq("reservation_id", reservation_id).eq("status", "pending_payment").execute()
    return (resp.data or [None])[0]


def cancel_reservation(reservation_id: str, guest_id: str | None = None) -> dict[str, Any] | None:
    from datetime import datetime, timezone
    sb = get_supabase()
    q = sb.table("reservations").update({
        "status": "cancelled",
        "cancelled_at": datetime.now(timezone.utc).isoformat(),
    }).eq("reservation_id", reservation_id)
    if guest_id:
        q = q.eq("guest_id", guest_id)
    resp = q.execute()
    return (resp.data or [None])[0]


def get_conversation_history(conversation_id: str, limit: int = 8) -> list[dict[str, Any]]:
    sb = get_supabase()
    resp = sb.table("messages").select("direction, role, agent_name, content, created_at") \
        .eq("conversation_id", conversation_id).order("created_at", desc=True).limit(limit).execute()
    return list(reversed(resp.data or []))


def get_guest_for_conversation(conversation_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    conv = sb.table("conversations").select("guest_id").eq("conversation_id", conversation_id).limit(1).execute()
    if not conv.data or not conv.data[0].get("guest_id"):
        return None
    gid = conv.data[0]["guest_id"]
    g = sb.table("guests").select("*").eq("guest_id", gid).limit(1).execute()
    return g.data[0] if g.data else None


def attach_guest_to_conversation(conversation_id: str, guest_id: str) -> None:
    get_supabase().table("conversations").update({"guest_id": guest_id}).eq("conversation_id", conversation_id).execute()


def open_escalation(*, conversation_id: str, triggered_by: str, reason_code: str,
                    severity: str, reason_detail: dict[str, Any] | None = None,
                    sla_hours: int = 1) -> dict[str, Any]:
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
        "state": "escalated_human", "last_agent": "human",
    }).eq("conversation_id", conversation_id).execute()
    return resp.data[0]


def rooms_status_overview() -> dict[str, Any]:
    """
    Vista en vivo de las 80 habitaciones para mostrar en el simulador.

    Devuelve:
      {
        "today": "YYYY-MM-DD",
        "rooms": [{"room_id", "room_number", "category_id", "floor",
                    "status_today": "available|pending_payment|confirmed|checked_in"}],
        "summary": {category_id: {"total": N, "available": M, ...}}
      }
    """
    sb = get_supabase()
    today = date.today().isoformat()

    rooms = sb.table("rooms").select("room_id, room_number, category_id, floor") \
        .eq("active", True).order("room_number").execute().data or []

    # Reservas activas que incluyen hoy
    today_res = sb.table("reservations").select("room_id, status") \
        .in_("status", ["pending_payment", "confirmed", "checked_in"]) \
        .lte("check_in", today).gt("check_out", today).execute().data or []
    by_room = {r["room_id"]: r["status"] for r in today_res}

    out_rooms = []
    summary: dict[str, dict[str, int]] = {}
    for r in rooms:
        st = by_room.get(r["room_id"], "available")
        out_rooms.append({
            "room_id": r["room_id"],
            "room_number": r["room_number"],
            "category_id": r["category_id"],
            "floor": r["floor"],
            "status_today": st,
        })
        cat = r["category_id"]
        summary.setdefault(cat, {"total": 0, "available": 0, "pending_payment": 0,
                                  "confirmed": 0, "checked_in": 0})
        summary[cat]["total"] += 1
        summary[cat][st] = summary[cat].get(st, 0) + 1

    return {"today": today, "rooms": out_rooms, "summary": summary}


__all__ = [
    "get_static_fact",
    "check_availability", "get_rate",
    "find_guest", "upsert_guest",
    "create_reservation", "get_reservation", "find_reservation_by_short_code",
    "list_reservations_for_guest", "mark_reservation_paid", "cancel_reservation",
    "get_conversation_history", "get_guest_for_conversation",
    "attach_guest_to_conversation",
    "open_escalation",
    "rooms_status_overview",
]
