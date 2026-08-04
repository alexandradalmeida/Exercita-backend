
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import Utilizador, UtilizadorAluno, PersonalTrainer
from django.contrib.auth import authenticate

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