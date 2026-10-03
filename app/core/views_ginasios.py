from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from .geo import anotar_distancia_km
from .models import Ginasio
from .serializers import GinasioSerializer

RAIO_POR_OMISSAO_KM = 10
RAIO_MAXIMO_KM = 500


def _numero(params, nome, minimo, maximo):
    valor = params.get(nome)
    if valor in (None, ""):
        return None
    try:
        numero = float(valor)
    except ValueError:
        raise ValidationError({nome: "Tem de ser numerico."})
    if not minimo <= numero <= maximo:
        raise ValidationError({nome: f"Tem de estar entre {minimo} e {maximo}."})
    return numero


class GinasioViewSet(viewsets.ModelViewSet):
    """/api/v1/gyms/ - leitura para utilizadores autenticados (so ginasios parceiros);
    criacao e gestao reservadas a administradores.
    GET ?lat=&lng=&raio_km= (por omissao 10 km) pesquisa por proximidade, do mais perto para o mais longe;
    tambem aceita ?equipamento= e ?q= (nome)."""
    serializer_class = GinasioSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsAdminUser()]

    def get_queryset(self):
        qs = Ginasio.objects.all().order_by("nome")
        if not self.request.user.is_staff:
            qs = qs.filter(estado_parceria=Ginasio.EstadoParceria.PARCEIRO)
        if self.action != "list":
            return qs

        params = self.request.query_params
        lat = _numero(params, "lat", -90, 90)
        lng = _numero(params, "lng", -180, 180)
        raio = _numero(params, "raio_km", 0, RAIO_MAXIMO_KM)
        if (lat is None) != (lng is None):
            raise ValidationError("lat e lng tem de ser indicados em conjunto.")
        if raio is not None and lat is None:
            raise ValidationError("raio_km exige lat e lng.")
        if equipamento := params.get("equipamento"):
            qs = qs.filter(equipamentos__contains=[equipamento.strip().lower()])
        if nome := params.get("q"):
            qs = qs.filter(nome__icontains=nome)
        if lat is not None:
            qs = anotar_distancia_km(qs.exclude(latitude=None).exclude(longitude=None),
                                     lat, lng, raio if raio is not None else RAIO_POR_OMISSAO_KM)
            qs = qs.order_by("distancia_km", "nome")
        return qs
