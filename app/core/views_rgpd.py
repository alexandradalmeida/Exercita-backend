from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import rgpd
from .services.sessoes import ErroNegocio


class ExportarDadosView(APIView):
    """GET /api/v1/users/me/data-export/ - todos os dados pessoais do utilizador (RGPD: acesso e portabilidade),
    como ficheiro JSON para descarregar."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        conteudo = JSONRenderer().render(rgpd.exportar_dados(request.user))
        resposta = HttpResponse(conteudo, content_type="application/json")
        resposta["Content-Disposition"] = 'attachment; filename="os-meus-dados-exercita.json"'
        return resposta


class ApagarContaView(APIView):
    """DELETE /api/v1/users/me/ {"password": "..."} - apaga/anonimiza a conta (RGPD: apagamento).
    Exige a password e que nao haja obrigacoes em aberto (sessoes, encomendas, pagamentos por libertar)."""
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        if not request.user.check_password(str(request.data.get("password", ""))):
            return Response({"mensagem": "Password incorreta."}, status=status.HTTP_403_FORBIDDEN)
        try:
            rgpd.apagar_conta(request.user)
        except ErroNegocio as erro:
            return Response({"mensagem": erro.mensagem}, status=erro.codigo)
        return Response(status=status.HTTP_204_NO_CONTENT)
