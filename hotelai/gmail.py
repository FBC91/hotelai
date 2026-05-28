"""
hotelai.gmail
==============

Gmail API wrapper - OAuth2 + send. Sin dependencias extra (usa urllib).
Cliente secret SIEMPRE viene de env var GOOGLE_OAUTH_CLIENT_SECRET.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from .db import get_supabase
from .settings import settings

logger = logging.getLogger("hotelai.gmail")

CLIENT_ID = "614028957513-31cp6jggscovrnp6qp1b9mjmbomhimjk.apps.googleusercontent.com"

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

SCOPES = "https://www.googleapis.com/auth/gmail.send"
HOTEL_FROM = "hotelia2026@gmail.com"


def _client_secret() -> str:
    secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    if not secret:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_SECRET no esta seteado en env.")
    return secret


def _redirect_uri() -> str:
    base = settings.web_chat_api_base_url.rstrip("/")
    if base.startswith("http://localhost"):
        return "http://localhost:8000/api/auth/google/callback"
    return f"{base}/api/auth/google/callback"


def consent_url(state: str = "hotelia") -> str:
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code: str) -> dict:
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": _client_secret(),
        "redirect_uri": _redirect_uri(),
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, method="POST", data=body,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read().decode())


def refresh_access_token(refresh_token: str) -> dict:
    body = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "client_secret": _client_secret(),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, method="POST", data=body,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read().decode())


def store_tokens(account_email: str, refresh_token: str, access_token: str,
                  expires_in: int, scope: str) -> None:
    sb = get_supabase()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    sb.table("oauth_tokens").upsert({
        "provider": "google",
        "account_email": account_email,
        "refresh_token": refresh_token,
        "access_token": access_token,
        "scope": scope,
        "expires_at": expires_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="provider,account_email").execute()


def load_token(account_email: str = HOTEL_FROM) -> dict | None:
    sb = get_supabase()
    resp = sb.table("oauth_tokens").select("*") \
        .eq("provider", "google").eq("account_email", account_email) \
        .limit(1).execute()
    return resp.data[0] if resp.data else None


def _ensure_fresh_access_token(token_row: dict) -> str:
    expires_at_str = token_row.get("expires_at")
    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) + timedelta(minutes=2) < expires_at and token_row.get("access_token"):
                return token_row["access_token"]
        except Exception:
            pass
    refreshed = refresh_access_token(token_row["refresh_token"])
    store_tokens(
        account_email=token_row["account_email"],
        refresh_token=token_row["refresh_token"],
        access_token=refreshed["access_token"],
        expires_in=refreshed.get("expires_in", 3600),
        scope=refreshed.get("scope", SCOPES),
    )
    return refreshed["access_token"]


def _build_raw_message(to: str, subject: str, body: str,
                       from_addr: str = HOTEL_FROM) -> str:
    msg = EmailMessage()
    msg["From"] = f"Hotel Bahia Serena <{from_addr}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send_real_email(to: str, subject: str, body: str) -> dict:
    """Envia email real via Gmail API. Devuelve {sent, reason, message_id}."""
    token_row = load_token(HOTEL_FROM)
    if not token_row:
        logger.warning("send_real_email · no oauth token")
        return {"sent": False, "reason": "no_oauth_token"}

    try:
        access_token = _ensure_fresh_access_token(token_row)
    except Exception as exc:
        logger.exception("falla refrescando access_token: %s", exc)
        return {"sent": False, "reason": f"refresh_failed:{exc}"}

    raw = _build_raw_message(to=to, subject=subject, body=body)
    req = urllib.request.Request(
        GMAIL_SEND_URL, method="POST",
        headers={"Authorization": f"Bearer {access_token}",
                 "Content-Type": "application/json"},
        data=json.dumps({"raw": raw}).encode(),
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        body_resp = json.loads(resp.read().decode())
        logger.info("gmail send OK · to=%s · id=%s", to, body_resp.get("id"))
        return {"sent": True, "message_id": body_resp.get("id")}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:500]
        logger.exception("gmail send HTTP %s: %s", e.code, err_body)
        return {"sent": False, "reason": f"http_{e.code}", "detail": err_body}
    except Exception as exc:
        logger.exception("gmail send fallo: %s", exc)
        return {"sent": False, "reason": str(exc)}


__all__ = [
    "consent_url", "exchange_code_for_tokens", "store_tokens", "load_token",
    "send_real_email", "HOTEL_FROM", "CLIENT_ID", "SCOPES",
]
