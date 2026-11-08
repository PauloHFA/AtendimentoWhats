from src.channel.adapter import ChannelAdapter, OutboundMessage


def send_first_contact(
    channel: ChannelAdapter, recipient: str, business_name: str
) -> tuple[OutboundMessage, OutboundMessage]:
    name = business_name.strip()
    if not name:
        raise ValueError("business_name must not be empty")

    introduction = (
        f"Olá! Sou o assistente automatizado da {name}. "
        "Para continuar, escolha ACEITO e os dados que você enviar serão usados "
        "para atender sua solicitação. Você pode falar com uma pessoa a qualquer "
        "momento ou digitar PARAR para bloquear mensagens ativas."
    )
    menu = {
        "type": "list",
        "body": "Como deseja continuar?",
        "action": {
            "button": "Opções",
            "sections": [
                {
                    "title": "Atendimento",
                    "rows": [
                        {
                            "id": "consent_yes",
                            "title": "ACEITO, continuar",
                            "description": "Concordo com o uso dos dados para atendimento.",
                        },
                        {
                            "id": "human_handoff",
                            "title": "Falar com pessoa",
                            "description": "Solicitar atendimento humano.",
                        },
                    ],
                }
            ],
        },
    }

    return (
        channel.send_text(recipient, introduction),
        channel.send_interactive(recipient, menu),
    )
