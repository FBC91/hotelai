"""hotelai.server - v3 con todos los routers."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth_router import router as auth_router
from .canal.router import router as canal_router
from .email_router import router as email_router
from .lifecycle_router import router as lifecycle_router
from .rooms_router import router as rooms_router
from .settings import settings

logger = logging.getLogger("hotelai")
logging.basicConfig(level=settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("hotelai v0.3 starting - hotel=%s", settings.hotel_name)
    yield
    logger.info("hotelai shutting down")


app = FastAPI(
    title="Hotel AI Concierge",
    description="Sistema multi-agente. Proyecto Intermedio 1 - ORT 2026.",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://facundobolani.com",
        "https://www.facundobolani.com",
        "http://localhost:8000",
        "http://localhost:3000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=3600,
)

app.include_router(canal_router, prefix="/api/web-chat", tags=["canal-web_chat"])
app.include_router(email_router, prefix="/api/email", tags=["canal-email"])
app.include_router(lifecycle_router, prefix="/api/lifecycle", tags=["lifecycle"])
app.include_router(rooms_router, prefix="/api/rooms", tags=["rooms"])
app.include_router(auth_router, prefix="/api/auth", tags=["oauth"])


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "service": "hotelai",
        "version": "0.3.0",
        "hotel": settings.hotel_name,
        "channels": ["web_chat", "email"],
        "endpoints": {
            "web_chat": "POST /api/web-chat/inbound",
            "email_inbound": "POST /api/email/inbound",
            "email_inbox": "GET  /api/email/inbox?email=...",
            "rooms_status": "GET  /api/rooms/status",
            "lifecycle_trigger": "POST /api/lifecycle/trigger",
            "google_oauth_start": "GET  /api/auth/google/start",
            "google_oauth_status": "GET  /api/auth/google/status",
        },
        "ok": True,
        "docs": "/docs",
    }


@app.get("/healthz", tags=["meta"])
def healthz() -> dict:
    return {"ok": True}
