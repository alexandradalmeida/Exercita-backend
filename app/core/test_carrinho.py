import json
from decimal import Decimal
from threading import Thread
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from .models import Encomenda, Notificacao, Pagamento, Produto
from .services.multicaixa import GatewayErro, MulticaixaMock, assinar
from .test_loja import criar_produto
from .test_pagamentos import SEGREDO, segredo_de_teste
from .test_sessoes import criar_aluno

CARRINHO = "/api/v1/shop/cart/"
ITENS = CARRINHO + "items/"
CHECKOUT = "/api/v1/shop/checkout/"


class LojaBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("cliente")
        self.client.force_authenticate(self.aluno.utilizador)
        self.whey = criar_produto("Whey", "250.00", 5)
        self.tshirt = criar_produto("T-shirt", "60.00", 20, categoria="vestuario")

    def adicionar(self, produto, quantidade=1):
        return self.client.post(ITENS, {"produto_id": produto.id, "quantidade": quantidade}, format="json")

    def checkout(self, morada="Rua A, Luanda"):
        return self.client.post(CHECKOUT, {"morada_entrega": morada}, format="json")


class CarrinhoTestCase(LojaBase):
    def test_adicionar_soma_e_calcula_total(self):
        self.adicionar(self.whey, 2)
        self.adicionar(self.whey, 1)
        self.adicionar(self.tshirt, 2)
        r = self.client.get(CARRINHO)
        self.assertEqual(len(r.data["itens"]), 2)
        self.assertEqual(Decimal(r.data["total"]), Decimal("870.00"))  # 3*250 + 2*60
        self.assertEqual(r.data["itens"][0]["quantidade"], 3)

    def test_nao_ultrapassa_stock(self):
        self.assertEqual(self.adicionar(self.whey, 6).status_code, 409)
        self.adicionar(self.whey, 5)
        self.assertEqual(self.adicionar(self.whey, 1).status_code, 409)

    def test_produto_inativo_ou_inexistente(self):
        inativo = criar_produto("Velho", "10", 5, ativo=False)
        self.assertEqual(self.adicionar(inativo).status_code, 404)
        self.assertEqual(self.client.post(ITENS, {"produto_id": 9999}, format="json").status_code, 404)

    def test_quantidade_invalida(self):
        self.assertEqual(self.client.post(ITENS, {"produto_id": self.whey.id, "quantidade": 0}, format="json").status_code, 400)

    def test_alterar_e_remover_item(self):
        self.adicionar(self.whey)
        r = self.client.patch(f"{ITENS}{self.whey.id}/", {"quantidade": 4}, format="json")
        self.assertEqual(r.data["quantidade"], 4)
        self.assertEqual(self.client.patch(f"{ITENS}{self.whey.id}/", {"quantidade": 9}, format="json").status_code, 409)
        self.assertEqual(self.client.delete(f"{ITENS}{self.whey.id}/").status_code, 204)
        self.assertEqual(self.client.delete(f"{ITENS}{self.whey.id}/").status_code, 404)
        self.assertEqual(self.client.patch(f"{ITENS}{self.whey.id}/", {"quantidade": 1}, format="json").status_code, 404)

    def test_esvaziar(self):
        self.adicionar(self.whey)
        self.assertEqual(self.client.delete(CARRINHO).status_code, 204)
        self.assertEqual(self.client.get(CARRINHO).data["itens"], [])

    def test_carrinhos_sao_por_aluno(self):
        self.adicionar(self.whey)
        self.client.force_authenticate(criar_aluno("outro_cliente").utilizador)
        self.assertEqual(self.client.get(CARRINHO).data["itens"], [])

    def test_so_alunos(self):
        from .test_nutricionista import criar_nutricionista
        self.client.force_authenticate(criar_nutricionista("nutri_loja").utilizador)
        self.assertEqual(self.client.get(CARRINHO).status_code, 403)


class CheckoutTestCase(LojaBase):
    def test_checkout_cria_encomenda_reserva_stock_e_esvazia_carrinho(self):
        self.adicionar(self.whey, 2)
        self.adicionar(self.tshirt, 1)
        r = self.checkout()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["estado"], "pendente_pagamento")
        self.assertEqual(Decimal(r.data["total"]), Decimal("560.00"))
        self.assertEqual(len(r.data["itens"]), 2)
        self.assertEqual(r.data["pagamentos"][0]["estado"], "pendente")
        self.assertEqual(Decimal(r.data["pagamentos"][0]["comissao_plataforma"]), Decimal("0"))
        self.whey.refresh_from_db()
        self.tshirt.refresh_from_db()
        self.assertEqual((self.whey.stock, self.tshirt.stock), (3, 19))
        self.assertEqual(self.client.get(CARRINHO).data["itens"], [])
        self.assertTrue(Notificacao.objects.filter(utilizador=self.aluno.utilizador).exists())

    def test_preco_da_encomenda_e_um_snapshot(self):
        self.adicionar(self.whey)
        enc = self.checkout().data
        Produto.objects.filter(pk=self.whey.pk).update(preco=Decimal("999"), nome="Outro")
        item = Encomenda.objects.get(pk=enc["id"]).itens.get()
        self.assertEqual((item.nome, item.preco_unitario), ("Whey", Decimal("250.00")))

    def test_carrinho_vazio_e_morada_obrigatoria(self):
        self.assertEqual(self.checkout().status_code, 409)
        self.adicionar(self.whey)
        self.assertEqual(self.checkout(morada="  ").status_code, 400)
        self.assertEqual(self.client.post(CHECKOUT, {}, format="json").status_code, 400)

    def test_stock_mudou_entre_carrinho_e_checkout(self):
        self.adicionar(self.whey, 4)
        Produto.objects.filter(pk=self.whey.pk).update(stock=2)
        r = self.checkout()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Encomenda.objects.count(), 0)
        self.assertEqual(len(self.client.get(CARRINHO).data["itens"]), 1)  # carrinho preservado

    def test_produto_desativado_entre_carrinho_e_checkout(self):
        self.adicionar(self.whey)
        Produto.objects.filter(pk=self.whey.pk).update(ativo=False)
        self.assertEqual(self.checkout().status_code, 409)


class PagamentoEncomendaTestCase(LojaBase):
    def setUp(self):
        super().setUp()
        self.adicionar(self.whey, 2)
        self.enc = Encomenda.objects.get(pk=self.checkout().data["id"])
        self.pag = self.enc.pagamentos.get()

    def iniciar(self):
        return self.client.post("/api/v1/payments/", {"encomenda_id": self.enc.id}, format="json")

    def webhook(self, estado, ref):
        corpo = json.dumps({"referencia": ref, "estado": estado}).encode()
        with patch("core.services.multicaixa.config", side_effect=segredo_de_teste):
            return APIClient().post(f"/api/v1/payments/{self.pag.id}/webhook/", corpo,
                                    content_type="application/json", HTTP_X_SIGNATURE=assinar(corpo, SEGREDO))

    def test_iniciar_pagamento_da_encomenda(self):
        r = self.iniciar()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["referencia_multicaixa"].startswith("MOCK-"))
        self.assertEqual(r.data["encomenda"], self.enc.id)
        self.assertEqual(self.iniciar().data["referencia_multicaixa"], r.data["referencia_multicaixa"])

    def test_nao_inicia_encomenda_de_outro(self):
        self.client.force_authenticate(criar_aluno("intruso_loja").utilizador)
        self.assertEqual(self.iniciar().status_code, 404)

    def test_webhook_aprovado_marca_encomenda_paga(self):
        ref = self.iniciar().data["referencia_multicaixa"]
        self.assertEqual(self.webhook("aprovado", ref).status_code, 200)
        self.enc.refresh_from_db()
        self.assertEqual(self.enc.estado, "paga")
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.estado, "aprovado")

    def test_webhook_repetido_nao_duplica(self):
        ref = self.iniciar().data["referencia_multicaixa"]
        self.webhook("aprovado", ref)
        self.assertFalse(self.webhook("aprovado", ref).json()["alterado"])

    def test_webhook_recusado_cancela_encomenda_e_repoe_stock(self):
        ref = self.iniciar().data["referencia_multicaixa"]
        self.assertEqual(self.webhook("recusado", ref).status_code, 200)
        self.enc.refresh_from_db()
        self.whey.refresh_from_db()
        self.assertEqual(self.enc.estado, "cancelada")
        self.assertEqual(self.whey.stock, 5)

    def test_encomenda_paga_nao_se_paga_de_novo(self):
        ref = self.iniciar().data["referencia_multicaixa"]
        self.webhook("aprovado", ref)
        self.assertEqual(self.iniciar().status_code, 409)

    def test_pagamento_de_encomenda_nao_se_liberta(self):  # a libertacao BR-03 so existe para sessoes
        ref = self.iniciar().data["referencia_multicaixa"]
        self.webhook("aprovado", ref)
        r = self.client.post(f"/api/v1/payments/{self.pag.id}/release/")
        self.assertEqual(r.status_code, 403)


class CancelarEncomendaServicoTestCase(LojaBase):
    def test_cancelar_paga_reembolsa_e_repoe_stock(self):
        from .services.loja import cancelar_encomenda
        self.adicionar(self.whey, 2)
        enc = Encomenda.objects.get(pk=self.checkout().data["id"])
        enc.pagamentos.get().transitar("aprovado")
        enc.transitar("paga")
        self.assertTrue(cancelar_encomenda(enc))
        self.assertEqual(enc.pagamentos.get().estado, "reembolsado")
        self.whey.refresh_from_db()
        self.assertEqual(self.whey.stock, 5)

    def test_falha_do_gateway_nao_cancela(self):
        from .services.loja import cancelar_encomenda
        from .services.sessoes import ErroNegocio
        self.adicionar(self.whey)
        enc = Encomenda.objects.get(pk=self.checkout().data["id"])
        enc.pagamentos.get().transitar("aprovado")
        enc.transitar("paga")
        with patch.object(MulticaixaMock, "reembolsar", side_effect=GatewayErro("x")):
            with self.assertRaises(ErroNegocio):
                cancelar_encomenda(enc)
        enc.refresh_from_db()
        self.assertEqual(enc.estado, "paga")


class StockConcorrenteTestCase(TransactionTestCase):
    """Dois checkouts em simultaneo nao podem vender mais do que o stock."""

    def test_ultimo_item_so_e_vendido_uma_vez(self):
        from .services.loja import adicionar_ao_carrinho, checkout
        from .services.sessoes import ErroNegocio
        produto = criar_produto("Raro", "10", 1)
        alunos = [criar_aluno(f"conc{i}") for i in range(2)]
        for a in alunos:
            adicionar_ao_carrinho(a, produto.id, 1)
        resultados = []

        def comprar(aluno):
            try:
                checkout(aluno, "Rua X")
                resultados.append("ok")
            except ErroNegocio:
                resultados.append("recusado")
            finally:
                connection.close()

        threads = [Thread(target=comprar, args=(a,)) for a in alunos]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(resultados), ["ok", "recusado"])
        produto.refresh_from_db()
        self.assertEqual(produto.stock, 0)
