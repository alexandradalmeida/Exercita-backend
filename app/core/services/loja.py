from decimal import Decimal

from django.db import transaction
from django.db.models import F

from ..models import Carrinho, Encomenda, EventoEncomenda, ItemCarrinho, ItemEncomenda, Pagamento, Produto
from . import notificacoes
from .multicaixa import GatewayErro, obter_gateway
from .sessoes import ErroNegocio

E = Encomenda.Estado


def obter_carrinho(aluno):
    carrinho, _ = Carrinho.objects.get_or_create(aluno=aluno)
    return carrinho


def _produto_disponivel(produto_id):
    produto = Produto.objects.filter(pk=produto_id, ativo=True).first()
    if produto is None:
        raise ErroNegocio("Produto nao encontrado.", 404)
    return produto


def adicionar_ao_carrinho(aluno, produto_id, quantidade):
    """Soma `quantidade` ao item (cria-o se nao existir). Nao reserva stock: isso so acontece no checkout."""
    produto = _produto_disponivel(produto_id)
    carrinho = obter_carrinho(aluno)
    item, _ = ItemCarrinho.objects.get_or_create(carrinho=carrinho, produto=produto, defaults={"quantidade": 0})
    nova = item.quantidade + quantidade
    if nova > produto.stock:
        raise ErroNegocio(f"Stock insuficiente: apenas {produto.stock} unidade(s) disponivel(eis).", 409)
    item.quantidade = nova
    item.save(update_fields=["quantidade"])
    return item


def definir_quantidade(aluno, produto_id, quantidade):
    item = ItemCarrinho.objects.filter(carrinho__aluno=aluno, produto_id=produto_id).select_related("produto").first()
    if item is None:
        raise ErroNegocio("Item nao esta no carrinho.", 404)
    if quantidade > item.produto.stock:
        raise ErroNegocio(f"Stock insuficiente: apenas {item.produto.stock} unidade(s) disponivel(eis).", 409)
    item.quantidade = quantidade
    item.save(update_fields=["quantidade"])
    return item


def remover_do_carrinho(aluno, produto_id):
    apagados, _ = ItemCarrinho.objects.filter(carrinho__aluno=aluno, produto_id=produto_id).delete()
    if not apagados:
        raise ErroNegocio("Item nao esta no carrinho.", 404)


def total_do_carrinho(carrinho):
    return sum((i.produto.preco * i.quantidade for i in carrinho.itens.select_related("produto")), Decimal("0"))


@transaction.atomic
def checkout(aluno, morada_entrega):
    """UC-12: transforma o carrinho em encomenda, reserva o stock e cria o pagamento pendente
    (que o aluno inicia depois com POST /payments/ {"encomenda_id": N})."""
    if not morada_entrega.strip():
        raise ErroNegocio("Indique a morada de entrega.")
    carrinho = obter_carrinho(aluno)
    itens = list(carrinho.itens.select_related("produto"))
    if not itens:
        raise ErroNegocio("O carrinho esta vazio.", 409)

    # trava os produtos por ordem de id: evita deadlocks e vendas acima do stock
    produtos = {p.pk: p for p in Produto.objects.select_for_update().filter(
        pk__in=[i.produto_id for i in itens]).order_by("pk")}
    for item in itens:
        produto = produtos[item.produto_id]
        if not produto.ativo:
            raise ErroNegocio(f"'{produto.nome}' ja nao esta disponivel.", 409)
        if item.quantidade > produto.stock:
            raise ErroNegocio(f"Stock insuficiente de '{produto.nome}' (disponivel: {produto.stock}).", 409)

    total = sum((produtos[i.produto_id].preco * i.quantidade for i in itens), Decimal("0"))
    encomenda = Encomenda.objects.create(aluno=aluno, total=total, morada_entrega=morada_entrega.strip())
    for item in itens:
        produto = produtos[item.produto_id]
        ItemEncomenda.objects.create(
            encomenda=encomenda, produto=produto, nome=produto.nome,
            preco_unitario=produto.preco, quantidade=item.quantidade)
        Produto.objects.filter(pk=produto.pk).update(stock=F("stock") - item.quantidade)
    Pagamento.objects.create(encomenda=encomenda, valor=total)  # sem comissao: a venda e da propria plataforma
    EventoEncomenda.objects.create(encomenda=encomenda, estado=E.PENDENTE_PAGAMENTO)
    carrinho.itens.all().delete()
    notificacoes.encomenda_criada(encomenda)
    return encomenda


def repor_stock(encomenda):
    for item in encomenda.itens.exclude(produto=None):
        Produto.objects.filter(pk=item.produto_id).update(stock=F("stock") + item.quantidade)


@transaction.atomic
def cancelar_encomenda(encomenda):
    """Cancela uma encomenda ainda nao enviada: repoe o stock e reembolsa se ja estava paga."""
    encomenda = Encomenda.objects.select_for_update().get(pk=encomenda.pk)
    if not encomenda.pode_transitar(E.CANCELADA):
        raise ErroNegocio(f"Uma encomenda '{encomenda.get_estado_display()}' ja nao pode ser cancelada.", 409)
    reembolsado = False
    for pagamento in encomenda.pagamentos.select_for_update():
        if pagamento.estado == Pagamento.EstadoPagamento.PENDENTE:
            pagamento.transitar(Pagamento.EstadoPagamento.RECUSADO)
        elif pagamento.estado == Pagamento.EstadoPagamento.APROVADO:
            try:
                obter_gateway().reembolsar(pagamento)
            except GatewayErro:
                raise ErroNegocio("Falha ao solicitar o reembolso ao Multicaixa; tente novamente.", 502)
            pagamento.transitar(Pagamento.EstadoPagamento.REEMBOLSADO)
            reembolsado = True
    encomenda.transitar(E.CANCELADA)
    repor_stock(encomenda)
    notificacoes.encomenda_atualizada(encomenda, "cancelada")
    return reembolsado


ACOES_ADMIN = {"preparar": E.EM_PREPARACAO, "enviar": E.ENVIADA, "entregar": E.ENTREGUE}


@transaction.atomic
def avancar_encomenda(encomenda, acao, codigo_rastreio=""):
    """Gestao de encomendas (admin): paga -> em preparacao -> enviada (com codigo de rastreio) -> entregue."""
    from django.utils import timezone
    encomenda = Encomenda.objects.select_for_update().get(pk=encomenda.pk)
    destino = ACOES_ADMIN[acao]
    if not encomenda.pode_transitar(destino):
        raise ErroNegocio(f"Nao e possivel '{acao}' uma encomenda '{encomenda.get_estado_display()}'.", 409)
    campos = {}
    if destino == E.ENVIADA:
        if not codigo_rastreio.strip():
            raise ErroNegocio("Indique o codigo de rastreio para enviar a encomenda.")
        campos = {"codigo_rastreio": codigo_rastreio.strip(), "data_envio": timezone.now()}
    elif destino == E.ENTREGUE:
        campos = {"data_entrega": timezone.now()}
    encomenda.transitar(destino, **campos)
    notificacoes.encomenda_atualizada(encomenda, encomenda.get_estado_display().lower())
    return encomenda
