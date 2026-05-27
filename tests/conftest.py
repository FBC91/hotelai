"""
tests/conftest.py
==================

Fixtures globales para los tests adversariales. Mockean Anthropic y Supabase
para que los tests corran rápido y sin red. La validación con LLMs reales se
hace en producción (audit_log + tests manuales sobre el deploy).
"""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

import pytest

# Set env vars dummy ANTES de importar el paquete (las settings se cargan al import)
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-placeholder")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "sb_test_placeholder")
os.environ.setdefault("WEB_CHAT_HMAC_SECRET", "test-secret")


# =============================================================================
# Mock de Claude (call_with_tools)
# =============================================================================


class FakeLLM:
    """Stub de call_with_tools. Le indicás qué tool devolver y con qué input."""

    def __init__(self):
        self.next_response: dict[str, Any] = {
            "tool_name": "respond_greeting",
            "tool_input": {"text": "hola"},
            "tokens_in": 100,
            "tokens_out": 20,
            "cost_usd": 0.0006,
            "stop_reason": "tool_use",
            "raw": None,
        }
        self.calls: list[dict[str, Any]] = []

    def set_response(self, tool_name: str, tool_input: dict[str, Any]) -> None:
        self.next_response = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tokens_in": 150,
            "tokens_out": 50,
            "cost_usd": 0.001,
            "stop_reason": "tool_use",
            "raw": None,
        }

    def __call__(self, *, model, system, user_text, tools, max_tokens=1024,
                 temperature=0.2, extra_context=None):
        self.calls.append({
            "model": model, "user_text": user_text,
            "tools": [t["name"] for t in tools],
        })
        return self.next_response


@pytest.fixture
def fake_llm(monkeypatch):
    """Reemplaza call_with_tools en todos los modules que lo usan."""
    llm = FakeLLM()
    import hotelai.llm
    import hotelai.agents.concierge
    import hotelai.agents.lifecycle
    monkeypatch.setattr(hotelai.llm, "call_with_tools", llm)
    monkeypatch.setattr(hotelai.agents.concierge, "call_with_tools", llm)
    monkeypatch.setattr(hotelai.agents.lifecycle, "call_with_tools", llm)
    return llm


# =============================================================================
# Mock de db_tools (sin red)
# =============================================================================


class FakeDB:
    """Repositorio en memoria que reemplaza db_tools functions."""

    def __init__(self):
        self.static_facts = {
            "wifi_password": "BahiaSerena2026",
            "wifi_ssid": "BahiaSerena_Guest",
            "checkin_time": "El check-in es desde las 15:00 hs.",
            "checkout_time": "El check-out es hasta las 11:00 hs.",
            "hotel_address": "Av. Roosevelt y Parada 5, Punta del Este",
            "breakfast_hours": "Desayuno 7:00 a 10:30 hs.",
        }
        self.guests: dict[str, dict] = {}
        self.reservations: dict[str, dict] = {}
        self.conversation_to_guest: dict[str, str] = {}
        self.escalations: list[dict] = []
        self.outbound_messages: list[dict] = []
        self.audit_events: list[dict] = []

    # — facts —
    def get_static_fact(self, key, lang="es"):
        return self.static_facts.get(key)

    # — guest —
    def get_guest_for_conversation(self, conv_id):
        gid = self.conversation_to_guest.get(conv_id)
        return self.guests.get(gid) if gid else None

    def get_conversation_history(self, conv_id, limit=8):
        return []

    def attach_guest_to_conversation(self, conv_id, guest_id):
        self.conversation_to_guest[conv_id] = guest_id

    def find_guest(self, email=None, phone=None):
        for g in self.guests.values():
            if email and g.get("email") == email.lower():
                return g
            if phone and g.get("phone") == phone:
                return g
        return None

    def upsert_guest(self, *, full_name=None, email=None, phone=None,
                     language_pref="es"):
        existing = self.find_guest(email=email, phone=phone)
        if existing:
            return existing
        gid = str(uuid4())
        guest = {
            "guest_id": gid,
            "full_name": full_name,
            "email": (email or "").lower() or None,
            "phone": phone,
            "language_pref": language_pref,
            "consent_marketing": False,
            "vip_flag": False,
        }
        self.guests[gid] = guest
        return guest

    # — reservations —
    def check_availability(self, check_in, check_out, category_id):
        # Para los tests: por default hay 1 cuarto disponible
        return [{"room_id": "11111111-1111-1111-1111-111111111111",
                 "room_number": "201"}]

    def get_rate(self, category_id):
        rates = {"single": 90.0, "double": 120.0, "twin": 120.0,
                 "junior_suite": 180.0, "suite": 280.0}
        return rates.get(category_id)

    def create_reservation(self, *, guest_id, room_id, check_in, check_out,
                           total_amount_usd, n_adults=1, n_children=0,
                           payment_hold_hours=24):
        rid = str(uuid4())
        row = {
            "reservation_id": rid, "guest_id": guest_id, "room_id": room_id,
            "check_in": check_in, "check_out": check_out,
            "status": "pending_payment", "payment_status": "pending",
            "total_amount_usd": total_amount_usd,
            "n_adults": n_adults, "n_children": n_children,
        }
        self.reservations[rid] = row
        return row

    def get_reservation(self, reservation_id, guest_id=None):
        row = self.reservations.get(reservation_id)
        if not row:
            return None
        if guest_id and row["guest_id"] != guest_id:
            return None  # Guard R3
        return row

    def list_reservations_for_guest(self, guest_id, limit=5):
        return [r for r in self.reservations.values() if r["guest_id"] == guest_id]

    def mark_reservation_paid(self, reservation_id):
        row = self.reservations.get(reservation_id)
        if not row or row["status"] != "pending_payment":
            return None
        row["status"] = "confirmed"
        row["payment_status"] = "paid"
        return row

    # — escalations —
    def open_escalation(self, *, conversation_id, triggered_by, reason_code,
                        severity, reason_detail=None, sla_hours=1):
        e = {
            "conversation_id": conversation_id,
            "triggered_by": triggered_by,
            "reason_code": reason_code,
            "severity": severity,
            "reason_detail": reason_detail or {},
            "sla_hours": sla_hours,
        }
        self.escalations.append(e)
        return e


@pytest.fixture
def fake_db(monkeypatch):
    """Patchea db_tools y módulos que llaman a Supabase directo."""
    db = FakeDB()
    import hotelai.agents.tools.db_tools as dbt
    import hotelai.agents.concierge as conc
    import hotelai.agents.reservas as res

    for name in [
        "get_static_fact", "get_guest_for_conversation", "get_conversation_history",
        "find_guest", "upsert_guest", "check_availability", "get_rate",
        "create_reservation", "get_reservation", "list_reservations_for_guest",
        "mark_reservation_paid", "open_escalation", "attach_guest_to_conversation",
    ]:
        monkeypatch.setattr(dbt, name, getattr(db, name))

    # Stub audit_span para evitar persistencia
    from contextlib import contextmanager

    @contextmanager
    def _noop_span(**kwargs):
        class S:
            def set_payload(self, *a, **k): pass
            def set_result(self, *a, **k): pass
            def set_tokens(self, *a, **k): pass
            def set_error(self, *a, **k): pass
        yield S()

    monkeypatch.setattr(conc, "audit_span", _noop_span)
    import hotelai.agents.lifecycle as lc
    monkeypatch.setattr(lc, "audit_span", _noop_span)

    return db
