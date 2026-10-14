from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def liveness(request):
    """GET /api/health/ - o processo esta vivo (para o orquestrador reiniciar se falhar)."""
    return JsonResponse({"estado": "ok"})


@require_GET
def readiness(request):
    """GET /api/health/ready/ - o servico consegue atender pedidos (base de dados acessivel).
    Usado pelo load balancer/monitorizacao de disponibilidade (RNF-04)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"estado": "indisponivel", "base_de_dados": "falhou"}, status=503)
    return JsonResponse({"estado": "ok", "base_de_dados": "ok"})
