import json
from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import SlotDisponibilidade
from .services.multicaixa import GatewayErro, MulticaixaMock, assinar
from .services.sessoes import contratar_personal_trainer
from .test_contratar import proxima_data
from .test_marketplace import criar_pt
from .test_sessoes import criar_aluno

SEGREDO = "segredo-de-teste"


def segredo_de_teste(chave, default=""):
    return SEGREDO if chave == "MULTICAIXA_WEBHOOK_SECRET" else default


class PagamentoBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("pagador")
        self.pt = criar_pt("ptpag", preco_hora=Decimal("5000"))
        self.slot = SlotDisponibilidade.objects.create(
            personal_trainer=self.pt, dia_semana=2, hora_inicio=time(8), hora_fim=time(9), capacidade=2)
        self.sessao, self.pag = contratar_personal_trainer(
            self.aluno, self.pt, self.slot, proxima_data(2) + timedelta(weeks=1), "individual")
        self.client.force_authenticate(self.aluno.utilizador)

    def iniciar(self):
        return self.client.post("/api/v1/payments/", {"sessao_id": self.sessao.id}, format="json")

    def webhook(self, corpo, assinatura="auto", pk=None):
        dados = json.dumps(corpo).encode()
        if assinatura == "auto":
            assinatura = assinar(dados, SEGREDO)
        headers = {"HTTP_X_SIGNATURE": assinatura} if assinatura else {}
        return APIClient().post(f"/api/v1/payments/{pk or self.pag.id}/webhook/", dados,
                                content_type="application/json", **headers)


class IniciarPagamentoTestCase(PagamentoBase):
    def test_inicia_e_devolve_referencia(self):
        r = self.iniciar()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["referencia_multicaixa"].startswith("MOCK-"))
        self.assertEqual(r.data["estado"], "pendente")

    def test_idempotente(self):
        ref1 = self.iniciar().data["referencia_multicaixa"]
        self.assertEqual(self.iniciar().data["referencia_multicaixa"], ref1)

    def test_nao_inicia_sessao_de_outro_aluno(self):
        self.client.force_authenticate(criar_aluno("outro_p").utilizador)
        self.assertEqual(self.iniciar().status_code, 404)

    def test_sessao_cancelada_nao_se_paga(self):
        self.sessao.transitar("cancelada")
        self.assertEqual(self.iniciar().status_code, 409)

    def test_pt_nao_inicia(self):
        self.client.force_authenticate(self.pt.utilizador)
        self.assertEqual(self.iniciar().status_code, 403)


@patch("core.services.multicaixa.config", side_effect=segredo_de_teste)
class WebhookTestCase(PagamentoBase):
    def setUp(self):
        super().setUp()
        self.ref = self.iniciar().data["referencia_multicaixa"]

    def test_aprova_pagamento(self, _):
        r = self.webhook({"referencia": self.ref, "estado": "aprovado"})
        self.assertEqual(r.status_code, 200, r.content)
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.estado, "aprovado")
        self.assertIsNotNone(self.pag.data_aprovacao)

    def test_recusa_pagamento(self, _):
        self.webhook({"referencia": self.ref, "estado": "recusado"})
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.estado, "recusado")

    def test_callback_repetido_e_idempotente(self, _):
        self.webhook({"referencia": self.ref, "estado": "aprovado"})
        r = self.webhook({"referencia": self.ref, "estado": "aprovado"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["alterado"])

    def test_resultado_contraditorio_recusado(self, _):
        self.webhook({"referencia": self.ref, "estado": "aprovado"})
        self.assertEqual(self.webhook({"referencia": self.ref, "estado": "recusado"}).status_code, 409)

    def test_assinatura_invalida_ou_ausente(self, _):
        corpo = {"referencia": self.ref, "estado": "aprovado"}
        self.assertEqual(self.webhook(corpo, assinatura="errada").status_code, 401)
        self.assertEqual(self.webhook(corpo, assinatura="").status_code, 401)
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.estado, "pendente")

    def test_referencia_errada(self, _):
        self.assertEqual(self.webhook({"referencia": "OUTRA", "estado": "aprovado"}).status_code, 400)

    def test_estado_invalido(self, _):
        self.assertEqual(self.webhook({"referencia": self.ref, "estado": "libertado"}).status_code, 400)

    def test_pagamento_inexistente(self, _):
        self.assertEqual(self.webhook({"referencia": self.ref, "estado": "aprovado"}, pk=99999).status_code, 404)


class WebhookSemSegredoTestCase(PagamentoBase):
    def test_sem_segredo_configurado_rejeita_tudo(self):
        dados = json.dumps({"referencia": "x", "estado": "aprovado"}).encode()
        r = APIClient().post(f"/api/v1/payments/{self.pag.id}/webhook/", dados,
                             content_type="application/json", HTTP_X_SIGNATURE=assinar(dados, ""))
        self.assertEqual(r.status_code, 401)


class ReembolsoGatewayTestCase(PagamentoBase):
    def test_falha_do_gateway_nao_cancela_sessao(self):
        self.pag.transitar("aprovado")
        with patch.object(MulticaixaMock, "reembolsar", side_effect=GatewayErro("falhou")):
            r = APIClient()
            r.force_authenticate(self.aluno.utilizador)
            resp = r.patch(f"/api/v1/sessions/{self.sessao.id}/", {"acao": "cancelar"}, format="json")
        self.assertEqual(resp.status_code, 502)
        self.sessao.refresh_from_db()
        self.pag.refresh_from_db()
        self.assertEqual(self.sessao.estado, "agendada")
        self.assertEqual(self.pag.estado, "aprovado")
