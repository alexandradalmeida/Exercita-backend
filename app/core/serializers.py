from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import authenticate
from .services.embeddings import atualizar_embedding
from datetime import time

from .models import Avaliacao, Certificacao, Ginasio, Notificacao, Pagamento, PersonalTrainer, Sessao, SlotDisponibilidade, Utilizador, UtilizadorAluno


class RegistoSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = Utilizador
        fields = ["username", "email", "password", "tipo", "telefone"]

    def create(self, validated_data):
        password = validated_data.pop("password")
        utilizador = Utilizador(**validated_data)
        utilizador.set_password(password)
        utilizador.is_active = False  # só ativa depois de confirmar o email
        utilizador.save()

        # cria o perfil correspondente ao tipo escolhido
        if utilizador.tipo == Utilizador.TipoUtilizador.ALUNO:
            UtilizadorAluno.objects.create(utilizador=utilizador)
        elif utilizador.tipo == Utilizador.TipoUtilizador.PERSONAL_TRAINER:
            PersonalTrainer.objects.create(utilizador=utilizador)

        return utilizador


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        utilizador = authenticate(username=data["username"], password=data["password"])
        if not utilizador:
            raise serializers.ValidationError("Credenciais invalidas.")
        if not utilizador.is_active:
            raise serializers.ValidationError("Conta ainda nao confirmada. Verifique o seu email.")
        data["utilizador"] = utilizador
        return data


class UtilizadorAlunoSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="utilizador.username", read_only=True)
    email = serializers.EmailField(source="utilizador.email", read_only=True)
    telefone = serializers.CharField(source="utilizador.telefone")

    class Meta:
        model = UtilizadorAluno
        fields = ["id", "username", "email", "telefone", "data_nascimento", "objetivo"]

    def update(self, instance, validated_data):
        utilizador_data = validated_data.pop("utilizador", {})
        if "telefone" in utilizador_data:
            instance.utilizador.telefone = utilizador_data["telefone"]
            instance.utilizador.save()

        return super().update(instance, validated_data)


class PersonalTrainerSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="utilizador.username", read_only=True)
    email = serializers.EmailField(source="utilizador.email", read_only=True)
    telefone = serializers.CharField(source="utilizador.telefone")

    class Meta:
        model = PersonalTrainer
        fields = [
            "id", "username", "email", "telefone",
            "estado_verificacao", "especialidade", "localizacao", "biografia",
            "preco_hora", "modalidades_pagamento", "janela_cancelamento_horas",
            "classificacao_media", "total_avaliacoes",
        ]
        read_only_fields = ["estado_verificacao", "classificacao_media", "total_avaliacoes"]  # só muda via processo de verificação, não pelo próprio PT

    def validate(self, data):
        # BR-01: publicar preco/modalidades equivale a publicar o servico
        publica = "preco_hora" in data or "modalidades_pagamento" in data
        if publica and self.instance and self.instance.estado_verificacao not in PersonalTrainer.ESTADOS_ATIVOS:
            raise serializers.ValidationError(
                "So Personal Trainers verificados podem publicar preco e modalidades de pagamento."
            )
        return data

    def update(self, instance, validated_data):
        utilizador_data = validated_data.pop("utilizador", {})
        if "telefone" in utilizador_data:
            instance.utilizador.telefone = utilizador_data["telefone"]
            instance.utilizador.save()
        instance = super().update(instance, validated_data)
        atualizar_embedding(instance)  # mantem o matching por IA sincronizado com o perfil
        return instance

class CertificacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Certificacao
        fields = ["id", "nome", "instituicao", "ano_obtencao"]


class SlotDisponibilidadeSerializer(serializers.ModelSerializer):
    vagas_disponiveis = serializers.IntegerField(read_only=True)
    dia_semana_display = serializers.CharField(source="get_dia_semana_display", read_only=True)

    class Meta:
        model = SlotDisponibilidade
        fields = [
            "id", "dia_semana", "dia_semana_display", "hora_inicio", "hora_fim",
            "capacidade", "vagas_ocupadas", "vagas_disponiveis",
        ]
        read_only_fields = ["vagas_ocupadas"]  # gerido pelo sistema ao agendar sessoes

    def validate(self, data):
        inicio = data.get("hora_inicio", getattr(self.instance, "hora_inicio", None))
        fim = data.get("hora_fim", getattr(self.instance, "hora_fim", None))
        if inicio and fim and fim <= inicio:
            raise serializers.ValidationError("hora_fim tem de ser posterior a hora_inicio.")
        capacidade = data.get("capacidade", getattr(self.instance, "capacidade", 1))
        if capacidade < 1:
            raise serializers.ValidationError("capacidade tem de ser pelo menos 1.")
        if self.instance and capacidade < self.instance.vagas_ocupadas:
            raise serializers.ValidationError("capacidade nao pode ser inferior as vagas ja ocupadas.")
        return data

class TrainerListaSerializer(serializers.ModelSerializer):
    """Resultado da pesquisa: dados publicos + disponibilidade (vagas vs lotacao)."""
    username = serializers.CharField(source="utilizador.username", read_only=True)
    avaliacao_media = serializers.FloatField(read_only=True)
    vagas_disponiveis = serializers.SerializerMethodField()
    lotacao_atingida = serializers.SerializerMethodField()

    class Meta:
        model = PersonalTrainer
        fields = [
            "id", "username", "especialidade", "localizacao", "preco_hora", "modalidades_pagamento",
            "avaliacao_media", "total_avaliacoes", "vagas_disponiveis", "lotacao_atingida",
        ]

    def get_vagas_disponiveis(self, obj):
        return max(obj.capacidade_total - obj.ocupadas_total, 0)

    def get_lotacao_atingida(self, obj):
        # sem slots publicados nao ha lotacao, apenas ausencia de horarios
        return obj.total_slots > 0 and obj.capacidade_total - obj.ocupadas_total <= 0

class AvaliacaoPublicaSerializer(serializers.ModelSerializer):
    aluno = serializers.CharField(source="autor.username", read_only=True)

    class Meta:
        model = Avaliacao
        fields = ["id", "aluno", "classificacao", "comentario", "data_criacao"]


class TrainerPerfilPublicoSerializer(serializers.ModelSerializer):
    """UC-06: perfil publico com certificacoes e avaliacoes verificadas
    (apenas avaliacoes de sessoes realizadas)."""
    username = serializers.CharField(source="utilizador.username", read_only=True)
    certificacoes = CertificacaoSerializer(many=True, read_only=True)
    avaliacao_media = serializers.FloatField(read_only=True)
    avaliacoes = serializers.SerializerMethodField()

    class Meta:
        model = PersonalTrainer
        fields = [
            "id", "username", "especialidade", "localizacao", "biografia", "preco_hora",
            "modalidades_pagamento", "certificacoes", "avaliacao_media", "total_avaliacoes", "avaliacoes",
        ]

    def get_avaliacoes(self, obj):
        qs = (
            Avaliacao.objects.filter(avaliado=obj.utilizador, sessao__estado__in=Sessao.ESTADOS_REALIZADOS)
            .select_related("autor").order_by("-data_criacao")[:20]
        )
        return AvaliacaoPublicaSerializer(qs, many=True).data


class PagamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pagamento
        fields = [
            "id", "sessao", "valor", "comissao_plataforma", "valor_liquido_pt", "estado",
            "referencia_multicaixa", "data_criacao", "data_aprovacao", "data_libertacao",
        ]
        read_only_fields = fields


class SessaoSerializer(serializers.ModelSerializer):
    pagamentos = PagamentoSerializer(many=True, read_only=True)
    trainer_id = serializers.IntegerField(source="personal_trainer_id", read_only=True)

    class Meta:
        model = Sessao
        fields = [
            "id", "trainer_id", "slot", "data_hora", "modalidade", "quantidade_sessoes",
            "valor_total", "estado", "data_cancelamento", "data_realizacao", "reclamacao", "notas", "pagamentos",
        ]
        read_only_fields = fields


class ContratarSessaoSerializer(serializers.Serializer):
    trainer_id = serializers.IntegerField()
    slot_id = serializers.IntegerField()
    data_hora = serializers.DateTimeField()
    modalidade = serializers.ChoiceField(choices=Sessao.Modalidade.choices, default=Sessao.Modalidade.INDIVIDUAL)
    quantidade_sessoes = serializers.IntegerField(min_value=1, default=1)


class AtualizarSessaoSerializer(serializers.Serializer):
    ACOES = ["cancelar", "reagendar", "confirmar", "iniciar", "concluir", "reclamar"]
    acao = serializers.ChoiceField(choices=ACOES)
    slot_id = serializers.IntegerField(required=False)
    data_hora = serializers.DateTimeField(required=False)
    motivo = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        if data["acao"] == "reagendar" and not ("slot_id" in data and "data_hora" in data):
            raise serializers.ValidationError("reagendar exige slot_id e data_hora.")
        return data


class NotificacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notificacao
        fields = ["id", "mensagem", "lida", "data_criacao"]
        read_only_fields = ["id", "mensagem", "data_criacao"]


class AvaliacaoSerializer(serializers.ModelSerializer):
    autor = serializers.CharField(source="autor.username", read_only=True)
    avaliado = serializers.CharField(source="avaliado.username", read_only=True)

    class Meta:
        model = Avaliacao
        fields = ["id", "sessao", "autor", "avaliado", "classificacao", "comentario", "data_criacao"]
        read_only_fields = ["id", "sessao", "autor", "avaliado", "data_criacao"]


class CriarAvaliacaoSerializer(serializers.Serializer):
    classificacao = serializers.IntegerField(min_value=1, max_value=5)
    comentario = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")


class GinasioSerializer(serializers.ModelSerializer):
    distancia_km = serializers.FloatField(read_only=True)

    class Meta:
        model = Ginasio
        fields = [
            "id", "nome", "morada", "latitude", "longitude", "equipamentos", "horarios",
            "estado_parceria", "distancia_km",
        ]

    def validate_latitude(self, valor):
        if valor is not None and not -90 <= valor <= 90:
            raise serializers.ValidationError("latitude tem de estar entre -90 e 90.")
        return valor

    def validate_longitude(self, valor):
        if valor is not None and not -180 <= valor <= 180:
            raise serializers.ValidationError("longitude tem de estar entre -180 e 180.")
        return valor

    def validate_horarios(self, horarios):
        if not isinstance(horarios, dict):
            raise serializers.ValidationError("horarios tem de ser um objeto {dia: [[abertura, fecho], ...]}.")
        for dia, intervalos in horarios.items():
            if dia not in {"0", "1", "2", "3", "4", "5", "6"}:
                raise serializers.ValidationError(f"Dia invalido '{dia}' (use 0 a 6, 0 = segunda).")
            if not isinstance(intervalos, list):
                raise serializers.ValidationError(f"Dia {dia}: esperada uma lista de intervalos.")
            for intervalo in intervalos:
                try:
                    abre, fecha = (time.fromisoformat(h) for h in intervalo)
                except (TypeError, ValueError):
                    raise serializers.ValidationError(f"Dia {dia}: intervalo invalido {intervalo} (use [\"HH:MM\", \"HH:MM\"]).")
                if fecha <= abre:
                    raise serializers.ValidationError(f"Dia {dia}: o fecho tem de ser posterior a abertura.")
        return horarios
