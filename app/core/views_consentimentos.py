from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ConsentimentoDados
from .services import consentimentos
from .services.sessoes import ErroNegocio


class ConsentimentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsentimentoDados
        fields = ["id", "tipo", "versao_termos", "data_concessao", "data_revogacao"]
        read_only_fields = fields


class ConceberConsentimentoSerializer(serializers.Serializer):
    versao = serializers.CharField(help_text="Versao dos termos que o utilizador viu (campo `versao` do GET).")
    aceito = serializers.BooleanField(help_text="Tem de ser true; nao ha aceitacao implicita.")


class RevogarConsentimentoSerializer(serializers.Serializer):
    apagar_dados = serializers.BooleanField(
        required=False, default=False, help_text="Se true, apaga tambem os dados de saude ja recolhidos.")


class ConsentimentoSaudeView(APIView):
    """/api/v1/consents/health/ - consentimento explicito para dados de saude.
    GET: texto e versao em vigor, estado atual e historico. POST: dar consentimento. DELETE: retirar."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ativo = consentimentos.consentimento_ativo(request.user)
        historico = ConsentimentoDados.objects.filter(utilizador=request.user, tipo=consentimentos.TIPO)
        return Response({
            "versao": consentimentos.versao_atual(),
            "texto": consentimentos.texto_atual(),
            "consentido": ativo is not None,
            "consentimento_atual": ConsentimentoSerializer(ativo).data if ativo else None,
            "historico": ConsentimentoSerializer(historico, many=True).data,
        })

    def post(self, request):
        entrada = ConceberConsentimentoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            consentimento = consentimentos.conceder(
                request.user, entrada.validated_data["versao"], request.data.get("aceito"))
        except ErroNegocio as erro:
            return Response({"mensagem": erro.mensagem}, status=erro.codigo)
        return Response(ConsentimentoSerializer(consentimento).data, status=status.HTTP_201_CREATED)

    def delete(self, request):
        entrada = RevogarConsentimentoSerializer(data=request.data or {})
        entrada.is_valid(raise_exception=True)
        if not consentimentos.tem_consentimento(request.user) and not entrada.validated_data["apagar_dados"]:
            return Response({"mensagem": "Nao ha consentimento em vigor."}, status=status.HTTP_404_NOT_FOUND)
        apagados = consentimentos.revogar(request.user, entrada.validated_data["apagar_dados"])
        return Response({"mensagem": "Consentimento retirado.", "registos_apagados": apagados})
