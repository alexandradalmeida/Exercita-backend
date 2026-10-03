from django.db import transaction
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
    notificacoes.nova_avaliacao(avaliacao)
    return avaliacao
