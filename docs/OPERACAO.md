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
`ALLOWED_HOSTS` estiver vazio. Opcional: `CREDIT_VALIDITY_DAYS` (validade do crédito por cancelamento tardio, 90 por omissão). Recomendadas: `REDIS_URL` (cache partilhada), `EMAIL_*`, `POSTGRES_SSLMODE=require`.

Credenciais externas ainda por obter (ver secção 6): Multicaixa Express, Google OAuth, Apple Sign In, FCM/APNs,
chave de geocodificação, `OPENAI_API_KEY` (embeddings).

## 3. Tarefas periódicas (a agendar — não existe agendador na aplicação)

| Comando | Frequência sugerida | Função |
|---|---|---|
| `libertar_pagamentos` | de hora a hora | BR-03: liberta pagamentos de sessões realizadas há > 24 h sem reclamação |
| `enviar_lembretes` | de hora a hora | lembretes de sessões nas próximas 24 h |
| `gerar_remuneracoes` | dia 1 de cada mês | BR-04: regista a remuneração mensal dos PTs parceiros |
| `avisar_creditos` | diário | avisa os alunos dos créditos que expiram nos próximos 7 dias |

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
- **Consentimento explícito para dados de saúde** (`/api/v1/consents/health/`): sem consentimento em vigor, os
  endpoints de medições, treinos, registo de refeições, resumo de progresso e wearables respondem 403, e um
  nutricionista não pode criar planos para o aluno nem ver os existentes. O aluno vê o texto e a versão (GET), consente
  com `{"versao": "1.0", "aceito": true}` (sem aceitação implícita; versão errada = 409) e retira com DELETE, opcionalmente
  `{"apagar_dados": true}` para apagar os dados de saúde já recolhidos. Cada consentimento guarda data, versão e o
  SHA-256 do texto aceite; revogar preenche a data de revogação e conserva o histórico. Mudar `HEALTH_CONSENT_VERSION`
  obriga todos a consentir de novo. **O texto atual é um rascunho técnico: tem de ser validado pelo jurídico/DPO**
  (substituível com `HEALTH_CONSENT_TEXT`, sem alterar código). O aluno continua a poder ver os planos que já tem
  (direito de acesso) depois de revogar.
- Retenção: não há política automática de expiração de dados; definir prazos com o DPO.

## 6. Pendente de dependências externas (Fase 9)

- Multicaixa Express (`core/services/multicaixa.py`): contrato real, credenciais, formato e assinatura do webhook.
- Push FCM/APNs; Google Calendar (OAuth de calendário); geocodificação (Google Maps); embeddings (OpenAI).
- Faturação certificada (as faturas atuais **não** têm valor fiscal).
- Integração com wearables (apenas a estrutura de ingestão existe).

## 7. Notas de desempenho da pesquisa

- A pesquisa com `q` ordena por distância do cosseno (pgvector). Com filtros o Postgres escolhe um plano exato
  (medido: 393 resultados corretos em ~7 ms com 3 000 PTs). Sem filtros pode usar o índice HNSW, que é
  **aproximado** e devolve, por omissão, no máximo `hnsw.ef_search` (=40) candidatos: páginas além das primeiras
  podem vir incompletas. Em produção, aumentar `hnsw.ef_search` (ex.: `SET hnsw.ef_search = 200`) ou ativar
  `hnsw.iterative_scan` (pgvector ≥ 0.8) se a paginação profunda for usada.
- Se o serviço de embeddings falhar (quota, rede), a pesquisa continua e ordena por avaliação (coberto por teste).
- Os testes de desempenho/carga medem o servidor sob a carga da própria máquina de desenvolvimento: num PC ocupado
  (sincronização OneDrive, navegador, etc.) o p95 pode subir 10x; por isso medem até 2 rodadas.

## 8. Crédito do aluno (cancelamento tardio)

- Se o **aluno** cancela dentro da janela do PT (`janela_cancelamento_horas`, 24 h por omissão), o pagamento fica
  `aprovado` e **retido pela plataforma**, e o aluno recebe um crédito do valor total, válido 90 dias
  (`GET /api/v1/credits/`). O PT não recebe nada nesse caso (a decidir se deve haver compensação).
- Usa-se com `POST /api/v1/payments/ {..., "usar_credito": true}`: o crédito que expira primeiro é consumido
  primeiro; o gateway cobra só o restante (`valor_a_pagar`). Se o crédito cobrir tudo, o pagamento é aprovado de
  imediato (referência `CREDITO`, sem gateway).
- Se o pagamento falhar, for cancelado ou reembolsado, o crédito consumido volta (como crédito novo de 90 dias se o
  original já tiver expirado). O estorno no gateway cobre apenas a parte paga em dinheiro.
- Contabilidade: um pagamento convertido em crédito **não conta como receita**; aparece como `credito_em_aberto`
  no relatório até ser usado. Créditos expirados e não usados aparecem em `credito_expirado_nao_usado`; o tratamento
  contabilístico/fiscal desse valor tem de ser validado com a contabilidade.
- Eliminar a conta é bloqueado enquanto houver crédito válido por utilizar.
