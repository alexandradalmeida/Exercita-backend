from django.utils import timezone
from rest_framework import serializers

from .models import HistoricoTreino, MetricaFisica, Sessao


class MetricaFisicaSerializer(serializers.ModelSerializer):
    imc = serializers.SerializerMethodField()

    class Meta:
        model = MetricaFisica
        fields = ["id", "data", "peso_kg", "altura_cm", "gordura_percentagem", "cintura_cm", "peito_cm",
                  "anca_cm", "braco_cm", "notas", "fonte", "imc"]
        read_only_fields = ["id", "fonte", "imc"]

    def get_imc(self, obj):
        if obj.peso_kg and obj.altura_cm:
            metros = float(obj.altura_cm) / 100
            return round(float(obj.peso_kg) / (metros * metros), 1)
        return None

    def validate(self, data):
        if self.instance is None and all(data.get(c) is None for c in MetricaFisica.CAMPOS_MEDIDA):
            raise serializers.ValidationError("Indique pelo menos uma medida.")
        return data

    def validate_data(self, valor):
        if valor > timezone.localdate():
            raise serializers.ValidationError("A data nao pode estar no futuro.")
        return valor


class HistoricoTreinoSerializer(serializers.ModelSerializer):
    class Meta:
        model = HistoricoTreino
        fields = ["id", "sessao", "data", "tipo", "duracao_minutos", "calorias_gastas", "notas", "fonte"]
        read_only_fields = ["id", "fonte"]

    def validate_data(self, valor):
        if valor > timezone.localdate():
            raise serializers.ValidationError("A data nao pode estar no futuro.")
        return valor

    def validate_sessao(self, sessao):
        aluno = self.context["request"].user.perfil_aluno
        if sessao is not None and (sessao.aluno_id != aluno.id or sessao.estado not in Sessao.ESTADOS_REALIZADOS):
            raise serializers.ValidationError("Indique uma sessao sua ja realizada.")
        return sessao


class WearableMetricaSerializer(MetricaFisicaSerializer):
    origem_externa_id = serializers.CharField(max_length=100)

    class Meta(MetricaFisicaSerializer.Meta):
        fields = MetricaFisicaSerializer.Meta.fields + ["origem_externa_id"]


class WearableTreinoSerializer(HistoricoTreinoSerializer):
    origem_externa_id = serializers.CharField(max_length=100)

    class Meta(HistoricoTreinoSerializer.Meta):
        fields = HistoricoTreinoSerializer.Meta.fields + ["origem_externa_id"]


class WearableIngestaoSerializer(serializers.Serializer):
    metricas = WearableMetricaSerializer(many=True, required=False)
    treinos = WearableTreinoSerializer(many=True, required=False)
