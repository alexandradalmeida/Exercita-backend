from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from .models import Utilizador
from .services import administracao
from .services.sessoes import ErroNegocio


class UtilizadorAdminSerializer(serializers.ModelSerializer):
    estado_perfil = serializers.SerializerMethodField()

    class Meta:
        model = Utilizador
        fields = ["id", "username", "email", "tipo", "is_active", "is_staff", "suspenso",
                  "motivo_suspensao", "data_suspensao", "data_criacao", "estado_perfil"]  # sem telefone (dado pessoal)
        read_only_fields = fields

    def get_estado_perfil(self, obj):
        for atributo in ("perfil_personal_trainer", "perfil_nutricionista"):
            perfil = getattr(obj, atributo, None)
            if perfil is not None:
                return perfil.estado_verificacao
        return None


class UtilizadorAdminViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """/api/v1/admin/users/ (UC-15) - gestao de utilizadores pelo administrador.
    Filtros: ?tipo= ?suspenso=true|false ?is_active=true|false ?q= (username/email).
    Acoes: POST .../{id}/suspend/ {"motivo"}, .../reactivate/, .../verify/, .../permissions/ {"is_staff"}."""
    serializer_class = UtilizadorAdminSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        qs = Utilizador.objects.all().order_by("id")
        p = self.request.query_params
        if tipo := p.get("tipo"):
            qs = qs.filter(tipo=tipo)
        for campo in ("suspenso", "is_active"):
            if p.get(campo) in ("true", "false"):
                qs = qs.filter(**{campo: p[campo] == "true"})
        if q := p.get("q"):
            qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q))
        return qs

    def _executar(self, request, pk, funcao, *args):
        alvo = get_object_or_404(Utilizador, pk=pk)
        try:
            funcao(alvo, request.user, *args)
        except ErroNegocio as erro:
            return Response({"mensagem": erro.mensagem}, status=erro.codigo)
        alvo.refresh_from_db()
        return Response(UtilizadorAdminSerializer(alvo).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        return self._executar(request, pk, administracao.suspender, str(request.data.get("motivo", "")))

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        return self._executar(request, pk, administracao.reativar_conta)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        return self._executar(request, pk, administracao.verificar_perfil)

    @action(detail=True, methods=["post"])
    def permissions(self, request, pk=None):
        valor = request.data.get("is_staff")
        if not isinstance(valor, bool):
            return Response({"is_staff": "Indique true ou false."}, status=status.HTTP_400_BAD_REQUEST)
        return self._executar(request, pk, administracao.definir_permissoes, valor)
