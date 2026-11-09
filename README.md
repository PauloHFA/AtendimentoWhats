# Atendimento via WhatsApp

Protótipo de atendimento automatizado que recebe eventos no formato de webhook
da WhatsApp Cloud API e permite experimentar jornadas em um **simulador local**.
Este documento é para pessoas desenvolvedoras, responsáveis por integrações e
demais integrantes que queiram entender o estágio do projeto.

**Estágio atual: desenvolvimento, não pronto para produção.** O projeto recebe
e processa eventos de teste, mas não envia mensagens para o WhatsApp nem entrega
conversas a atendentes. Não use dados reais no simulador.

## O que já funciona e o que falta

| Área | Estado | Detalhes |
|---|---|---|
| API e webhook | Funciona localmente | `/health`, verificação de assinatura HMAC, limite de requisições, persistência e deduplicação de eventos. |
| Worker e simulador | Funciona localmente | Processa eventos da fila, registra mensagens e gera respostas simuladas no banco quando habilitado. |
| Jornadas | Funciona no simulador | Saudação, aceite de atendimento, FAQ, consulta de pedidos, agendamento e consentimento de marketing, com as limitações abaixo. |
| Expediente | Parcial | Configuração opcional informa quando a solicitação de humano ocorre fora do horário; não restringe reservas nem cria fila. |
| Handoff | Parcial | Há serviço interno de tickets e transição de posse, mas ele não está conectado à jornada, a uma interface ou ao Chatwoot. |
| Janela de mensagens e templates | Parcial | A política e `GuardedChannel` existem, mas não protegem um fluxo real de envio. |
| Contagem de uso | Parcial | Serviço interno idempotente para mensagens confirmadas, ainda não conectado a envios ou callbacks reais. |
| Máquina de estados | Parcial | Existe uma classe isolada com expiração e sugestão de handoff após falhas. O worker utiliza seus próprios estados da jornada e não usa essa classe. |
| WhatsApp e atendimento humano reais | Pendente | Faltam o adaptador de envio Meta, integração Chatwoot, interface de atendente e validação em sandbox. |
| Operação e segurança | Pendente | Faltam controles completos de privacidade, retenção, métricas e validações para produção. |

O [plano de implementação](plan.md) contém os requisitos e etapas; o
[acompanhamento](checkpoints/tasks-to-impl.yaml) registra o progresso por tarefa.
Uma tarefa em andamento não significa que a funcionalidade esteja pronta para
uso real.

## Como o processamento funciona

```text
POST /webhook
    → valida assinatura, tamanho e limite no Redis
    → grava o evento no banco e publica sua referência no Celery
    → worker lê o evento e registra contato, conversa e mensagem
    → se o simulador estiver habilitado, gera respostas no banco
```

1. [`src/api/webhook.py`](src/api/webhook.py) valida o corpo e a assinatura,
   persiste em `webhook_events` e solicita a publicação na fila. Se a publicação
   falhar, retorna erro após persistir o evento; um reenvio pode tentar novamente.
2. Redis fornece a fila e o controle de taxa; o Celery executa o worker definido
   em [`src/tasks.py`](src/tasks.py).
3. O worker usa [`SimulatorAdapter`](src/channel/simulator.py) para interpretar
   o payload, deduplica mensagens pelo identificador do canal e persiste os dados.
4. Com `SIMULATOR_BUSINESS_NAME` definido, a jornada em
   [`src/flows/faq_journey.py`](src/flows/faq_journey.py) registra saídas em
   `messages`, com `direction=OUTBOUND` e `delivery_status=SIMULATED`.
   **Essas saídas não são enviadas ao WhatsApp.**

O envio real, a política de saída protegida e o atendimento humano não estão
conectados a esse fluxo.

## Requisitos

- Python 3.12 para desenvolvimento e testes locais.
- Docker Desktop com Docker Compose para a opção com contêineres.
- Para rodar API e worker sem Docker: Redis acessível; SQLite é usado por padrão
  para desenvolvimento local. O Compose usa PostgreSQL e Redis em contêineres.

Os exemplos abaixo usam PowerShell no Windows, executado na raiz do repositório.

## Executar com Docker Compose

1. Copie a configuração de exemplo, se ainda não existir um `.env`:

   ```powershell
   Copy-Item .env.example .env
   ```

   Não sobrescreva um `.env` existente sem revisar seu conteúdo.

2. No `.env`, mantenha `POSTGRES_PASSWORD` definido e, para o tutorial de
   simulação abaixo, ajuste estes valores **somente para teste local**:

   ```text
   META_APP_SECRET=segredo-local-de-teste
   SIMULATOR_BUSINESS_NAME=Loja Exemplo
   ```

   Esse segredo fictício é usado para assinar o webhook de teste, não é uma
   credencial da Meta. Com `SIMULATOR_BUSINESS_NAME` vazio, o worker não gera
   respostas simuladas.

3. Inicie os serviços e verifique a API:

   ```powershell
   docker compose up --build -d
   docker compose ps
   Invoke-RestMethod http://localhost:8000/health
   ```

   A resposta esperada é `{"status":"ok"}`. A documentação das rotas está em
   `http://localhost:8000/docs`. A API aplica as migrações na inicialização.

Após alterar `.env`, execute `docker compose up -d` novamente para recriar os
serviços cuja configuração mudou. `docker compose down` para os serviços; os
volumes de PostgreSQL e Redis permanecem.

## Experimentar a jornada simulada

Este tutorial usa a API e o banco do Compose, não uma interface de chat.
Execute-o após os passos anteriores, no mesmo terminal PowerShell. A função
gera um identificador novo para cada mensagem e assina os bytes exatos do JSON.
O segredo deve ser igual ao `META_APP_SECRET` configurado no `.env`.

```powershell
$appSecret = 'segredo-local-de-teste'
$waId = '1555' + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

function Send-SimulatedMessage([string] $text) {
    $message = @{
        id = 'local.' + [guid]::NewGuid().ToString()
        from = $waId
        timestamp = [string][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        type = 'text'
        text = @{ body = $text }
    }
    $payload = @{
        entry = @(@{
            changes = @(@{
                field = 'messages'
                value = @{ messages = @($message) }
            })
        })
    }
    $json = ConvertTo-Json -InputObject $payload -Depth 20 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $key = [System.Text.Encoding]::UTF8.GetBytes($appSecret)
    $hmac = [System.Security.Cryptography.HMACSHA256]::new($key)
    try {
        $signature = 'sha256=' + (
            [BitConverter]::ToString($hmac.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant()
        )
    } finally {
        $hmac.Dispose()
    }
    Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/webhook' `
        -Headers @{ 'X-Hub-Signature-256' = $signature } `
        -ContentType 'application/json' -Body $bytes
}

Send-SimulatedMessage 'Oi'
```

O HTTP deve retornar `status: accepted`: isso confirma a aceitação do evento,
**não** que o worker já terminou. Aguarde alguns segundos e consulte as
mensagens deste contato fictício:

```powershell
$sql = "SELECT m.direction, m.delivery_status, m.content FROM messages m JOIN conversations c ON c.id = m.conversation_id JOIN contacts p ON p.id = c.contact_id WHERE p.wa_id = '$waId' ORDER BY m.created_at, m.id;"
docker compose exec -T db psql -U atendimento -d atendimento -c $sql
```

Devem aparecer a mensagem `INBOUND` e duas mensagens `OUTBOUND`/`SIMULATED`:
uma apresentação e um menu de aceite. Se as saídas ainda não aparecerem,
repita a consulta e verifique `docker compose logs worker`.

Depois que a saudação aparecer, continue usando a mesma função e consulte o
banco novamente após cada mensagem:

```powershell
Send-SimulatedMessage 'ACEITO'
```

O aceite apenas permite continuar o atendimento; ele **não** autoriza marketing.
Uma vez recebida a resposta de aceite, experimente `PEDIDO`, `AGENDAMENTOS` ou
`AGENDAR Consulta | 01/01/2035 10:00` (use uma data futura). Para não depender
da ordem assíncrona da fila, aguarde a resposta de cada etapa antes da próxima.
`MARKETING` abre uma pergunta com botões; para responder aos botões é necessário
enviar um payload interativo com o ID correspondente, pois esta função envia
apenas texto. Não há uma interface visual de chat implementada.

## Executar sem Docker

Para instalar e executar os testes, não é necessário iniciar Redis ou fornecer
credenciais. Estes comandos usam o Python instalado no Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m alembic upgrade head
python -m pytest
```

Fora do Compose, a aplicação **não carrega `.env` automaticamente**. Para
executar a API e o worker, inicie Redis separadamente em `localhost:6379` e
execute os comandos seguintes em **cada um de dois terminais** abertos na raiz
do projeto. Eles configuram valores locais fictícios para ambos os processos:

```powershell
.\.venv\Scripts\Activate.ps1
$env:DATABASE_URL = 'sqlite:///./atendimento.db'
$env:REDIS_URL = 'redis://localhost:6379/0'
$env:CELERY_RESULT_BACKEND = 'redis://localhost:6379/1'
$env:META_APP_SECRET = 'segredo-local-de-teste'
$env:SIMULATOR_BUSINESS_NAME = 'Loja Exemplo'
```

No primeiro terminal, aplique as migrações e inicie a API:

```powershell
python -m alembic upgrade head
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

No segundo, inicie o worker:

```powershell
python -m celery -A src.celery_app:celery_app worker --loglevel=INFO --pool=solo
```

As variáveis definidas em um terminal não são compartilhadas automaticamente
com outro. `--pool=solo` é uma opção de desenvolvimento no Windows, não uma
configuração de produção. O tutorial de envio acima também pode chamar essa
API, mas a consulta com `docker compose exec` vale apenas para o banco do
Compose; fora dele, consulte o arquivo SQLite configurado em `DATABASE_URL`.

## Jornadas e componentes internos

### FAQ, pedidos e consentimento

- Cadastre artigos em `knowledge_articles`; não há conteúdo comercial
  pré-cadastrado. O FAQ determinístico cita a fonte e oferece falar com pessoa
  quando não encontra resposta confiável. O atendimento humano ainda não está
  disponível e o simulador informa essa limitação.
- `PEDIDO` solicita um número de 4 a 20 dígitos ASCII e consulta apenas pedidos
  da tabela `simulated_orders` vinculados ao contato. Não há pedidos
  pré-cadastrados. Essa associação **não é autenticação suficiente** para dados
  reais.
- `MARKETING` abre uma pergunta opcional separada do aceite de atendimento.
  Uma confirmação recebida no mesmo segundo da pergunta é rejeitada; solicite
  a pergunta novamente. `PARAR`, `SAIR` e `CANCELAR` registram opt-out mesmo
  com o simulador desabilitado. O histórico fica em `consent_events`; a
  prevenção de envios ativos reais ainda precisa ser integrada.

### Agendamentos simulados

Após aceitar o atendimento, envie pelo webhook:

- `AGENDAR Consulta | 01/01/2035 10:00`: cria uma reserva simulada futura.
- `AGENDAMENTOS`: lista as reservas ativas do contato.
- `DESMARCAR <código>`: desmarca uma reserva pertencente ao contato.

Horários são em UTC, em intervalos de 30 minutos; conflitos retornam sugestões.
Os nomes de serviços são livres e não há catálogo, expediente aplicado ou
integração com agenda real. `CANCELAR` é opt-out, não cancelamento de reserva.
O serviço em [`src/integrations/appointments.py`](src/integrations/appointments.py)
usa a transação do chamador.

### Expediente

Opcionalmente, configure `SIMULATOR_BUSINESS_HOURS` como JSON. Exemplo:

```text
SIMULATOR_BUSINESS_HOURS={"timezone":"America/Sao_Paulo","intervals":[{"weekday":0,"start":"09:00","end":"18:00"}]}
```

O exemplo define apenas segunda-feira; `weekday` vai de 0 (segunda) a 6
(domingo). O início é incluído e o fim excluído. Dias sem intervalos estão
fechados; turnos atravessando meia-noite não são suportados. O fuso IANA deve
estar disponível no sistema. Sem configuração, o simulador não presume
expediente. Isso apenas adiciona um aviso na solicitação de humano, sem
restringir agendamentos nem criar fila.

### Tickets, política e uso

- [`src/handoff/service.py`](src/handoff/service.py) cria e lista tickets,
  transfere a posse e devolve a conversa ao bot na transação do chamador. Em
  PostgreSQL, as operações serializam pela linha da conversa; SQLite não
  fornece o mesmo bloqueio. `list_open_tickets` não reserva tickets para
  atendentes e páginas podem mudar entre consultas. Não existe fila operacional.
- [`src/flows/message_policy.py`](src/flows/message_policy.py) valida janela,
  consentimento e catálogo fornecido pelo chamador;
  [`GuardedChannel`](src/channel/guarded.py) aplica essa política antes de
  delegar. Nenhum canal real ou worker usa esse adaptador atualmente.
- [`src/usage/service.py`](src/usage/service.py) conta, por mês UTC, número e
  categoria, mensagens persistidas com ID do canal e status `SENT`, `DELIVERED`
  ou `READ`. É idempotente por mensagem e não conta simulações. A categoria e o
  horário vêm do chamador. É contagem técnica, não cobrança oficial. O serviço
  não está ligado a envios nem reconcilia mudanças posteriores.
  O downgrade da migração de contagem é bloqueado se houver registros, para
  evitar duplicações. Ao excluir mensagens, os registros de idempotência também
  são excluídos, mas os agregados permanecem; uma futura política de retenção
  deve considerar essa diferença.

## Segurança e requisitos antes de produção

- Use apenas dados fictícios e segredos locais neste estágio. Nunca versione
  credenciais reais; `.env.example` contém valores de desenvolvimento.
- Não habilite o simulador como canal real. Antes do envio real é necessário
  conectar o adaptador protegido a contexto e catálogo confiáveis e resolver a
  sincronização entre opt-out e envio concorrente.
- Defina autenticação e autorização adequadas para dados de clientes e
  atendimento. A associação simulada entre pedido e contato não basta.
- Defina e valide com o responsável por privacidade as políticas de retenção,
  exclusão, minimização de dados e tratamento de logs; elas não estão completas.
- Avalie configuração segura de segredos, acesso aos serviços, limites, backup,
  monitoramento e recuperação. Valide o sistema e as regras vigentes da Meta em
  sandbox antes de qualquer piloto.

## Integrações externas pendentes

Estas etapas dependem de serviços, configuração e credenciais que você pode
providenciar posteriormente:

- Adaptador de envio e recebimento efetivo com a WhatsApp Cloud API, incluindo
  catálogo de templates e validação no sandbox da Meta.
- Chatwoot ou outra solução de atendimento humano, com interface de atendente,
  entrega e devolução de conversas.
- Sistemas reais de pedidos e agenda, com autenticação e regras comerciais.
- Integração e conciliação de dados de uso/faturamento oficiais, se necessárias.

Ainda há tarefas **internas**, não apenas integrações: fila operacional,
controles de privacidade, métricas, testes de carga e documentação operacional.

## Verificações

```powershell
python -m pytest
ruff check .
mypy
```

Os testes concorrentes de PostgreSQL são opcionais e gravam dados de teste.
Use **somente um banco PostgreSQL descartável e isolado**, aplique as migrações
nesse banco e forneça sua URL em `TEST_POSTGRESQL_DATABASE_URL`:

```powershell
$env:TEST_POSTGRESQL_DATABASE_URL = 'postgresql+psycopg://usuario:senha@localhost:5432/banco_descartavel'
$env:DATABASE_URL = $env:TEST_POSTGRESQL_DATABASE_URL
python -m alembic upgrade head
python -m pytest tests\integration\test_usage_postgresql.py tests\integration\test_handoff_postgresql.py
```

Sem essa variável, os dois testes são ignorados. Não aponte para banco
compartilhado ou de produção. `DATABASE_URL` permanece configurada no terminal
após esses comandos; remova ou restaure seu valor antes de outras operações.
