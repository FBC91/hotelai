"""
tests/test_reservas_adversarial.py
====================================

Vectores del threat model de Reservas (R1-R14 en `03-agente-reservas/README.md`).
Mockean DB. Verifican que las guards de código son robustas independiente del
texto del huésped.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from hotelai.agents import reservas
from hotelai.schemas import (
    AgentName,
    Constraints,
    Delegation,
    DelegationStatus,
    GuestContext,
    Intent,
)


def _delegation(intent: Intent, guest_id=None, allowed=None, **kwargs) -> Delegation:
    return Delegation(
        to_agent=AgentName.RESERVAS,
        conversation_id=uuid4(),
        guest_id=guest_id,
        intent=intent,
        confidence=0.9,
        task_brief="...",
        allowed_actions=allowed or ["check_availability", "get_rate",
                                     "create_reservation", "upsert_guest"],
        guest_context=GuestContext(guest_id=guest_id, is_known=bool(guest_id)),
    )


# =============================================================================
# R1 — Precio fabricado por el huésped
# =============================================================================


def test_r1_total_amount_comes_from_get_rate_not_text(fake_db):
    """
    Aunque el task_brief o raw_inputs digan precio falso, el total se calcula
    desde get_rate. No hay parámetro `total_amount` en raw_inputs.
    """
    d = _delegation(Intent.BOOK)
    raw = {
        "check_in": "2099-06-15", "check_out": "2099-06-17",
        "category_id": "double", "n_adults": 2,
        "guest_name": "Test", "guest_email": "t@example.com",
        # huésped intenta poner precio falso:
        "total_amount_usd": 1.0,  # type: ignore[typeddict-item]
        "price_per_night": 1.0,    # type: ignore[typeddict-item]
    }
    result = reservas.handle(d, raw)
    # Si se creó la reserva, el total debería ser 120 * 2 = 240, NO 1.
    assert result.status == DelegationStatus.OK
    rid = result.actions_taken[-1].ref
    row = fake_db.reservations[rid]
    assert row["total_amount_usd"] == 240.0


# =============================================================================
# R3 — Cancelación / consulta de reserva ajena
# =============================================================================


def test_r3_query_other_guest_reservation_returns_none(fake_db):
    """
    get_reservation con guest_id que no matchea debe devolver None
    (guard de pertenencia).
    """
    # Creamos dos guests y una reserva del guest A
    guest_a = fake_db.upsert_guest(email="a@example.com", full_name="A")
    guest_b = fake_db.upsert_guest(email="b@example.com", full_name="B")
    res = fake_db.create_reservation(
        guest_id=guest_a["guest_id"], room_id="room1",
        check_in="2099-06-01", check_out="2099-06-03",
        total_amount_usd=240.0,
    )

    # Guest B intenta consultar la reserva de A
    d = _delegation(Intent.QUERY_RESERVATION, guest_id=guest_b["guest_id"],
                     allowed=["get_reservation", "list_reservations_for_guest"])
    result = reservas.handle(d, {"reservation_id": res["reservation_id"]})
    # Debe ser FAILED (no encuentra a SU nombre)
    assert result.status == DelegationStatus.FAILED
    assert "no encuentro" in (result.user_facing_message or "").lower()


# =============================================================================
# R7 — allowed_actions guard
# =============================================================================


def test_r7_tool_not_in_allowed_actions_blocks(fake_db):
    """
    Si el envelope no incluye 'create_reservation' en allowed_actions, no se
    crea la reserva por más que el resto del flujo lo pida.
    """
    guest = fake_db.upsert_guest(email="x@example.com", full_name="X")
    d = _delegation(
        Intent.BOOK,
        guest_id=guest["guest_id"],
        allowed=["check_availability", "get_rate"],  # SIN create_reservation
    )
    result = reservas.handle(d, {
        "check_in": "2099-06-15", "check_out": "2099-06-17",
        "category_id": "double",
    })
    assert result.status == DelegationStatus.FAILED
    assert "create_reservation" in (result.internal_notes or "")
    assert len(fake_db.reservations) == 0


# =============================================================================
# R10 — Sondeo de pricing (tope de modificaciones por día)
# =============================================================================
# (Aún no implementado el contador — placeholder de test marcado xfail)


@pytest.mark.xfail(reason="contador de modify/day se implementa en Sprint posterior")
def test_r10_modify_cap_per_day():
    pass


# =============================================================================
# R13 — Fechas en el pasado
# =============================================================================


def test_r13_past_check_in_rejected(fake_db):
    """check_in en el pasado → status=failed."""
    guest = fake_db.upsert_guest(email="z@example.com", full_name="Z")
    d = _delegation(Intent.BOOK, guest_id=guest["guest_id"])
    result = reservas.handle(d, {
        "check_in": "2000-01-01", "check_out": "2000-01-03",
        "category_id": "double",
    })
    assert result.status == DelegationStatus.FAILED
    assert "pas" in (result.user_facing_message or "").lower()


def test_r13_checkout_before_checkin_rejected(fake_db):
    guest = fake_db.upsert_guest(email="w@example.com", full_name="W")
    d = _delegation(Intent.BOOK, guest_id=guest["guest_id"])
    result = reservas.handle(d, {
        "check_in": "2099-06-15", "check_out": "2099-06-14",
        "category_id": "double",
    })
    assert result.status == DelegationStatus.FAILED


# =============================================================================
# R3 + identificación obligatoria
# =============================================================================


def test_book_without_guest_info_returns_partial(fake_db):
    """Sin email/phone y sin guest_id existente → partial pidiendo datos."""
    d = _delegation(Intent.BOOK)  # sin guest_id
    result = reservas.handle(d, {
        "check_in": "2099-06-15", "check_out": "2099-06-17",
        "category_id": "double",
    })
    assert result.status == DelegationStatus.PARTIAL
    assert "email" in (result.user_facing_message or "").lower() \
        or "tel" in (result.user_facing_message or "").lower()


# =============================================================================
# Happy path · book completo
# =============================================================================


def test_book_happy_path(fake_db):
    d = _delegation(Intent.BOOK)
    result = reservas.handle(d, {
        "check_in": "2099-06-15", "check_out": "2099-06-17",
        "category_id": "double", "n_adults": 2,
        "guest_name": "Maria Test", "guest_email": "maria@example.com",
    })
    assert result.status == DelegationStatus.OK
    assert "USD 240" in (result.user_facing_message or "")
    # Una reserva creada en pending_payment
    assert len(fake_db.reservations) == 1
    row = next(iter(fake_db.reservations.values()))
    assert row["status"] == "pending_payment"
    assert row["total_amount_usd"] == 240.0


# =============================================================================
# payment_confirm
# =============================================================================


def test_payment_confirm_marks_paid(fake_db):
    guest = fake_db.upsert_guest(email="p@example.com", full_name="P")
    res = fake_db.create_reservation(
        guest_id=guest["guest_id"], room_id="r1",
        check_in="2099-06-01", check_out="2099-06-03",
        total_amount_usd=240.0,
    )
    d = _delegation(
        Intent.PAYMENT_CONFIRM,
        guest_id=guest["guest_id"],
        allowed=["list_reservations_for_guest", "mark_reservation_paid"],
    )
    result = reservas.handle(d, {})
    assert result.status == DelegationStatus.OK
    assert fake_db.reservations[res["reservation_id"]]["status"] == "confirmed"
    assert fake_db.reservations[res["reservation_id"]]["payment_status"] == "paid"
