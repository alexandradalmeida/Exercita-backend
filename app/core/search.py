from django.db.models import Avg, Count, F, FloatField, IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce

from pgvector.django import CosineDistance

from .models import Avaliacao, PersonalTrainer, Sessao, SlotDisponibilidade
from .services.embeddings import obter_gerador


def pesquisar_trainers(params, gerador=None):
    """Pesquisa de PTs verificados com filtros (UC-05). `params` e um QueryDict/dict.
    Com `q`, ordena por relevancia (matching por embeddings, distancia do cosseno).
    Os agregados usam subqueries para nao multiplicar linhas entre relacoes diferentes."""
    avaliacoes = (
        Avaliacao.objects.filter(sessao__personal_trainer=OuterRef("pk"), sessao__estado__in=Sessao.ESTADOS_REALIZADOS)
        .values("sessao__personal_trainer")
    )
    slots = SlotDisponibilidade.objects.filter(personal_trainer=OuterRef("pk")).values("personal_trainer")

    qs = PersonalTrainer.objects.filter(
        estado_verificacao=PersonalTrainer.EstadoVerificacao.VERIFICADO
    ).select_related("utilizador").annotate(
        avaliacao_media=Subquery(avaliacoes.annotate(m=Avg("classificacao")).values("m"), output_field=FloatField()),
        total_avaliacoes=Coalesce(
            Subquery(avaliacoes.annotate(c=Count("id")).values("c"), output_field=IntegerField()), 0),
        total_slots=Coalesce(
            Subquery(slots.annotate(c=Count("id")).values("c"), output_field=IntegerField()), 0),
        capacidade_total=Coalesce(
            Subquery(slots.annotate(s=Sum("capacidade")).values("s"), output_field=IntegerField()), 0),
        ocupadas_total=Coalesce(
            Subquery(slots.annotate(s=Sum("vagas_ocupadas")).values("s"), output_field=IntegerField()), 0),
    )

    if especialidade := params.get("especialidade"):
        qs = qs.filter(especialidade__icontains=especialidade)
    if localizacao := params.get("localizacao"):
        qs = qs.filter(localizacao__icontains=localizacao)
    if modalidade := params.get("modalidade_pagamento"):
        qs = qs.filter(modalidades_pagamento__contains=[modalidade])
    if (minima := params.get("avaliacao_minima")) not in (None, ""):
        qs = qs.filter(avaliacao_media__gte=float(minima))

    # disponibilidade: slots com vagas livres, opcionalmente num dia da semana
    dia = params.get("dia_semana")
    if dia not in (None, "") or params.get("com_vagas") in ("1", "true", "True"):
        livres = SlotDisponibilidade.objects.filter(vagas_ocupadas__lt=F("capacidade"))
        if dia not in (None, ""):
            livres = livres.filter(dia_semana=int(dia))
        qs = qs.filter(pk__in=livres.values("personal_trainer"))

    if consulta := (params.get("q") or "").strip():
        vetor = (gerador or obter_gerador()).gerar(consulta)
        # PTs sem embedding ficam no fim (nulls_last); desempate por avaliacao
        return qs.annotate(distancia=CosineDistance("embedding", vetor)).order_by(
            F("distancia").asc(nulls_last=True), "-avaliacao_media", "id"
        )

    return qs.order_by("-avaliacao_media", "id")