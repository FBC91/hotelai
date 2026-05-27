"""
hotelai.server
===============

Entry point del backend FastAPI. Despliega en Render free tier.

Arranque local:
    uvicorn hotelai.server:app --reload --port 8000

Arranque producción:
    uvicorn hotelai.server:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .canal.router import router as canal_router
from .settings import settings

logger = logging.getLogger("hotelai")
logging.basicConfig(level=settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    logger.info(
        "hotelai starting · hotel=%s · models=concierge:%s, lifecycle:%s, haiku:%s",
        settings.hotel_name,
        settings.concierge_model,
        settings.lifecycle_model,
        settings.haiku_model,
    )
    yield
    logger.info("hotelai shutting down")


app = FastAPI(
    title="Hotel AI Concierge",
    description=(
        "Sistema multi-agente para hotelería. "
        "Proyecto Intermedio 1 · Universidad ORT Uruguay · 2026."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: solo permitimos el origen del simulador (portfolio del autor) + dev local.
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

app.include_router(canal_router, prefix="/api/web-chat", tags=["canal · web_chat"])


@app.get("/", tags=["meta"])
def root() -> dict:
    """Landing simple para verificar que el servicio está vivo."""
    return {
        "service": "hotelai",
        "version": "0.1.0",
        "hotel": settings.hotel_name,
        "ok": True,
        "docs": "/docs",
    }


@app.get("/healthz", tags=["meta"])
def healthz() -> dict:
    """Liveness probe para Render."""
    return {"ok": True}
