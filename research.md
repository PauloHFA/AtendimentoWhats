# Decisões e pendências da elaboração do plano

## Base consultada

- `Automação de Atendimento via WhatsApp Documento de Requisitos e Especificações.pdf` — requisitos funcionais e não funcionais, regras, stack sugerida, arquitetura, dados, API, testes, critérios de aceite, sequência de entrega e riscos.
- Workspace examinado: contém apenas esse PDF; não há código-fonte, `constitution.md`, knowledge graph, artefato separado de arquitetura ou suíte de testes para inventariar.

## Decisões provisórias

| Decisão | Escolha no plano | Motivo |
|---|---|---|
| Stack | Python 3.12, FastAPI, PostgreSQL 16, Redis/Celery, Docker Compose | É a combinação recomendada no documento e permite reproduzir o fluxo localmente |
| Canal | Cloud API oficial como principal; simulador local antes do sandbox | Reduz risco de política e custo e permite testar sem número real |
| Handoff | Chatwoot como integração inicial | O documento aponta menor esforço que desenvolver um painel próprio |
| IA | Adiada para fase posterior ao MVP, mas mantida no roadmap | Primeiro estabelecer baseline previsível por regras; IA restrita e RAG exigem avaliação própria |
| Domínio | Dados demonstrativos configuráveis de clínica/serviços | O documento oferece esse exemplo e não identifica o negócio real |
| Identificadores | Preservar RF/RNF/RN originais | A especificação não usa `REQ-XXX`; manter os IDs originais evita perder rastreabilidade |

Essas escolhas são premissas de planejamento, não aprovações do usuário. O pedido de confirmação não pôde ser respondido; portanto, confirmar as decisões antes de iniciar tarefas que as tornem custosas de alterar.

## Pendências e limites

- Constituição do projeto ausente; o plano usa provisoriamente as regras de negócio, RNFs e DoD do PDF.
- A especificação apresenta modelo de dados, endpoints resumidos e arquitetura suficiente para o roadmap, mas não contém contratos detalhados de integração. Detalhar payloads e contratos durante a implementação, sem antecipar integração com sistemas reais de pedidos/agenda.
- O documento alerta que preços e políticas da Meta mudam. Revalidar oficialmente antes do sandbox e da produção; não codificar tarifas como constantes.
- Retenção de 90 dias é apenas exemplo no documento, não decisão de política. Não aplicar como valor definitivo sem aprovação.
- Não há suíte legado nem comando de teste existente, por se tratar de um workspace sem implementação.
