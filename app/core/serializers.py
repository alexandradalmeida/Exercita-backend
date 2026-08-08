from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import authenticate
from .models import Utilizador, UtilizadorAluno, PersonalTrainer


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
            "estado_verificacao", "especialidade", "biografia",
        ]
        read_only_fields = ["estado_verificacao"]  # só muda via processo de verificação, não pelo próprio PT

        