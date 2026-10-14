# Exercita backend — operação, segurança e lançamento

## 1. Executar

| Ambiente | Como |
|---|---|
| Local | `docker compose up -d db`, `cd app`, `python manage.py migrate`, `python manage.py runserver` |
| Testes | `python manage.py test core` (usa hash de passwords rápido e embeddings locais) |
| Produção | imagem `docker/Dockerfile.prod` (gunicorn, utilizador não-root), `DJANGO_SETTINGS_MODULE=config.settings.production` |

Documentação da API (OpenAPI): `/api/docs/` (Swagger), `/api/redoc/`, `/api/schema/`.
O schema é validado em cada `manage.py test` (`core/test_documentacao.py`, falha com qualquer aviso).

## 2. Variáveis de ambiente de produção

Ver `.env.example`. Obrigatórias: `DJANGO_SECRET_KEY` (≥ 50 caracteres, única), `ALLOWED_HOSTS` (sem `*`),
`POSTGRES_*`, `FIELD_ENCRYPTION_KEY`. A aplicação **recusa arrancar** em produção se a chave for fraca ou
`ALLOWED_HOSTS` estiver vazio. Recomendadas: `REDIS_URL` (cache partilhada), `EMAIL_*`, `POSTGRES_SSLMODE=require`.

Credenciais externas ainda por obter (ver secção 6): Multicaixa Express, Google OAuth, Apple Sign In, FCM/APNs,
chave de geocodificação, `OPENAI_API_KEY` (embeddings).

## 3. Tarefas periódicas (a agendar — não existe agendador na aplicação)

| Comando | Frequência sugerida | Função |
|---|---|---|
| `libertar_pagamentos` | de hora a hora | BR-03: liberta pagamentos de sessões realizadas há > 24 h sem reclamação |
| `enviar_lembretes` | de hora a hora | lembretes de sessões nas próximas 24 h |
| `gerar_remuneracoes` | dia 1 de cada mês | BR-04: regista a remuneração mensal dos PTs parceiros |

Executar como *cron job* / tarefa agendada do orquestrador, com a mesma imagem e variáveis de ambiente.
As migrações (`python manage.py migrate`) correm como passo do deploy, não em cada réplica.

## 4. Disponibilidade e escala (RNF-04: 99,5%)

Implementado na aplicação:
- `GET /api/health/` (liveness) e `GET /api/health/ready/` (readiness: verifica a base de dados, devolve 503 se falhar).
- Aplicação *stateless* (sessões via JWT); estado partilhado (cache de `state` OAuth, limites de pedidos) em Redis.
- Logs para stdout.

**A configurar na infraestrutura** (não faz parte deste repositório):
- ≥ 2 réplicas atrás de um load balancer, com health checks nos endpoints acima e TLS terminado no balanceador
  (que tem de enviar `X-Forwarded-Proto`).
- Auto-scaling horizontal por CPU/latência, mínimo 2 e máximo dimensionado pelo teste de carga (`loadtests/README.md`).
- PostgreSQL gerido com *backups* diários e réplica; extensão `vector` (pgvector) disponível.
- Monitorização externa de disponibilidade (ping a `/api/health/ready/` de uma região externa) e alertas
  para taxa de erros 5xx, p95 de latência > 2 s e falhas dos comandos periódicos.
- 99,5% equivale a ~3,6 h de indisponibilidade/mês: planear deploys sem downtime (rolling) e migrações compatíveis.

## 5. Auditoria de segurança (RNF-02) e RGPD

| Controlo | Estado |
|---|---|
| TLS em trânsito (HTTPS forçado, HSTS 1 ano, cookies seguros, `X-Forwarded-Proto`) | feito em `production.py`, verificado com `check --deploy` |
| TLS até à base de dados (`sslmode=require`) | feito (configurável) |
| Encriptação em repouso: telefone com AES-256-GCM ao nível do campo | feito |
| Encriptação em repouso do disco/backups da base de dados | **infraestrutura** (volume/BD gerida encriptada) |
| Passwords: hash Django (PBKDF2) + validadores; login/registo limitados a 10 pedidos/min por IP | feito |
| JWT: acesso 1 h, refresh 7 dias com rotação e *blacklist*; contas suspensas invalidadas de imediato | feito |
| OAuth Google: `state` único com expiração, validação do `id_token`; Apple: validação JWKS | feito |
| Webhook de pagamento: assinatura HMAC, comparação em tempo constante; sem segredo configurado rejeita tudo | feito |
| Autorização por objeto (um utilizador só vê/edita o que é seu) | coberta por testes em todos os módulos |
| Injeção SQL (ORM, sem SQL cru) e injeção de fórmulas em CSV exportados | feito |
| Segredos fora do repositório (`.env`, chaves `.p8` ignorados no git) | feito |
| Dependências sem auditoria automática | **pendente**: ativar `pip-audit`/Dependabot no CI |
| CORS | não ativado (a API serve a app móvel); se houver cliente web, configurar `django-cors-headers` com lista de origens |

RGPD:
- **Acesso e portabilidade**: `GET /api/v1/users/me/data-export/` (JSON com todos os dados do titular).
- **Apagamento**: `DELETE /api/v1/users/me/` (exige password). Anonimiza a conta e apaga dados pessoais e de saúde
  (medições, treinos, refeições, planos, favoritos, reservas, notificações). Faturas, recibos e pagamentos são
  **conservados** por obrigação legal, mas deixam de identificar a pessoa. Bloqueado enquanto houver sessões,
  encomendas ou pagamentos por libertar.
- Dados de saúde (UC-11/UC-14) são dados sensíveis: o consentimento explícito e a base legal devem ser formalizados nos
  termos da app (o backend ainda não regista consentimento).
- Retenção: não há política automática de expiração de dados; definir prazos com o DPO.

## 6. Pendente de dependências externas (Fase 9)

- Multicaixa Express (`core/services/multicaixa.py`): contrato real, credenciais, formato e assinatura do webhook.
- Push FCM/APNs; Google Calendar (OAuth de calendário); geocodificação (Google Maps); embeddings (OpenAI).
- Faturação certificada (as faturas atuais **não** têm valor fiscal).
- Integração com wearables (apenas a estrutura de ingestão existe).
