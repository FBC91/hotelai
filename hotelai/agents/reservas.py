"""
hotelai.agents.reservas
========================

Agente Reservas — Procedural (sin LLM en este sprint).

Recibe un Delegation envelope del Concierge y ejecuta la transacción:
    - query_reservation: lee reserva o lista reservas del huésped
    - book: crea reserva en pending_payment + pide confirmación de pago manual
    - payment_confirm: marca pending_payment → confirmed/paid
    - (más adelante) modify, cancel, checkin, checkout

Guards (ver 03-agente-reservas/README.md threat model):
    R1 — precio viene SIEMPRE de get_rate(), nunca del task_brief
    R3 — guest_id viene del envelope, no se acepta de texto del huésped
    R7 — toda tool invocada se checkea contra allowed_actions
    R11 — si el LLM intenta una tool fuera de scope, falla con forbidden
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from uuid import uuid4

from ..schemas import (
    ActionTaken,
    AgentName,
    Delegation,
    DelegationResult,
    DelegationStatus,
    Escalation,
    EscalationSeverity,
)
from ..settings import settings
from .tools import db_tools as t

logger = logging.getLogger("hotelai.reservas")

# Las tools que Reservas puede invocar bajo ningún concepto fuera de esta lista.
ALL_TOOLS = {
    "check_availability",
    "get_rate",
    "create_reservation",
    "get_reservation",
    "list_reservations_for_guest",
    "mark_reservation_paid",
    "upsert_guest",
}


# =============================================================================
# Entry point
# =============================================================================


def handle(envelope: Delegation, raw_inputs: dict | None = None) -> DelegationResult:
    """Despacha según intent. raw_inputs es lo extraído por el Concierge."""
    raw_inputs = raw_inputs or {}

    # Guard R7: cada tool que vamos a invocar debe estar en allowed_actions
    def can(tool: str) -> bool:
        return tool in envelope.allowed_actions

    intent = envelope.intent.value
    logger.info("reservas.handle intent=%s allowed=%s", intent, envelope.allowed_actions)

    try:
        if intent == "query_reservation":
            return _handle_query(envelope, raw_inputs, can)
        if intent == "book":
            return _handle_book(envelope, raw_inputs, can)
        if intent == "payment_confirm":
            return _handle_payment_confirm(envelope, raw_inputs, can)
        # Para los demás intents (modify, cancel, checkin, checkout, upgrade)
        # devolvemos partial — los implementaremos en próximos sprints.
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.PARTIAL,
            user_facing_message=(
                "Esa acción aún no está implementada en esta versión del MVP. "
                "Te conecto con el equipo de recepción."
            ),
            internal_notes=f"intent={intent} no soportado todavía",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("reservas error trace=%s", envelope.trace_id)
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.FAILED,
            internal_notes=f"{type(exc).__name__}: {exc}",
        )


# =============================================================================
# query_reservation
# =============================================================================


def _handle_query(envelope: Delegation, raw: dict, can) -> DelegationResult:
    """Devuelve resumen de una reserva o lista las del huésped."""
    actions: list[ActionTaken] = []

    if not envelope.guest_id:
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.PARTIAL,
            user_facing_message=(
                "Para consultar tu reserva necesito identificarte. "
                "Decime tu email o teléfono, y el código de reserva si lo tenés a mano."
            ),
        )

    reservation_id = raw.get("reservation_id")
    if reservation_id and can("get_reservation"):
        row = t.get_reservation(reservation_id, guest_id=str(envelope.guest_id))
        actions.append(ActionTaken(tool="get_reservation", result="ok" if row else "error",
                                    ref=reservation_id))
        if not row:
            return DelegationResult(
                from_agent=AgentName.RESERVAS,
                status=DelegationStatus.FAILED,
                user_facing_message="No encuentro esa reserva a tu nombre. ¿Podés verificar el código?",
                actions_taken=actions,
            )
        msg = _format_reservation(row)
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.OK,
            user_facing_message=msg,
            actions_taken=actions,
        )

    if can("list_reservations_for_guest"):
        rows = t.list_reservations_for_guest(str(envelope.guest_id))
        actions.append(ActionTaken(tool="list_reservations_for_guest", result="ok",
                                    ref=f"{len(rows)} rows"))
        if not rows:
            return DelegationResult(
                from_agent=AgentName.RESERVAS,
                status=DelegationStatus.OK,
                user_facing_message="No tengo reservas a tu nombre. ¿Querés armar una?",
                actions_taken=actions,
            )
        body = "\n\n".join(_format_reservation(r, brief=True) for r in rows)
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.OK,
            user_facing_message=f"Tenés estas reservas:\n\n{body}",
            actions_taken=actions,
        )

    return DelegationResult(
        from_agent=AgentName.RESERVAS,
        status=DelegationStatus.FAILED,
        internal_notes="Sin allowed_actions adecuadas para query_reservation",
    )


# =============================================================================
# book
# =============================================================================


def _handle_book(envelope: Delegation, raw: dict, can) -> DelegationResult:
    """Crea reserva en pending_payment + envía prompt manual de pago."""
    actions: list[ActionTaken] = []

    # 1. Validar parámetros mínimos que el Concierge debió extraer
    check_in = raw.get("check_in")
    check_out = raw.get("check_out")
    category_id = raw.get("category_id")
    n_adults = int(raw.get("n_adults") or 1)
    n_children = int(raw.get("n_children") or 0)

    missing = []
    if not check_in: missing.append("fecha de check-in")
    if not check_out: missing.append("fecha de check-out")
    if not category_id: missing.append("tipo de habitación (single, double, twin, suite)")

    if missing:
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.PARTIAL,
            user_facing_message=(
                f"Para armar la reserva necesito: {', '.join(missing)}. "
                "¿Me lo confirmás?"
            ),
        )

    # Validar fechas razonables (R13: no permitir pasado)
    try:
        ci = date.fromisoformat(check_in)
        co = date.fromisoformat(check_out)
    except ValueError:
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.FAILED,
            user_facing_message="Las fechas no se ven válidas. ¿Las podés decir de nuevo?",
        )
    today = date.today()
    if ci < today:
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.FAILED,
            user_facing_message="La fecha de ingreso ya pasó. ¿Querés probar con otra?",
        )
    if co <= ci:
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.FAILED,
            user_facing_message="El check-out tiene que ser después del check-in.",
        )
    nights = (co - ci).days

    # 2. Necesitamos guest_id. Si no hay, pedimos datos al huésped.
    guest_id = str(envelope.guest_id) if envelope.guest_id else None
    if not guest_id:
        # Extraído del LLM si vino
        name = (raw.get("guest_name") or "").strip() or None
        email = (raw.get("guest_email") or "").strip().lower() or None
        phone = (raw.get("guest_phone") or "").strip() or None

        if not email and not phone:
            return DelegationResult(
                from_agent=AgentName.RESERVAS,
                status=DelegationStatus.PARTIAL,
                user_facing_message=(
                    "Genial, hay un detalle: para confirmar la reserva necesito "
                    "tu **nombre completo** y un **email o teléfono** de contacto."
                ),
            )
        if not can("upsert_guest"):
            return DelegationResult(
                from_agent=AgentName.RESERVAS,
                status=DelegationStatus.FAILED,
                internal_notes="upsert_guest no permitido por allowed_actions",
            )
        guest = t.upsert_guest(full_name=name, email=email, phone=phone,
                               language_pref=envelope.guest_context.language)
        guest_id = guest["guest_id"]
        actions.append(ActionTaken(tool="upsert_guest", result="ok", ref=guest_id))
        # Adjuntar a la conversación
        try:
            t.attach_guest_to_conversation(str(envelope.conversation_id), guest_id)
        except Exception as exc:
            logger.warning("attach_guest_to_conversation falló: %s", exc)

    # 3. Check availability
    if not can("check_availability"):
        return DelegationResult(from_agent=AgentName.RESERVAS, status=DelegationStatus.FAILED,
                                internal_notes="check_availability no permitido")
    rooms = t.check_availability(check_in, check_out, category_id)
    actions.append(ActionTaken(tool="check_availability", result="ok",
                                ref=f"{len(rooms)} rooms"))
    if not rooms:
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.PARTIAL,
            user_facing_message=(
                f"No tengo habitaciones {category_id} disponibles del "
                f"{check_in} al {check_out}. ¿Querés que pruebe con otro tipo de "
                f"habitación o cambiando las fechas?"
            ),
            actions_taken=actions,
        )

    # 4. Rate
    if not can("get_rate"):
        return DelegationResult(from_agent=AgentName.RESERVAS, status=DelegationStatus.FAILED,
                                internal_notes="get_rate no permitido")
    rate = t.get_rate(category_id)
    actions.append(ActionTaken(tool="get_rate", result="ok" if rate else "error",
                                ref=str(rate)))
    if rate is None:
        return DelegationResult(from_agent=AgentName.RESERVAS, status=DelegationStatus.FAILED,
                                internal_notes=f"no rate para {category_id}")
    total = float(rate) * nights

    # 5. Create reservation (pending_payment)
    if not can("create_reservation"):
        return DelegationResult(from_agent=AgentName.RESERVAS, status=DelegationStatus.FAILED,
                                internal_notes="create_reservation no permitido")
    room = rooms[0]
    try:
        res = t.create_reservation(
            guest_id=guest_id,
            room_id=room["room_id"],
            check_in=check_in,
            check_out=check_out,
            total_amount_usd=total,
            n_adults=n_adults,
            n_children=n_children,
            payment_hold_hours=settings.payment_hold_ttl_hours,
        )
    except Exception as exc:
        # Probable doble-booking (constraint EXCLUDE)
        logger.warning("create_reservation falló: %s", exc)
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.PARTIAL,
            user_facing_message=(
                "Esa habitación se reservó justo ahora. Probá con otras fechas o "
                "tipo de habitación, por favor."
            ),
            actions_taken=actions,
        )
    actions.append(ActionTaken(tool="create_reservation", result="ok",
                                ref=res["reservation_id"]))

    # 6. Mensaje al huésped con flujo manual de pago
    short_code = res["reservation_id"].split("-")[0]
    user_msg = (
        f"✅ Tengo la reserva lista:\n"
        f"• Habitación {room['room_number']} ({category_id})\n"
        f"• Del {check_in} al {check_out} ({nights} noche{'s' if nights != 1 else ''})\n"
        f"• Total: USD {total:.2f}\n\n"
        f"Código de reserva: `{short_code}`\n\n"
        f"La habitación queda bloqueada por {settings.payment_hold_ttl_hours} horas. "
        f"Cuando hagas la transferencia, escribime *\"ya pagué\"* y la confirmo."
    )
    return DelegationResult(
        from_agent=AgentName.RESERVAS,
        status=DelegationStatus.OK,
        user_facing_message=user_msg,
        actions_taken=actions,
        internal_notes=f"reservation_id={res['reservation_id']} total={total}",
    )


# =============================================================================
# payment_confirm
# =============================================================================


def _handle_payment_confirm(envelope: Delegation, raw: dict, can) -> DelegationResult:
    """El huésped dice 'ya pagué'. Buscamos su última reserva pending_payment."""
    actions: list[ActionTaken] = []

    if not envelope.guest_id:
        return DelegationResult(
            from_agent=AgentName.RESERVAS, status=DelegationStatus.PARTIAL,
            user_facing_message="¿Sobre qué código de reserva confirmás? Pasame el código por favor.",
        )

    reservations = t.list_reservations_for_guest(str(envelope.guest_id))
    pending = [r for r in reservations if r["status"] == "pending_payment"]
    if not pending:
        return DelegationResult(
            from_agent=AgentName.RESERVAS, status=DelegationStatus.OK,
            user_facing_message="No tengo reservas pendientes de pago a tu nombre. ¿Es esto correcto?",
        )

    if not can("mark_reservation_paid"):
        return DelegationResult(from_agent=AgentName.RESERVAS, status=DelegationStatus.FAILED,
                                internal_notes="mark_reservation_paid no permitido")

    # Confirma la más vieja primero (FIFO)
    target = pending[0]
    updated = t.mark_reservation_paid(target["reservation_id"])
    actions.append(ActionTaken(tool="mark_reservation_paid",
                                result="ok" if updated else "error",
                                ref=target["reservation_id"]))
    if not updated:
        return DelegationResult(from_agent=AgentName.RESERVAS, status=DelegationStatus.FAILED,
                                user_facing_message="No pude actualizar la reserva, te paso con recepción.",
                                actions_taken=actions)
    short = target["reservation_id"].split("-")[0]
    return DelegationResult(
        from_agent=AgentName.RESERVAS, status=DelegationStatus.OK,
        user_facing_message=(
            f"¡Perfecto! Confirmamos la reserva `{short}` por USD {target['total_amount_usd']}. "
            f"Te esperamos el {target['check_in']} desde las 15:00 hs 🌊"
        ),
        actions_taken=actions,
    )


# =============================================================================
# Helpers
# =============================================================================


def _format_reservation(row: dict, brief: bool = False) -> str:
    short = row["reservation_id"].split("-")[0]
    status_es = {
        "pending_payment": "esperando pago",
        "confirmed": "confirmada",
        "checked_in": "check-in hecho",
        "checked_out": "checkout hecho",
        "cancelled": "cancelada",
        "no_show": "no-show",
    }.get(row["status"], row["status"])

    if brief:
        return (
            f"• `{short}` · {row['check_in']} → {row['check_out']} · {status_es} · "
            f"USD {row['total_amount_usd']}"
        )
    return (
        f"📋 Reserva `{short}`\n"
        f"• Fechas: {row['check_in']} → {row['check_out']}\n"
        f"• Estado: {status_es}\n"
        f"• Total: USD {row['total_amount_usd']}"
    )
