from rest_framework import generics, status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Nutricionista
from .serializers import NutricionistaSerializer


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
