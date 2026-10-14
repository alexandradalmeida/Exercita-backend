from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from ..models import Nutricionista, PersonalTrainer, Utilizador
from . import notificacoes
from .sessoes import ErroNegocio


def _protegido(alvo, admin):
    if alvo.pk == admin.pk:
        raise ErroNegocio("Nao pode alterar a sua propria conta.", 409)
    if alvo.is_superuser:
        raise ErroNegocio("Contas de superutilizador nao podem ser alteradas por aqui.", 403)


def revogar_sessoes(utilizador):
    """Poe na lista negra todos os refresh tokens do utilizador."""
    for token in OutstandingToken.objects.filter(user=utilizador):
        BlacklistedToken.objects.get_or_create(token=token)


@transaction.atomic
def suspender(alvo, admin, motivo):
    _protegido(alvo, admin)
    if alvo.suspenso:
        raise ErroNegocio("O utilizador ja esta suspenso.", 409)
    if not motivo.strip():
        raise ErroNegocio("Indique o motivo da suspensao.")
    alvo.suspenso, alvo.motivo_suspensao, alvo.data_suspensao = True, motivo.strip(), timezone.now()
    alvo.save(update_fields=["suspenso", "motivo_suspensao", "data_suspensao"])
    revogar_sessoes(alvo)
    notificacoes.notificar(alvo, f"A sua conta foi suspensa: {alvo.motivo_suspensao}", "Conta suspensa")


@transaction.atomic
def reativar_conta(alvo, admin):
    _protegido(alvo, admin)
    if not alvo.suspenso:
        raise ErroNegocio("O utilizador nao esta suspenso.", 409)
    alvo.suspenso, alvo.motivo_suspensao, alvo.data_suspensao = False, "", None
    alvo.save(update_fields=["suspenso", "motivo_suspensao", "data_suspensao"])
    notificacoes.notificar(alvo, "A sua conta foi reativada.", "Conta reativada")


@transaction.atomic
def definir_permissoes(alvo, admin, is_staff):
    """Concede ou retira acesso de administrador. Reservado a superutilizadores."""
    if not admin.is_superuser:
        raise ErroNegocio("Apenas um superutilizador pode alterar permissoes de administracao.", 403)
    _protegido(alvo, admin)
    alvo.is_staff = is_staff
    alvo.save(update_fields=["is_staff"])


@transaction.atomic
def verificar_perfil(alvo, admin):
    """Verifica o perfil profissional do utilizador (PT ou nutricionista)."""
    _protegido(alvo, admin)
    if alvo.tipo == Utilizador.TipoUtilizador.PERSONAL_TRAINER:
        pt = alvo.perfil_personal_trainer
        if pt.estado_verificacao == PersonalTrainer.EstadoVerificacao.SUSPENSO:
            raise ErroNegocio("Personal Trainer suspenso por qualidade: use a reativacao.", 409)
        pt.estado_verificacao = PersonalTrainer.EstadoVerificacao.VERIFICADO
        pt.save(update_fields=["estado_verificacao"])
    elif alvo.tipo == Utilizador.TipoUtilizador.NUTRICIONISTA:
        nutri = alvo.perfil_nutricionista
        nutri.estado_verificacao = Nutricionista.EstadoVerificacao.VERIFICADO
        nutri.save(update_fields=["estado_verificacao"])
    else:
        raise ErroNegocio("Este tipo de utilizador nao tem perfil a verificar.")
