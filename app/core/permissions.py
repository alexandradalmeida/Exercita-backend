from rest_framework.permissions import BasePermission

from .models import PersonalTrainer, Utilizador


class IsPersonalTrainerVerificado(BasePermission):
    """BR-01: so PTs verificados pelo admin podem publicar servicos."""
    message = "O seu perfil de Personal Trainer ainda nao foi verificado."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        pt = getattr(user, "perfil_personal_trainer", None)
        return pt is not None and pt.estado_verificacao in PersonalTrainer.ESTADOS_ATIVOS

class IsAluno(BasePermission):
    message = "Apenas alunos podem usar esta funcionalidade."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated
            and user.tipo == Utilizador.TipoUtilizador.ALUNO
            and hasattr(user, "perfil_aluno")
        )
