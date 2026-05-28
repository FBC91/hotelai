"""
hotelai.agents.reservas
========================

Agente Reservas v2. Mejoras:
    - Acepta reservation_id en formato corto (prefijo de UUID) via
      find_reservation_by_short_code.
    - Mejora mensajes para que el huesped entienda que falta y que tiene.
    - cancel_reservation soportado.
"""

from __future__ import annotations

import logging
from datetime import date

from ..schemas import (
    ActionTaken, AgentName, Delegation, DelegationResult, DelegationStatus,
)
from ..settings import settings
from .tools import db_tools as t

logger = logging.getLogger("hotelai.reservas")


def handle(envelope: Delegation, raw_inputs: dict | None = None) -> DelegationResult:
    raw_inputs = raw_inputs or {}

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
        if intent == "cancel":
            return _handle_cancel(envelope, raw_inputs, can)
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.PARTIAL,
            user_facing_message=(
                "Esa accion aun no esta implementada. Te paso con recepcion."
            ),
            internal_notes=f"intent={intent} no soportado",
        )
    except Exception as exc:
        logger.exception("reservas error trace=%s", envelope.trace_id)
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.FAILED,
            internal_notes=f"{type(exc).__name__}: {exc}",
        )


def _handle_query(envelope: Delegation, raw: dict, can) -> DelegationResult:
    actions: list[ActionTaken] = []

    if not envelope.guest_id:
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.PARTIAL,
            user_facing_message=(
                "Para consultar tu reserva necesito identificarte. "
                "Decime tu email completo o telefono. Si tenes el codigo de "
                "reserva (los primeros 8 caracteres alcanzan), pasamelo tambien."
            ),
        )

    reservation_id = (raw.get("reservation_id") or "").strip()

    if reservation_id and can("find_reservation_by_short_code"):
        row = t.find_reservation_by_short_code(reservation_id, guest_id=str(envelope.guest_id))
        actions.append(ActionTaken(
            tool="find_reservation_by_short_code",
            result="ok" if row else "error",
            ref=reservation_id,
        ))
        if row:
            return DelegationResult(
                from_agent=AgentName.RESERVAS,
                status=DelegationStatus.OK,
                user_facing_message=_format_reservation(row),
                actions_taken=actions,
            )
        # No matchea por prefijo - listamos las del huesped igual
        if can("list_reservations_for_guest"):
            rows = t.list_reservations_for_guest(str(envelope.guest_id))
            actions.append(ActionTaken(
                tool="list_reservations_for_guest", result="ok",
                ref=f"{len(rows)} rows",
            ))
            if not rows:
                return DelegationResult(
                    from_agent=AgentName.RESERVAS,
                    status=DelegationStatus.OK,
                    user_facing_message=(
                        f"No encuentro la reserva `{reservation_id}` a tu nombre y "
                        f"tampoco tenes otras reservas. Queres armar una nueva?"
                    ),
                    actions_taken=actions,
                )
            body = "\n".join(_format_reservation(r, brief=True) for r in rows)
            return DelegationResult(
                from_agent=AgentName.RESERVAS,
                status=DelegationStatus.OK,
                user_facing_message=(
                    f"No encontre la reserva `{reservation_id}`, pero tenes estas otras:\n\n{body}"
                ),
                actions_taken=actions,
            )

    # Sin reservation_id: listar todas
    if can("list_reservations_for_guest"):
        rows = t.list_reservations_for_guest(str(envelope.guest_id))
        actions.append(ActionTaken(
            tool="list_reservations_for_guest", result="ok",
            ref=f"{len(rows)} rows",
        ))
        if not rows:
            return DelegationResult(
                from_agent=AgentName.RESERVAS,
                status=DelegationStatus.OK,
                user_facing_message="No tengo reservas a tu nombre. Queres armar una?",
                actions_taken=actions,
            )
        body = "\n".join(_format_reservation(r, brief=True) for r in rows)
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.OK,
            user_facing_message=f"Tenes estas reservas:\n\n{body}",
            actions_taken=actions,
        )

    return DelegationResult(
        from_agent=AgentName.RESERVAS,
        status=DelegationStatus.FAILED,
        internal_notes="Sin allowed_actions para query",
    )


def _handle_book(envelope: Delegation, raw: dict, can) -> DelegationResult:
    actions: list[ActionTaken] = []

    check_in = raw.get("check_in")
    check_out = raw.get("check_out")
    category_id = raw.get("category_id")
    n_adults = int(raw.get("n_adults") or 1)
    n_children = int(raw.get("n_children") or 0)

    missing = []
    if not check_in: missing.append("fecha de check-in")
    if not check_out: missing.append("fecha de check-out")
    if not category_id: missing.append("tipo de habitacion (single, double, twin, junior_suite, suite)")
    if missing:
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.PARTIAL,
            user_facing_message=f"Para la reserva necesito: {', '.join(missing)}.",
        )

    try:
        ci = date.fromisoformat(check_in)
        co = date.fromisoformat(check_out)
    except ValueError:
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.FAILED,
            user_facing_message="Las fechas no se ven validas. Las podes confirmar?",
        )
    today = date.today()
    if ci < today:
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.FAILED,
            user_facing_message="La fecha de ingreso ya paso. Queres probar con otra?",
        )
    if co <= ci:
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.FAILED,
            user_facing_message="El check-out tiene que ser despues del check-in.",
        )
    nights = (co - ci).days

    # Identidad del guest
    guest_id = str(envelope.guest_id) if envelope.guest_id else None
    if not guest_id:
        name = (raw.get("guest_name") or "").strip() or None
        email = (raw.get("guest_email") or "").strip().lower() or None
        phone = (raw.get("guest_phone") or "").strip() or None
        if not email and not phone:
            return DelegationResult(
                from_agent=AgentName.RESERVAS,
                status=DelegationStatus.PARTIAL,
                user_facing_message=(
                    "Para confirmar la reserva necesito tu nombre completo y un "
                    "email o telefono de contacto."
                ),
            )
        if not can("upsert_guest"):
            return DelegationResult(
                from_agent=AgentName.RESERVAS, status=DelegationStatus.FAILED,
                internal_notes="upsert_guest no permitido",
            )
        guest = t.upsert_guest(full_name=name, email=email, phone=phone,
                               language_pref=envelope.guest_context.language)
        guest_id = guest["guest_id"]
        actions.append(ActionTaken(tool="upsert_guest", result="ok", ref=guest_id))
        try:
            t.attach_guest_to_conversation(str(envelope.conversation_id), guest_id)
        except Exception:
            pass

    # Disponibilidad
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
                f"No tengo habitaciones {category_id} disponibles del {check_in} al "
                f"{check_out}. Queres probar con otro tipo o cambiar fechas?"
            ),
            actions_taken=actions,
        )

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

    if not can("create_reservation"):
        return DelegationResult(from_agent=AgentName.RESERVAS, status=DelegationStatus.FAILED,
                                internal_notes="create_reservation no permitido")
    room = rooms[0]
    try:
        res = t.create_reservation(
            guest_id=guest_id, room_id=room["room_id"],
            check_in=check_in, check_out=check_out,
            total_amount_usd=total, n_adults=n_adults, n_children=n_children,
            payment_hold_hours=settings.payment_hold_ttl_hours,
        )
    except Exception as exc:
        logger.warning("create_reservation fallo: %s", exc)
        return DelegationResult(
            from_agent=AgentName.RESERVAS,
            status=DelegationStatus.PARTIAL,
            user_facing_message=(
                "Esa habitacion se reservo justo ahora. Proba con otras fechas o "
                "tipo de habitacion."
            ),
            actions_taken=actions,
        )
    actions.append(ActionTaken(tool="create_reservation", result="ok",
                                ref=res["reservation_id"]))

    short_code = res["reservation_id"].split("-")[0]
    user_msg = (
        f"Tengo la reserva lista:\n"
        f"- Habitacion {room['room_number']} ({category_id})\n"
        f"- Del {check_in} al {check_out} ({nights} noche{'s' if nights != 1 else ''})\n"
        f"- Total: USD {total:.2f}\n\n"
        f"Codigo: `{short_code}`\n\n"
        f"La habitacion queda reservada por {settings.payment_hold_ttl_hours} horas. "
        f"Cuando hagas la transferencia, escribime \"ya pague\" y la confirmo."
    )
    return DelegationResult(
        from_agent=AgentName.RESERVAS,
        status=DelegationStatus.OK,
        user_facing_message=user_msg,
        actions_taken=actions,
        internal_notes=f"reservation_id={res['reservation_id']} total={total}",
    )


def _handle_payment_confirm(envelope: Delegation, raw: dict, can) -> DelegationResult:
    actions: list[ActionTaken] = []
    if not envelope.guest_id:
        return DelegationResult(
            from_agent=AgentName.RESERVAS, status=DelegationStatus.PARTIAL,
            user_facing_message="Sobre que codigo de reserva confirmas? Decime tu email para identificarte.",
        )

    reservations = t.list_reservations_for_guest(str(envelope.guest_id))
    pending = [r for r in reservations if r["status"] == "pending_payment"]
    if not pending:
        return DelegationResult(
            from_agent=AgentName.RESERVAS, status=DelegationStatus.OK,
            user_facing_message="No tengo reservas pendientes de pago a tu nombre.",
        )

    if not can("mark_reservation_paid"):
        return DelegationResult(from_agent=AgentName.RESERVAS, status=DelegationStatus.FAILED,
                                internal_notes="mark_reservation_paid no permitido")

    target = pending[0]
    updated = t.mark_reservation_paid(target["reservation_id"])
    actions.append(ActionTaken(tool="mark_reservation_paid",
                                result="ok" if updated else "error",
                                ref=target["reservation_id"]))
    if not updated:
        return DelegationResult(from_agent=AgentName.RESERVAS, status=DelegationStatus.FAILED,
                                user_facing_message="No pude actualizar, te paso con recepcion.",
                                actions_taken=actions)
    short = target["reservation_id"].split("-")[0]
    return DelegationResult(
        from_agent=AgentName.RESERVAS, status=DelegationStatus.OK,
        user_facing_message=(
            f"Perfecto! Confirmamos la reserva `{short}` por USD {target['total_amount_usd']}. "
            f"Te esperamos el {target['check_in']} desde las 15:00 hs."
        ),
        actions_taken=actions,
    )


def _handle_cancel(envelope: Delegation, raw: dict, can) -> DelegationResult:
    """Cancelacion simple (sin politica de refund automatico - escalamos).

    En esta version pedimos confirmacion humana para el refund. Para MVP basta
    con marcar la reserva como cancelled y notificar.
    """
    actions: list[ActionTaken] = []
    if not envelope.guest_id:
        return DelegationResult(
            from_agent=AgentName.RESERVAS, status=DelegationStatus.PARTIAL,
            user_facing_message="Para cancelar necesito identificarte. Decime tu email.",
        )
    reservation_id = (raw.get("reservation_id") or "").strip()
    target = None
    if reservation_id:
        target = t.find_reservation_by_short_code(reservation_id, guest_id=str(envelope.guest_id))
        actions.append(ActionTaken(tool="find_reservation_by_short_code",
                                    result="ok" if target else "error", ref=reservation_id))
    if not target:
        # Tomar la mas reciente cancelable
        rows = [r for r in t.list_reservations_for_guest(str(envelope.guest_id))
                if r["status"] in ("pending_payment", "confirmed")]
        if not rows:
            return DelegationResult(
                from_agent=AgentName.RESERVAS, status=DelegationStatus.OK,
                user_facing_message="No tengo reservas cancelables a tu nombre.",
                actions_taken=actions,
            )
        if len(rows) > 1:
            body = "\n".join(_format_reservation(r, brief=True) for r in rows)
            return DelegationResult(
                from_agent=AgentName.RESERVAS, status=DelegationStatus.PARTIAL,
                user_facing_message=f"Tenes varias reservas. Cual queres cancelar? Pasa el codigo:\n\n{body}",
                actions_taken=actions,
            )
        target = rows[0]
    try:
        updated = t.cancel_reservation(target["reservation_id"], guest_id=str(envelope.guest_id))
    except Exception as exc:
        return DelegationResult(from_agent=AgentName.RESERVAS, status=DelegationStatus.FAILED,
                                internal_notes=str(exc))
    actions.append(ActionTaken(tool="cancel_reservation",
                                result="ok" if updated else "error",
                                ref=target["reservation_id"]))
    short = target["reservation_id"].split("-")[0]
    return DelegationResult(
        from_agent=AgentName.RESERVAS, status=DelegationStatus.OK,
        user_facing_message=(
            f"Cancele la reserva `{short}`. El equipo te confirma por email el "
            f"reintegro segun politica."
        ),
        actions_taken=actions,
    )


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
        return f"- `{short}` · {row['check_in']} -> {row['check_out']} · {status_es} · USD {row['total_amount_usd']}"
    return (
        f"Reserva `{short}`\n"
        f"- Fechas: {row['check_in']} -> {row['check_out']}\n"
        f"- Estado: {status_es}\n"
        f"- Total: USD {row['total_amount_usd']}"
    )
