import math

from django.db.models import FloatField
from django.db.models.functions import ACos, Cast, Cos, Greatest, Least, Radians, Sin
from django.db.models.expressions import Value

RAIO_TERRA_KM = 6371.0088


def anotar_distancia_km(qs, lat, lng, raio_km=None):
    """Anota `distancia_km` (Haversine/lei dos cossenos esferica, calculada na base de dados) e,
    com `raio_km`, filtra por proximidade. Um bounding box previo reduz o trabalho aos candidatos."""
    if raio_km is not None:
        delta_lat = math.degrees(raio_km / RAIO_TERRA_KM)
        cos_lat = max(math.cos(math.radians(lat)), 1e-6)
        delta_lng = min(math.degrees(raio_km / (RAIO_TERRA_KM * cos_lat)), 180)
        qs = qs.filter(
            latitude__gte=lat - delta_lat, latitude__lte=lat + delta_lat,
            longitude__gte=lng - delta_lng, longitude__lte=lng + delta_lng,
        )
    lat_r, lng_r = math.radians(lat), math.radians(lng)
    latitude = Radians(Cast("latitude", FloatField()))
    longitude = Radians(Cast("longitude", FloatField()))
    coseno = (
        Sin(Value(lat_r)) * Sin(latitude)
        + Cos(Value(lat_r)) * Cos(latitude) * Cos(longitude - Value(lng_r))
    )
    # o clamp evita erros de arredondamento fora de [-1, 1] no ACos
    qs = qs.annotate(distancia_km=ACos(Least(Value(1.0), Greatest(Value(-1.0), coseno))) * Value(RAIO_TERRA_KM, output_field=FloatField()))
    if raio_km is not None:
        qs = qs.filter(distancia_km__lte=raio_km)
    return qs
