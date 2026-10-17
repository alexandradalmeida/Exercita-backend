# Exercita — backend

API da plataforma de saúde e bem-estar Exercita: marketplace de Personal Trainers, agendamento, pagamentos
(Multicaixa Express), avaliações, ginásios, nutrição, loja, progresso físico e administração.

**Stack:** Django 6 · Django REST Framework · PostgreSQL 16 + pgvector · JWT (simplejwt) · drf-spectacular.

## Começar

```bash
docker compose up -d db                      # Postgres + pgvector (porta DB_HOST_PORT, 5432 por omissão)
python -m venv venv && venv/Scripts/pip install -r app/requirements.txt
cp .env.example .env                         # preencher valores reais; com a API fora do Docker, POSTGRES_HOST=localhost
cd app
python manage.py migrate
python manage.py runserver
python manage.py test core                   # ~480 testes
```

Documentação interativa da API: `http://localhost:8000/api/docs/` (Swagger) · `/api/redoc/` · `/api/schema/`.

## Estado do projeto (fases do cronograma)

| Fase | Conteúdo | Estado |
|---|---|---|
| 0–1 | Infraestrutura, autenticação (email, Google, Apple), perfis, verificação de PT (BR-01) | feito |
| 2 | Marketplace: pesquisa, perfis públicos, disponibilidade, favoritos, matching por embeddings | feito |
| 3 | Sessões, pagamentos Multicaixa, comissão (BR-06), libertação (BR-03), notificações, calendário | feito (gateway simulado) |
| 4 | Avaliações mútuas (BR-05), reputação e qualidade do PT (BR-02) | feito |
| 5 | Ginásios, geolocalização, reservas | feito (geocodificação por chave: pendente) |
| 6 | Nutrição, loja, faturas/recibos, PTs parceiros (BR-04) | feito |
| 7 | Progresso físico, administração, relatórios, configuração | feito |
| 8 | E2E, carga, segurança/RGPD, Swagger, imagem de produção | feito |
| 9 | Contingência: integrações externas, guardas de produção, lista de lançamento | feito (ver abaixo) |
| extra | Crédito do aluno por cancelamento tardio (90 dias) | feito |

## Antes do lançamento

O que impede o lançamento comercial **não é código**: são dependências externas. O estado em tempo real está em
`GET /api/v1/admin/integrations/` (apenas admin) e a lista completa em
[`docs/LANCAMENTO.md`](docs/LANCAMENTO.md). Operação, segurança e RGPD: [`docs/OPERACAO.md`](docs/OPERACAO.md).
Testes de carga em staging: [`loadtests/README.md`](loadtests/README.md).

## Estrutura

```
app/config/        definições (base, dev, production) e URLs
app/core/          modelos, serviços (services/), views_*.py, testes (test_*.py)
app/core/services/ regras de negócio e integrações atrás de interfaces (multicaixa, embeddings, geocoding, ...)
docker/            Dockerfile (dev) e Dockerfile.prod (gunicorn, não-root)
docs/              operação e lista de lançamento
loadtests/         locustfile para staging
```

## Convenções

Nomes de modelos, campos e mensagens em português; rotas sob `/api/v1/`; erros no formato
`{"erro": true, "codigo": N, "detalhes": ...}`; commits `tipo: descrição curta` (ver `CommitLabels.txt`).
