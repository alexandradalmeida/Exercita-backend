from datetime import date

from django.db.models import Sum
from django.utils import timezone
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Nutricionista, PlanoNutricional, RegistoRefeicao
from .permissions import IsAluno, IsNutricionistaVerificado
from .serializers import NutricionistaSerializer, PlanoNutricionalSerializer, RegistoRefeicaoSerializer


class MeuPerfilNutricionistaView(generics.RetrieveUpdateAPIView):
    serializer_class = NutricionistaSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        from django.http import Http404
        perfil = getattr(self.request.user, "perfil_nutricionista", None)
        if perfil is None:
            raise Http404
        return perfil


class VerificarNutricionistaView(APIView):
    """POST /api/v1/nutricionistas/{id}/verificar/ - o admin verifica o nutricionista (como a BR-01 nos PTs)."""
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            nutricionista = Nutricionista.objects.get(pk=pk)
        except Nutricionista.DoesNotExist:
            return Response({"mensagem": "Nutricionista nao encontrado."}, status=status.HTTP_404_NOT_FOUND)
        nutricionista.estado_verificacao = Nutricionista.EstadoVerificacao.VERIFICADO
        nutricionista.save(update_fields=["estado_verificacao"])
        return Response({"mensagem": "Nutricionista verificado com sucesso.", "id": nutricionista.id,
                         "estado_verificacao": nutricionista.estado_verificacao})


class PlanoNutricionalViewSet(viewsets.ModelViewSet):
    """/api/v1/nutrition/plans/ - o nutricionista verificado gere os planos que criou;
    o aluno consulta (so leitura) os planos que lhe foram atribuidos."""
    serializer_class = PlanoNutricionalSerializer

    def _nutricionista(self):
        return getattr(self.request.user, "perfil_nutricionista", None)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsNutricionistaVerificado()]

    def get_queryset(self):
        qs = PlanoNutricional.objects.prefetch_related("refeicoes").order_by("-data_criacao", "-id")
        nutri = self._nutricionista()
        if nutri is not None:
            return qs.filter(nutricionista=nutri)
        if hasattr(self.request.user, "perfil_aluno"):
            return qs.filter(aluno=self.request.user.perfil_aluno)
        return qs.none()

    def perform_create(self, serializer):
        serializer.save(nutricionista=self._nutricionista())


class RegistoRefeicaoViewSet(viewsets.ModelViewSet):
    """/api/v1/nutrition/logs/ - registo diario de refeicoes do aluno. Filtros: ?data=, ?de=, ?ate= (AAAA-MM-DD)."""
    serializer_class = RegistoRefeicaoSerializer
    permission_classes = [IsAluno]

    def get_queryset(self):
        qs = RegistoRefeicao.objects.filter(aluno=self.request.user.perfil_aluno).order_by("-data", "-id")
        params = self.request.query_params
        try:
            if data := params.get("data"):
                qs = qs.filter(data=date.fromisoformat(data))
            if de := params.get("de"):
                qs = qs.filter(data__gte=date.fromisoformat(de))
            if ate := params.get("ate"):
                qs = qs.filter(data__lte=date.fromisoformat(ate))
        except ValueError:
            raise ValidationError("Datas no formato AAAA-MM-DD.")
        return qs

    def perform_create(self, serializer):
        serializer.save(aluno=self.request.user.perfil_aluno)

    @action(detail=False, methods=["get"])
    def resumo(self, request):
        """GET .../logs/resumo/?data= - total de calorias do dia face ao objetivo do plano ativo."""
        dia = request.query_params.get("data")
        try:
            dia = date.fromisoformat(dia) if dia else timezone.localdate()
        except ValueError:
            raise ValidationError("Data no formato AAAA-MM-DD.")
        aluno = request.user.perfil_aluno
        total = RegistoRefeicao.objects.filter(aluno=aluno, data=dia).aggregate(t=Sum("calorias"))["t"] or 0
        plano = aluno.planos_nutricionais.filter(ativo=True).order_by("-data_criacao").first()
        objetivo = plano.calorias_diarias if plano else None
        return Response({"data": dia, "total_calorias": total, "objetivo_calorias": objetivo,
                         "restante": None if objetivo is None else objetivo - total})
