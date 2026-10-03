from django.shortcuts import get_object_or_404
from rest_framework import generics, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import Certificacao, PersonalTrainer, SlotDisponibilidade
from .permissions import IsPersonalTrainerVerificado
from .search import pesquisar_trainers
from .serializers import (
    CertificacaoSerializer,
    PersonalTrainerSerializer,
    SlotDisponibilidadeSerializer,
    TrainerListaSerializer,
    TrainerPerfilPublicoSerializer,
)


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

class TrainerPerfilView(generics.RetrieveUpdateAPIView):
    """GET /api/v1/trainers/{id}/profile/ - perfil publico (UC-06).
    PUT/PATCH - o proprio PT atualiza o perfil (UC-04)."""
    http_method_names = ["get", "put", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.request.method == "GET":
            return TrainerPerfilPublicoSerializer
        return PersonalTrainerSerializer

    def get_object(self):
        if self.request.method == "GET":
            return get_object_or_404(
                pesquisar_trainers({}), pk=self.kwargs["pk"]
            )
        pt = get_object_or_404(PersonalTrainer, pk=self.kwargs["pk"])
        if pt.utilizador_id != self.request.user.id:
            raise PermissionDenied("So pode editar o seu proprio perfil.")
        return pt


class TrainerDisponibilidadeView(generics.ListAPIView):
    """GET /api/v1/trainers/{id}/availability/ - slots com vagas livres/ocupadas."""
    serializer_class = SlotDisponibilidadeSerializer
    pagination_class = None

    def get_queryset(self):
        pt = get_object_or_404(
            PersonalTrainer, pk=self.kwargs["pk"],
            estado_verificacao=PersonalTrainer.EstadoVerificacao.VERIFICADO,
        )
        return pt.slots_disponibilidade.order_by("dia_semana", "hora_inicio")
