from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from src.channel.adapter import ChannelAdapter
from src.integrations.appointments import (
    AppointmentConflict,
    AppointmentService,
    InvalidAppointment,
)


def handle_appointment_command(
    channel: ChannelAdapter,
    recipient: str,
    text: str,
    service: AppointmentService,
    contact_id: UUID,
) -> bool:
    command, _, arguments = text.strip().partition(" ")
    command = command.casefold()
    if command == "agendar":
        name, separator, raw_time = arguments.partition("|")
        try:
            if not separator:
                raise ValueError("missing separator")
            start = datetime.strptime(raw_time.strip(), "%d/%m/%Y %H:%M").replace(tzinfo=UTC)
        except ValueError:
            channel.send_text(
                recipient, "Formato: AGENDAR serviço | DD/MM/AAAA HH:MM (horário UTC)."
            )
            return True
        try:
            appointment = service.book(contact_id, name, start)
        except AppointmentConflict as error:
            alternatives = ", ".join(_format_time(value) for value in error.alternatives)
            suffix = f" Alternativas em UTC: {alternatives}." if alternatives else ""
            channel.send_text(recipient, f"Horário indisponível.{suffix}")
            return True
        except InvalidAppointment:
            channel.send_text(
                recipient, "Serviço ou horário inválido: use horário futuro em intervalos "
                "de 30 minutos, em UTC."
            )
            return True
        channel.send_text(
            recipient,
            f"Agendamento simulado confirmado: {appointment.service}, "
            f"{_format_time(start)} UTC. Código: {appointment.id}.",
        )
        return True

    if command == "agendamentos" and not arguments.strip():
        appointments = [
            item for item in service.list_for_contact(contact_id) if item.status == "BOOKED"
        ]
        if not appointments:
            channel.send_text(recipient, "Nenhum agendamento simulado ativo para este contato.")
        else:
            lines = [
                f"{item.service}: {_format_time(item.starts_at)} UTC — {item.id}"
                for item in appointments
            ]
            channel.send_text(recipient, "Agendamentos simulados:\n" + "\n".join(lines))
        return True

    if command == "desmarcar":
        try:
            appointment_id = UUID(arguments.strip())
        except ValueError:
            channel.send_text(recipient, "Informe DESMARCAR seguido do código do agendamento.")
            return True
        if service.cancel(contact_id, appointment_id):
            channel.send_text(recipient, "Agendamento simulado desmarcado.")
        else:
            channel.send_text(recipient, "Agendamento ativo não encontrado para este contato.")
        return True
    return False


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%d/%m/%Y %H:%M")
