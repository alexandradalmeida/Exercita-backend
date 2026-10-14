from datetime import timedelta
from decimal import Decimal

from decouple import config
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from ..models import CreditoAluno
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
