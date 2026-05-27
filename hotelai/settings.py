"""
hotelai.settings
=================

Configuración global validada por pydantic-settings. Lee del entorno y/o `.env`.

Uso:
    from hotelai.settings import settings
    settings.anthropic_api_key  # validado, tipo correcto

En Etapa 1 (este archivo + schemas + state) no se necesita ninguna variable
real, pero declaramos todas para que los agentes posteriores las consuman
sin tener que tocar este archivo.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Variables de entorno del sistema. Carga `.env` si existe."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignora vars del SO que no nos interesan
        case_sensitive=False,
    )

    # ─── LLMs (Etapa 3+) ───────────────────────────────────────────────────
    anthropic_api_key: SecretStr = Field(default=SecretStr(""))
    concierge_model: str = "claude-sonnet-4-6"
    lifecycle_model: str = "claude-sonnet-4-6"
    haiku_model: str = "claude-haiku-4-5-20251001"

    # ─── Supabase (Etapa 4+) ───────────────────────────────────────────────
    supabase_url: str = ""
    supabase_service_role_key: SecretStr = Field(default=SecretStr(""))
    supabase_anon_key: SecretStr = Field(default=SecretStr(""))
    database_url: SecretStr = Field(default=SecretStr(""))

    # ─── Canal · Email (Gmail) ─────────────────────────────────────────────
    gmail_user: str = "hotelia2026@gmail.com"
    gmail_app_password: SecretStr = Field(default=SecretStr(""))
    gmail_smtp_host: str = "smtp.gmail.com"
    gmail_smtp_port: int = 587
    gmail_imap_host: str = "imap.gmail.com"
    gmail_imap_port: int = 993
    gmail_imap_poll_seconds: int = 30

    # ─── Canal · Web chat (simulador en facundobolani.com) ────────────────
    web_chat_api_base_url: str = "http://localhost:8000"
    web_chat_hmac_secret: SecretStr = Field(default=SecretStr(""))
    web_chat_allowed_origin: str = "https://facundobolani.com"

    # ─── Política operativa ────────────────────────────────────────────────
    hotel_name: str = "Hotel Bahía Serena"
    tz: str = "America/Montevideo"
    default_language: str = "es"

    # Pago manual (sin gateway real en el MVP)
    payment_reminder_hours: int = 6
    payment_max_reminders: int = 2
    payment_hold_ttl_hours: int = 24

    # Refunds: hard cap auto
    refund_auto_cap_usd: float = 200.0

    # Rate limiting por huésped
    rate_limit_msg_per_min: int = 30
    rate_limit_msg_per_hour: int = 200

    # ─── Observabilidad ────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings cacheado. Recargar solo via tests con `get_settings.cache_clear()`."""
    return Settings()


# Conveniencia: `from hotelai.settings import settings`
settings = get_settings()


__all__ = ["Settings", "settings", "get_settings"]
