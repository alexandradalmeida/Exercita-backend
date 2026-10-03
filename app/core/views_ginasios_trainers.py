from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Ginasio, PersonalTrainer
from .search import pesquisar_trainers
from .serializers import TrainerListaSerializer


class GinasioTrainersView(generics.ListAPIView):
    """GET /api/v1/gyms/{id}/trainers/ - PTs que trabalham no ginasio.
    POST {"trainer_id": N} - associa um PT (o proprio PT ativo, ou um admin)."""
    serializer_class = TrainerListaSerializer
    permission_classes = [IsAuthenticated]

    def _ginasio(self):
        qs = Ginasio.objects.all()
        if not self.request.user.is_staff:
            qs = qs.filter(estado_parceria=Ginasio.EstadoParceria.PARCEIRO)
        return get_object_or_404(qs, pk=self.kwargs["pk"])

    def get_queryset(self):
        return pesquisar_trainers({}).filter(ginasios=self._ginasio())

    def _trainer_alvo(self, request, trainer_id):
        """O PT so mexe nas suas proprias associacoes; o admin em qualquer uma."""
        if not str(trainer_id).isdigit():
            raise ValidationError({"trainer_id": "Indique o id do Personal Trainer."})
        pt = get_object_or_404(PersonalTrainer, pk=trainer_id)
        if not request.user.is_staff and pt.utilizador_id != request.user.id:
            raise PermissionDenied("So pode gerir as suas proprias associacoes.")
        return pt

    def post(self, request, pk):
        ginasio = self._ginasio()
        if ginasio.estado_parceria != Ginasio.EstadoParceria.PARCEIRO:
            return Response({"mensagem": "O ginasio nao e parceiro."}, status=status.HTTP_409_CONFLICT)
        pt = self._trainer_alvo(request, request.data.get("trainer_id"))
        if pt.estado_verificacao not in PersonalTrainer.ESTADOS_ATIVOS:
            return Response({"mensagem": "Personal Trainer nao esta ativo."}, status=status.HTTP_409_CONFLICT)
        ginasio.personal_trainers.add(pt)  # idempotente
        return Response({"mensagem": "Personal Trainer associado.", "ginasio_id": ginasio.id, "trainer_id": pt.id},
                        status=status.HTTP_201_CREATED)


class GinasioTrainerDetalheView(GinasioTrainersView):
    """DELETE /api/v1/gyms/{id}/trainers/{trainer_id}/ - remove a associacao."""
    http_method_names = ["delete", "options"]

    def delete(self, request, pk, trainer_id):
        ginasio = self._ginasio()
        pt = self._trainer_alvo(request, trainer_id)
        if not ginasio.personal_trainers.filter(pk=pt.pk).exists():
            return Response({"mensagem": "Associacao nao encontrada."}, status=status.HTTP_404_NOT_FOUND)
        ginasio.personal_trainers.remove(pt)
        return Response(status=status.HTTP_204_NO_CONTENT)
