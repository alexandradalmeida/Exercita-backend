import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from .models import CreditoAluno, DocumentoFinanceiro, Notificacao
from .services import creditos
from .services.multicaixa import MulticaixaMock, assinar
from .test_admin_utilizadores import criar_staff
from .test_pagamentos import SEGREDO, PagamentoBase, segredo_de_teste


class CreditoBase(PagamentoBase):
    """PagamentoBase: sessao de 5000 Kz, pagamento pendente, aluno 'pagador'."""

    def dar_credito(self, valor, dias=30, origem="cancelamento_tardio"):
        return CreditoAluno.objects.create(
            aluno=self.aluno, origem=origem, valor=Decimal(valor), valor_restante=Decimal(valor),
            data_expiracao=timezone.now() + timedelta(days=dias))

    def pagar(self, **extra):
        return self.client.post("/api/v1/payments/", {"sessao_id": self.sessao.id, **extra}, format="json")

    def webhook(self, estado, ref):
        corpo = json.dumps({"referencia": ref, "estado": estado}).encode()
        with patch("core.services.multicaixa.config", side_effect=segredo_de_teste):
            return APIClient().post(f"/api/v1/payments/{self.pag.id}/webhook/", corpo,
                                    content_type="application/json", HTTP_X_SIGNATURE=assinar(corpo, SEGREDO))

    def cancelar(self, tarde=False):
        if tarde:
            self.sessao.data_hora = timezone.now() + timedelta(hours=3)
            self.sessao.save()
        return self.client.patch(f"/api/v1/sessions/{self.sessao.id}/", {"acao": "cancelar"}, format="json")


class UsarCreditoTestCase(CreditoBase):
    def test_credito_parcial_reduz_o_que_o_gateway_cobra(self):
        c = self.dar_credito("2000")
        r = self.pagar(usar_credito=True)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data["credito_aplicado"]), Decimal("2000"))
        self.assertEqual(Decimal(r.data["valor_a_pagar"]), Decimal("3000"))
        self.assertTrue(r.data["referencia_multicaixa"].startswith("MOCK-"))
        self.assertEqual(r.data["estado"], "pendente")
        c.refresh_from_db()
        self.assertEqual(c.valor_restante, Decimal("0"))

    def test_credito_total_aprova_sem_gateway_e_emite_documentos(self):
        c = self.dar_credito("6000")
        with patch.object(MulticaixaMock, "iniciar_transacao") as gateway:
            r = self.pagar(usar_credito=True)
        gateway.assert_not_called()
        self.assertEqual((r.status_code, r.data["estado"], r.data["referencia_multicaixa"]), (201, "aprovado", "CREDITO"))
        self.assertEqual(Decimal(r.data["valor_a_pagar"]), Decimal("0"))
        c.refresh_from_db()
        self.assertEqual(c.valor_restante, Decimal("1000"))
        self.assertEqual(DocumentoFinanceiro.objects.filter(pagamento=self.pag).count(), 2)
        self.assertTrue(Notificacao.objects.filter(utilizador=self.pt.utilizador, mensagem__contains="aprovado").exists())

    def test_sem_a_opcao_o_credito_nao_e_usado(self):
        c = self.dar_credito("6000")
        r = self.pagar()
        self.assertEqual(Decimal(r.data["credito_aplicado"]), Decimal("0"))
        c.refresh_from_db()
        self.assertEqual(c.valor_restante, Decimal("6000"))

    def test_usa_primeiro_o_credito_que_expira_mais_cedo(self):
        tarde = self.dar_credito("3000", dias=60)
        cedo = self.dar_credito("3000", dias=5)
        self.pagar(usar_credito=True)
        cedo.refresh_from_db()
        tarde.refresh_from_db()
        self.assertEqual((cedo.valor_restante, tarde.valor_restante), (Decimal("0"), Decimal("1000")))

    def test_ignora_creditos_expirados(self):
        self.dar_credito("5000", dias=-1)
        r = self.pagar(usar_credito=True)
        self.assertEqual(Decimal(r.data["credito_aplicado"]), Decimal("0"))
        self.assertEqual(Decimal(r.data["valor_a_pagar"]), Decimal("5000"))

    def test_pedir_duas_vezes_nao_gasta_credito_a_dobrar(self):
        self.dar_credito("2000")
        self.dar_credito("2000")
        self.pagar(usar_credito=True)
        r = self.pagar(usar_credito=True)
        self.assertEqual(Decimal(r.data["credito_aplicado"]), Decimal("4000"))
        self.assertEqual(creditos.saldo(self.aluno), Decimal("0"))

    def test_nao_se_acrescenta_credito_a_uma_referencia_ja_emitida(self):
        self.pagar()
        self.dar_credito("1000")
        self.assertEqual(self.pagar(usar_credito=True).status_code, 409)
        self.assertEqual(creditos.saldo(self.aluno), Decimal("1000"))

    def test_credito_nao_cobre_o_valor_de_outro_aluno(self):
        from .test_sessoes import criar_aluno
        outro = criar_aluno("outro_cred")
        CreditoAluno.objects.create(aluno=outro, origem="cancelamento_tardio", valor=Decimal("9999"),
                                    valor_restante=Decimal("9999"), data_expiracao=timezone.now() + timedelta(days=9))
        r = self.pagar(usar_credito=True)
        self.assertEqual(Decimal(r.data["credito_aplicado"]), Decimal("0"))


class ReporCreditoTestCase(CreditoBase):
    def test_pagamento_recusado_repoe_o_credito(self):
        c = self.dar_credito("2000")
        ref = self.pagar(usar_credito=True).data["referencia_multicaixa"]
        self.assertEqual(self.webhook("recusado", ref).status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.valor_restante, Decimal("2000"))

    def test_cancelar_antes_de_pagar_repoe_o_credito(self):
        c = self.dar_credito("2000")
        self.pagar(usar_credito=True)
        self.cancelar()
        c.refresh_from_db()
        self.assertEqual(c.valor_restante, Decimal("2000"))

    def test_cancelar_com_antecedencia_um_pagamento_misto_estorna_so_o_dinheiro_e_repoe_o_credito(self):
        c = self.dar_credito("2000")
        ref = self.pagar(usar_credito=True).data["referencia_multicaixa"]
        self.webhook("aprovado", ref)
        with patch.object(MulticaixaMock, "reembolsar") as estorno:
            r = self.cancelar()
        estorno.assert_called_once()
        self.assertTrue(r.data["reembolsado"])
        c.refresh_from_db()
        self.assertEqual(c.valor_restante, Decimal("2000"))

    def test_cancelar_um_pagamento_so_com_credito_nao_chama_o_gateway(self):
        c = self.dar_credito("6000")
        self.pagar(usar_credito=True)
        with patch.object(MulticaixaMock, "reembolsar") as estorno:
            r = self.cancelar()
        estorno.assert_not_called()
        self.assertTrue(r.data["reembolsado"])
        c.refresh_from_db()
        self.assertEqual(c.valor_restante, Decimal("6000"))

    def test_credito_original_expirado_na_reposicao_gera_credito_novo(self):
        c = self.dar_credito("2000", dias=1)
        self.pagar(usar_credito=True)
        CreditoAluno.objects.filter(pk=c.pk).update(data_expiracao=timezone.now() - timedelta(hours=1))
        self.cancelar()
        novo = CreditoAluno.objects.exclude(pk=c.pk).get()
        self.assertEqual((novo.origem, novo.valor_restante), ("estorno", Decimal("2000")))
        self.assertGreater((novo.data_expiracao - timezone.now()).days, 88)

    def test_cancelamento_tardio_de_sessao_paga_com_credito_gera_credito_do_valor_total(self):
        self.dar_credito("2000")
        ref = self.pagar(usar_credito=True).data["referencia_multicaixa"]
        self.webhook("aprovado", ref)
        r = self.cancelar(tarde=True)
        self.assertFalse(r.data["reembolsado"])
        self.assertEqual(Decimal(r.data["credito_gerado"]["valor"]), Decimal("5000"))
        self.assertEqual(creditos.saldo(self.aluno), Decimal("5000"))

    def test_nao_se_repoe_duas_vezes(self):
        c = self.dar_credito("2000")
        self.pagar(usar_credito=True)
        creditos.restituir_creditos(self.pag)
        creditos.restituir_creditos(self.pag)
        c.refresh_from_db()
        self.assertEqual(c.valor_restante, Decimal("2000"))


class CicloCompletoTestCase(CreditoBase):
    def test_cancelamento_tardio_depois_credito_paga_nova_sessao(self):
        """O fluxo pedido: valor retido -> credito 90 dias -> usado para pagar outra sessao."""
        from .services.sessoes import contratar_personal_trainer
        from .test_contratar import proxima_data
        ref = self.pagar().data["referencia_multicaixa"]
        self.webhook("aprovado", ref)
        self.cancelar(tarde=True)
        self.assertEqual(creditos.saldo(self.aluno), Decimal("5000"))

        sessao2, pag2 = contratar_personal_trainer(
            self.aluno, self.pt, self.slot, proxima_data(2) + timedelta(weeks=3), "individual")
        r = self.client.post("/api/v1/payments/", {"sessao_id": sessao2.id, "usar_credito": True}, format="json")
        self.assertEqual((r.data["estado"], r.data["referencia_multicaixa"]), ("aprovado", "CREDITO"))
        self.assertEqual(creditos.saldo(self.aluno), Decimal("0"))
        self.assertEqual(self.client.get("/api/v1/credits/").data["creditos"][0]["valor_restante"], "0.00")


class CreditoNaLojaTestCase(CreditoBase):
    def test_credito_paga_encomenda(self):
        from .services.loja import adicionar_ao_carrinho, checkout
        from .test_loja import criar_produto
        produto = criar_produto("Whey", "1500.00", 5)
        adicionar_ao_carrinho(self.aluno, produto.id, 2)
        enc = checkout(self.aluno, "Rua X")
        c = self.dar_credito("3000")
        r = self.client.post("/api/v1/payments/", {"encomenda_id": enc.id, "usar_credito": True}, format="json")
        self.assertEqual((r.status_code, r.data["estado"]), (201, "aprovado"))
        enc.refresh_from_db()
        self.assertEqual(enc.estado, "paga")
        c.refresh_from_db()
        self.assertEqual(c.valor_restante, Decimal("0"))

    def test_cancelar_encomenda_paga_com_credito_repoe_o_credito(self):
        from .services.loja import adicionar_ao_carrinho, cancelar_encomenda, checkout
        from .test_loja import criar_produto
        produto = criar_produto("Whey", "1500.00", 5)
        adicionar_ao_carrinho(self.aluno, produto.id, 2)
        enc = checkout(self.aluno, "Rua X")
        c = self.dar_credito("3000")
        self.client.post("/api/v1/payments/", {"encomenda_id": enc.id, "usar_credito": True}, format="json")
        with patch.object(MulticaixaMock, "reembolsar") as estorno:
            cancelar_encomenda(enc)
        estorno.assert_not_called()
        c.refresh_from_db()
        self.assertEqual(c.valor_restante, Decimal("3000"))


class RelatoriosEAvisosTestCase(CreditoBase):
    def test_pagamento_convertido_em_credito_nao_conta_como_receita_mas_e_divida(self):
        ref = self.pagar().data["referencia_multicaixa"]
        self.webhook("aprovado", ref)
        self.cancelar(tarde=True)
        admin = APIClient()
        admin.force_authenticate(criar_staff("cred_admin"))
        receita = admin.get("/api/v1/admin/reports/platform/").data["receita"]
        self.assertEqual(Decimal(str(receita["comissoes_plataforma"])), Decimal("0"))
        self.assertEqual(Decimal(str(receita["credito_em_aberto"])), Decimal("5000"))

    def test_csv_tem_colunas_de_credito(self):
        ref = self.pagar().data["referencia_multicaixa"]
        self.webhook("aprovado", ref)
        self.cancelar(tarde=True)
        admin = APIClient()
        admin.force_authenticate(criar_staff("cred_admin2"))
        cabecalho = admin.get("/api/v1/admin/reports/financial/").content.decode("utf-8-sig").splitlines()[0]
        self.assertIn("credito_aplicado", cabecalho)
        self.assertIn("convertido_em_credito", cabecalho)

    def test_aviso_de_expiracao_enviado_uma_vez(self):
        self.dar_credito("1000", dias=3)
        self.dar_credito("1000", dias=40)
        Notificacao.objects.all().delete()
        self.assertEqual(creditos.expirar_e_avisar(), (1, 0))
        self.assertTrue(Notificacao.objects.filter(utilizador=self.aluno.utilizador, mensagem__contains="expira").exists())
        self.assertEqual(creditos.expirar_e_avisar(), (0, 0))

    def test_comando_de_gestao(self):
        self.dar_credito("1000", dias=2)
        out = StringIO()
        call_command("avisar_creditos", stdout=out)
        self.assertIn("1 aviso(s) enviado(s)", out.getvalue())
