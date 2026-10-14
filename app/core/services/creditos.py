from datetime import timedelta
from decimal import Decimal

from decouple import config
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from ..models import CreditoAluno, UsoCredito
from . import notificacoes


def validade_dias():
    return int(config("CREDIT_VALIDITY_DAYS", default="90"))


def ativos(aluno, agora=None):
    """Creditos utilizaveis: com saldo e ainda dentro da validade, os que expiram primeiro vem primeiro."""
    return CreditoAluno.objects.filter(
        aluno=aluno, valor_restante__gt=0, data_expiracao__gt=agora or timezone.now()).order_by("data_expiracao", "id")


def saldo(aluno, agora=None):
    return ativos(aluno, agora).aggregate(t=Sum("valor_restante"))["t"] or Decimal("0")


@transaction.atomic
def gerar_credito_cancelamento(pagamento):
    """Converte em credito o valor retido de um pagamento cujo cancelamento nao tem direito a reembolso.
    Idempotente: um pagamento so gera credito uma vez. O pagamento fica `aprovado` (valor retido pela plataforma)."""
    existente = CreditoAluno.objects.filter(pagamento_origem=pagamento).first()
    if existente:
        return existente
    origem = pagamento.sessao or pagamento.encomenda
    credito = CreditoAluno.objects.create(
        aluno=origem.aluno, origem=CreditoAluno.Origem.CANCELAMENTO_TARDIO, valor=pagamento.valor,
        valor_restante=pagamento.valor, pagamento_origem=pagamento,
        data_expiracao=timezone.now() + timedelta(days=validade_dias()))
    pagamento.convertido_em_credito = True
    pagamento.save(update_fields=["convertido_em_credito"])
    notificacoes.credito_gerado(credito)
    return credito


@transaction.atomic
def aplicar_credito(pagamento):
    """Desconta ao pagamento (pendente) o credito disponivel do aluno, usando primeiro o que expira mais cedo.
    Idempotente: se ja foi aplicado credito a este pagamento nao aplica de novo. Devolve o valor aplicado."""
    if pagamento.credito_aplicado > 0:
        return pagamento.credito_aplicado
    origem = pagamento.sessao or pagamento.encomenda
    em_falta = pagamento.valor
    aplicado = Decimal("0")
    for credito in ativos(origem.aluno).select_for_update():
        if em_falta <= 0:
            break
        usar = min(credito.valor_restante, em_falta)
        credito.valor_restante -= usar
        credito.save(update_fields=["valor_restante"])
        UsoCredito.objects.create(credito=credito, pagamento=pagamento, valor=usar)
        aplicado += usar
        em_falta -= usar
    if aplicado:
        pagamento.credito_aplicado = aplicado
        pagamento.save(update_fields=["credito_aplicado"])
    return aplicado


@transaction.atomic
def restituir_creditos(pagamento):
    """Devolve ao aluno o credito que este pagamento tinha consumido (pagamento recusado, cancelado ou reembolsado).
    Se o credito original ja expirou, devolve-se um credito novo com a validade completa (nao se perde o direito)."""
    for uso in pagamento.usos_credito.select_for_update().filter(restituido=False).select_related("credito"):
        credito = uso.credito
        if credito.data_expiracao > timezone.now():
            credito.valor_restante += uso.valor
            credito.save(update_fields=["valor_restante"])
        else:
            CreditoAluno.objects.create(
                aluno=credito.aluno, origem=CreditoAluno.Origem.ESTORNO, valor=uso.valor, valor_restante=uso.valor,
                data_expiracao=timezone.now() + timedelta(days=validade_dias()))
        uso.restituido = True
        uso.save(update_fields=["restituido"])


def expirar_e_avisar(agora=None, dias_aviso=7):
    """Tarefa periodica: avisa dos creditos a expirar nos proximos `dias_aviso` dias (uma vez por credito).
    A expiracao em si e imediata: um credito vencido deixa logo de ser utilizavel (ver `ativos`).
    Devolve (avisados, expirados_com_saldo)."""
    agora = agora or timezone.now()
    a_expirar = CreditoAluno.objects.filter(
        valor_restante__gt=0, data_expiracao__gt=agora, data_expiracao__lte=agora + timedelta(days=dias_aviso),
        expiracao_notificada=False).select_related("aluno__utilizador")
    avisados = 0
    for credito in a_expirar:
        notificacoes.credito_a_expirar(credito)
        credito.expiracao_notificada = True
        credito.save(update_fields=["expiracao_notificada"])
        avisados += 1
    expirados = CreditoAluno.objects.filter(valor_restante__gt=0, data_expiracao__lte=agora).count()
    return avisados, expirados
