from decimal import Decimal

from rest_framework.test import APIClient

from .models import Encomenda, Notificacao
from .test_carrinho import LojaBase
from .test_ginasios import criar_admin

ORDERS = "/api/v1/shop/orders/"


class EncomendasBase(LojaBase):
    def setUp(self):
        super().setUp()
        self.adicionar(self.whey, 2)
        self.enc = Encomenda.objects.get(pk=self.checkout().data["id"])
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(criar_admin("enc_admin"))

    def pagar(self):
        self.enc.pagamentos.get().transitar("aprovado")
        self.enc.transitar("paga")

    def patch(self, client, **corpo):
        return client.patch(f"{ORDERS}{self.enc.id}/", corpo, format="json")


class ConsultaTestCase(EncomendasBase):
    def test_aluno_ve_as_suas_com_rastreamento(self):
        r = self.client.get(ORDERS)
        self.assertEqual([e["id"] for e in r.data["results"]], [self.enc.id])
        detalhe = self.client.get(f"{ORDERS}{self.enc.id}/").data
        self.assertEqual([e["estado"] for e in detalhe["rastreamento"]], ["pendente_pagamento"])

    def test_aluno_nao_ve_encomendas_alheias(self):
        from .test_sessoes import criar_aluno
        self.client.force_authenticate(criar_aluno("alheio_enc").utilizador)
        self.assertEqual(self.client.get(ORDERS).data["count"], 0)
        self.assertEqual(self.client.get(f"{ORDERS}{self.enc.id}/").status_code, 404)

    def test_admin_ve_todas(self):
        self.assertEqual(self.admin_client.get(ORDERS).data["count"], 1)


class FluxoAdminTestCase(EncomendasBase):
    def test_fluxo_completo_com_rastreamento(self):
        self.pagar()
        self.assertEqual(self.patch(self.admin_client, acao="preparar").data["estado"], "em_preparacao")
        r = self.patch(self.admin_client, acao="enviar", codigo_rastreio="AO123456")
        self.assertEqual(r.data["estado"], "enviada")
        self.assertEqual(r.data["codigo_rastreio"], "AO123456")
        self.assertIsNotNone(r.data["data_envio"])
        r = self.patch(self.admin_client, acao="entregar")
        self.assertEqual(r.data["estado"], "entregue")
        self.assertIsNotNone(r.data["data_entrega"])
        self.assertEqual([e["estado"] for e in r.data["rastreamento"]],
                         ["pendente_pagamento", "paga", "em_preparacao", "enviada", "entregue"])

    def test_cada_passo_notifica_o_aluno(self):
        self.pagar()
        Notificacao.objects.all().delete()
        self.patch(self.admin_client, acao="preparar")
        self.assertTrue(Notificacao.objects.filter(utilizador=self.aluno.utilizador).exists())

    def test_enviar_exige_codigo_de_rastreio(self):
        self.pagar()
        self.patch(self.admin_client, acao="preparar")
        self.assertEqual(self.patch(self.admin_client, acao="enviar").status_code, 400)
        self.assertEqual(self.patch(self.admin_client, acao="enviar", codigo_rastreio="  ").status_code, 400)

    def test_nao_salta_estados(self):
        self.assertEqual(self.patch(self.admin_client, acao="preparar").status_code, 409)  # ainda nao paga
        self.pagar()
        self.assertEqual(self.patch(self.admin_client, acao="entregar").status_code, 409)
        self.assertEqual(self.patch(self.admin_client, acao="enviar", codigo_rastreio="X").status_code, 409)

    def test_aluno_nao_avanca_encomenda(self):
        self.pagar()
        for acao in ("preparar", "enviar", "entregar"):
            self.assertEqual(self.patch(self.client, acao=acao, codigo_rastreio="X").status_code, 403)

    def test_acao_invalida(self):
        self.assertEqual(self.patch(self.admin_client, acao="apagar").status_code, 400)

    def test_put_nao_permitido(self):
        self.assertEqual(self.client.put(f"{ORDERS}{self.enc.id}/", {"acao": "cancelar"}, format="json").status_code, 405)


class CancelamentoTestCase(EncomendasBase):
    def test_aluno_cancela_pendente_repoe_stock(self):
        r = self.patch(self.client, acao="cancelar")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["estado"], "cancelada")
        self.assertFalse(r.data["reembolsado"])
        self.whey.refresh_from_db()
        self.assertEqual(self.whey.stock, 5)
        self.assertEqual(self.enc.pagamentos.get().estado, "recusado")

    def test_aluno_cancela_paga_e_e_reembolsado(self):
        self.pagar()
        r = self.patch(self.client, acao="cancelar")
        self.assertTrue(r.data["reembolsado"])
        self.assertEqual(self.enc.pagamentos.get().estado, "reembolsado")

    def test_cancelar_em_preparacao_permitido_mas_nao_depois_de_enviada(self):
        self.pagar()
        self.patch(self.admin_client, acao="preparar")
        self.patch(self.admin_client, acao="enviar", codigo_rastreio="X")
        self.assertEqual(self.patch(self.client, acao="cancelar").status_code, 409)

    def test_nao_cancela_duas_vezes(self):
        self.patch(self.client, acao="cancelar")
        self.assertEqual(self.patch(self.client, acao="cancelar").status_code, 409)

    def test_cancelamento_regista_evento(self):
        r = self.patch(self.client, acao="cancelar")
        self.assertEqual(r.data["rastreamento"][-1]["estado"], "cancelada")

    def test_total_nao_muda(self):
        self.assertEqual(Decimal(self.patch(self.client, acao="cancelar").data["total"]), Decimal("500.00"))
