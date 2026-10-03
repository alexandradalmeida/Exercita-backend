from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from ..models import Pagamento, PersonalTrainer, Sessao, SlotDisponibilidade
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
    return sessao, pagamento
