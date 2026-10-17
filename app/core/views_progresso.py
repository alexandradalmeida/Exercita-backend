from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import HistoricoTreino, MetricaFisica
from .permissions import TemConsentimentoSaude
from .serializers_progresso import (
    HistoricoTreinoSerializer, MetricaFisicaSerializer, WearableIngestaoSerializer,
)


def _filtrar_por_datas(qs, params):
    try:
        if de := params.get("de"):
            qs = qs.filter(data__gte=date.fromisoformat(de))
        if ate := params.get("ate"):
            qs = qs.filter(data__lte=date.fromisoformat(ate))
    except ValueError:
        raise ValidationError("Datas no formato AAAA-MM-DD.")
    return qs


class MetricaFisicaViewSet(viewsets.ModelViewSet):
    """/api/v1/progress/metrics/ - medicoes corporais do aluno (UC-14). Filtros: ?de= ?ate="""
    serializer_class = MetricaFisicaSerializer
    permission_classes = [TemConsentimentoSaude]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MetricaFisica.objects.none()
        qs = MetricaFisica.objects.filter(aluno=self.request.user.perfil_aluno)
        return _filtrar_por_datas(qs, self.request.query_params)

    def perform_create(self, serializer):
        serializer.save(aluno=self.request.user.perfil_aluno, fonte=MetricaFisica.Fonte.MANUAL)


class HistoricoTreinoViewSet(viewsets.ModelViewSet):
    """/api/v1/progress/workouts/ - historico de treinos do aluno. Filtros: ?de= ?ate= ?tipo="""
    serializer_class = HistoricoTreinoSerializer
    permission_classes = [TemConsentimentoSaude]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return HistoricoTreino.objects.none()
        qs = HistoricoTreino.objects.filter(aluno=self.request.user.perfil_aluno)
        if tipo := self.request.query_params.get("tipo"):
            qs = qs.filter(tipo__iexact=tipo)
        return _filtrar_por_datas(qs, self.request.query_params)

    def perform_create(self, serializer):
        serializer.save(aluno=self.request.user.perfil_aluno, fonte=MetricaFisica.Fonte.MANUAL)


class ResumoProgressoView(APIView):
    """GET /api/v1/progress/summary/ - ultima medicao, variacao de peso desde a primeira e treinos dos ultimos 30 dias."""
    permission_classes = [TemConsentimentoSaude]

    def get(self, request):
        aluno = request.user.perfil_aluno
        metricas = MetricaFisica.objects.filter(aluno=aluno)
        ultima = metricas.first()
        com_peso = metricas.exclude(peso_kg=None)
        peso_atual, peso_inicial = com_peso.first(), com_peso.last()
        desde = timezone.localdate() - timedelta(days=30)
        treinos = HistoricoTreino.objects.filter(aluno=aluno, data__gte=desde).aggregate(
            total=Count("id"), minutos=Sum("duracao_minutos"), calorias=Sum("calorias_gastas"))
        variacao = None
        if peso_atual and peso_atual != peso_inicial:
            variacao = peso_atual.peso_kg - peso_inicial.peso_kg
        return Response({
            "ultima_medicao": MetricaFisicaSerializer(ultima).data if ultima else None,
            "peso_inicial_kg": peso_inicial.peso_kg if peso_inicial else None,
            "peso_atual_kg": peso_atual.peso_kg if peso_atual else None,
            "variacao_peso_kg": variacao,
            "treinos_ultimos_30_dias": {
                "total": treinos["total"], "minutos": treinos["minutos"] or 0, "calorias": treinos["calorias"] or 0},
        })


class WearableIngestaoView(APIView):
    """POST /api/v1/progress/wearables/ingest/ - estrutura preparada para wearables.

    TODO: ainda nao ha integracao com nenhum fabricante (Apple Health, Google Fit, ...). Este endpoint define o
    contrato de ingestao: a app (ou um conector futuro) envia medicoes/treinos com `origem_externa_id` estavel, e
    repetir o envio nao duplica registos. A autenticacao do dispositivo/fabricante fica por definir."""
    permission_classes = [TemConsentimentoSaude]

    @transaction.atomic
    def post(self, request):
        fonte = MetricaFisica.Fonte.WEARABLE
        aluno = request.user.perfil_aluno
        entrada = WearableIngestaoSerializer(data=request.data, context={"request": request})
        entrada.is_valid(raise_exception=True)
        criados = {"metricas": 0, "treinos": 0}
        ignorados = {"metricas": 0, "treinos": 0}
        for chave, modelo in (("metricas", MetricaFisica), ("treinos", HistoricoTreino)):
            for dados in entrada.validated_data.get(chave, []):
                _, criado = modelo.objects.get_or_create(
                    aluno=aluno, fonte=fonte, origem_externa_id=dados["origem_externa_id"],
                    defaults={k: v for k, v in dados.items() if k != "origem_externa_id"})
                (criados if criado else ignorados)[chave] += 1
        return Response({"criados": criados, "ignorados": ignorados}, status=status.HTTP_201_CREATED)
