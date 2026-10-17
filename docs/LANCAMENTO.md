# Lista de verificação de lançamento (Fase 9)

Estado em tempo real: `GET /api/v1/admin/integrations/` (admin) devolve, para cada integração, o modo, o estado
(`ativa`, `simulada`, `em_falta`) e o que falta. `pronto_para_lancamento` só é `true` com Multicaixa, email e
Google OAuth ativos.

## A. Bloqueantes — dependem de terceiros

| # | Item | O que é preciso | Onde mexer |
|---|---|---|---|
| 1 | **Multicaixa Express** | contrato, credenciais, documentação da API e do webhook (formato e assinatura), sandbox | implementar `MulticaixaReal` em `core/services/multicaixa.py` (`iniciar_transacao`, `reembolsar`, `transferir_para_pt`) e ajustar `assinar`/`assinatura_valida`; definir `MULTICAIXA_BACKEND=real` e `MULTICAIXA_WEBHOOK_SECRET`; o gateway tem de cobrar `pagamento.valor_a_pagar` (valor menos crédito) |
| 2 | **Email transacional** | servidor SMTP / serviço de email e domínio verificado | `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, `BACKEND_URL` |
| 3 | **Google OAuth** | projeto Google Cloud, ecrã de consentimento aprovado, URIs de redirecionamento de produção | `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` |
| 4 | **Apple Sign In** | conta Apple Developer, Services ID, chave `.p8` | `APPLE_CLIENT_ID/TEAM_ID/KEY_ID/PRIVATE_KEY_PATH` (o endpoint móvel já valida o `id_token`; falta o fluxo web) |
| 5 | **Infraestrutura** | domínio + TLS, PostgreSQL gerido com pgvector, Redis, ≥ 2 réplicas, backups, monitorização, auto-scaling | `docs/OPERACAO.md` §4; variáveis de produção em `.env.example` |

Como testar a integração Multicaixa quando chegar o sandbox: criar uma subclasse de `GatewayContratoMixin`
(`core/test_fase9.py`) com `criar_gateway` a devolver `MulticaixaReal()`; o contrato é o mesmo do mock.

Arrancar em produção com `MULTICAIXA_BACKEND=mock` é recusado (um mock marcaria estornos como feitos sem mexer em
dinheiro real). Em staging usar `ALLOW_MOCK_INTEGRATIONS=True`.

## B. Importantes, mas não bloqueiam um lançamento fechado

| Item | Situação |
|---|---|
| Push (FCM/APNs) | simulado (log); falta credenciais, tokens de dispositivo e `PushGateway` real |
| Geocodificação (Google Maps) | sem chave os ginásios precisam de latitude/longitude manuais |
| Embeddings (OpenAI) | com `OPENAI_API_KEY` válida usa `text-embedding-3-small`; sem ela, matching lexical local. Falha do serviço não derruba a pesquisa |
| Google Calendar | exportação `.ics` funciona; sincronização automática exige OAuth de calendário |
| Wearables | só a estrutura de ingestão (`/progress/wearables/ingest/`) |
| Faturação certificada | as faturas internas **não têm valor fiscal**; é preciso software certificado antes de faturar a clientes |
| Auditoria de dependências | ligar `pip-audit`/Dependabot ao CI |
| Teste de carga HTTP a 2× 50 000 MAU | correr o `locustfile` em staging (`loadtests/README.md`) |

## C. Decisões de negócio por fechar

| Tema | Pergunta |
|---|---|
| Cancelamento tardio | o PT recebe alguma compensação? (hoje: nada; o valor fica retido e o aluno recebe crédito de 90 dias) |
| Crédito expirado | tratamento contabilístico/fiscal do valor retido que expira |
| Pacote e plano mensal | regras de preço, número de sessões e renovação (hoje: preço × quantidade, uma sessão) |
| Consentimento e retenção de dados | termos, consentimento explícito para dados de saúde, prazos de retenção |
| Fornecedores e "planos" | modelo e regras de pagamento (o cronograma menciona-os na gestão de parceiros) |
| Aulas de ginásio | lotação por aula; confirmação pelo ginásio |
| Nutricionista | consentimento do aluno antes de lhe atribuírem um plano |

## D. Antes do primeiro utilizador real

1. Aplicar migrações (`python manage.py migrate`) como passo do deploy.
2. Criar o superutilizador (`createsuperuser`) e, por ele, as contas de admin (`/api/v1/admin/users/{id}/permissions/`).
3. Definir comissão e limiares em `/api/v1/admin/config/` se diferirem dos valores por omissão (15%, 4.0/3.0/5).
4. Agendar: `libertar_pagamentos` e `enviar_lembretes` (horário), `avisar_creditos` (diário), `gerar_remuneracoes` (dia 1).
5. Confirmar `GET /api/health/ready/` no load balancer e os alertas (5xx, p95 > 2 s).
6. Fazer um ensaio completo em staging (registo → contratação → pagamento → sessão → libertação → avaliação).
