# Plano de Implementação: Automação de Atendimento via WhatsApp

**Data**: 2026-11-08 | **Especificação**: `Automação de Atendimento via WhatsApp Documento de Requisitos e Especificações.pdf`

## Resumo

Construir um MVP de atendimento automatizado pelo WhatsApp que começa com um simulador local e regras determinísticas, depois integra a WhatsApp Cloud API oficial. O sistema terá webhook validado, processamento assíncrono e idempotente, sessões de conversa, FAQ fundamentado, consulta de pedidos, agendamentos simulados, consentimento e transferência para atendente. A IA com RAG fica prevista como fase posterior ao MVP, limitada ao conteúdo do negócio.

O plano preserva a sequência do documento: primeiro tornar o fluxo reproduzível sem WhatsApp; depois validar o canal oficial em sandbox; por fim concluir integrações, handoff, métricas e uma fase opcional de IA. As escolhas técnicas abaixo são premissas recomendadas, ainda não confirmadas pelo usuário.

## Contexto técnico

**Linguagem/versão**: Python 3.12  
**API**: FastAPI  
**Fila e sessões temporárias**: Redis + Celery  
**Persistência**: PostgreSQL 16 e migrações versionadas  
**Canal**: interface `ChannelAdapter`, simulador local e WhatsApp Cloud API oficial  
**Atendimento humano**: integração com Chatwoot, como opção de menor esforço  
**Execução local**: Docker Compose com API, worker, PostgreSQL, Redis e simulador  
**Testes**: pytest, FastAPI TestClient/httpx, respx, diálogos dourados e testes de integração com PostgreSQL/Redis reais  
**IA**: fora do MVP inicial; fase posterior com provedor abstraído, RAG local e guardrails  
**Custo de desenvolvimento/teste**: R$ 0, usando simulador e sandbox Meta; não incluir chamadas pagas em testes automatizados  
**Restrições**: regras de negócio independentes da Meta; deduplicação por `wamid`; janela de 24 h e templates; opt-in/opt-out; acesso humano sempre disponível; minimização e retenção de dados; não registrar segredos ou PII em logs.

## Premissas e decisões provisórias

1. Adotar a stack recomendada no PDF: FastAPI, PostgreSQL, Redis/Celery, Docker Compose e Cloud API oficial.
2. Usar Chatwoot para o primeiro painel de atendimento; uma tela própria permanece alternativa, não parte do escopo atual.
3. Implementar primeiro FAQ por regras/busca simples. A IA/RAG entra depois da validação do MVP.
4. Manter integrações de pedidos e agenda como APIs internas simuladas; não pressupor acesso a ERP/CRM reais.
5. Usar a clínica/loja de serviços do documento como dados de demonstração configuráveis, sem fixar regras de um negócio real.
6. O PDF usa IDs `RF`, `RNF` e `RN`, não `REQ-XXX`; o plano preserva os IDs originais para evitar uma tradução artificial.

## Verificação da constituição

Não foi encontrado `constitution.md` no workspace. Como referência provisória, os princípios e limites abaixo vêm diretamente da especificação:

| Princípio da especificação | Verificação |
|---|---|
| Cloud API oficial como canal principal; simulador para desenvolvimento | Conforme |
| Nenhuma regra de negócio depende diretamente da Meta | Conforme, via `ChannelAdapter` |
| Processamento idempotente e sem perda após reinício | Conforme, persistência antes do ACK/fila durável e chave única por `wamid` |
| Consentimento, opt-out, janela de 24 h e acesso humano | Conforme, como regras centrais dos fluxos |
| Dados minimizados, telefone mascarado e retenção definida | Conforme, incluído na fase transversal |
| IA limitada ao negócio, fundamentada e com fallback humano | Conforme, somente na fase posterior |
| Custo de R$ 0 para desenvolvimento/teste | Conforme no simulador e sandbox; custos de produção não são assumidos |

**Estado do gate**: aprovado com ressalva documental. Registrar uma constituição explícita antes de ampliar o escopo ou iniciar implementação em produção.

## Diretrizes aplicadas

Não há diretório `skills/guidelines/` no workspace nem migração de framework em andamento. Portanto, nenhuma diretriz externa de migração foi aplicada. As decisões técnicas e os padrões de canal, fluxo, dados e teste seguem a própria especificação.

## Etapas de implementação

Os incrementos abaixo seguem os Sprints 0–7 sugeridos no documento. A duração de uma semana é uma cadência proposta, não uma estimativa comprometida.

### Etapa 1 — Setup

#### 1.1 Estrutura do projeto e execução local
- **Requisitos**: RF-21, RNF-07, RNF-09
- **Entradas de desenho**: seções 3, 10.2, 10.3 e 15 da especificação
- **Descrição**: criar o esqueleto Python, configuração segura por ambiente, Docker Compose e comandos repetíveis de desenvolvimento/teste. Garantir que API, worker, PostgreSQL, Redis e simulador subam localmente sem credenciais da Meta.

#### 1.2 Abstração de canal e simulador
- **Requisitos**: RF-05, RF-07, RF-08, RF-21, RNF-10
- **Entradas de desenho**: seção 3 e seção 10.3
- **Descrição**: definir `ChannelAdapter` para parsing de entrada, texto, interativos, templates e marcação de leitura; implementar simulador que injeta payloads e captura respostas. Nenhum fluxo de negócio deve importar diretamente o cliente Meta.

### Etapa 2 — Fundacional

#### 2.1 Persistência e migrações
- **Requisitos**: RF-04, RF-06, RF-12, RF-15, RNF-02
- **Entradas de desenho**: seção 12
- **Descrição**: implementar modelos e migrações para contatos, conversas, mensagens, tickets, agendamentos, artigos, eventos de webhook e contadores de uso. Aplicar unicidade de `wamid` às mensagens e chave de deduplicação aos eventos: atualizações de status (`sent`, `delivered`, `read`) reutilizam o mesmo `wamid` e não podem ser descartadas como duplicatas.

#### 2.2 Entrada segura de eventos
- **Requisitos**: RF-01, RF-02, RF-03, RF-04, RF-22, RNF-01, RNF-02, RNF-04, RN-10
- **Entradas de desenho**: seções 7, 9, 10.1, 11 e 14
- **Descrição**: implementar verificação GET, assinatura HMAC do POST, limites de tamanho e taxa compartilhados via Redis, gravação durável do evento, deduplicação de mensagens/status e enfileiramento. Responder rapidamente apenas após o evento estar registrado de forma segura para processamento.

#### 2.3 Worker, retentativas e status
- **Requisitos**: RF-03, RNF-02, RN-10
- **Entradas de desenho**: seções 9, 10.1 e 17.1 (CA-03, CA-13)
- **Descrição**: consumir eventos de forma idempotente; aplicar backoff em falhas temporárias; atualizar status de entrega a partir dos webhooks; possibilitar reprocessamento auditável sem duplicar respostas.

### Etapa 3 — US1: Primeiro contato e FAQ

#### 3.1 Sessão e máquina de estados
- **Requisitos**: RF-06, RN-04, RN-09
- **Entradas de desenho**: seções 6, 9 e 12
- **Descrição**: manter estado por contato/conversa, expiração configurável e transições explícitas entre bot, humano e encerrado. Após duas falhas seguidas de entendimento, oferecer handoff; aceitar pedido de humano em qualquer estado.

#### 3.2 Saudação, menus e tipos de mensagem
- **Requisitos**: RF-05, RF-07, RF-08, RN-05
- **Entradas de desenho**: seções 6, 10.3 e 11
- **Descrição**: criar saudação com identificação do bot, aviso de dados/consentimento e caminho para atendente; menus interativos; parsing de texto, botão, lista e mídia, com resposta segura para tipos não suportados.

#### 3.3 FAQ e fallback seguro
- **Requisitos**: RF-09, RN-06, RN-07, RN-08
- **Entradas de desenho**: seções 6, 13 e 17.1 (CA-05, CA-06, CA-12)
- **Descrição**: implementar busca por regras/palavras-chave sobre artigos configuráveis, citar o título da fonte e não inventar respostas. Para ausência de evidência ou tema fora do negócio, informar a limitação e oferecer humano.

### Etapa 4 — US2: Pedidos, agendamento e consentimento

#### 4.1 Consulta de pedido
- **Requisitos**: RF-10
- **Entradas de desenho**: seções 6, 10.3 e 17.1 (CA-07)
- **Descrição**: criar integração interna simulada para consulta de status, validação do identificador antes da consulta e mensagens de resultado/erro sem expor dados de outro cliente.

#### 4.2 Agendamento
- **Requisitos**: RF-11
- **Entradas de desenho**: seções 6, 10.3 e 12
- **Descrição**: implementar serviço simulado para disponibilidade, criação, consulta e cancelamento. Em conflito de horário, sugerir alternativas; persistir o agendamento e confirmar o resultado.

#### 4.3 Consentimento, expediente e janela de mensagens
- **Requisitos**: RF-14, RF-15, RF-16, RF-18, RN-01, RN-02, RN-03
- **Entradas de desenho**: seções 2, 6, 9, 12, 17.1 (CA-10, CA-11) e 19
- **Descrição**: registrar consentimentos e revogações; reconhecer PARAR/SAIR/CANCELAR; aplicar horário comercial; impedir mensagem livre fora de 24 h; permitir somente template aprovado quando aplicável; registrar categoria e contagem mensal sem fixar tarifa volátil no código.

### Etapa 5 — US3: Handoff humano

#### 5.1 Tickets, fila e atendimento
- **Requisitos**: RF-12, RF-13, RN-04, RN-09
- **Entradas de desenho**: seções 6, 10.1, 10.2, 12 e 14
- **Descrição**: criar ticket com motivo e resumo, enfileirar para atendimento, encaminhar a conversa ao Chatwoot e permitir resposta do atendente pelas rotas internas. O bot deve permanecer silencioso enquanto o controle for humano e só retomar após devolução explícita.

### Etapa 6 — US4: IA restrita (fase posterior ao MVP)

#### 6.1 Classificação, RAG e guardrails
- **Requisitos**: RF-17, RN-06, RN-07, RN-08
- **Entradas de desenho**: seção 13 e metas de qualidade da seção 17.3
- **Descrição**: adicionar classificação de intenção e RAG sobre artigos do negócio atrás de flag/configuração. Validar saída estruturada, limitar tamanho, proteger contra prompt injection, recusar temas gerais e encaminhar baixa confiança para humano. Comparar qualidade com a linha de base por regras antes de ativar.

### Etapa 7 — Transversal e conclusão

#### 7.1 Métricas, privacidade e controles operacionais
- **Requisitos**: RF-18, RF-19, RF-20, RF-22, RNF-03, RNF-05, RNF-06, RNF-09, RN-08, RN-11
- **Entradas de desenho**: seções 8, 9, 12, 14, 17.3 e 18
- **Descrição**: expor saúde e métricas, medir latência/handoff/erros/categorias de mensagens, oferecer pesquisa de satisfação ao encerrar atendimento, exportar dados anonimizados, mascarar telefones e aplicar retenção/exclusão. Monitorar qualidade do número e pausar envios ativos quando necessário.

#### 7.2 Validação ponta a ponta e documentação
- **Requisitos**: RF-21, RNF-01, RNF-02, RNF-07, RNF-08, RNF-10
- **Entradas de desenho**: seções 15–17 e 22
- **Descrição**: consolidar testes de unidade, contrato, diálogos e integração; medir as metas de desempenho; executar checklist manual no sandbox Meta; documentar configuração, segredos, retenção, execução local e limitações antes de qualquer piloto real.

## Estrutura projetada

```text
whatsapp-atendimento/
  docker/
  src/
    api/                 # webhook e API interna
    channel/             # adapter, Cloud API e simulador
    flows/               # máquina de estados e respostas
    nlu/                 # regras, classificador e guardrails
    knowledge/           # artigos, busca e RAG
    integrations/         # pedidos e agenda simulados
    handoff/             # tickets, fila e Chatwoot
    consent/              # opt-in, opt-out e expediente
    db/                   # modelos e migrações
  tests/
    unit/
    contract/
    dialogs/
    integration/
  simulator/
    payloads/
  docs/
  docker-compose.yml
  pyproject.toml
  .env.example
```

## Estratégia de testes

**appType**: mensageria + API HTTP (webhook e rotas internas); sem interface HTML própria no plano atual. O painel Chatwoot é externo.  
**Jornadas críticas**:
1. Evento de entrada válido: assinatura verificada, ACK rápido, enfileiramento, resposta única e persistida.
2. Primeiro contato/menu e FAQ: aviso de bot, resposta com fonte ou fallback sem invenção.
3. Consulta de pedido: válido retorna status; inválido não dispara consulta.
4. Agendamento: horário disponível cria/retorna confirmação; conflito oferece opções.
5. Handoff: ticket e resumo criados, atendente responde e bot fica silenciado até a devolução.
6. Opt-out/janela: palavras de opt-out bloqueiam mensagens ativas; fora da janela só template permitido.

**Stack primária**: pytest; FastAPI TestClient/httpx para rotas; respx para contratos externos; simulador para diálogos; Docker Compose com PostgreSQL 16 e Redis reais nos testes de integração; sandbox oficial para smoke test manual.

**Matriz de fallback por capacidade**:
- `infra-tier`: PostgreSQL/Redis reais via Docker Compose → somente se Docker não estiver disponível após tentativa documentada, SQLite e substituto em memória da fila/cache. Lacunas: semântica de constraints/transações PostgreSQL e TTL/concorrência Redis não ficam plenamente verificadas.
- `browser-tier`: não aplicável ao serviço planejado, que não renderiza HTML. A UI do Chatwoot é externa; validar a integração por contrato e checklist manual no sandbox. Se o escopo mudar para painel web próprio, revisar o plano e adicionar Playwright.
- `external-api-tier`: Meta e Chatwoot simulados por mocks de transporte nos testes automatizados; nenhuma chamada externa ou cobrada em CI. Sandbox Meta apenas no teste manual controlado.

**Ambiente**: Python 3.12; Docker funcional para integração; Docker Compose; rede externa apenas para preparar o sandbox manual; Node.js/Playwright não necessários no escopo atual.

**Dados de teste**: sem depender de dados preexistentes; fixtures criam dados com IDs únicos, isolam cada cenário e limpam/reinicializam o banco. Payloads Meta gravados devem estar anonimizados.

**Critérios de aceite e evidência**:
- Cobrir CA-01 a CA-13 da especificação com testes automatizados ou checklist sandbox conforme o canal.
- ACK do webhook < 1 s p95; primeira resposta < 5 s p95; 50 conversas simuladas simultâneas.
- Zero respostas duplicadas para mesmo `wamid`; nenhum evento perdido após reinício; retry com backoff.
- Pelo menos 80% de cobertura na lógica de fluxo.
- Diálogos dourados: intenção correta ≥85%, resolução sem humano ≥60%, handoff correto ≥95%, recusa fora de escopo ≥90% e zero respostas inventadas.
- `pytest` e verificações de lint/tipagem passam na CI; todo teste informa contagens de pass/fail/skip.

**Infraestrutura de testes**: `tests/conftest.py` fornece configuração, fixtures de banco e sessão; PostgreSQL e Redis reais para integração via Compose; respx simula Cloud API/Chatwoot; serviços de pedidos/agenda usam doubles contratuais. Cada módulo terá teste de inicialização/health e de contrato para suas fronteiras. Cada tarefa executa os testes do módulo afetado e reporta o resultado.

**Expectativas de revisão**: conferir que cada requisito RF/RNF/RN tem evidência; que os mocks não escondem requisitos de assinatura/idempotência; que os testes de integração usam PostgreSQL/Redis reais quando Docker estiver disponível; que nenhuma credencial ou PII foi incluída; e que os resultados do sandbox e os limites de cobertura estão explícitos.

## Tarefas

### Fase 1 — Setup

- [x] T001 [Plan:1.1] Criar `pyproject.toml`, `src/main.py`, configuração FastAPI, `.env.example`, `docker-compose.yml` e documentação inicial de execução local.
- [x] T002 [P] [Plan:1.1] Criar workflow de CI em `.github/workflows/ci.yml` para pytest, lint e tipagem, sem segredos de canal.
- [x] T003 [Plan:1.2] Implementar `src/channel/adapter.py` e `src/channel/simulator.py`, incluindo marcação como lida/indicador de digitação quando disponíveis, com payloads locais e testes em `tests/contract/test_channel_adapter.py`.

### Fase 2 — Fundacional

- [x] T004 [Plan:2.1] Implementar modelos e migrações para contatos, conversas, mensagens, tickets, agendamentos, artigos, eventos e contadores em `src/db/`.
- [x] T005 [Plan:2.2] Implementar GET/POST `/webhook`, validação HMAC, limites do payload e testes em `src/api/webhook.py` e `tests/contract/test_webhook.py`.
- [x] T006 [Plan:2.2] Persistir evento antes do enfileiramento, deduplicar `wamid` e registrar resultado em `src/api/webhook.py`, `src/db/` e `tests/integration/test_webhook_idempotency.py`.
- [x] T007 [Plan:2.3] Implementar worker Celery, backoff, reprocessamento e atualização de status de entrega em `src/worker.py` e `tests/integration/test_worker_retries.py`.

### Fase 3 — US1: Primeiro contato e FAQ

- [x] T008 [Plan:3.1] Implementar estados e transições da conversa, expiração configurável e limite de duas falhas em `src/flows/state_machine.py` e `tests/unit/test_state_machine.py`.
- [x] T009 [US1] [Plan:3.2] Criar saudação, aviso do bot, consentimento inicial e menus interativos em `src/flows/` e `tests/dialogs/test_first_contact.py`.
- [x] T010 [P] [US1] [Plan:3.2] Tratar textos, botões, listas e tipos de mídia em `src/channel/` e `tests/contract/test_inbound_message_types.py`.
- [x] T011 [US1] [Plan:3.3] Implementar busca FAQ com citação do título e fallback para humano em `src/knowledge/` e `tests/unit/test_faq_grounding.py`.
- [ ] T012 [US1] [Plan:3.3] Criar diálogos dourados de primeiro contato, FAQ, ausência de resposta e fora de escopo em `tests/dialogs/`.

### Fase 4 — US2: Pedidos, agendamentos e consentimento

- [ ] T013 [US2] [Plan:4.1] Implementar consulta simulada de pedidos com validação prévia em `src/integrations/orders.py` e `tests/unit/test_order_status.py`.
- [ ] T014 [US2] [Plan:4.2] Implementar disponibilidade, criação, consulta e cancelamento de agendamentos em `src/integrations/appointments.py` e `tests/integration/test_appointments.py`.
- [ ] T015 [US2] [Plan:4.3] Implementar registro de opt-in/opt-out e bloqueio das palavras PARAR, SAIR e CANCELAR em `src/consent/` e `tests/unit/test_consent.py`.
- [ ] T016 [US2] [Plan:4.3] Implementar janela de 24 h, templates permitidos e contagem por categoria em `src/flows/` e `src/channel/`, com testes em `tests/unit/test_message_window.py`.
- [ ] T017 [US2] [Plan:4.3] Criar diálogos para pedido válido/inválido, conflito de agenda, opt-out e template fora da janela em `tests/dialogs/`.

### Fase 5 — US3: Handoff humano

- [ ] T018 [US3] [Plan:5.1] Criar tickets com resumo, fila e estado de silêncio do bot em `src/handoff/` e `tests/integration/test_handoff.py`.
- [ ] T019 [US3] [Plan:5.1] Integrar Chatwoot e as rotas de listagem/resposta/devolução em `src/handoff/chatwoot.py`, `src/api/conversations.py` e `tests/contract/test_chatwoot.py`.

### Fase 6 — US4: IA restrita (fase posterior ao MVP)

- [ ] T020 [US4] [Plan:6.1] Implementar classificador de intenção atrás de configuração/feature flag em `src/nlu/` e `tests/unit/test_intent_classifier.py`.
- [ ] T021 [US4] [Plan:6.1] Implementar RAG sobre a base de conhecimento, validação de saída, recusa fora do escopo e fallback para humano em `src/knowledge/` e `src/nlu/`.
- [ ] T022 [US4] [Plan:6.1] Adicionar testes contra prompt injection, conteúdo sem fonte e baixa confiança em `tests/dialogs/test_ai_guardrails.py`; comparar métricas com a linha de base.

### Fase 7 — Transversal e conclusão

- [ ] T023 [Plan:7.1] Implementar `/health`, `/metrics`, pesquisa de satisfação, exportação anonimizada e medições de latência/handoff/consumo em `src/api/metrics.py`, `src/flows/` e `tests/integration/test_metrics.py`.
- [ ] T024 [Plan:7.1] Implementar mascaramento de telefone, retenção e exclusão sob demanda em `src/` e `tests/unit/test_privacy.py`; documentar a política em `docs/`.
- [ ] T025 [Plan:7.1] Implementar monitoramento de qualidade e pausa de envios ativos em `src/` e `tests/unit/test_quality_controls.py`.
- [ ] T026 [Plan:7.2] Completar testes unitários, contrato e integração com fixtures isoladas em `tests/conftest.py`; demonstrar ≥80% de cobertura da lógica de fluxo.
- [ ] T027 [Plan:7.2] Executar teste de 50 conversas simultâneas e validar p95 de ACK/resposta em `tests/integration/` ou script de carga documentado.
- [ ] T028 [Plan:7.2] Executar checklist de sandbox Meta com número de teste e registrar evidências anonimizadas em `docs/sandbox-checklist.md`.
- [ ] T029 [Plan:7.2] Documentar setup, variáveis, operação local, limites de custo e critérios de produção em `README.md` e `docs/`.

## Mapeamento de requisitos

### Requisitos funcionais

| ID | Descrição resumida | Etapas | Evidência de implementação |
|---|---|---|---|
| RF-01 | Verificação GET do webhook Meta | 2.2 | `src/api/webhook.py`, `tests/contract/test_webhook.py` |
| RF-02 | Assinatura POST e ACK rápido | 2.2 | `src/api/webhook.py`, `tests/contract/test_webhook.py` |
| RF-03 | Processamento assíncrono | 2.2, 2.3 | `src/worker.py`, `tests/integration/` |
| RF-04 | Deduplicação por `wamid` | 2.1, 2.2 | `src/db/`, `tests/integration/test_webhook_idempotency.py` |
| RF-05 | Texto, interativos e mídia | 1.2, 3.2 | `src/channel/`, `tests/contract/test_inbound_message_types.py` |
| RF-06 | Sessão e estado por cliente | 2.1, 3.1 | `src/flows/state_machine.py`, `src/db/` |
| RF-07 | Menus e mensagens de texto | 1.2, 3.2 | `src/channel/`, `src/flows/` |
| RF-08 | Marcação como lida e indicador disponível | 1.2, 3.2 | `src/channel/`, `src/flows/` |
| RF-09 | FAQ com citação da fonte | 3.3 | `src/knowledge/`, `tests/unit/test_faq_grounding.py` |
| RF-10 | Consulta validada de pedido | 4.1 | `src/integrations/orders.py` |
| RF-11 | Agendamento e disponibilidade | 4.2 | `src/integrations/appointments.py` |
| RF-12 | Handoff com ticket, resumo e fila | 5.1 | `src/handoff/`, `tests/integration/test_handoff.py` |
| RF-13 | Painel mínimo de atendimento | 5.1 | `src/handoff/chatwoot.py`, `src/api/conversations.py` |
| RF-14 | Janela de 24 h e templates | 4.3 | `src/flows/`, `src/channel/` |
| RF-15 | Registro de opt-in/opt-out | 4.3 | `src/consent/`, `src/db/` |
| RF-16 | Expediente e mensagem fora do horário | 4.3 | `src/consent/`, `src/flows/` |
| RF-17 | IA restrita ao negócio (fase 2) | 6.1 | `src/nlu/`, `src/knowledge/` |
| RF-18 | Contagem por categoria e alerta | 4.3, 7.1 | `src/db/`, `src/api/metrics.py` |
| RF-19 | Pesquisa de satisfação | 7.1 | `src/flows/`, `src/db/` |
| RF-20 | Exportação anonimizada | 7.1 | `src/api/metrics.py` |
| RF-21 | Simulador para testes locais | 1.1, 1.2 | `src/channel/simulator.py`, `simulator/` |
| RF-22 | `/health` e `/metrics` | 7.1 | `src/api/metrics.py`, testes de integração |

### Requisitos não funcionais

| ID | Descrição resumida | Etapas | Evidência de implementação |
|---|---|---|---|
| RNF-01 | ACK <1 s p95 e resposta <5 s p95 | 2.2, 7.2 | testes de carga e métricas |
| RNF-02 | Backoff, durabilidade e idempotência | 2.1–2.3 | worker, banco e testes de reinício |
| RNF-03 | Reinício automático e meta de disponibilidade | 7.1 | Compose, health checks e runbook |
| RNF-04 | Assinatura, segredos e rate limiting | 2.2, 7.1 | webhook e configuração de ambiente |
| RNF-05 | Minimização, mascaramento, retenção e exclusão | 7.1 | controles de privacidade e testes |
| RNF-06 | Logs estruturados e métricas operacionais | 7.1 | `src/api/metrics.py` e logs |
| RNF-07 | Subida por Docker Compose | 1.1 | `docker-compose.yml` |
| RNF-08 | Simulador e cobertura de fluxo ≥80% | 1.2, 7.2 | suite pytest e relatório de cobertura |
| RNF-09 | Ferramentas gratuitas e consumo controlado | 1.1, 4.3, 7.1 | simulador, sandbox e contadores |
| RNF-10 | Canal abstrato e versão Graph configurável | 1.2 | `src/channel/adapter.py` e `meta_cloud.py` |

### Regras de negócio

| ID | Descrição resumida | Etapas | Evidência de implementação |
|---|---|---|---|
| RN-01 | Mensagem livre apenas dentro de 24 h | 4.3 | testes de janela |
| RN-02 | Template aprovado fora da janela | 4.3 | validação de template/categoria |
| RN-03 | Opt-in para mensagens ativas; opt-out imediato | 4.3 | testes de consentimento |
| RN-04 | Humano pode ser solicitado a qualquer momento | 3.1, 5.1 | testes de estado e handoff |
| RN-05 | Identificar bot na primeira mensagem | 3.2 | diálogo de primeiro contato |
| RN-06 | IA limitada aos assuntos do negócio | 3.3, 6.1 | guardrails e diálogos |
| RN-07 | FAQ fundamentada; sem fonte, oferecer humano | 3.3 | teste de grounding |
| RN-08 | Não solicitar dados sensíveis desnecessários | 3.3, 7.1 | filtros e testes de privacidade |
| RN-09 | Após duas falhas, oferecer humano | 3.1, 5.1 | teste de transição |
| RN-10 | Cada `wamid` processado uma vez | 2.1–2.3 | teste de idempotência |
| RN-11 | Monitorar qualidade e pausar envio ativo | 7.1 | controles operacionais e testes |

## Itens a confirmar antes da implementação

- Aprovar ou substituir a stack provisória e a integração com Chatwoot.
- Confirmar domínio e conteúdo real da base de conhecimento; até lá, usar dados demonstrativos.
- Confirmar retenção de dados e requisitos de exclusão com responsável por privacidade/jurídico antes de operar com clientes reais.
- Revalidar preços, limites, templates e políticas da Meta nas fontes oficiais antes de produção; os valores do PDF são voláteis.
- Definir se os itens opcionais RF-19/RF-20 entram no primeiro piloto ou ficam para uma iteração posterior.
