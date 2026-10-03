from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from .models import DocumentoFinanceiro
from .serializers import DocumentoFinanceiroSerializer


class DocumentoFinanceiroViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """/api/v1/billing/documents/ - faturas e recibos do utilizador (o admin ve todos). Filtro: ?tipo=FT|RC."""
    serializer_class = DocumentoFinanceiroSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = DocumentoFinanceiro.objects.select_related("pagamento")
        if not self.request.user.is_staff:
            qs = qs.filter(cliente=self.request.user)
        if tipo := self.request.query_params.get("tipo"):
            qs = qs.filter(tipo=tipo.upper())
        return qs
