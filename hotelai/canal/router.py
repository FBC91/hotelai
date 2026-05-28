"""
hotelai.canal.router
=====================

Endpoint del canal web_chat. Delega TODO el trabajo al handler compartido
en hotelai/canal/handler.py.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..schemas import ACTIVE_CHANNELS, Channel
from .handler import process_inbound

router = APIRouter()


class WebChatInbound(BaseModel):
    conversation_id: str = Field(min_length=8, max_length=64)
    channel: str = Field(default="web_chat")
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("conversation_id")
    @classmethod
    def must_be_uuid(cls, v: str) -> str:
        try:
            UUID(v)
        except ValueError as exc:
            raise ValueError("conversation_id debe ser un UUID valido") from exc
        return v


class WebChatOutbound(BaseModel):
    text: str
    trace_id: str
    agent: str = Field(default="concierge")


@router.post(
    "/inbound",
    response_model=WebChatOutbound,
    summary="Recibe un mensaje del simulador web (canal web_chat)",
)
async def inbound(payload: WebChatInbound) -> WebChatOutbound:
    if payload.channel != Channel.WEB_CHAT.value:
        raise HTTPException(400, f"Canal {payload.channel!r} no soportado por este endpoint.")
    if Channel.WEB_CHAT not in ACTIVE_CHANNELS:
        raise HTTPException(503, "Canal web_chat deshabilitado.")

    result = process_inbound(
        channel=Channel.WEB_CHAT,
        conversation_id=payload.conversation_id,
        text=payload.text,
    )
    return WebChatOutbound(**result)
