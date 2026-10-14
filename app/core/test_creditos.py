from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone
from rest_framework.test import APIClient

from .models import CreditoAluno, Notificacao
from .services import creditos
from .test_libertacao import LibertacaoBase

CREDITOS = "/api/v1/credits/"


class CreditoPorCancelamentoTardioTestCase(LibertacaoBase):
    """LibertacaoBase: sessao de 5000 Kz, ja com pagamento aprovado."""

    def cancelar_tarde(self, user=None):
        self.sessao.data_hora = timezone.now() + timedelta(hours=5)  # dentro das 24h
        self.sessao.save()
        c = APIClient()
        c.force_authenticate(user or self.aluno.utilizador)
        return c.patch(f"/api/v1/sessions/{self.sessao.id}/", {"acao": "cancelar"}, format="json")

    def test_valor_retido_converte_se_em_credito_de_90_dias(self):
        r = self.cancelar_tarde()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["reembolsado"])
        self.assertEqual(Decimal(r.data["credito_gerado"]["valor"]), Decimal("5000.00"))
        credito = CreditoAluno.objects.get()
        self.assertEqual((credito.aluno, credito.valor, credito.valor_restante), (self.aluno, Decimal("5000.00"), Decimal("5000.00")))
        self.assertEqual(credito.origem, "cancelamento_tardio")
        dias = (credito.data_expiracao - timezone.now()).total_seconds() / 86400
        self.assertTrue(89.9 < dias <= 90, dias)

    def test_pagamento_continua_retido_nao_reembolsado_nem_libertado(self):
        self.cancelar_tarde()
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.estado, "aprovado")
        self.assertTrue(self.pag.convertido_em_credito)

    def test_aluno_e_notificado(self):
        Notificacao.objects.all().delete()
        self.cancelar_tarde()
        self.assertTrue(Notificacao.objects.filter(utilizador=self.aluno.utilizador, mensagem__contains="credito").exists())

    def test_cancelamento_com_antecedencia_continua_a_reembolsar_sem_credito(self):
        c = APIClient()
        c.force_authenticate(self.aluno.utilizador)
        r = c.patch(f"/api/v1/sessions/{self.sessao.id}/", {"acao": "cancelar"}, format="json")
        self.assertTrue(r.data["reembolsado"])
        self.assertNotIn("credito_gerado", r.data)
        self.assertEqual(CreditoAluno.objects.count(), 0)

    def test_cancelamento_pelo_pt_reembolsa_e_nao_gera_credito(self):
        r = self.cancelar_tarde(self.pt.utilizador)
        self.assertTrue(r.data["reembolsado"])
        self.assertEqual(CreditoAluno.objects.count(), 0)

    def test_so_gera_credito_uma_vez(self):
        self.cancelar_tarde()
        creditos.gerar_credito_cancelamento(self.pag)
        self.assertEqual(CreditoAluno.objects.count(), 1)

    def test_validade_configuravel(self):
        with patch("core.services.creditos.config", return_value="30"):
            self.cancelar_tarde()
        dias = (CreditoAluno.objects.get().data_expiracao - timezone.now()).days
        self.assertIn(dias, (28, 29))

    def test_pagamento_retido_nao_e_libertado_ao_pt(self):
        self.cancelar_tarde()
        from .services.transacoes import libertar_pagamentos_elegiveis
        self.assertEqual(libertar_pagamentos_elegiveis(), 0)  # sessao cancelada: nao e elegivel


class SaldoDeCreditosTestCase(LibertacaoBase):
    def setUp(self):
        super().setUp()
        self.c = APIClient()
        self.c.force_authenticate(self.aluno.utilizador)

    def novo(self, valor, dias, restante=None):
        return CreditoAluno.objects.create(
            aluno=self.aluno, origem="cancelamento_tardio", valor=Decimal(valor),
            valor_restante=Decimal(restante if restante is not None else valor),
            data_expiracao=timezone.now() + timedelta(days=dias))

    def test_saldo_so_conta_creditos_validos_com_saldo(self):
        self.novo("1000", 10)
        self.novo("2000", 40)
        self.novo("500", -1)            # expirado
        self.novo("700", 20, "0")       # ja gasto
        self.assertEqual(creditos.saldo(self.aluno), Decimal("3000"))

    def test_endpoint_devolve_saldo_proxima_expiracao_e_historico(self):
        self.novo("1000", 10)
        self.novo("2000", 40)
        expirado = self.novo("500", -1)
        r = self.c.get(CREDITOS)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Decimal(str(r.data["saldo"])), Decimal("3000"))
        self.assertEqual(len(r.data["creditos"]), 3)
        self.assertTrue(next(c for c in r.data["creditos"] if c["id"] == expirado.id)["expirado"])
        self.assertIsNotNone(r.data["proxima_expiracao"])

    def test_sem_creditos(self):
        r = self.c.get(CREDITOS)
        self.assertEqual((Decimal(str(r.data["saldo"])), r.data["proxima_expiracao"], r.data["creditos"]),
                         (Decimal("0"), None, []))

    def test_isolamento_e_permissoes(self):
        self.novo("1000", 10)
        self.c.force_authenticate(self.pt.utilizador)
        self.assertEqual(self.c.get(CREDITOS).status_code, 403)
        from .test_sessoes import criar_aluno
        self.c.force_authenticate(criar_aluno("outro_credito").utilizador)
        self.assertEqual(Decimal(str(self.c.get(CREDITOS).data["saldo"])), Decimal("0"))
        self.assertEqual(APIClient().get(CREDITOS).status_code, 401)
