from datetime import time

from django.utils import timezone

from ..models import Ginasio, ReservaGinasio
from . import notificacoes
from .sessoes import ErroNegocio


def dentro_do_horario(ginasio, data_hora):
    """Sem horarios definidos o ginasio aceita qualquer hora; com horarios, a hora tem de cair num intervalo."""
    if not ginasio.horarios:
        return True
    local = timezone.localtime(data_hora)
    hora = local.time().replace(second=0, microsecond=0)
    for abre, fecha in ginasio.horarios.get(str(local.weekday()), []):
        if time.fromisoformat(abre) <= hora < time.fromisoformat(fecha):
            return True
    return False


def reservar(aluno, ginasio, tipo, data_hora, personal_trainer=None, notas=""):
    if ginasio.estado_parceria != Ginasio.EstadoParceria.PARCEIRO:
        raise ErroNegocio("O ginasio nao aceita reservas.", 404)
    if data_hora <= timezone.now():
        raise ErroNegocio("data_hora tem de estar no futuro.")
    if not dentro_do_horario(ginasio, data_hora):
        raise ErroNegocio("O ginasio esta fechado a essa hora.")
    if personal_trainer is not None and not ginasio.personal_trainers.filter(pk=personal_trainer.pk).exists():
        raise ErroNegocio("O Personal Trainer nao trabalha neste ginasio.")
    ativas = ReservaGinasio.objects.filter(aluno=aluno, ginasio=ginasio, estado=ReservaGinasio.Estado.CONFIRMADA)
    if ativas.filter(data_hora=data_hora).exists():
        raise ErroNegocio("Ja tem uma reserva neste ginasio a essa hora.", 409)
    if tipo == ReservaGinasio.Tipo.AULA_EXPERIMENTAL and ativas.filter(
            tipo=ReservaGinasio.Tipo.AULA_EXPERIMENTAL, data_hora__gt=timezone.now()).exists():
        raise ErroNegocio("Ja tem uma aula experimental marcada neste ginasio.", 409)

    reserva = ReservaGinasio.objects.create(
        aluno=aluno, ginasio=ginasio, personal_trainer=personal_trainer, tipo=tipo, data_hora=data_hora, notas=notas)
    notificacoes.reserva_ginasio(reserva, "confirmada")
    return reserva


def cancelar_reserva(reserva):
    if reserva.estado != ReservaGinasio.Estado.CONFIRMADA:
        raise ErroNegocio("A reserva ja esta cancelada.", 409)
    if reserva.data_hora <= timezone.now():
        raise ErroNegocio("Nao e possivel cancelar uma reserva que ja passou.", 409)
    reserva.estado = ReservaGinasio.Estado.CANCELADA
    reserva.save(update_fields=["estado"])
    notificacoes.reserva_ginasio(reserva, "cancelada")
