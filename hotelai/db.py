"""
hotelai.db
===========

Cliente Supabase singleton. Usa la *service role key* (bypasea RLS); por eso
los checks de scope viven en código de las tools, no en RLS para este servicio.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from .settings import settings


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Cliente Supabase cacheado para toda la vida del proceso."""
    url = settings.supabase_url
    key = settings.supabase_service_role_key.get_secret_value()
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY son obligatorios "
            "para conectarse a la base. Verificá tu .env o las env vars del host."
        )
    return create_client(url, key)


__all__ = ["get_supabase"]
