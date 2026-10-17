from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..models import Encomenda, Pagamento, Sessao
from . import creditos, faturacao, loja, notificacoes
from .multicaixa import GatewayErro, obter_gateway
from .pagamentos import PagamentoErro

E = Pagamento.EstadoPagamento
REFERENCIA_CREDITO = "CREDITO"  # pagamento coberto integralmente por credito (sem gateway)


def _emitir_referencia(pagamento, usar_credito):
    """Aplica (opcionalmente) o credito do aluno e pede a referencia ao gateway pelo valor que falta.
    Se o credito cobre tudo, o pagamento e aprovado de imediato, sem passar pelo gateway.
    Idempotente: com a referencia ja emitida nao muda nada (nem o valor a cobrar)."""
    if pagamento.referencia_multicaixa:
        if usar_credito and pagamento.credito_aplicado == 0:
            raise PagamentoErro("A referencia de pagamento ja foi emitida sem credito; nao pode ser alterada.", 409)
        return pagamento
    if usar_credito:
        creditos.aplicar_credito(pagamento)
    if pagamento.valor_a_pagar <= 0:
        pagamento.referencia_multicaixa = REFERENCIA_CREDITO
        pagamento.save(update_fields=["referencia_multicaixa"])
        aprovar_pagamento(pagamento)
    else:
        # o gateway deve cobrar `pagamento.valor_a_pagar` (valor menos o credito aplicado)
        try:
            pagamento.referencia_multicaixa = obter_gateway().iniciar_transacao(pagamento)
        except GatewayErro as erro:
            # o credito eventualmente aplicado volta ao aluno: nada fica a meio
            creditos.restituir_creditos(pagamento)
            raise PagamentoErro(f"Nao foi possivel iniciar o pagamento: {erro}", 502)
        pagamento.save(update_fields=["referencia_multicaixa"])
    return pagamento


@transaction.atomic
def iniciar_pagamento(sessao, usar_credito=False):
    """POST /payments: pede ao gateway uma referencia para o pagamento pendente da sessao."""
    if sessao.estado != Sessao.EstadoSessao.AGENDADA:
        raise PagamentoErro("So se pode pagar uma sessao agendada.", 409)
    pagamento = sessao.pagamentos.select_for_update().filter(estado__in=[E.PENDENTE, E.APROVADO]).first()
    if pagamento is None or (pagamento.estado == E.APROVADO and pagamento.referencia_multicaixa != REFERENCIA_CREDITO):
        raise PagamentoErro("Nao existe pagamento pendente para esta sessao.", 409)
    return _emitir_referencia(pagamento, usar_credito)


def aprovar_pagamento(pagamento):
    """Passa o pagamento a aprovado e dispara o que depende disso (documentos, encomenda paga, avisos)."""
    pagamento.transitar(E.APROVADO, data_aprovacao=timezone.now())
    faturacao.emitir_documentos(pagamento)
    if pagamento.encomenda_id:
        encomenda = pagamento.encomenda
        encomenda.transitar(Encomenda.Estado.PAGA)
        notificacoes.encomenda_atualizada(encomenda, "paga e vai ser preparada")
    else:
        notificacoes.pagamento_aprovado(pagamento)


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
        aprovar_pagamento(pagamento)
    else:
        pagamento.transitar(E.RECUSADO)
        creditos.restituir_creditos(pagamento)
        if pagamento.encomenda_id:
            loja.cancelar_encomenda(pagamento.encomenda)  # liberta o stock reservado
        else:
            notificacoes.pagamento_recusado(pagamento)
    return pagamento, True


@transaction.atomic
def iniciar_pagamento_encomenda(encomenda, usar_credito=False):
    """POST /payments {"encomenda_id": N}: referencia do gateway para o pagamento pendente da encomenda."""
    if encomenda.estado != Encomenda.Estado.PENDENTE_PAGAMENTO:
        raise PagamentoErro("So se pode pagar uma encomenda pendente de pagamento.", 409)
    pagamento = encomenda.pagamentos.select_for_update().filter(estado=E.PENDENTE).first()
    if pagamento is None:
        raise PagamentoErro("Nao existe pagamento pendente para esta encomenda.", 409)
    return _emitir_referencia(pagamento, usar_credito)


@transaction.atomic
def libertar_pagamento(pagamento_id, user=None, automatico=False):
    """BR-03: liberta ao PT o valor liquido de um pagamento aprovado cuja sessao foi realizada.
    Manual: pelo aluno (confirmacao de realizacao) ou por um admin. Automatico: ver
    `libertar_pagamentos_elegiveis`."""
    try:
        pagamento = Pagamento.objects.select_for_update(of=("self",)).select_related("sessao__aluno").get(pk=pagamento_id)
    except Pagamento.DoesNotExist:
        raise PagamentoErro("Pagamento nao encontrado.", 404)
    sessao = pagamento.sessao
    if not automatico:
        if not (user.is_staff or (sessao and sessao.aluno.utilizador_id == user.id)):
            raise PagamentoErro("Sem permissao para libertar este pagamento.", 403)
    if pagamento.estado != E.APROVADO:
        raise PagamentoErro(f"Apenas pagamentos aprovados podem ser libertados (atual: '{pagamento.estado}').", 409)
    if sessao is None or sessao.estado not in Sessao.ESTADOS_REALIZADOS:
        raise PagamentoErro("A sessao ainda nao foi realizada.", 409)
    if sessao.reclamacao and not (user and user.is_staff):
        raise PagamentoErro("Existe uma reclamacao em aberto para esta sessao.", 409)
    try:
        obter_gateway().transferir_para_pt(pagamento)
    except GatewayErro:
        raise PagamentoErro("Falha na transferencia para o profissional; tente novamente.", 502)
    pagamento.transitar(E.LIBERTADO, data_libertacao=timezone.now())
    notificacoes.pagamento_libertado(pagamento)
    return pagamento


JANELA_LIBERTACAO_AUTOMATICA = timedelta(hours=24)


def libertar_pagamentos_elegiveis(agora=None):
    """BR-03: liberta os pagamentos de sessoes realizadas ha mais de 24h sem reclamacao.
    Pensado para correr periodicamente (cron / `manage.py libertar_pagamentos`). Devolve a contagem."""
    limite = (agora or timezone.now()) - JANELA_LIBERTACAO_AUTOMATICA
    candidatos = Pagamento.objects.filter(
        estado=E.APROVADO, sessao__estado__in=Sessao.ESTADOS_REALIZADOS,
        sessao__data_realizacao__lte=limite, sessao__reclamacao="",
    ).values_list("pk", flat=True)
    libertados = 0
    for pk in candidatos:
        try:
            libertar_pagamento(pk, automatico=True)
            libertados += 1
        except PagamentoErro:
            continue  # fica para a proxima execucao
    return libertados
