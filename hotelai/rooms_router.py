"""
hotelai.rooms_router
=====================

Endpoint publico de solo lectura para la tabla de habitaciones en vivo del
simulador. Devuelve el estado de las 80 habitaciones hoy + resumen por categoria.

Lo consume el simulador en facundobolani.com/hotelia/ via polling cada N segundos.
"""

from __future__ import annotations

from fastapi import APIRouter

from .agents.tools import db_tools as t

router = APIRouter()


@router.get(
    "/status",
    summary="Estado actual (hoy) de todas las habitaciones del hotel",
)
async def rooms_status() -> dict:
    """
    Devuelve la grilla completa de habitaciones con:
      - room_id, room_number, category_id, floor
      - status_today: available | pending_payment | confirmed | checked_in

    Mas un resumen por categoria.
    """
    return t.rooms_status_overview()
