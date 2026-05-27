"""
hotelai.state
==============

LangGraph state: el contenedor que viaja entre nodos del grafo del Concierge.

Es deliberadamente flat (TypedDict) para que LangGraph pueda hacer
checkpointing serializable. Los reducers usan `operator.add` para campos
acumulativos (audit events).
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict
from uuid import UUID

from .schemas import (
    AuditEvent,
    Classification,
    DBConversationState,
    Delegation,
    DelegationResult,
    GuestContext,
    InboundMessage,
    OutboundMessage,
)


class GraphState(TypedDict, total=False):
    """Estado compartido del grafo LangGraph del Concierge.

    `total=False`: todos los campos opcionales para que LangGraph pueda hacer
    merges parciales sin requerir reconstrucción del state completo.
    """

    # ─── Identidad del turno ───────────────────────────────────────────────
    trace_id: UUID
    conversation_id: UUID
    guest_id: UUID | None

    # ─── Datos del huésped cargados de DB ──────────────────────────────────
    guest_context: GuestContext | None
    history_summary: str | None
    db_conv_state: DBConversationState | None

    # ─── Entrada ───────────────────────────────────────────────────────────
    inbound: InboundMessage

    # ─── Clasificación ─────────────────────────────────────────────────────
    classification: Classification | None

    # ─── Delegación ────────────────────────────────────────────────────────
    delegation: Delegation | None
    delegation_result: DelegationResult | None

    # ─── Salida ────────────────────────────────────────────────────────────
    outbound: OutboundMessage | None

    # ─── Control de flujo ──────────────────────────────────────────────────
    retry_count: int
    escalate: bool
    # Razón inmediata de la escalación, si aplica (loggear y mandar a humano).
    escalate_reason: str | None

    # ─── Auditoría (reducer: append) ───────────────────────────────────────
    audit_events: Annotated[list[AuditEvent], operator.add]


def initial_state(inbound: InboundMessage) -> GraphState:
    """Estado inicial al recibir un mensaje del Canal.

    Todos los campos opcionales quedan ausentes (el grafo los puebla).
    """
    return GraphState(
        trace_id=inbound.trace_id,
        conversation_id=inbound.conversation_id,
        guest_id=inbound.guest_id,
        inbound=inbound,
        retry_count=0,
        escalate=False,
        escalate_reason=None,
        audit_events=[],
    )


__all__ = ["GraphState", "initial_state"]
