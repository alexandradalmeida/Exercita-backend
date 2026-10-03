from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PersonalTrainer, Sessao, SlotDisponibilidade, Utilizador
from .permissions import IsAluno
from .serializers import ContratarSessaoSerializer, SessaoSerializer
from .services.sessoes import ErroNegocio, contratar_personal_trainer


def responder_erro_negocio(erro):
    return Response({"mensagem": erro.mensagem}, status=erro.codigo)


class SessaoListCreateView(generics.ListAPIView):
    """GET /api/v1/sessions/ - sessoes do utilizador autenticado (aluno ou PT).
    POST /api/v1/sessions/ - contratarPersonalTrainer (UC-07), so alunos."""
    serializer_class = SessaoSerializer

    def get_permissions(self):
        return [IsAluno()] if self.request.method == "POST" else [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = Sessao.objects.prefetch_related("pagamentos").order_by("-data_hora")
        if user.tipo == Utilizador.TipoUtilizador.ALUNO:
            return qs.filter(aluno__utilizador=user)
        return qs.filter(personal_trainer__utilizador=user)

    def post(self, request):
        entrada = ContratarSessaoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data

        pt = get_object_or_404(PersonalTrainer, pk=dados["trainer_id"])
        slot = get_object_or_404(SlotDisponibilidade, pk=dados["slot_id"])
        try:
            sessao, _ = contratar_personal_trainer(
                request.user.perfil_aluno, pt, slot, dados["data_hora"],
                dados["modalidade"], dados["quantidade_sessoes"],
            )
        except ErroNegocio as erro:
            return responder_erro_negocio(erro)
        return Response(SessaoSerializer(sessao).data, status=status.HTTP_201_CREATED)
