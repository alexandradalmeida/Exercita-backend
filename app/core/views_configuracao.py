from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ConfiguracaoPlataforma
from .services.configuracao import valores_efetivos


class ConfiguracaoSerializer(serializers.ModelSerializer):
    efetivos = serializers.SerializerMethodField()

    class Meta:
        model = ConfiguracaoPlataforma
        fields = ["comissao_percentagem", "qualidade_limiar_alerta", "qualidade_limiar_suspensao",
                  "qualidade_minimo_avaliacoes", "efetivos", "data_atualizacao"]
        read_only_fields = ["efetivos", "data_atualizacao"]

    def get_efetivos(self, obj):
        return valores_efetivos(obj)

    def validate(self, data):
        atual = self.instance
        alerta = data.get("qualidade_limiar_alerta", atual.qualidade_limiar_alerta if atual else None)
        suspensao = data.get("qualidade_limiar_suspensao", atual.qualidade_limiar_suspensao if atual else None)
        for nome, valor in (("qualidade_limiar_alerta", alerta), ("qualidade_limiar_suspensao", suspensao)):
            if valor is not None and not 1 <= valor <= 5:
                raise serializers.ValidationError({nome: "Tem de estar entre 1 e 5."})
        if alerta is not None and suspensao is not None and suspensao > alerta:
            raise serializers.ValidationError("O limiar de suspensao nao pode ser superior ao de alerta.")
        return data


class ConfiguracaoView(APIView):
    """GET/PATCH /api/v1/admin/config/ - comissao da plataforma (BR-06) e limiares de qualidade (BR-02).
    Enviar null num campo volta a usar o valor por omissao do ambiente. `efetivos` mostra o que esta em vigor."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response(ConfiguracaoSerializer(ConfiguracaoPlataforma.obter()).data)

    def patch(self, request):
        configuracao = ConfiguracaoPlataforma.obter()
        serializer = ConfiguracaoSerializer(configuracao, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(atualizado_por=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)
