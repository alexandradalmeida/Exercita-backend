from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from .models import Produto
from .permissions import IsAluno
from .services.loja import (
    adicionar_ao_carrinho, checkout, definir_quantidade, obter_carrinho, remover_do_carrinho, total_do_carrinho,
)
from .services.sessoes import ErroNegocio
from .serializers import (
    AdicionarItemSerializer, CheckoutSerializer, EncomendaSerializer, ItemCarrinhoSerializer,
    ProdutoSerializer, QuantidadeItemSerializer,
)


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


class CarrinhoView(APIView):
    """GET /api/v1/shop/cart/ - carrinho do aluno. DELETE - esvazia."""
    permission_classes = [IsAluno]

    def get(self, request):
        carrinho = obter_carrinho(request.user.perfil_aluno)
        itens = carrinho.itens.select_related("produto").order_by("id")
        return Response({"itens": ItemCarrinhoSerializer(itens, many=True).data,
                         "total": total_do_carrinho(carrinho)})

    def delete(self, request):
        obter_carrinho(request.user.perfil_aluno).itens.all().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CarrinhoItensView(APIView):
    """POST /api/v1/shop/cart/items/ {"produto_id", "quantidade"} - adiciona (soma) ao carrinho."""
    permission_classes = [IsAluno]

    def post(self, request):
        entrada = AdicionarItemSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            item = adicionar_ao_carrinho(request.user.perfil_aluno, **entrada.validated_data)
        except ErroNegocio as erro:
            return Response({"mensagem": erro.mensagem}, status=erro.codigo)
        return Response(ItemCarrinhoSerializer(item).data, status=status.HTTP_201_CREATED)


class CarrinhoItemView(APIView):
    """PATCH /api/v1/shop/cart/items/{produto_id}/ {"quantidade"} define a quantidade; DELETE remove o item."""
    permission_classes = [IsAluno]

    def patch(self, request, produto_id):
        entrada = QuantidadeItemSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            item = definir_quantidade(request.user.perfil_aluno, produto_id, entrada.validated_data["quantidade"])
        except ErroNegocio as erro:
            return Response({"mensagem": erro.mensagem}, status=erro.codigo)
        return Response(ItemCarrinhoSerializer(item).data)

    def delete(self, request, produto_id):
        try:
            remover_do_carrinho(request.user.perfil_aluno, produto_id)
        except ErroNegocio as erro:
            return Response({"mensagem": erro.mensagem}, status=erro.codigo)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CheckoutView(APIView):
    """POST /api/v1/shop/checkout/ {"morada_entrega"} - cria a encomenda a partir do carrinho (UC-12)."""
    permission_classes = [IsAluno]

    def post(self, request):
        entrada = CheckoutSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            encomenda = checkout(request.user.perfil_aluno, entrada.validated_data["morada_entrega"])
        except ErroNegocio as erro:
            return Response({"mensagem": erro.mensagem}, status=erro.codigo)
        return Response(EncomendaSerializer(encomenda).data, status=status.HTTP_201_CREATED)
