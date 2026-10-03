from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response

from .models import Ginasio, ReservaGinasio
from .permissions import IsAluno
from .serializers import ReservaGinasioSerializer
from .services.reservas_ginasio import cancelar_reserva, reservar
from .services.sessoes import ErroNegocio


class ReservarGinasioView(generics.GenericAPIView):
    """POST /api/v1/gyms/{id}/bookings/ - reserva de aula experimental ou visita (so alunos)."""
    permission_classes = [IsAluno]
    serializer_class = ReservaGinasioSerializer

    def post(self, request, pk):
        ginasio = get_object_or_404(Ginasio, pk=pk, estado_parceria=Ginasio.EstadoParceria.PARCEIRO)
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data
        try:
            reserva = reservar(request.user.perfil_aluno, ginasio, dados["tipo"], dados["data_hora"],
                               dados.get("personal_trainer"), dados.get("notas", ""))
        except ErroNegocio as erro:
            return Response({"mensagem": erro.mensagem}, status=erro.codigo)
        return Response(self.get_serializer(reserva).data, status=status.HTTP_201_CREATED)


class MinhasReservasView(generics.ListAPIView):
    """GET /api/v1/gym-bookings/ - reservas do aluno autenticado."""
    permission_classes = [IsAluno]
    serializer_class = ReservaGinasioSerializer

    def get_queryset(self):
        return ReservaGinasio.objects.filter(aluno=self.request.user.perfil_aluno).select_related("ginasio") \
            .order_by("-data_hora")


class ReservaDetalheView(generics.GenericAPIView):
    """PATCH /api/v1/gym-bookings/{id}/ {"acao": "cancelar"}"""
    permission_classes = [IsAluno]
    serializer_class = ReservaGinasioSerializer

    def patch(self, request, pk):
        reserva = get_object_or_404(ReservaGinasio, pk=pk, aluno=request.user.perfil_aluno)
        if request.data.get("acao") != "cancelar":
            return Response({"mensagem": "acao invalida (use 'cancelar')."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            cancelar_reserva(reserva)
        except ErroNegocio as erro:
            return Response({"mensagem": erro.mensagem}, status=erro.codigo)
        return Response(self.get_serializer(reserva).data)
