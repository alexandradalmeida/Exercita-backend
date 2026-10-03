from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import PersonalTrainer, Sessao, SlotDisponibilidade, Utilizador
from .permissions import IsAluno
from .serializers import (
    AtualizarSessaoSerializer, ContratarSessaoSerializer, PagamentoSerializer, SessaoSerializer,
)
from .services.multicaixa import assinatura_valida
from .services.pagamentos import PagamentoErro
from .services.transacoes import iniciar_pagamento, processar_callback
from .services.sessoes import (
    ErroNegocio, avancar_sessao, cancelar_sessao, contratar_personal_trainer, reagendar_sessao,
)


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


class SessaoDetalheView(generics.RetrieveUpdateAPIView):
    """GET /api/v1/sessions/{id}/ ; PATCH com {"acao": cancelar|reagendar|confirmar|iniciar|concluir}."""
    serializer_class = SessaoSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = Sessao.objects.prefetch_related("pagamentos")
        if user.tipo == Utilizador.TipoUtilizador.ALUNO:
            return qs.filter(aluno__utilizador=user)
        return qs.filter(personal_trainer__utilizador=user)

    def patch(self, request, *args, **kwargs):
        sessao = self.get_object()
        entrada = AtualizarSessaoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data
        extra = {}
        try:
            if dados["acao"] == "cancelar":
                extra["reembolsado"] = cancelar_sessao(sessao, request.user)
            elif dados["acao"] == "reagendar":
                slot = get_object_or_404(SlotDisponibilidade, pk=dados["slot_id"])
                reagendar_sessao(sessao, request.user, slot, dados["data_hora"])
            else:
                avancar_sessao(sessao, request.user, dados["acao"])
        except ErroNegocio as erro:
            return responder_erro_negocio(erro)
        sessao = self.get_queryset().get(pk=sessao.pk)
        return Response({**SessaoSerializer(sessao).data, **extra})


class IniciarPagamentoView(APIView):
    """POST /api/v1/payments/ {"sessao_id": N} - inicia a transacao no Multicaixa Express."""
    permission_classes = [IsAluno]

    def post(self, request):
        sessao = get_object_or_404(Sessao, pk=request.data.get("sessao_id"), aluno__utilizador=request.user)
        try:
            pagamento = iniciar_pagamento(sessao)
        except PagamentoErro as erro:
            return Response({"mensagem": erro.mensagem}, status=erro.codigo)
        return Response(PagamentoSerializer(pagamento).data, status=status.HTTP_201_CREATED)


class PagamentoWebhookView(APIView):
    """POST /api/v1/payments/{id}/webhook/ - callback assincrono do gateway (assinado)."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, pk):
        if not assinatura_valida(request.body, request.headers.get("X-Signature", "")):
            return Response({"mensagem": "Assinatura invalida."}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            pagamento, alterado = processar_callback(
                pk, request.data.get("referencia"), request.data.get("estado"))
        except PagamentoErro as erro:
            return Response({"mensagem": erro.mensagem}, status=erro.codigo)
        return Response({"estado": pagamento.estado, "alterado": alterado})
