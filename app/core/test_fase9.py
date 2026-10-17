"""Fase 9: contingencia para integracoes externas ainda por ativar e robustez no lancamento."""
import os
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from .services.geocoding import GeocodingGoogle
from .services.integracoes import estado_das_integracoes, pronto_para_lancamento
from .services.multicaixa import GatewayErro, MulticaixaMock, MulticaixaReal, obter_gateway
from .test_admin_utilizadores import criar_staff
from .test_creditos_uso import CreditoBase
from .test_ginasios import criar_admin
from .test_seguranca import CHAVE_FORTE, verificar_producao


class GatewayRealNaoImplementadoTestCase(CreditoBase):
    """Com MULTICAIXA_BACKEND=real antes de existir a integracao, os pagamentos falham de forma controlada."""

    def usar_real(self):
        def cfg(chave, default=None, **_):
            return "real" if chave == "MULTICAIXA_BACKEND" else default
        return patch("core.services.multicaixa.config", side_effect=cfg)

    def test_obter_gateway_devolve_o_real(self):
        with self.usar_real():
            self.assertIsInstance(obter_gateway(), MulticaixaReal)

    def test_iniciar_pagamento_devolve_502_e_nao_500(self):
        with self.usar_real():
            r = self.pagar()
        self.assertEqual(r.status_code, 502)
        self.assertIn("Multicaixa", r.data["mensagem"])
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.referencia_multicaixa, "")

    def test_credito_nao_fica_preso_se_o_gateway_falha(self):
        credito = self.dar_credito("2000")
        with self.usar_real():
            self.assertEqual(self.pagar(usar_credito=True).status_code, 502)
        credito.refresh_from_db()
        self.assertEqual(credito.valor_restante, Decimal("2000"))
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.credito_aplicado, 0)

    def test_pagamento_totalmente_coberto_por_credito_nao_precisa_do_gateway(self):
        self.dar_credito("6000")
        with self.usar_real():
            r = self.pagar(usar_credito=True)
        self.assertEqual((r.status_code, r.data["estado"]), (201, "aprovado"))

    def test_todas_as_operacoes_falham_com_gatewayerro(self):
        for metodo in ("iniciar_transacao", "reembolsar", "transferir_para_pt"):
            with self.assertRaises(GatewayErro):
                getattr(MulticaixaReal(), metodo)(self.pag)


class GatewayContratoMixin:
    """Contrato que qualquer implementacao do gateway tem de cumprir. Quando existir MulticaixaReal (contra o
    sandbox oficial), basta criar uma subclasse deste mixin com `criar_gateway`."""

    def criar_gateway(self):
        raise NotImplementedError

    def test_iniciar_transacao_devolve_referencia_unica_nao_vazia(self):
        g = self.criar_gateway()
        refs = {g.iniciar_transacao(self.pag) for _ in range(3)}
        self.assertEqual(len(refs), 3)
        self.assertTrue(all(isinstance(r, str) and r for r in refs))

    def test_reembolso_e_repasse_confirmam_ou_levantam_gatewayerro(self):
        g = self.criar_gateway()
        for metodo in ("reembolsar", "transferir_para_pt"):
            try:
                self.assertTrue(getattr(g, metodo)(self.pag))
            except GatewayErro:
                pass


class ContratoDoMockTestCase(GatewayContratoMixin, CreditoBase):
    def criar_gateway(self):
        return MulticaixaMock()


class GeocodificacaoSemChaveTestCase(TestCase):
    def test_google_nao_implementado_devolve_none_em_vez_de_rebentar(self):
        with self.assertLogs("core.services.geocoding", level="WARNING"):
            self.assertIsNone(GeocodingGoogle().geocodificar("Rua X, Luanda"))

    def test_criar_ginasio_parceiro_com_google_ativo_pede_coordenadas(self):
        client = APIClient()
        client.force_authenticate(criar_admin("geo9"))
        with patch("core.serializers.obter_geocoder", return_value=GeocodingGoogle()):
            r = client.post("/api/v1/gyms/", {"nome": "G", "morada": "Rua X", "estado_parceria": "parceiro"}, format="json")
        self.assertEqual(r.status_code, 400)  # erro de validacao claro, nao 500


class GuardasDeProducaoTestCase(TestCase):
    base = dict(ALLOWED_HOSTS="api.exercita.ao", DJANGO_SECRET_KEY=CHAVE_FORTE)

    def test_gateway_mock_e_recusado_em_producao(self):
        r = verificar_producao(**self.base, MULTICAIXA_BACKEND="mock")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MULTICAIXA_BACKEND=mock", r.stderr)

    def test_gateway_por_omissao_tambem_e_mock(self):
        r = verificar_producao(**self.base, MULTICAIXA_BACKEND="")
        self.assertNotEqual(r.returncode, 0)

    def test_mock_so_com_aceitacao_explicita_para_staging(self):
        r = verificar_producao(**self.base, MULTICAIXA_BACKEND="mock", ALLOW_MOCK_INTEGRATIONS="True")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_gateway_real_exige_segredo_do_webhook(self):
        r = verificar_producao(**self.base, MULTICAIXA_BACKEND="real", MULTICAIXA_WEBHOOK_SECRET="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MULTICAIXA_WEBHOOK_SECRET", r.stderr)


class IntegracoesAdminTestCase(TestCase):
    URL = "/api/v1/admin/integrations/"

    def test_so_admin(self):
        c = APIClient()
        self.assertEqual(c.get(self.URL).status_code, 401)
        from .test_sessoes import criar_aluno
        c.force_authenticate(criar_aluno("int_aluno").utilizador)
        self.assertEqual(c.get(self.URL).status_code, 403)

    def test_lista_integracoes_e_bloqueios(self):
        c = APIClient()
        c.force_authenticate(criar_staff("int_admin"))
        r = c.get(self.URL)
        self.assertEqual(r.status_code, 200)
        dados = r.data["integracoes"]
        for chave in ("multicaixa_express", "google_oauth", "apple_sign_in", "email", "push_fcm_apns",
                      "geocodificacao", "embeddings_matching", "google_calendar", "wearables", "faturacao_certificada"):
            self.assertIn(chave, dados)
            self.assertIn(dados[chave]["estado"], ("ativa", "simulada", "em_falta"))
        self.assertFalse(r.data["pronto_para_lancamento"])  # multicaixa ainda simulada
        self.assertIn("multicaixa_express", r.data["bloqueios"])

    def test_nao_expoe_segredos(self):
        c = APIClient()
        c.force_authenticate(criar_staff("int_admin2"))
        texto = str(c.get(self.URL).data)
        for nome in ("OPENAI_API_KEY", "MULTICAIXA_WEBHOOK_SECRET", "GOOGLE_CLIENT_SECRET", "DJANGO_SECRET_KEY"):
            valor = os.environ.get(nome, "")
            if len(valor) > 6:
                self.assertNotIn(valor, texto)

    def test_so_fica_pronto_com_integracoes_criticas_ativas(self):
        ativo = {"estado": "ativa"}
        estado = {"multicaixa_express": ativo, "email": ativo, "google_oauth": ativo}
        self.assertEqual(pronto_para_lancamento(estado), [])
        estado["email"] = {"estado": "em_falta"}
        self.assertEqual(pronto_para_lancamento(estado), ["email"])

    def test_deteta_configuracao_real(self):
        valores = {"MULTICAIXA_BACKEND": "real", "EMAIL_HOST": "smtp.x.com",
                   "GOOGLE_CLIENT_ID": "abc.apps.googleusercontent.com", "MULTICAIXA_WEBHOOK_SECRET": "s"}
        with patch("core.services.integracoes.config", side_effect=lambda k, default=None, **_: valores.get(k, default)):
            estado = estado_das_integracoes()
        self.assertEqual(estado["email"]["estado"], "ativa")
        self.assertEqual(estado["google_oauth"]["estado"], "ativa")
        self.assertEqual(estado["multicaixa_express"]["estado"], "em_falta")  # real escolhido mas ainda por implementar
