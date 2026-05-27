"""
tests/test_schemas.py
======================

Tests unitarios de los envelopes Pydantic. Sin Claude, sin DB.
Validan que los validators rechazan inputs maliciosos a nivel schema.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from hotelai.schemas import (
    ACTIVE_CHANNELS,
    AgentName,
    Channel,
    Constraints,
    Delegation,
    DelegationResult,
    DelegationStatus,
    Escalation,
    EscalationSeverity,
    GuestContext,
    InboundMessage,
    Intent,
    OutboundMessage,
    TrustSignals,
)


# =============================================================================
# InboundMessage
# =============================================================================


def test_inbound_web_chat_valid():
    msg = InboundMessage(
        conversation_id=uuid4(),
        channel=Channel.WEB_CHAT,
        raw_text="hola",
        trust=TrustSignals(channel_authenticated=True),
    )
    assert msg.channel == Channel.WEB_CHAT


def test_inbound_email_valid():
    msg = InboundMessage(
        conversation_id=uuid4(),
        channel=Channel.EMAIL,
        raw_text="hola",
        trust=TrustSignals(channel_authenticated=True),
    )
    assert msg.channel == Channel.EMAIL


def test_inbound_voice_rejected():
    """Voice no está activo en MVP, debe rechazarse."""
    with pytest.raises(ValidationError):
        InboundMessage(
            conversation_id=uuid4(),
            channel=Channel.VOICE,
            raw_text="hola",
            trust=TrustSignals(channel_authenticated=True),
        )


def test_inbound_whatsapp_rejected():
    """WhatsApp tampoco está activo (es reservado para fase futura)."""
    with pytest.raises(ValidationError):
        InboundMessage(
            conversation_id=uuid4(),
            channel=Channel.WHATSAPP,
            raw_text="hola",
            trust=TrustSignals(channel_authenticated=True),
        )


def test_inbound_extra_field_rejected():
    """`extra=forbid` debe rechazar campos desconocidos (defensa contra inyección de payload)."""
    with pytest.raises(ValidationError):
        InboundMessage(
            conversation_id=uuid4(),
            channel=Channel.WEB_CHAT,
            raw_text="hola",
            trust=TrustSignals(channel_authenticated=True),
            sneaky_field="malicious",  # type: ignore[call-arg]
        )


def test_inbound_text_length_capped():
    """Mensajes muy largos deben rechazarse a nivel schema."""
    huge = "A" * 60_000
    with pytest.raises(ValidationError):
        InboundMessage(
            conversation_id=uuid4(),
            channel=Channel.WEB_CHAT,
            raw_text=huge,
            trust=TrustSignals(channel_authenticated=True),
        )


# =============================================================================
# Delegation (Concierge → especializado)
# =============================================================================


def _make_delegation(**overrides):
    base = dict(
        to_agent=AgentName.RESERVAS,
        conversation_id=uuid4(),
        intent=Intent.BOOK,
        confidence=0.9,
        task_brief="reservar doble",
        allowed_actions=["check_availability", "get_rate"],
        guest_context=GuestContext(),
    )
    base.update(overrides)
    return Delegation(**base)


def test_delegation_to_canal_rejected():
    """Canal NO puede recibir delegación (no es agente especializado)."""
    with pytest.raises(ValidationError):
        _make_delegation(to_agent=AgentName.CANAL)


def test_delegation_to_concierge_self_rejected():
    """Loops Concierge → Concierge están prohibidos."""
    with pytest.raises(ValidationError):
        _make_delegation(to_agent=AgentName.CONCIERGE)


def test_delegation_to_human_rejected():
    """Humano se escala via Escalation, no delegation."""
    with pytest.raises(ValidationError):
        _make_delegation(to_agent=AgentName.HUMAN)


def test_delegation_allowed_actions_required():
    """allowed_actions vacío debe rechazarse."""
    with pytest.raises(ValidationError):
        _make_delegation(allowed_actions=[])


def test_delegation_confidence_bounds():
    with pytest.raises(ValidationError):
        _make_delegation(confidence=1.5)
    with pytest.raises(ValidationError):
        _make_delegation(confidence=-0.1)


def test_delegation_to_reservas_valid():
    d = _make_delegation(to_agent=AgentName.RESERVAS)
    assert d.to_agent == AgentName.RESERVAS


def test_delegation_to_lifecycle_valid():
    d = _make_delegation(to_agent=AgentName.LIFECYCLE)
    assert d.to_agent == AgentName.LIFECYCLE


# =============================================================================
# DelegationResult
# =============================================================================


def test_result_escalate_without_escalation_rejected():
    """status=escalate SIN campo escalation debe fallar (consistency check)."""
    with pytest.raises(ValidationError):
        DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.ESCALATE,
            # falta escalation
        )


def test_result_ok_with_escalation_rejected():
    """status=ok no debe llevar campo escalation."""
    with pytest.raises(ValidationError):
        DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.OK,
            escalation=Escalation(
                reason_code="x", severity=EscalationSeverity.LOW),
        )


def test_result_from_canal_rejected():
    """Canal no puede ser from_agent (no genera DelegationResult)."""
    with pytest.raises(ValidationError):
        DelegationResult(
            from_agent=AgentName.CANAL,
            status=DelegationStatus.OK,
        )


def test_result_valid_ok():
    r = DelegationResult(
        from_agent=AgentName.RESERVAS,
        status=DelegationStatus.OK,
        user_facing_message="listo",
    )
    assert r.status == DelegationStatus.OK


# =============================================================================
# OutboundMessage
# =============================================================================


def test_outbound_inactive_channel_rejected():
    with pytest.raises(ValidationError):
        OutboundMessage(
            conversation_id=uuid4(),
            channel=Channel.VOICE,
            text="hola",
        )


def test_outbound_extra_field_rejected():
    with pytest.raises(ValidationError):
        OutboundMessage(
            conversation_id=uuid4(),
            channel=Channel.WEB_CHAT,
            text="hola",
            secret="payload",  # type: ignore[call-arg]
        )


# =============================================================================
# Conjuntos congelados (config invariants)
# =============================================================================


def test_active_channels_are_web_and_email():
    assert ACTIVE_CHANNELS == frozenset({Channel.WEB_CHAT, Channel.EMAIL})


def test_specialized_agents_invariant():
    from hotelai.schemas import SPECIALIZED_AGENTS
    assert SPECIALIZED_AGENTS == frozenset({AgentName.RESERVAS, AgentName.LIFECYCLE})
