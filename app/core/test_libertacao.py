from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Utilizador
from .services.multicaixa import GatewayErro, MulticaixaMock
from .services.transacoes import libertar_pagamentos_elegiveis
from .test_pagamentos import PagamentoBase


class LibertacaoBase(PagamentoBase):
    def setUp(self):
        super().setUp()
        self.pag.transitar("aprovado", data_aprovacao=timezone.now())
        self.pt_client = APIClient()
        self.pt_client.force_authenticate(self.pt.utilizador)

    def realizar(self, ha_horas=0):
        for acao in ("confirmar", "iniciar", "concluir"):
            r = self.pt_client.patch(f"/api/v1/sessions/{self.sessao.id}/", {"acao": acao}, format="json")
            self.assertEqual(r.status_code, 200, r.data)
        self.sessao.refresh_from_db()
        self.sessao.data_realizacao = timezone.now() - timedelta(hours=ha_horas)
        self.sessao.save()

    def release(self, user=None):
        c = APIClient()
        c.force_authenticate(user or self.aluno.utilizador)
        return c.post(f"/api/v1/payments/{self.pag.id}/release/")


class LibertarManualTestCase(LibertacaoBase):
    def test_aluno_confirma_e_liberta(self):
        self.realizar()
        r = self.release()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["estado"], "libertado")
        self.assertIsNotNone(r.data["data_libertacao"])

    def test_nao_liberta_antes_da_sessao_realizada(self):
        self.assertEqual(self.release().status_code, 409)

    def test_nao_liberta_duas_vezes(self):
        self.realizar()
        self.release()
        self.assertEqual(self.release().status_code, 409)

    def test_pt_nao_se_paga_a_si_proprio(self):
        self.realizar()
        self.assertEqual(self.release(self.pt.utilizador).status_code, 403)

    def test_outro_aluno_nao_liberta(self):
        self.realizar()
        from .test_sessoes import criar_aluno
        self.assertEqual(self.release(criar_aluno("intruso_l").utilizador).status_code, 403)

    def test_nao_liberta_pagamento_pendente(self):
        self.pag.refresh_from_db()
        self.pag.estado = "pendente"
        self.pag.save()
        self.realizar_sem_pagamento = None
        self.assertEqual(self.release().status_code, 409)

    def test_falha_de_transferencia_mantem_aprovado(self):
        self.realizar()
        with patch.object(MulticaixaMock, "transferir_para_pt", side_effect=GatewayErro("x")):
            self.assertEqual(self.release().status_code, 502)
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.estado, "aprovado")


class ReclamacaoTestCase(LibertacaoBase):
    def reclamar(self, motivo="Nao compareceu"):
        c = APIClient()
        c.force_authenticate(self.aluno.utilizador)
        return c.patch(f"/api/v1/sessions/{self.sessao.id}/", {"acao": "reclamar", "motivo": motivo}, format="json")

    def test_reclamacao_bloqueia_libertacao(self):
        self.realizar()
        self.assertEqual(self.reclamar().status_code, 200)
        self.assertEqual(self.release().status_code, 409)

    def test_admin_pode_libertar_apesar_da_reclamacao(self):
        self.realizar()
        self.reclamar()
        admin = Utilizador.objects.create_user(username="adm", password="x", tipo="aluno", is_staff=True, is_active=True)
        self.assertEqual(self.release(admin).status_code, 200)

    def test_so_apos_realizada_e_com_motivo(self):
        self.assertEqual(self.reclamar().status_code, 409)
        self.realizar()
        self.assertEqual(self.reclamar("  ").status_code, 400)


class LibertacaoAutomaticaTestCase(LibertacaoBase):
    def test_liberta_apos_24h_sem_reclamacao(self):
        self.realizar(ha_horas=25)
        self.assertEqual(libertar_pagamentos_elegiveis(), 1)
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.estado, "libertado")

    def test_nao_liberta_antes_de_24h(self):
        self.realizar(ha_horas=23)
        self.assertEqual(libertar_pagamentos_elegiveis(), 0)

    def test_nao_liberta_com_reclamacao(self):
        self.realizar(ha_horas=30)
        self.sessao.reclamacao = "problema"
        self.sessao.save()
        self.assertEqual(libertar_pagamentos_elegiveis(), 0)
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.estado, "aprovado")

    def test_comando_de_gestao(self):
        self.realizar(ha_horas=48)
        out = StringIO()
        call_command("libertar_pagamentos", stdout=out)
        self.assertIn("1 pagamento(s) libertado(s)", out.getvalue())

    def test_falha_num_pagamento_nao_impede_os_restantes(self):
        self.realizar(ha_horas=48)
        with patch.object(MulticaixaMock, "transferir_para_pt", side_effect=GatewayErro("x")):
            self.assertEqual(libertar_pagamentos_elegiveis(), 0)
        self.assertEqual(libertar_pagamentos_elegiveis(), 1)
