from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID

from src.channel.adapter import ChannelAdapter, InboundMessage
from src.flows.appointment_journey import handle_appointment_command
from src.flows.business_hours import BusinessHours
from src.flows.welcome import send_first_contact
from src.integrations.appointments import AppointmentService
from src.integrations.orders import InvalidOrderNumber, OrderLookup
from src.knowledge.faq import ArticleLike, FAQService


def handle_simulated_turn(
    channel: ChannelAdapter,
    message: InboundMessage,
    *,
    state: str,
    is_first_contact: bool,
    business_name: str,
    business_hours: BusinessHours | None,
    articles: Sequence[ArticleLike],
    orders: OrderLookup,
    appointments: AppointmentService,
    contact_id: UUID,
    confirm_marketing: Callable[[], bool],
) -> str:
    if is_first_contact:
        send_first_contact(channel, message.sender, business_name)
        state = "awaiting_consent"

    text = (message.text or "").strip()
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    if message.selection_id == "human_handoff" or normalized in {
        "humano",
        "atendente",
        "falar com pessoa",
        "falar com atendente",
        "falar com humano",
    }:
        response = "O atendimento humano ainda não está disponível nesta demonstração."
        if business_hours is not None and not business_hours.is_open(
            datetime.fromtimestamp(message.timestamp, UTC)
        ):
            response += " A mensagem foi recebida fora do horário comercial configurado."
        channel.send_text(message.sender, response)
        return state

    if is_first_contact:
        return state

    if state == "awaiting_consent":
        if message.selection_id == "consent_yes" or normalized == "aceito":
            channel.send_text(
                message.sender,
                "Obrigado. Qual é a sua dúvida? Para consultar um pedido, digite PEDIDO. "
                "Para agendar na simulação, digite AGENDAR.",
            )
            return "faq"
        channel.send_text(
            message.sender,
            "Para continuar, escolha ACEITO ou peça para falar com uma pessoa.",
        )
        return state

    if state == "awaiting_order":
        try:
            order = orders.lookup(contact_id, text)
        except InvalidOrderNumber:
            channel.send_text(message.sender, "Número inválido. Informe de 4 a 20 dígitos.")
            return state
        if order is None:
            channel.send_text(message.sender, "Não encontrei esse pedido para este contato.")
        else:
            response = f"Pedido {order.number}: {order.status}."
            if order.expected_date is not None:
                response += f" Previsão: {order.expected_date:%d/%m/%Y}."
            channel.send_text(message.sender, response)
        return "faq"

    if state.startswith("awaiting_marketing:"):
        if message.selection_id == "marketing_yes":
            prompt_timestamp = int(state.removeprefix("awaiting_marketing:"))
            if message.timestamp > prompt_timestamp and confirm_marketing():
                channel.send_text(message.sender, "Sua autorização de marketing foi registrada.")
            else:
                channel.send_text(
                    message.sender,
                    "Não foi possível registrar essa confirmação. "
                    "Digite MARKETING para tentar novamente.",
                )
            return "faq"
        if message.selection_id == "marketing_no":
            channel.send_text(message.sender, "Tudo bem. Nenhuma autorização foi concedida.")
            return "faq"
        channel.send_text(
            message.sender, "Escolha uma das opções para autorizar ou recusar o marketing."
        )
        return state

    if state != "faq":
        raise ValueError(f"Unknown simulated conversation state: {state}")

    if message.message_type == "text" and handle_appointment_command(
        channel, message.sender, text, appointments, contact_id
    ):
        return state

    if message.message_type == "text" and normalized == "marketing":
        channel.send_interactive(
            message.sender,
            {
                "type": "button",
                "body": (
                    "Você autoriza receber mensagens de marketing? "
                    "Essa escolha é opcional. Para revogar, envie PARAR."
                ),
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": "marketing_yes", "title": "Sim, autorizo"},
                        },
                        {"type": "reply", "reply": {"id": "marketing_no", "title": "Não autorizo"}},
                    ]
                },
            },
        )
        return f"awaiting_marketing:{message.timestamp}"

    if message.selection_id == "order_status" or normalized in {
        "pedido",
        "meu pedido",
        "status do pedido",
        "consultar pedido",
    }:
        channel.send_text(message.sender, "Informe o número do pedido (4 a 20 dígitos).")
        return "awaiting_order"

    answer = FAQService().answer(text, articles) if message.message_type == "text" else None
    if answer is not None:
        channel.send_text(message.sender, answer.text)
    else:
        channel.send_interactive(
            message.sender,
            {
                "type": "button",
                "body": "Não encontrei uma resposta confiável. Deseja falar com uma pessoa?",
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": "human_handoff", "title": "Falar com pessoa"},
                        }
                    ]
                },
            },
        )
    return state
