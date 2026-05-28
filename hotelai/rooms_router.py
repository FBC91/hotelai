"""
hotelai.rooms_router
=====================

Endpoints publicos read-only para el simulador.
- GET /api/rooms/status             estado de hoy
- GET /api/rooms/availability?days=N&from=YYYY-MM-DD  grilla N dias por categoria
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query

from .agents.tools import db_tools as t
from .db import get_supabase

router = APIRouter()


@router.get("/status", summary="Estado de hoy de todas las habitaciones")
async def rooms_status() -> dict:
    return t.rooms_status_overview()


@router.get(
    "/availability",
    summary="Disponibilidad por categoria proximos N dias",
)
async def rooms_availability(
    days: int = Query(default=14, ge=1, le=60),
    start: str | None = Query(default=None, description="Fecha inicial YYYY-MM-DD, default=hoy"),
) -> dict[str, Any]:
    """
    Devuelve por cada categoria, dia por dia, cuantas habitaciones estan libres.

    Estructura:
      {
        "from": "2026-05-28",
        "days": [
          {"date": "2026-05-28", "by_category": {"single": 18, "double": 25, ...}},
          ...
        ],
        "categories": {
            "single": {"total": 20, "price_usd": 90},
            "double": {"total": 30, "price_usd": 120},
            ...
        }
      }
    """
    sb = get_supabase()

    if start:
        try:
            d0 = date.fromisoformat(start)
        except ValueError:
            d0 = date.today()
    else:
        d0 = date.today()
    d_end = d0 + timedelta(days=days)

    # Categorias con conteo total + precio
    cats = sb.table("room_categories").select("category_id, display_name").execute().data or []
    rates = sb.table("rates").select("category_id, price_usd").execute().data or []
    price_by_cat = {r["category_id"]: float(r["price_usd"]) for r in rates}

    rooms = sb.table("rooms").select("room_id, category_id") \
        .eq("active", True).execute().data or []
    rooms_by_cat: dict[str, list[str]] = {}
    for r in rooms:
        rooms_by_cat.setdefault(r["category_id"], []).append(r["room_id"])

    categories = {
        c["category_id"]: {
            "display_name": c["display_name"],
            "total": len(rooms_by_cat.get(c["category_id"], [])),
            "price_usd": price_by_cat.get(c["category_id"]),
        }
        for c in cats
    }

    # Reservas activas que overlapan con [d0, d_end]
    reservations = sb.table("reservations").select(
        "room_id, check_in, check_out, status"
    ).in_("status", ["pending_payment", "confirmed", "checked_in"]) \
     .lt("check_in", d_end.isoformat()).gt("check_out", d0.isoformat()) \
     .execute().data or []

    # Por dia: cuantas rooms de cada cat estan libres
    days_out = []
    cur = d0
    while cur < d_end:
        busy_by_cat: dict[str, int] = {}
        for res in reservations:
            ci = date.fromisoformat(res["check_in"])
            co = date.fromisoformat(res["check_out"])
            if ci <= cur < co:
                # Buscar categoria del room
                for cat, ids in rooms_by_cat.items():
                    if res["room_id"] in ids:
                        busy_by_cat[cat] = busy_by_cat.get(cat, 0) + 1
                        break
        by_category = {}
        for cat in categories:
            total = categories[cat]["total"]
            available = total - busy_by_cat.get(cat, 0)
            by_category[cat] = max(available, 0)
        days_out.append({
            "date": cur.isoformat(),
            "weekday": cur.strftime("%a"),
            "by_category": by_category,
        })
        cur += timedelta(days=1)

    return {
        "from": d0.isoformat(),
        "to": (d_end - timedelta(days=1)).isoformat(),
        "days_count": days,
        "categories": categories,
        "days": days_out,
    }
