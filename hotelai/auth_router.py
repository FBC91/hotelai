"""
hotelai.auth_router
====================

Endpoints OAuth2 para obtener un refresh_token de hotelia2026@gmail.com.

Flujo (una vez al hacer setup):
    1. Operador abre https://hotelai-kg75.onrender.com/api/auth/google/start
    2. Es redirigido al consent screen de Google.
    3. Loguea como hotelia2026@gmail.com y aprueba.
    4. Google redirige a /api/auth/google/callback?code=...
    5. Backend guarda el refresh_token en oauth_tokens.
    6. A partir de ahi, send_real_email funciona.

IMPORTANTE: en Google Cloud Console del proyecto hotelai-497522 debe estar
registrado este redirect_uri como Authorized redirect URI del OAuth client web.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from . import gmail

logger = logging.getLogger("hotelai.auth")
router = APIRouter()


@router.get("/google/start", summary="Inicia flujo OAuth para hotelia2026@gmail.com")
async def google_start():
    """Redirige al consent screen de Google."""
    url = gmail.consent_url(state="hotelia")
    return RedirectResponse(url=url, status_code=302)


@router.get("/google/callback", summary="Callback de Google OAuth")
async def google_callback(code: str | None = None, error: str | None = None,
                            state: str | None = None) -> HTMLResponse:
    if error:
        return HTMLResponse(f"<h1>Error de autenticacion</h1><pre>{error}</pre>", status_code=400)
    if not code:
        return HTMLResponse("<h1>Falta el parametro code</h1>", status_code=400)

    try:
        tokens = gmail.exchange_code_for_tokens(code)
    except Exception as exc:
        logger.exception("error en exchange: %s", exc)
        raise HTTPException(500, f"intercambio fallo: {exc}") from exc

    if "refresh_token" not in tokens:
        return HTMLResponse(
            "<h1>OAuth completado sin refresh_token</h1>"
            "<p>Esto pasa si ya habias autorizado antes. Andá a "
            "https://myaccount.google.com/permissions, revoca el acceso a "
            "'hotelai-497522' y volve a hacer /api/auth/google/start.</p>"
            f"<pre>{tokens}</pre>",
            status_code=200,
        )

    gmail.store_tokens(
        account_email=gmail.HOTEL_FROM,
        refresh_token=tokens["refresh_token"],
        access_token=tokens.get("access_token", ""),
        expires_in=tokens.get("expires_in", 3600),
        scope=tokens.get("scope", gmail.SCOPES),
    )

    return HTMLResponse(
        "<html><body style='font-family:system-ui;padding:40px;max-width:600px;margin:auto;'>"
        "<h1 style='color:#00a884'>OK!</h1>"
        f"<p>refresh_token guardado para <b>{gmail.HOTEL_FROM}</b>.</p>"
        "<p>A partir de ahora el sistema envia emails reales en los triggers "
        "del Lifecycle.</p>"
        "<p><a href='https://facundobolani.com/hotelia/'>Volver a la demo</a></p>"
        "</body></html>",
        status_code=200,
    )


@router.get("/google/status", summary="Verifica si hay refresh_token guardado")
async def google_status() -> dict:
    row = gmail.load_token(gmail.HOTEL_FROM)
    if not row:
        return {
            "configured": False,
            "account": gmail.HOTEL_FROM,
            "hint": "abrir /api/auth/google/start para configurar",
        }
    return {
        "configured": True,
        "account": row["account_email"],
        "scope": row.get("scope"),
        "expires_at": row.get("expires_at"),
        "created_at": row.get("created_at"),
    }
