from decimal import Decimal

from decouple import config
from django.db import transaction
from django.utils import timezone
from django.db.models import Avg, Count

from ..models import Avaliacao, PersonalTrainer, Sessao
from . import notificacoes
from .sessoes import ErroNegocio


def recalcular_reputacao(pt):
    """Atualiza classificacao_media e total_avaliacoes do PT com as avaliacoes que recebeu."""
    agregado = Avaliacao.objects.filter(
        avaliado=pt.utilizador, sessao__estado__in=Sessao.ESTADOS_REALIZADOS
    ).aggregate(media=Avg("classificacao"), total=Count("id"))
    pt.classificacao_media = round(agregado["media"], 2) if agregado["media"] is not None else None
    pt.total_avaliacoes = agregado["total"]
    pt.save(update_fields=["classificacao_media", "total_avaliacoes"])


@transaction.atomic
def avaliar_sessao(sessao, autor, classificacao, comentario=""):
    """UC-09: avaliacao mutua. BR-05: so sessoes realizadas na plataforma podem ser avaliadas."""
    aluno_u, pt_u = sessao.aluno.utilizador, sessao.personal_trainer.utilizador
    if autor.id not in (aluno_u.id, pt_u.id):
        raise ErroNegocio("Sem permissao para esta sessao.", 403)
    if sessao.estado not in Sessao.ESTADOS_REALIZADOS:
        raise ErroNegocio("So se podem avaliar sessoes realizadas.", 409)
    avaliado = pt_u if autor.id == aluno_u.id else aluno_u
    if Avaliacao.objects.filter(sessao=sessao, autor=autor).exists():
        raise ErroNegocio("Ja avaliou esta sessao.", 409)

    avaliacao = Avaliacao.objects.create(
        sessao=sessao, autor=autor, avaliado=avaliado, classificacao=classificacao, comentario=comentario)

    if autor.id == aluno_u.id and sessao.estado == Sessao.EstadoSessao.REALIZADA:
        sessao.transitar(Sessao.EstadoSessao.AVALIADA)
    if avaliado.id == pt_u.id:
        pt = PersonalTrainer.objects.select_for_update().get(pk=sessao.personal_trainer_id)
        recalcular_reputacao(pt)
        avaliar_qualidade(pt)
    notificacoes.nova_avaliacao(avaliacao)
    return avaliacao


# --- BR-02: qualidade do PT (Verificado -> Em Alerta -> Suspenso) ---
def limiar_alerta():
    return Decimal(config("QUALITY_ALERT_THRESHOLD", default="4.0"))


def limiar_suspensao():
    return Decimal(config("QUALITY_SUSPEND_THRESHOLD", default="3.0"))


def minimo_avaliacoes():
    return int(config("QUALITY_MIN_REVIEWS", default="5"))


@transaction.atomic
def avaliar_qualidade(pt):
    """Aplica a BR-02 ao PT. So atua com `minimo_avaliacoes()` avaliacoes (desde a ultima reativacao).
    - media < limiar de suspensao  -> Suspenso (so o admin reativa)
    - media < limiar de alerta     -> Em Alerta
    - Em Alerta com media >= alerta -> volta a Verificado
    Devolve o novo estado se mudou, ou None."""
    E = PersonalTrainer.EstadoVerificacao
    if pt.estado_verificacao not in PersonalTrainer.ESTADOS_ATIVOS:
        return None  # pendente ou suspenso: nao ha transicao automatica
    avaliacoes = Avaliacao.objects.filter(avaliado=pt.utilizador, sessao__estado__in=Sessao.ESTADOS_REALIZADOS)
    if pt.avaliacoes_desde:
        avaliacoes = avaliacoes.filter(data_criacao__gte=pt.avaliacoes_desde)
    agregado = avaliacoes.aggregate(media=Avg("classificacao"), total=Count("id"))
    if agregado["total"] < minimo_avaliacoes():
        return None
    media = Decimal(str(agregado["media"]))

    if media < limiar_suspensao():
        novo = E.SUSPENSO
    elif media < limiar_alerta():
        novo = E.EM_ALERTA
    else:
        novo = E.VERIFICADO
    if novo == pt.estado_verificacao:
        return None
    pt.estado_verificacao = novo
    pt.save(update_fields=["estado_verificacao"])
    notificacoes.estado_qualidade_alterado(pt, media)
    return novo


@transaction.atomic
def reativar_trainer(pt):
    """Admin: levanta a suspensao. O historico anterior deixa de contar para a BR-02."""
    if pt.estado_verificacao != PersonalTrainer.EstadoVerificacao.SUSPENSO:
        raise ErroNegocio("O Personal Trainer nao esta suspenso.", 409)
    pt.estado_verificacao = PersonalTrainer.EstadoVerificacao.VERIFICADO
    pt.avaliacoes_desde = timezone.now()
    pt.save(update_fields=["estado_verificacao", "avaliacoes_desde"])
    notificacoes.estado_qualidade_alterado(pt, None)
