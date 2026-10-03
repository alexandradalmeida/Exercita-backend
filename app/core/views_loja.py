from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from .models import Produto
from .serializers import ProdutoSerializer


class ProdutoViewSet(viewsets.ModelViewSet):
    """/api/v1/shop/products/ - catalogo. Utilizadores autenticados consultam os produtos ativos;
    a gestao (criar/editar/apagar) e do admin.
    Filtros: ?categoria=, ?q=, ?preco_min=, ?preco_max=, ?em_stock=true."""
    serializer_class = ProdutoSerializer

    def get_permissions(self):
        return [IsAuthenticated()] if self.action in ("list", "retrieve") else [IsAdminUser()]

    def get_queryset(self):
        qs = Produto.objects.all().order_by("nome", "id")
        if not self.request.user.is_staff:
            qs = qs.filter(ativo=True)
        if self.action != "list":
            return qs
        params = self.request.query_params
        if categoria := params.get("categoria"):
            qs = qs.filter(categoria=categoria)
        if q := params.get("q"):
            qs = qs.filter(nome__icontains=q)
        try:
            if minimo := params.get("preco_min"):
                qs = qs.filter(preco__gte=float(minimo))
            if maximo := params.get("preco_max"):
                qs = qs.filter(preco__lte=float(maximo))
        except ValueError:
            raise ValidationError("preco_min e preco_max tem de ser numericos.")
        if params.get("em_stock") in ("1", "true", "True"):
            qs = qs.filter(stock__gt=0)
        return qs
