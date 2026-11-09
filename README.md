# Atendimento via WhatsApp

Projeto de automação de atendimento usando a WhatsApp Cloud API oficial. O desenvolvimento começa pelo simulador local; nenhuma credencial da Meta é necessária para iniciar a API.

## Requisitos

- Python 3.12
- Docker Compose (para subir API, worker, PostgreSQL e Redis)

## Desenvolvimento local

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m alembic upgrade head
python -m pytest
```

## Subir os serviços

Após configurar `.env`, execute:

```powershell
docker compose up --build
```

A API fica disponível em `http://localhost:8000`; verifique a inicialização em `http://localhost:8000/health` e consulte a documentação OpenAPI em `http://localhost:8000/docs`.

O serviço da API executa as migrações Alembic antes de iniciar. No uso fora do Compose, aplique-as com `python -m alembic upgrade head`.

O `.env.example` contém apenas valores locais de desenvolvimento. Não use esses valores em ambientes compartilhados ou de produção e nunca inclua tokens reais no repositório.

## Componentes implementados

- `SimulatorAdapter` analisa payloads locais no formato de webhook e captura mensagens de saída sem chamar a Meta.
- A máquina de estados mantém a conversa no bot ou no atendimento humano, sugere handoff após duas falhas seguidas e aplica expiração configurável.
- O primeiro contato identifica o bot e apresenta opções interativas para consentimento ou atendimento humano.
- O FAQ determinístico busca evidências em artigos e cita o título da fonte; perguntas sem cobertura suficiente ou com resultados ambíguos devem seguir para atendimento humano.
- O webhook verifica o token de inscrição, valida HMAC `X-Hub-Signature-256`, limita o tamanho e a taxa de requisições via Redis e persiste eventos antes de enfileirá-los.
- O worker grava mensagens recebidas com deduplicação por `wamid`; as migrações criam as tabelas de contatos, conversas, mensagens e demais domínios.

Para exercitar a jornada de primeiro contato e FAQ no worker, defina
`SIMULATOR_BUSINESS_NAME` no `.env` com o nome fictício do negócio. O modo é
desativado por padrão. As respostas são armazenadas em `messages` com
`direction=OUTBOUND` e `delivery_status=SIMULATED`; **não são enviadas ao
WhatsApp**. A base de artigos deve ser cadastrada em `knowledge_articles`;
nenhum conteúdo comercial é criado automaticamente. A escolha de continuar é
mantida apenas no estado da conversa e não registra opt-in de marketing.
PARAR, SAIR e CANCELAR registram opt-out no contato mesmo fora do modo
simulado; o histórico é salvo em `consent_events`. O serviço de registro
de opt-in de marketing exige uma fonte explícita. No simulador, após aceitar
o atendimento, digite `MARKETING` para abrir uma pergunta opcional e autorizar
ou recusar por botão; essa autorização é distinta do aceite de atendimento.
Uma resposta enviada no mesmo segundo da pergunta é rejeitada por segurança;
nesse caso, solicite a pergunta novamente. O bloqueio de envios ativos reais
ainda precisa ser implementado. O
handoff humano ainda não está disponível; a simulação informa essa limitação.
Não habilite este modo como integração real com a Meta.

Na simulação, após aceitar a mensagem inicial, digite `pedido` para consultar
um pedido cadastrado na tabela `simulated_orders`. O número deve ter de 4 a
20 dígitos ASCII e o registro deve estar vinculado ao contato simulado.
Não há pedidos pré-cadastrados. A associação por contato serve apenas à
simulação e não substitui autenticação para uma integração real.

O serviço simulado de agendamentos em `src/integrations/appointments.py`
oferece horários fixos de 30 minutos, alinhados em UTC, por serviço. Ele cria,
lista e cancela reservas por contato e sugere alternativas em caso de conflito.
O chamador deve confirmar ou reverter a transação do banco. Não há catálogo de
serviços nem horário comercial configurados; a jornada de agendamento no
simulador e a integração com uma agenda real ainda não foram implementadas.

O componente `src/flows/message_policy.py` verifica a janela de 24 horas,
o consentimento para mensagens ativas e templates de uma lista aprovada
fornecida pelo chamador. `GuardedChannel` aplica essa política antes de
delegar um envio e consulta o contexto novamente a cada mensagem. O worker
simulado e qualquer futuro canal real **ainda não usam esse adaptador**;
o catálogo aprovado, o contexto confiável, a contagem de uso e a sincronização
do opt-out com o envio real precisam ser integrados antes de mensagens reais.

Os testes de contrato, fluxo e API rodam com `python -m pytest`; não precisam de Docker nem de credenciais da Meta.

## Verificações

```powershell
python -m pytest
ruff check .
mypy
```
