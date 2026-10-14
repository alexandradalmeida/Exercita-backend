from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CreditoAluno
from .permissions import IsAluno
from .serializers import CreditoAlunoSerializer
from .services import creditos


class CreditosView(APIView):
    """GET /api/v1/credits/ - saldo utilizavel e historico de creditos do aluno (validade por omissao 90 dias)."""
    permission_classes = [IsAluno]

    def get(self, request):
        aluno = request.user.perfil_aluno
        todos = CreditoAluno.objects.filter(aluno=aluno).order_by("-data_criacao", "-id")
        proxima = creditos.ativos(aluno).first()
        return Response({
            "saldo": creditos.saldo(aluno),
            "proxima_expiracao": proxima.data_expiracao if proxima else None,
            "creditos": CreditoAlunoSerializer(todos, many=True).data,
        })
