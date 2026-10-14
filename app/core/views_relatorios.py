from datetime import date

from django.http import HttpResponse
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import relatorios


def _datas(params):
    try:
        de = date.fromisoformat(params["de"]) if params.get("de") else None
        ate = date.fromisoformat(params["ate"]) if params.get("ate") else None
    except ValueError:
        raise ValidationError("Datas no formato AAAA-MM-DD.")
    if de and ate and ate < de:
        raise ValidationError("'ate' nao pode ser anterior a 'de'.")
    return de, ate


class RelatorioPlataformaView(APIView):
    """GET /api/v1/admin/reports/platform/?de=&ate= - metricas globais para o painel de administracao (UC-15)."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response(relatorios.relatorio_plataforma(*_datas(request.query_params)))


class RelatorioFinanceiroView(APIView):
    """GET /api/v1/admin/reports/financial/?tipo=pagamentos|parcerias&de=&ate= - exportacao em CSV."""
    permission_classes = [IsAdminUser]

    GERADORES = {"pagamentos": relatorios.csv_pagamentos, "parcerias": relatorios.csv_parcerias}

    def get(self, request):
        tipo = request.query_params.get("tipo", "pagamentos")
        if tipo not in self.GERADORES:
            raise ValidationError({"tipo": "Use 'pagamentos' ou 'parcerias'."})
        conteudo = self.GERADORES[tipo](*_datas(request.query_params))
        resposta = HttpResponse(conteudo, content_type="text/csv; charset=utf-8")
        resposta["Content-Disposition"] = f'attachment; filename="relatorio-{tipo}.csv"'
        return resposta
