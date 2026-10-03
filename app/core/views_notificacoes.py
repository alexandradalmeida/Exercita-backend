from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notificacao
from .serializers import NotificacaoSerializer


class NotificacaoListView(generics.ListAPIView):
    """GET /api/v1/notifications/?lida=false - notificacoes do utilizador, mais recentes primeiro."""
    serializer_class = NotificacaoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Notificacao.objects.filter(utilizador=self.request.user).order_by("-data_criacao", "-id")
        lida = self.request.query_params.get("lida")
        if lida in ("true", "false"):
            qs = qs.filter(lida=(lida == "true"))
        return qs


class NotificacaoDetalheView(generics.UpdateAPIView):
    """PATCH /api/v1/notifications/{id}/ {"lida": true}"""
    serializer_class = NotificacaoSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["patch", "options"]

    def get_queryset(self):
        return Notificacao.objects.filter(utilizador=self.request.user)


class NotificacoesMarcarLidasView(APIView):
    """POST /api/v1/notifications/read-all/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        n = Notificacao.objects.filter(utilizador=request.user, lida=False).update(lida=True)
        return Response({"marcadas": n}, status=status.HTTP_200_OK)
