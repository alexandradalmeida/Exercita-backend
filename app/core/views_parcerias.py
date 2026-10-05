from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ParceriaPT, RemuneracaoParceria
from .serializers import ParceriaSerializer, RemuneracaoParceriaSerializer
from .services import parcerias
from .services.sessoes import ErroNegocio


def _erro(erro):
    return Response({"mensagem": erro.mensagem}, status=erro.codigo)


class MinhaParceriaView(APIView):
    """GET /api/v1/partnerships/me/ - a minha candidatura/parceria e as remuneracoes.
    POST /api/v1/partnerships/apply/ {"mensagem"} - candidatura de PT a parceiro (UC-13)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        pt = getattr(request.user, "perfil_personal_trainer", None)
        parceria = getattr(pt, "parceria", None) if pt else None
        if parceria is None:
            return Response({"mensagem": "Sem candidatura."}, status=status.HTTP_404_NOT_FOUND)
        dados = ParceriaSerializer(parceria).data
        dados["remuneracoes"] = RemuneracaoParceriaSerializer(parceria.remuneracoes.all(), many=True).data
        return Response(dados)

    def post(self, request):
        pt = getattr(request.user, "perfil_personal_trainer", None)
        if pt is None:
            return Response({"mensagem": "Apenas Personal Trainers."}, status=status.HTTP_403_FORBIDDEN)
        try:
            parceria = parcerias.candidatar(pt, str(request.data.get("mensagem", "")))
        except ErroNegocio as erro:
            return _erro(erro)
        return Response(ParceriaSerializer(parceria).data, status=status.HTTP_201_CREATED)


class ParceriasAdminListView(generics.ListAPIView):
    """GET /api/v1/partnerships/?estado= - candidaturas e parcerias (admin)."""
    permission_classes = [IsAdminUser]
    serializer_class = ParceriaSerializer

    def get_queryset(self):
        qs = ParceriaPT.objects.select_related("personal_trainer__utilizador").order_by("-data_candidatura")
        if estado := self.request.query_params.get("estado"):
            qs = qs.filter(estado=estado)
        return qs


class ParceriaAcaoView(APIView):
    """POST /api/v1/partnerships/{id}/{aprovar|recusar|terminar}/ (admin). Aprovar exige `remuneracao_mensal`."""
    permission_classes = [IsAdminUser]

    def post(self, request, pk, acao):
        if acao not in ("aprovar", "recusar", "terminar"):
            return Response(status=status.HTTP_404_NOT_FOUND)
        parceria = get_object_or_404(ParceriaPT, pk=pk)
        try:
            if acao == "aprovar":
                try:
                    valor = Decimal(str(request.data.get("remuneracao_mensal")))
                except InvalidOperation:
                    return Response({"remuneracao_mensal": "Indique a remuneracao mensal."},
                                    status=status.HTTP_400_BAD_REQUEST)
                parcerias.aprovar(parceria, valor)
            elif acao == "recusar":
                parcerias.recusar(parceria)
            else:
                parcerias.terminar(parceria)
        except ErroNegocio as erro:
            return _erro(erro)
        parceria.refresh_from_db()
        return Response(ParceriaSerializer(parceria).data)


class RemuneracaoPagaView(APIView):
    """POST /api/v1/partnerships/payouts/{id}/pay/ - o admin regista que a remuneracao foi paga."""
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        remuneracao = get_object_or_404(RemuneracaoParceria, pk=pk)
        try:
            parcerias.marcar_paga(remuneracao)
        except ErroNegocio as erro:
            return _erro(erro)
        return Response(RemuneracaoParceriaSerializer(remuneracao).data)
