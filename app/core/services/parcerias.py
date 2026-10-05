from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..models import ParceriaPT, PersonalTrainer, RemuneracaoParceria
from . import notificacoes
from .sessoes import ErroNegocio

E = ParceriaPT.Estado


def candidatar(pt, mensagem=""):
    if pt.estado_verificacao not in PersonalTrainer.ESTADOS_ATIVOS:
        raise ErroNegocio("Apenas Personal Trainers ativos podem candidatar-se a parceiros.", 403)
    parceria, criada = ParceriaPT.objects.get_or_create(personal_trainer=pt, defaults={"mensagem": mensagem})
    if criada:
        return parceria
    if parceria.estado in (E.PENDENTE, E.ATIVA):
        raise ErroNegocio("Ja tem uma candidatura ou parceria em curso.", 409)
    # candidatura anterior recusada ou terminada: reabre
    parceria.estado, parceria.mensagem = E.PENDENTE, mensagem
    parceria.remuneracao_mensal = parceria.data_inicio = parceria.data_fim = None
    parceria.save()
    return parceria


@transaction.atomic
def aprovar(parceria, remuneracao_mensal):
    if parceria.estado != E.PENDENTE:
        raise ErroNegocio("So se aprovam candidaturas pendentes.", 409)
    if Decimal(remuneracao_mensal) <= 0:
        raise ErroNegocio("A remuneracao mensal tem de ser positiva.")
    parceria.estado, parceria.remuneracao_mensal = E.ATIVA, remuneracao_mensal
    parceria.data_inicio = timezone.localdate()
    parceria.save(update_fields=["estado", "remuneracao_mensal", "data_inicio"])
    notificacoes.parceria_atualizada(parceria, f"aprovada, com remuneracao mensal de {remuneracao_mensal} Kz")


@transaction.atomic
def recusar(parceria):
    if parceria.estado != E.PENDENTE:
        raise ErroNegocio("So se recusam candidaturas pendentes.", 409)
    parceria.estado = E.RECUSADA
    parceria.save(update_fields=["estado"])
    notificacoes.parceria_atualizada(parceria, "recusada")


@transaction.atomic
def terminar(parceria):
    if parceria.estado != E.ATIVA:
        raise ErroNegocio("So se termina uma parceria ativa.", 409)
    parceria.estado, parceria.data_fim = E.TERMINADA, timezone.localdate()
    parceria.save(update_fields=["estado", "data_fim"])
    notificacoes.parceria_atualizada(parceria, "terminada")


def gerar_remuneracoes(mes=None):
    """Regista a remuneracao do mes para cada parceria ativa. Idempotente. Devolve quantas criou.
    Pensado para correr no inicio de cada mes (`manage.py gerar_remuneracoes`)."""
    hoje = timezone.localdate()
    mes = (mes or hoje).replace(day=1)
    criadas = 0
    proximo_mes = date(mes.year + (mes.month == 12), mes.month % 12 + 1, 1)
    for parceria in ParceriaPT.objects.filter(estado=E.ATIVA, data_inicio__lt=proximo_mes):
        _, nova = RemuneracaoParceria.objects.get_or_create(
            parceria=parceria, mes=mes, defaults={"valor": parceria.remuneracao_mensal})
        criadas += nova
    return criadas


def marcar_paga(remuneracao):
    if remuneracao.estado == RemuneracaoParceria.Estado.PAGA:
        raise ErroNegocio("Esta remuneracao ja esta paga.", 409)
    remuneracao.estado, remuneracao.data_pagamento = RemuneracaoParceria.Estado.PAGA, timezone.now()
    remuneracao.save(update_fields=["estado", "data_pagamento"])
    notificacoes.remuneracao_paga(remuneracao)
