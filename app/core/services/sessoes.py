from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from ..models import Pagamento, PersonalTrainer, Sessao, SlotDisponibilidade
from . import notificacoes
from .multicaixa import GatewayErro, obter_gateway
from .pagamentos import calcular_comissao


class ErroNegocio(Exception):
    """Violacao de uma regra de negocio; `codigo` e o status HTTP sugerido."""

    def __init__(self, mensagem, codigo=400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo


def _validar_slot_e_data(slot, data_hora):
    local = timezone.localtime(data_hora)
    if local.weekday() != slot.dia_semana or local.time().replace(second=0, microsecond=0) != slot.hora_inicio:
        raise ErroNegocio("data_hora nao corresponde ao dia e hora de inicio do slot.")
    if data_hora <= timezone.now():
        raise ErroNegocio("data_hora tem de estar no futuro.")


@transaction.atomic
def contratar_personal_trainer(aluno, pt, slot, data_hora, modalidade, quantidade_sessoes=1):
    """UC-07: cria a sessao (estado Agendada) e o pagamento pendente, reservando uma vaga do slot."""
    if pt.estado_verificacao != PersonalTrainer.EstadoVerificacao.VERIFICADO:
        raise ErroNegocio("Personal Trainer nao disponivel.", 404)
    if pt.preco_hora is None:
        raise ErroNegocio("Este Personal Trainer ainda nao definiu preco.")
    if slot.personal_trainer_id != pt.id:
        raise ErroNegocio("O slot nao pertence a este Personal Trainer.")
    if modalidade == Sessao.Modalidade.INDIVIDUAL:
        quantidade_sessoes = 1
    elif quantidade_sessoes < 2:
        raise ErroNegocio("Pacote e plano mensal exigem quantidade_sessoes >= 2.")  # TODO: regras de pacote/plano a confirmar
    _validar_slot_e_data(slot, data_hora)

    # trava a linha do slot para que dois pedidos simultaneos nao ocupem a ultima vaga
    slot = SlotDisponibilidade.objects.select_for_update().get(pk=slot.pk)
    if slot.vagas_disponiveis < 1:
        raise ErroNegocio("Lotacao atingida para este horario.", 409)
    if Sessao.objects.filter(aluno=aluno, slot=slot, data_hora=data_hora).exclude(
            estado=Sessao.EstadoSessao.CANCELADA).exists():
        raise ErroNegocio("Ja tem uma sessao marcada para este horario.", 409)

    valor = pt.preco_hora * Decimal(quantidade_sessoes)
    sessao = Sessao.objects.create(
        aluno=aluno, personal_trainer=pt, slot=slot, data_hora=data_hora, modalidade=modalidade,
        quantidade_sessoes=quantidade_sessoes, valor_total=valor,
    )
    comissao, liquido = calcular_comissao(valor)
    pagamento = Pagamento.objects.create(
        sessao=sessao, valor=valor, comissao_plataforma=comissao, valor_liquido_pt=liquido,
    )
    SlotDisponibilidade.objects.filter(pk=slot.pk).update(vagas_ocupadas=F("vagas_ocupadas") + 1)
    notificacoes.sessao_contratada(sessao)
    return sessao, pagamento


def _liberar_vaga(slot):
    if slot is not None:
        SlotDisponibilidade.objects.filter(pk=slot.pk, vagas_ocupadas__gt=0).update(
            vagas_ocupadas=F("vagas_ocupadas") - 1)


def _e_aluno(sessao, user):
    return sessao.aluno.utilizador_id == user.id


def _e_pt(sessao, user):
    return sessao.personal_trainer.utilizador_id == user.id


@transaction.atomic
def cancelar_sessao(sessao, user):
    """UC-08. Devolve True se o pagamento foi reembolsado.
    Cancelamento pelo PT: reembolso total. Pelo aluno: reembolso total se feito com pelo menos
    `janela_cancelamento_horas` de antecedencia; caso contrario nao ha reembolso."""
    if not (_e_aluno(sessao, user) or _e_pt(sessao, user)):
        raise ErroNegocio("Sem permissao para esta sessao.", 403)
    if not sessao.pode_transitar(Sessao.EstadoSessao.CANCELADA):
        raise ErroNegocio(f"Uma sessao '{sessao.get_estado_display()}' ja nao pode ser cancelada.", 409)

    agora = timezone.now()
    janela = timedelta(hours=sessao.personal_trainer.janela_cancelamento_horas)
    reembolsar = _e_pt(sessao, user) or sessao.data_hora - agora >= janela

    sessao.cancelada_por = user
    sessao.data_cancelamento = agora
    sessao.transitar(Sessao.EstadoSessao.CANCELADA)
    sessao.save(update_fields=["cancelada_por", "data_cancelamento"])
    _liberar_vaga(sessao.slot)

    reembolsado = False
    for pagamento in sessao.pagamentos.select_for_update():
        if pagamento.estado == Pagamento.EstadoPagamento.PENDENTE:
            pagamento.transitar(Pagamento.EstadoPagamento.RECUSADO)  # nunca chegou a ser pago
        elif pagamento.estado == Pagamento.EstadoPagamento.APROVADO and reembolsar:
            try:
                obter_gateway().reembolsar(pagamento)
            except GatewayErro:
                raise ErroNegocio("Falha ao solicitar o reembolso ao Multicaixa; tente novamente.", 502)
            pagamento.transitar(Pagamento.EstadoPagamento.REEMBOLSADO)
            reembolsado = True
        # aprovado sem direito a reembolso: fica retido ate decisao do admin (regra a confirmar)
    notificacoes.sessao_cancelada(sessao, user, reembolsado)
    return reembolsado


@transaction.atomic
def reagendar_sessao(sessao, user, slot, data_hora):
    """UC-08: muda a sessao para outro slot do mesmo PT, respeitando a janela do profissional."""
    if not _e_aluno(sessao, user):
        raise ErroNegocio("Apenas o aluno pode reagendar.", 403)
    if sessao.estado not in (Sessao.EstadoSessao.AGENDADA, Sessao.EstadoSessao.CONFIRMADA):
        raise ErroNegocio("Esta sessao ja nao pode ser reagendada.", 409)
    janela = timedelta(hours=sessao.personal_trainer.janela_cancelamento_horas)
    if sessao.data_hora - timezone.now() < janela:
        raise ErroNegocio(
            f"So e possivel reagendar com {sessao.personal_trainer.janela_cancelamento_horas}h de antecedencia.", 409)
    if slot.personal_trainer_id != sessao.personal_trainer_id:
        raise ErroNegocio("O slot nao pertence ao Personal Trainer da sessao.")
    _validar_slot_e_data(slot, data_hora)

    antigo = sessao.slot
    slot = SlotDisponibilidade.objects.select_for_update().get(pk=slot.pk)
    if antigo is None or slot.pk != antigo.pk:
        if slot.vagas_disponiveis < 1:
            raise ErroNegocio("Lotacao atingida para este horario.", 409)
        SlotDisponibilidade.objects.filter(pk=slot.pk).update(vagas_ocupadas=F("vagas_ocupadas") + 1)
        _liberar_vaga(antigo)
    sessao.slot = slot
    sessao.data_hora = data_hora
    sessao.lembrete_enviado = False
    sessao.save(update_fields=["slot", "data_hora", "lembrete_enviado"])
    notificacoes.sessao_reagendada(sessao)


ACOES_PT = {
    "confirmar": Sessao.EstadoSessao.CONFIRMADA,
    "iniciar": Sessao.EstadoSessao.EM_CURSO,
    "concluir": Sessao.EstadoSessao.REALIZADA,
}


@transaction.atomic
def avancar_sessao(sessao, user, acao):
    """O PT faz a sessao avancar: confirmar -> iniciar -> concluir."""
    if not _e_pt(sessao, user):
        raise ErroNegocio("Apenas o Personal Trainer da sessao pode fazer esta acao.", 403)
    destino = ACOES_PT[acao]
    if not sessao.pode_transitar(destino):
        raise ErroNegocio(f"Nao e possivel '{acao}' uma sessao '{sessao.get_estado_display()}'.", 409)
    if destino == Sessao.EstadoSessao.CONFIRMADA and not sessao.pagamentos.filter(
            estado=Pagamento.EstadoPagamento.APROVADO).exists():
        raise ErroNegocio("A sessao so pode ser confirmada depois do pagamento aprovado.", 409)
    sessao.transitar(destino)
    if destino == Sessao.EstadoSessao.CONFIRMADA:
        notificacoes.sessao_confirmada(sessao)
    if destino == Sessao.EstadoSessao.REALIZADA:
        sessao.data_realizacao = timezone.now()
        sessao.save(update_fields=["data_realizacao"])
        _liberar_vaga(sessao.slot)
        notificacoes.sessao_realizada(sessao)


@transaction.atomic
def reclamar_sessao(sessao, user, motivo):
    """BR-03: o aluno contesta uma sessao realizada; o pagamento deixa de ser libertado automaticamente."""
    if not _e_aluno(sessao, user):
        raise ErroNegocio("Apenas o aluno pode reclamar.", 403)
    if sessao.estado not in Sessao.ESTADOS_REALIZADOS:
        raise ErroNegocio("So se pode reclamar de uma sessao realizada.", 409)
    if sessao.pagamentos.filter(estado=Pagamento.EstadoPagamento.LIBERTADO).exists():
        raise ErroNegocio("O pagamento ja foi libertado ao profissional.", 409)
    if not motivo.strip():
        raise ErroNegocio("Indique o motivo da reclamacao.")
    sessao.reclamacao = motivo.strip()
    sessao.save(update_fields=["reclamacao"])
