from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Encomenda, PersonalTrainer, Sessao, SlotDisponibilidade, Utilizador
from .permissions import IsAluno
from .serializers import (
    AvaliacaoSerializer, CriarAvaliacaoSerializer,
    AtualizarSessaoSerializer, ContratarSessaoSerializer, PagamentoSerializer, SessaoSerializer,
)
from .services.avaliacoes import avaliar_sessao
from .services.calendario import sessao_para_ics
from .services.multicaixa import assinatura_valida
from .services.pagamentos import PagamentoErro
from .services.transacoes import (
    iniciar_pagamento, iniciar_pagamento_encomenda, libertar_pagamento, processar_callback,
)
from .services.sessoes import (
    ErroNegocio, avancar_sessao, cancelar_sessao, contratar_personal_trainer, reagendar_sessao, reclamar_sessao,
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
            elif dados["acao"] == "reclamar":
                reclamar_sessao(sessao, request.user, dados.get("motivo", ""))
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
    """POST /api/v1/payments/ {"sessao_id": N} ou {"encomenda_id": N} - inicia a transacao no Multicaixa Express."""
    permission_classes = [IsAluno]

    def post(self, request):
        aluno = request.user.perfil_aluno
        try:
            if request.data.get("encomenda_id") is not None:
                encomenda = get_object_or_404(Encomenda, pk=request.data["encomenda_id"], aluno=aluno)
                pagamento = iniciar_pagamento_encomenda(encomenda)
            else:
                sessao = get_object_or_404(Sessao, pk=request.data.get("sessao_id"), aluno=aluno)
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


class LibertarPagamentoView(APIView):
    """POST /api/v1/payments/{id}/release/ - o aluno confirma a realizacao e liberta o valor ao PT (BR-03)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            pagamento = libertar_pagamento(pk, user=request.user)
        except PagamentoErro as erro:
            return Response({"mensagem": erro.mensagem}, status=erro.codigo)
        return Response(PagamentoSerializer(pagamento).data)


class SessaoCalendarioView(APIView):
    """GET /api/v1/sessions/{id}/calendar/ - ficheiro .ics para Google/Apple Calendar."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        user = request.user
        qs = Sessao.objects.select_related("slot", "personal_trainer__utilizador")
        if user.tipo == Utilizador.TipoUtilizador.ALUNO:
            qs = qs.filter(aluno__utilizador=user)
        else:
            qs = qs.filter(personal_trainer__utilizador=user)
        sessao = get_object_or_404(qs, pk=pk)
        resposta = HttpResponse(sessao_para_ics(sessao), content_type="text/calendar; charset=utf-8")
        resposta["Content-Disposition"] = f'attachment; filename="sessao-{sessao.pk}.ics"'
        return resposta


class SessaoAvaliacoesView(APIView):
    """GET/POST /api/v1/sessions/{id}/reviews/ - avaliacao mutua aluno <-> PT (UC-09)."""
    permission_classes = [IsAuthenticated]

    def _sessao(self, request, pk):
        user = request.user
        qs = Sessao.objects.select_related("aluno__utilizador", "personal_trainer__utilizador")
        qs = qs.filter(aluno__utilizador=user) if user.tipo == Utilizador.TipoUtilizador.ALUNO \
            else qs.filter(personal_trainer__utilizador=user)
        return get_object_or_404(qs, pk=pk)

    def get(self, request, pk):
        sessao = self._sessao(request, pk)
        avaliacoes = sessao.avaliacoes.select_related("autor", "avaliado").order_by("id")
        return Response(AvaliacaoSerializer(avaliacoes, many=True).data)

    def post(self, request, pk):
        sessao = self._sessao(request, pk)
        entrada = CriarAvaliacaoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            avaliacao = avaliar_sessao(sessao, request.user, entrada.validated_data["classificacao"],
                                       entrada.validated_data["comentario"])
        except ErroNegocio as erro:
            return responder_erro_negocio(erro)
        return Response(AvaliacaoSerializer(avaliacao).data, status=status.HTTP_201_CREATED)
