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

Opcionalmente, configure `SIMULATOR_BUSINESS_HOURS` com JSON para informar
quando um pedido de atendimento humano chega fora do expediente. Por exemplo:

```text
SIMULATOR_BUSINESS_HOURS={"timezone":"America/Sao_Paulo","intervals":[{"weekday":0,"start":"09:00","end":"18:00"}]}
```

O exemplo define apenas segunda-feira; `weekday` vai de 0 (segunda) a 6
(domingo). Cada intervalo pertence a um único dia, inclui o início e exclui o
fim. Dias sem intervalos estão fechados; turnos que atravessam a meia-noite
não são suportados. Informe um fuso IANA disponível no sistema. Sem essa
configuração, o simulador não presume expediente. Ela não aplica restrições a
agendamentos nem cria fila de atendimento; não substitui integração real.

O serviço interno `src/handoff/service.py` permite criar e listar tickets abertos,
transferir a posse para atendimento humano e devolver a conversa ao bot,
fechando o ticket na mesma transação. O chamador deve confirmar ou reverter
essa transação. Em PostgreSQL, as operações serializam pela linha da conversa;
SQLite é apenas para desenvolvimento e não fornece o mesmo bloqueio. Uma
conversa sob atendimento humano não expira automaticamente. Esse serviço ainda
não está conectado ao simulador, a uma interface de atendente ou ao Chatwoot:
não existe fila operacional nem entrega ao atendente.
`list_open_tickets` oferece uma consulta paginada, ordenada por criação e ID;
ela não reserva tickets para atendentes e páginas podem mudar entre consultas.

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
simulador aceita comandos após o aceite inicial:

- `AGENDAR Consulta | 01/01/2035 10:00` cria uma reserva simulada.
- `AGENDAMENTOS` lista as reservas ativas do contato.
- `DESMARCAR <código>` cancela uma reserva do contato.

Todos os horários são em UTC, futuros e em intervalos de 30 minutos; em caso
de conflito são sugeridas alternativas. Os nomes de serviços são livres e a
disponibilidade é apenas simulada, sem aplicação de horário comercial.
`CANCELAR` continua sendo opt-out de mensagens ativas e não cancela reservas.
Não há integração com uma agenda real nem autenticação suficiente para usá-la.

O componente `src/flows/message_policy.py` verifica a janela de 24 horas,
o consentimento para mensagens ativas e templates de uma lista aprovada
fornecida pelo chamador. `GuardedChannel` aplica essa política antes de
delegar um envio e consulta o contexto novamente a cada mensagem. O worker
simulado e qualquer futuro canal real **ainda não usam esse adaptador**;
o catálogo aprovado, o contexto confiável, a contagem de uso e a sincronização
do opt-out com o envio real precisam ser integrados antes de mensagens reais.

O serviço interno `src/usage/service.py` registra contagem mensal em UTC por
número e categoria, de modo idempotente por mensagem e na transação do chamador.
Aceita apenas mensagens de saída persistidas, com identificador do canal e
status confirmado (`SENT`, `DELIVERED` ou `READ`); mensagens simuladas não
contam. A categoria e o horário de envio são responsabilidade do chamador.
Essa é uma contagem técnica, não uma estimativa de cobrança da Meta. O serviço
ainda não está conectado a um canal real ou aos callbacks e não reconcilia
alterações de categoria, falhas posteriores nem dados de faturamento oficiais.
O downgrade da migração de contagem é bloqueado se houver registros, para
evitar contagens duplicadas em reprocessamentos. Se mensagens forem excluídas,
seus registros de idempotência também são excluídos, mas os agregados permanecem;
qualquer futura política de retenção deve levar isso em conta.

Os testes de contrato, fluxo e API rodam com `python -m pytest`; não precisam de Docker nem de credenciais da Meta.

## Verificações

```powershell
python -m pytest
ruff check .
mypy
```

Os testes concorrentes de PostgreSQL são opcionais e gravam dados de teste.
Para executá-los, use **somente um banco PostgreSQL descartável e isolado**,
aplique as migrações e forneça a URL desse banco em
`TEST_POSTGRESQL_DATABASE_URL`:

```powershell
python -m pytest tests\integration\test_usage_postgresql.py tests\integration\test_handoff_postgresql.py
```

Sem essa variável, os dois testes são ignorados. Não aponte para banco de
desenvolvimento compartilhado ou produção.
