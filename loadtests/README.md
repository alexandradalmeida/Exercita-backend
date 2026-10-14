# Testes de carga (RNF-01 e RNF-05)

Requisitos do SRS: respostas < 2 s em 95% dos pedidos (RNF-01) e suporte a 50 000 utilizadores ativos
mensais (RNF-05); a Fase 8 pede validação a **2x** essa capacidade (100 000 MAU).

## O que já está automatizado (corre em `manage.py test`)
- `core/test_performance.py`: pesquisa com 2 000 PTs, 100 pedidos sequenciais.
- `core/test_carga.py`: 3 000 PTs, 600 pedidos com 16 clientes em simultâneo (pesquisa, perfil, disponibilidade,
  notificações). Resultado de referência numa máquina de desenvolvimento (Postgres em Docker):
  p50 ≈ 0,19 s, p95 ≈ 0,36 s, 0 erros 5xx.

Estes testes correm em processo, sem rede nem servidor WSGI: detetam regressões e erros de concorrência, mas
**não provam** a capacidade do ambiente de produção.

## Teste de carga HTTP (staging)
`locustfile.py` simula um aluno típico. Dimensionamento (pressupostos a validar com dados reais do produto):

| Pressuposto | Valor |
|---|---|
| MAU alvo x2 (RNF-05 x2) | 100 000 |
| Utilizadores ativos por dia (20% dos MAU) | 20 000 |
| Pedidos por sessão de utilização | ~30 |
| Concentração: 40% do tráfego diário em 2 h de pico | |
| **Pico estimado** | 20 000 x 30 x 0,4 / 7 200 s ≈ **33 pedidos/s** |

Aponta-se a um alvo com folga (ex.: 100 pedidos/s, ~1 000 utilizadores virtuais com espera de 1–5 s) e valida-se
p95 < 2 s, taxa de erros < 1% e CPU/ligações de BD estáveis. Repetir após cada alteração relevante de modelo ou índice.

## Antes de correr contra staging
1. Usar uma base com volume realista (dezenas de milhares de PTs/sessões) e a cache Redis configurada (`REDIS_URL`).
2. As quotas de `THROTTLE_*` aplicam-se por IP/utilizador: para testes de carga a partir de poucos IPs, aumentar
   temporariamente `THROTTLE_USER`/`THROTTLE_ANON` no staging.
3. Não correr contra produção.
