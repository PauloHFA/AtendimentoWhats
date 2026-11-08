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

Os testes de contrato, fluxo e API rodam com `python -m pytest`; não precisam de Docker nem de credenciais da Meta.

## Verificações

```powershell
python -m pytest
ruff check .
mypy
```
