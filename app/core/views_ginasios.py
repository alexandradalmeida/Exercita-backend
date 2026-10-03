from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from .models import Ginasio
from .serializers import GinasioSerializer


class GinasioViewSet(viewsets.ModelViewSet):
    """/api/v1/gyms/ - leitura para utilizadores autenticados (so ginasios parceiros);
    criacao e gestao reservadas a administradores."""
    serializer_class = GinasioSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsAdminUser()]

    def get_queryset(self):
        qs = Ginasio.objects.all().order_by("nome")
        if not self.request.user.is_staff:
            qs = qs.filter(estado_parceria=Ginasio.EstadoParceria.PARCEIRO)
        return qs
