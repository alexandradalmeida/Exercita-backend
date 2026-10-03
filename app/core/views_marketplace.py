from rest_framework import generics, viewsets
from rest_framework.exceptions import ValidationError

from .models import Certificacao, SlotDisponibilidade
from .permissions import IsPersonalTrainerVerificado
from .search import pesquisar_trainers
from .serializers import CertificacaoSerializer, SlotDisponibilidadeSerializer, TrainerListaSerializer


class _RecursoDoMeuPTViewSet(viewsets.ModelViewSet):
    """Recursos que pertencem ao PT autenticado. Apenas PTs verificados (BR-01)
    podem gerir o que e publicado no seu perfil."""
    permission_classes = [IsPersonalTrainerVerificado]

    def get_queryset(self):
        return self.queryset.filter(personal_trainer=self.request.user.perfil_personal_trainer)

    def perform_create(self, serializer):
        serializer.save(personal_trainer=self.request.user.perfil_personal_trainer)


class CertificacaoViewSet(_RecursoDoMeuPTViewSet):
    queryset = Certificacao.objects.all().order_by("id")
    serializer_class = CertificacaoSerializer


class SlotDisponibilidadeViewSet(_RecursoDoMeuPTViewSet):
    queryset = SlotDisponibilidade.objects.all().order_by("dia_semana", "hora_inicio")
    serializer_class = SlotDisponibilidadeSerializer

class TrainerListView(generics.ListAPIView):
    """GET /api/v1/trainers/ - pesquisa com filtros: especialidade, localizacao,
    modalidade_pagamento, dia_semana, com_vagas, avaliacao_minima."""
    serializer_class = TrainerListaSerializer

    def get_queryset(self):
        try:
            return pesquisar_trainers(self.request.query_params)
        except ValueError:
            raise ValidationError("avaliacao_minima e dia_semana tem de ser numericos.")
