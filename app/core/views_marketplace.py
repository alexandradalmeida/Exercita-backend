from rest_framework import viewsets

from .models import Certificacao, SlotDisponibilidade
from .permissions import IsPersonalTrainerVerificado
from .serializers import CertificacaoSerializer, SlotDisponibilidadeSerializer


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