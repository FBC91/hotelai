"""
hotelai.schemas
================

Pydantic v2 · Enums, envelopes y modelos compartidos entre los 4 agentes.

Reglas del dominio:
- Todos los handoffs entre agentes usan envelopes JSON validados contra schema.
- `extra="forbid"` en todos los modelos: rechazar campos desconocidos.
- Cada envelope lleva `schema_version` y `trace_id` para auditoría.
- Ningún agente acepta texto libre de otro agente; siempre debe validar el sobre.

Ver `00-arquitectura/README.md §4` para la spec detallada de los envelopes.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

# StrEnum es 3.11+. Polyfill para 3.10.
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Polyfill de enum.StrEnum (3.11+) para Python 3.10."""

        def __str__(self) -> str:
            return self.value


# =============================================================================
# CONSTANTES
# =============================================================================

SCHEMA_VERSION: Literal["1.0"] = "1.0"
MAX_RAW_TEXT_LENGTH = 50_000
MAX_OUTBOUND_TEXT_LENGTH = 4096
MAX_TASK_BRIEF_LENGTH = 500


# =============================================================================
# ENUMS
# =============================================================================


class Channel(StrEnum):
    """Canales por los que llega/sale un mensaje.

    MVP activo: WEB_CHAT (simulador en facundobolani.com) y EMAIL (hotelia2026@gmail.com).
    """

    WEB_CHAT = "web_chat"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    SMS = "sms"
    VOICE = "voice"


ACTIVE_CHANNELS: frozenset[Channel] = frozenset({Channel.WEB_CHAT, Channel.EMAIL})


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class DBConversationState(StrEnum):
    ACTIVE = "active"
    AWAITING_PAYMENT = "awaiting_payment"
    ESCALATED_HUMAN = "escalated_human"
    CLOSED = "closed"


class GuestPhase(StrEnum):
    NONE = "none"
    PRE_STAY = "pre_stay"
    IN_STAY = "in_stay"
    POST_STAY = "post_stay"


class ReservationStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    REFUNDED = "refunded"
    PARTIAL_REFUND = "partial_refund"


class ReservationSource(StrEnum):
    DIRECT = "direct"
    BOOKING = "booking"
    EXPEDIA = "expedia"
    AIRBNB = "airbnb"


class AgentName(StrEnum):
    CONCIERGE = "concierge"
    CANAL = "canal"
    RESERVAS = "reservas"
    LIFECYCLE = "lifecycle"
    HUMAN = "human"
    SYSTEM = "system"


SPECIALIZED_AGENTS: frozenset[AgentName] = frozenset(
    {AgentName.RESERVAS, AgentName.LIFECYCLE}
)


class Intent(StrEnum):
    BOOK = "book"
    MODIFY = "modify"
    CANCEL = "cancel"
    CHECKIN = "checkin"
    CHECKOUT = "checkout"
    QUERY_RESERVATION = "query_reservation"
    UPGRADE = "upgrade"
    INFO = "info"
    COMPLAIN = "complain"
    UPSELL_ACCEPT = "upsell_accept"
    GREETING = "greeting"
    PAYMENT_CONFIRM = "payment_confirm"
    OPT_OUT = "opt_out"
    EMERGENCY = "emergency"
    EMOTIONAL_ASSESSMENT = "emotional_assessment"
    SMALL_TALK = "small_talk"
    UNKNOWN = "unknown"


DIRECT_RESPONSE_INTENTS: frozenset[Intent] = frozenset(
    {Intent.GREETING, Intent.INFO, Intent.SMALL_TALK}
)


class DelegationStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    ESCALATE = "escalate"


class LifecycleTriggerKind(StrEnum):
    PRE_STAY_T7 = "pre_stay_t7"
    PRE_STAY_T1 = "pre_stay_t1"
    IN_STAY_MIDCHECK = "in_stay_midcheck"
    POST_STAY_T1 = "post_stay_t1"
    POST_STAY_T7 = "post_stay_t7"
    PAYMENT_REMINDER = "payment_reminder"


class ToneHint(StrEnum):
    FORMAL = "formal"
    CASUAL = "casual"
    EMPATHETIC = "empathetic"


class EscalationSeverity(StrEnum):
    LOW = "low"
    MED = "med"
    HIGH = "high"
    CRITICAL = "critical"


class EnvelopeType(StrEnum):
    INBOUND_MESSAGE = "inbound_message"
    DELEGATION = "delegation"
    DELEGATION_RESULT = "delegation_result"
    OUTBOUND_MESSAGE = "outbound_message"
    LIFECYCLE_TRIGGER = "lifecycle_trigger"


# =============================================================================
# MODELOS COMPARTIDOS
# =============================================================================


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TrustSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_authenticated: bool
    identity_verified: bool = False
    matches_known_guest: bool = False


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["image", "audio", "document"]
    url: str = Field(max_length=2048)
    mime_type: str | None = None
    bytes_size: int | None = Field(default=None, ge=0)


class GuestContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guest_id: UUID | None = None
    is_known: bool = False
    vip: bool = False
    language: str = Field(default="es", pattern=r"^[a-z]{2}$")
    consent_marketing: bool = False
    history_summary: str | None = Field(default=None, max_length=500)


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tool_calls: int = Field(default=6, ge=1, le=20)
    max_refund_usd: float = Field(default=200.0, ge=0)
    must_not_disclose: list[str] = Field(default_factory=list)
    require_human_for: list[str] = Field(default_factory=list)


class ActionTaken(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(max_length=100)
    result: Literal["ok", "error", "skipped"]
    ref: str | None = Field(default=None, max_length=200)
    error_message: str | None = Field(default=None, max_length=500)


class Escalation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(max_length=64)
    severity: EscalationSeverity
    message: str | None = Field(default=None, max_length=500)


# =============================================================================
# ENVELOPES
# =============================================================================


class _EnvelopeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    trace_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=_utcnow)


class InboundMessage(_EnvelopeBase):
    envelope_type: Literal[EnvelopeType.INBOUND_MESSAGE] = EnvelopeType.INBOUND_MESSAGE
    conversation_id: UUID
    guest_id: UUID | None = None
    channel: Channel
    raw_text: str = Field(max_length=MAX_RAW_TEXT_LENGTH)
    metadata: dict[str, Any] = Field(default_factory=dict)
    trust: TrustSignals
    attachments: list[Attachment] = Field(default_factory=list)

    @model_validator(mode="after")
    def channel_must_be_active(self) -> "InboundMessage":
        if self.channel not in ACTIVE_CHANNELS:
            raise ValueError(
                f"Channel {self.channel!r} no está activo en el MVP. "
                f"Canales activos: {sorted(c.value for c in ACTIVE_CHANNELS)}"
            )
        return self


class Delegation(_EnvelopeBase):
    envelope_type: Literal[EnvelopeType.DELEGATION] = EnvelopeType.DELEGATION
    from_agent: Literal[AgentName.CONCIERGE] = AgentName.CONCIERGE
    to_agent: AgentName
    conversation_id: UUID
    guest_id: UUID | None = None
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    task_brief: str = Field(max_length=MAX_TASK_BRIEF_LENGTH)
    allowed_actions: list[str] = Field(min_length=1)
    constraints: Constraints = Field(default_factory=Constraints)
    guest_context: GuestContext

    @model_validator(mode="after")
    def to_agent_must_be_specialized(self) -> "Delegation":
        if self.to_agent not in SPECIALIZED_AGENTS:
            raise ValueError(
                f"Delegation.to_agent debe ser un agente especializado "
                f"({sorted(a.value for a in SPECIALIZED_AGENTS)}); "
                f"recibido {self.to_agent!r}."
            )
        return self


class DelegationResult(_EnvelopeBase):
    envelope_type: Literal[EnvelopeType.DELEGATION_RESULT] = EnvelopeType.DELEGATION_RESULT
    from_agent: AgentName
    status: DelegationStatus
    user_facing_message: str | None = Field(default=None, max_length=MAX_OUTBOUND_TEXT_LENGTH)
    internal_notes: str | None = Field(default=None, max_length=2000)
    actions_taken: list[ActionTaken] = Field(default_factory=list)
    escalation: Escalation | None = None

    @model_validator(mode="after")
    def escalate_requires_escalation_field(self) -> "DelegationResult":
        if self.status == DelegationStatus.ESCALATE and self.escalation is None:
            raise ValueError("status=escalate requiere campo `escalation` no nulo.")
        if self.status != DelegationStatus.ESCALATE and self.escalation is not None:
            raise ValueError(
                "campo `escalation` solo permitido cuando status=escalate."
            )
        return self

    @model_validator(mode="after")
    def from_agent_must_be_specialized(self) -> "DelegationResult":
        if self.from_agent not in SPECIALIZED_AGENTS:
            raise ValueError(
                f"DelegationResult.from_agent debe ser un agente especializado; "
                f"recibido {self.from_agent!r}."
            )
        return self


class OutboundMessage(_EnvelopeBase):
    envelope_type: Literal[EnvelopeType.OUTBOUND_MESSAGE] = EnvelopeType.OUTBOUND_MESSAGE
    conversation_id: UUID
    channel: Channel
    text: str = Field(max_length=MAX_OUTBOUND_TEXT_LENGTH)
    tone_hint: ToneHint = ToneHint.CASUAL
    attachments: list[Attachment] = Field(default_factory=list)
    requires_signature: bool = False

    @model_validator(mode="after")
    def channel_must_be_active(self) -> "OutboundMessage":
        if self.channel not in ACTIVE_CHANNELS:
            raise ValueError(
                f"Channel {self.channel!r} no está activo en el MVP."
            )
        return self


class LifecycleTrigger(_EnvelopeBase):
    envelope_type: Literal[EnvelopeType.LIFECYCLE_TRIGGER] = EnvelopeType.LIFECYCLE_TRIGGER
    trigger: LifecycleTriggerKind
    guest_id: UUID
    reservation_id: UUID
    phase: GuestPhase


# =============================================================================
# CLASIFICACIÓN (interna del Concierge)
# =============================================================================


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    target_agent: AgentName
    is_emergency: bool = False
    detected_language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    flags: list[str] = Field(default_factory=list)


# =============================================================================
# AUDIT
# =============================================================================


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(default_factory=_utcnow)
    agent_name: AgentName
    action: str = Field(max_length=100)
    trace_id: UUID
    conversation_id: UUID | None = None
    payload_hash: str | None = Field(default=None, max_length=64)
    result_hash: str | None = Field(default=None, max_length=64)
    duration_ms: int | None = Field(default=None, ge=0)
    tokens_in: int | None = Field(default=None, ge=0)
    tokens_out: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    error: str | None = Field(default=None, max_length=500)


# =============================================================================
# UNION TYPE para parseo polimórfico
# =============================================================================

Envelope = Annotated[
    InboundMessage | Delegation | DelegationResult | OutboundMessage | LifecycleTrigger,
    Field(discriminator="envelope_type"),
]


__all__ = [
    "SCHEMA_VERSION",
    "ACTIVE_CHANNELS",
    "SPECIALIZED_AGENTS",
    "DIRECT_RESPONSE_INTENTS",
    "Channel",
    "MessageDirection",
    "DBConversationState",
    "GuestPhase",
    "ReservationStatus",
    "PaymentStatus",
    "ReservationSource",
    "AgentName",
    "Intent",
    "DelegationStatus",
    "LifecycleTriggerKind",
    "ToneHint",
    "EscalationSeverity",
    "EnvelopeType",
    "TrustSignals",
    "Attachment",
    "GuestContext",
    "Constraints",
    "ActionTaken",
    "Escalation",
    "InboundMessage",
    "Delegation",
    "DelegationResult",
    "OutboundMessage",
    "LifecycleTrigger",
    "Envelope",
    "Classification",
    "AuditEvent",
]
