import csv
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from ..models import (
    Avaliacao, CreditoAluno, Encomenda, Pagamento, ParceriaPT, PersonalTrainer, RemuneracaoParceria, Sessao, Utilizador,
)

P = Pagamento.EstadoPagamento
# pagamentos que representam dinheiro efetivamente recebido pela plataforma (nao reembolsado)
RECEBIDOS = (P.APROVADO, P.LIBERTADO)


def intervalo(de=None, ate=None):
    """Converte datas (inclusivas) para um intervalo [inicio, fim) de datetimes no fuso local; None = sem limite."""
    zona = timezone.get_current_timezone()
    inicio = timezone.make_aware(datetime.combine(de, time.min), zona) if de else None
    fim = timezone.make_aware(datetime.combine(ate + timedelta(days=1), time.min), zona) if ate else None
    return inicio, fim


def _no_intervalo(qs, campo, inicio, fim):
    if inicio:
        qs = qs.filter(**{f"{campo}__gte": inicio})
    if fim:
        qs = qs.filter(**{f"{campo}__lt": fim})
    return qs


def _contagem_por(qs, campo):
    return {linha[campo]: linha["total"] for linha in qs.values(campo).annotate(total=Count("id")).order_by(campo)}


def relatorio_plataforma(de=None, ate=None):
    """RelatorioPlataforma (UC-15): utilizadores, sessoes e receita. As datas filtram o que aconteceu no periodo
    (registos novos, sessoes agendadas, pagamentos aprovados); `utilizadores.total` e sempre o total atual."""
    inicio, fim = intervalo(de, ate)
    agora = timezone.now()

    utilizadores = Utilizador.objects.all()
    novos = _no_intervalo(utilizadores, "data_criacao", inicio, fim)
    sessoes = _no_intervalo(Sessao.objects.all(), "data_hora", inicio, fim)
    pagamentos = _no_intervalo(Pagamento.objects.filter(data_aprovacao__isnull=False), "data_aprovacao", inicio, fim)
    # pagamentos retidos e convertidos em credito nao sao receita: sao uma divida ao aluno ate o credito ser usado
    recebidos = pagamentos.filter(estado__in=RECEBIDOS, convertido_em_credito=False)
    sessoes_pag = recebidos.filter(sessao__isnull=False)
    loja_pag = recebidos.filter(encomenda__isnull=False)
    reembolsos = pagamentos.filter(estado=P.REEMBOLSADO)

    soma = lambda qs, campo: qs.aggregate(t=Sum(campo))["t"] or Decimal("0")  # noqa: E731
    comissoes = soma(sessoes_pag, "comissao_plataforma")
    vendas_loja = soma(loja_pag, "valor")
    parcerias = RemuneracaoParceria.objects.all()  # `mes` e um DateField: filtra-se por data, nao por datetime
    if de:
        parcerias = parcerias.filter(mes__gte=de.replace(day=1))
    if ate:
        parcerias = parcerias.filter(mes__lte=ate)
    custo_parcerias = soma(parcerias, "valor")

    return {
        "periodo": {"de": de, "ate": ate},
        "utilizadores": {
            "total": utilizadores.count(),
            "por_tipo": _contagem_por(utilizadores, "tipo"),
            "novos_no_periodo": novos.count(),
            "suspensos": utilizadores.filter(suspenso=True).count(),
        },
        "sessoes": {
            "total": sessoes.count(),
            "por_estado": _contagem_por(sessoes, "estado"),
            "avaliacao_media": Avaliacao.objects.filter(
                avaliado__perfil_personal_trainer__isnull=False,
                sessao__in=sessoes).aggregate(m=Avg("classificacao"))["m"],
        },
        "personal_trainers": {
            "por_estado": _contagem_por(PersonalTrainer.objects.all(), "estado_verificacao"),
            "parceiros_ativos": ParceriaPT.objects.filter(estado=ParceriaPT.Estado.ATIVA).count(),
        },
        "encomendas": {
            "total": _no_intervalo(Encomenda.objects.all(), "data_criacao", inicio, fim).count(),
            "por_estado": _contagem_por(_no_intervalo(Encomenda.objects.all(), "data_criacao", inicio, fim), "estado"),
        },
        "receita": {
            "pagamentos_sessoes_bruto": soma(sessoes_pag, "valor"),
            "comissoes_plataforma": comissoes,
            "liquido_devido_a_pts": soma(sessoes_pag, "valor_liquido_pt"),
            "vendas_loja": vendas_loja,
            "reembolsado": soma(reembolsos, "valor"),
            "custo_parcerias_registado": custo_parcerias,
            "credito_utilizado": soma(recebidos, "credito_aplicado"),
            "credito_em_aberto": soma(CreditoAluno.objects.filter(data_expiracao__gt=agora), "valor_restante"),
            "credito_expirado_nao_usado": soma(CreditoAluno.objects.filter(data_expiracao__lte=agora), "valor_restante"),
            "receita_plataforma": comissoes + vendas_loja,
            "resultado_apos_parcerias": comissoes + vendas_loja - custo_parcerias,
        },
        "pagamentos_por_estado": _contagem_por(pagamentos, "estado"),
    }


# --- exportacao CSV ---
def _celula(valor):
    """Neutraliza injecao de formulas quando o CSV e aberto em folhas de calculo."""
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


def _csv(cabecalho, linhas):
    saida = io.StringIO()
    escritor = csv.writer(saida)
    escritor.writerow(cabecalho)
    for linha in linhas:
        escritor.writerow([_celula(c) for c in linha])
    return "﻿" + saida.getvalue()  # BOM: o Excel reconhece UTF-8


def csv_pagamentos(de=None, ate=None):
    inicio, fim = intervalo(de, ate)
    qs = _no_intervalo(
        Pagamento.objects.filter(data_aprovacao__isnull=False)
        .select_related("sessao__aluno__utilizador", "sessao__personal_trainer__utilizador", "encomenda__aluno__utilizador")
        .prefetch_related("documentos").order_by("data_aprovacao", "id"),
        "data_aprovacao", inicio, fim)
    linhas = []
    for p in qs:
        origem = p.sessao or p.encomenda
        faturas = ",".join(d.numero for d in p.documentos.all() if d.tipo == "FT")
        linhas.append([
            p.id, "sessao" if p.sessao_id else "encomenda", origem.id if origem else "",
            timezone.localtime(p.data_aprovacao).strftime("%Y-%m-%d %H:%M"),
            origem.aluno.utilizador.username if origem else "",
            p.sessao.personal_trainer.utilizador.username if p.sessao_id else "",
            p.valor, p.credito_aplicado, p.comissao_plataforma, p.valor_liquido_pt, p.estado,
            "sim" if p.convertido_em_credito else "", p.referencia_multicaixa, faturas,
        ])
    return _csv(["pagamento_id", "tipo", "origem_id", "data_aprovacao", "cliente", "personal_trainer", "valor",
                 "credito_aplicado", "comissao_plataforma", "valor_liquido_pt", "estado", "convertido_em_credito",
                 "referencia_multicaixa", "fatura"], linhas)


def csv_parcerias(de=None, ate=None):
    qs = RemuneracaoParceria.objects.select_related("parceria__personal_trainer__utilizador").order_by("mes", "id")
    if de:
        qs = qs.filter(mes__gte=de.replace(day=1))
    if ate:
        qs = qs.filter(mes__lte=ate)
    linhas = [[r.id, r.parceria.personal_trainer.utilizador.username, r.mes.strftime("%Y-%m"), r.valor, r.estado,
               timezone.localtime(r.data_pagamento).strftime("%Y-%m-%d %H:%M") if r.data_pagamento else ""] for r in qs]
    return _csv(["remuneracao_id", "personal_trainer", "mes", "valor", "estado", "data_pagamento"], linhas)
