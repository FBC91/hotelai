"""
hotelai.audit
==============

Helper centralizado para escribir filas a `audit_log`. Tracking de tokens,
costo, duración y errores por cada acción de cada agente.

Uso típico:
    with audit_span(agent="concierge", action="classify_intent",
                    trace_id=tid, conversation_id=cid) as span:
        result = do_something()
        span.set_tokens(in_=200, out=80, cost=0.0015)
"""

from __future__ import annotations

import logging
import time
import traceback
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from .db import get_supabase

logger = logging.getLogger("hotelai.audit")


class _AuditSpan:
    """Acumula data durante el span; al __exit__ se persiste."""

    def __init__(
        self,
        agent: str,
        action: str,
        trace_id: UUID | str,
        conversation_id: UUID | str | None = None,
        prompt_version: str | None = None,
    ):
        self.agent = agent
        self.action = action
        self.trace_id = str(trace_id)
        self.conversation_id = str(conversation_id) if conversation_id else None
        self.prompt_version = prompt_version
        self.payload: dict[str, Any] = {}
        self.result: dict[str, Any] = {}
        self.tokens_in: int | None = None
        self.tokens_out: int | None = None
        self.cost_usd: float | None = None
        self.error: str | None = None
        self._t0 = time.perf_counter()

    def set_payload(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def set_result(self, result: dict[str, Any]) -> None:
        self.result = result

    def set_tokens(self, in_: int, out: int, cost: float) -> None:
        self.tokens_in = in_
        self.tokens_out = out
        self.cost_usd = cost

    def set_error(self, err: str) -> None:
        self.error = err[:500]


@contextmanager
def audit_span(
    *,
    agent: str,
    action: str,
    trace_id: UUID | str,
    conversation_id: UUID | str | None = None,
    prompt_version: str | None = None,
):
    """Context manager que persiste un audit_log al salir."""
    span = _AuditSpan(agent, action, trace_id, conversation_id, prompt_version)
    try:
        yield span
    except Exception as exc:
        span.set_error(f"{type(exc).__name__}: {exc}")
        logger.exception("audit span error (%s.%s): %s", agent, action, exc)
        raise
    finally:
        duration_ms = int((time.perf_counter() - span._t0) * 1000)
        try:
            row = {
                "trace_id": span.trace_id,
                "agent_name": span.agent,
                "action": span.action,
                "payload": _truncate_jsonb(span.payload),
                "result": _truncate_jsonb(span.result),
                "duration_ms": duration_ms,
                "tokens_in": span.tokens_in,
                "tokens_out": span.tokens_out,
                "cost_usd": span.cost_usd,
                "error": span.error,
                "prompt_version": span.prompt_version,
            }
            if span.conversation_id:
                row["conversation_id"] = span.conversation_id
            get_supabase().table("audit_log").insert(row).execute()
        except Exception as exc:  # noqa: BLE001
            logger.exception("no pude persistir audit_log: %s", exc)


def _truncate_jsonb(obj: dict[str, Any], max_chars: int = 4000) -> dict[str, Any]:
    """Recorta strings muy largos antes de mandar a Postgres como JSONB."""
    if not obj:
        return obj
    out = {}
    for k, v in obj.items():
        if isinstance(v, str) and len(v) > max_chars:
            out[k] = v[:max_chars] + "…[truncated]"
        else:
            out[k] = v
    return out


__all__ = ["audit_span"]
