from django.db import transaction
from django.utils import timezone

from ..models import Pagamento, Sessao
from .multicaixa import obter_gateway
from .pagamentos import PagamentoErro

E = Pagamento.EstadoPagamento


def iniciar_pagamento(sessao):
    """POST /payments: pede ao gateway uma referencia para o pagamento pendente da sessao."""
    if sessao.estado != Sessao.EstadoSessao.AGENDADA:
        raise PagamentoErro("So se pode pagar uma sessao agendada.", 409)
    pagamento = sessao.pagamentos.filter(estado=E.PENDENTE).first()
    if pagamento is None:
        raise PagamentoErro("Nao existe pagamento pendente para esta sessao.", 409)
    if not pagamento.referencia_multicaixa:  # idempotente: reutiliza a referencia ja emitida
        pagamento.referencia_multicaixa = obter_gateway().iniciar_transacao(pagamento)
        pagamento.save(update_fields=["referencia_multicaixa"])
    return pagamento


@transaction.atomic
def processar_callback(pagamento_id, referencia, resultado):
    """Webhook assincrono do gateway. Idempotente: repetir o mesmo resultado nao altera nada."""
    try:
        pagamento = Pagamento.objects.select_for_update().get(pk=pagamento_id)
    except Pagamento.DoesNotExist:
        raise PagamentoErro("Pagamento nao encontrado.", 404)
    if not pagamento.referencia_multicaixa or pagamento.referencia_multicaixa != referencia:
        raise PagamentoErro("Referencia nao corresponde ao pagamento.", 400)
    if resultado not in (E.APROVADO, E.RECUSADO):
        raise PagamentoErro("Resultado invalido.", 400)

    if pagamento.estado == resultado:
        return pagamento, False
    if pagamento.estado != E.PENDENTE:
        raise PagamentoErro(f"Pagamento ja se encontra '{pagamento.estado}'.", 409)

    if resultado == E.APROVADO:
        pagamento.transitar(E.APROVADO, data_aprovacao=timezone.now())
    else:
        pagamento.transitar(E.RECUSADO)
    return pagamento, True
