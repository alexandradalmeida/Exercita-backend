from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Avaliacao, Notificacao, PersonalTrainer, Utilizador
from .services.avaliacoes import avaliar_qualidade, recalcular_reputacao
from .test_marketplace import criar_avaliacao, criar_pt

E = PersonalTrainer.EstadoVerificacao


def dar_notas(pt, notas):
    for nota in notas:
        criar_avaliacao(pt, nota)
    pt.refresh_from_db()
    return avaliar_qualidade(pt)


class DistribuicoesTestCase(TestCase):
    """BR-02 com limiares por omissao: alerta < 4.0, suspensao < 3.0, minimo de 5 avaliacoes."""

    def setUp(self):
        self.pt = criar_pt("ptq")

    def test_abaixo_do_minimo_nunca_muda(self):
        self.assertIsNone(dar_notas(self.pt, [1, 1, 1, 1]))
        self.assertEqual(self.pt.estado_verificacao, E.VERIFICADO)

    def test_media_boa_mantem_verificado(self):
        self.assertIsNone(dar_notas(self.pt, [5, 4, 4, 5, 4]))

    def test_media_exatamente_no_limiar_de_alerta_nao_alerta(self):
        self.assertIsNone(dar_notas(self.pt, [4, 4, 4, 4, 4]))

    def test_media_abaixo_de_4_entra_em_alerta(self):
        self.assertEqual(dar_notas(self.pt, [4, 4, 4, 3, 4]), E.EM_ALERTA)  # 3.8
        self.assertEqual(self.pt.estado_verificacao, E.EM_ALERTA)

    def test_media_exatamente_3_fica_so_em_alerta(self):
        self.assertEqual(dar_notas(self.pt, [3, 3, 3, 3, 3]), E.EM_ALERTA)

    def test_media_abaixo_de_3_suspende(self):
        self.assertEqual(dar_notas(self.pt, [1, 2, 3, 3, 3]), E.SUSPENSO)  # 2.4

    def test_alerta_recupera_sozinho(self):
        dar_notas(self.pt, [3, 3, 3, 3, 3])
        self.assertEqual(self.pt.estado_verificacao, E.EM_ALERTA)
        self.assertEqual(dar_notas(self.pt, [5, 5, 5, 5, 5]), E.VERIFICADO)  # media 4.0

    def test_alerta_pode_agravar_para_suspenso(self):
        dar_notas(self.pt, [3, 4, 4, 4, 4])
        self.assertEqual(self.pt.estado_verificacao, E.EM_ALERTA)
        self.assertEqual(dar_notas(self.pt, [1, 1, 1, 1, 1, 1]), E.SUSPENSO)

    def test_suspenso_nao_recupera_sozinho(self):
        dar_notas(self.pt, [1, 1, 1, 1, 1])
        self.assertIsNone(dar_notas(self.pt, [5] * 30))
        self.assertEqual(self.pt.estado_verificacao, E.SUSPENSO)

    def test_pendente_nao_e_avaliado(self):
        pt = criar_pt("ptpend", verificado=False)
        self.assertIsNone(dar_notas(pt, [1] * 6))
        self.assertEqual(pt.estado_verificacao, E.PENDENTE)

    @patch("core.services.avaliacoes.config", side_effect=lambda k, default=None: {
        "QUALITY_ALERT_THRESHOLD": "4.5", "QUALITY_SUSPEND_THRESHOLD": "4.0", "QUALITY_MIN_REVIEWS": "2"}[k])
    def test_limiares_configuraveis(self, _):
        self.assertEqual(dar_notas(self.pt, [4, 3]), E.SUSPENSO)


class ConsequenciasTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = Utilizador.objects.create_user(username="busca", password="x", tipo="aluno", is_active=True)
        self.client.force_authenticate(self.aluno)

    def test_em_alerta_continua_visivel_e_operacional(self):
        pt = criar_pt("alerta")
        dar_notas(pt, [3, 3, 3, 3, 3])
        ids = [x["id"] for x in self.client.get("/api/v1/trainers/").data["results"]]
        self.assertIn(pt.id, ids)
        self.client.force_authenticate(pt.utilizador)
        r = self.client.post("/api/v1/perfil/personal-trainer/certificacoes/", {"nome": "X"}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_suspenso_desaparece_e_nao_publica(self):
        pt = criar_pt("susp")
        dar_notas(pt, [1, 1, 1, 1, 1])
        ids = [x["id"] for x in self.client.get("/api/v1/trainers/").data["results"]]
        self.assertNotIn(pt.id, ids)
        self.assertEqual(self.client.get(f"/api/v1/trainers/{pt.id}/profile/").status_code, 404)
        self.client.force_authenticate(pt.utilizador)
        r = self.client.post("/api/v1/perfil/personal-trainer/certificacoes/", {"nome": "X"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_mudanca_de_estado_notifica_o_pt(self):
        pt = criar_pt("notif")
        dar_notas(pt, [1, 1, 1, 1, 1])
        self.assertTrue(Notificacao.objects.filter(utilizador=pt.utilizador, mensagem__contains="suspenso").exists())


class AdminReativacaoTestCase(TestCase):
    def setUp(self):
        self.admin = Utilizador.objects.create_user(
            username="admq", password="x", tipo="aluno", is_staff=True, is_active=True)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.pt = criar_pt("reativar")
        dar_notas(self.pt, [1, 1, 1, 1, 1])

    def reativar(self, pt=None):
        return self.client.post(f"/api/v1/personal-trainers/{(pt or self.pt).id}/reativar/")

    def test_admin_reativa_e_historico_deixa_de_contar(self):
        self.assertEqual(self.reativar().status_code, 200)
        self.pt.refresh_from_db()
        self.assertEqual(self.pt.estado_verificacao, E.VERIFICADO)
        # as 5 avaliacoes antigas ja nao contam: so novas avaliacoes decidem
        self.assertIsNone(avaliar_qualidade(self.pt))
        self.assertIsNone(dar_notas(self.pt, [5, 5, 5, 5]))  # abaixo do minimo desde a reativacao
        self.assertEqual(self.pt.estado_verificacao, E.VERIFICADO)

    def test_pode_voltar_a_ser_suspenso_por_novas_avaliacoes(self):
        self.reativar()
        self.pt.refresh_from_db()
        Avaliacao.objects.all().update(data_criacao=timezone.now() - timedelta(days=1))
        self.assertEqual(dar_notas(self.pt, [1, 1, 1, 1, 1]), E.SUSPENSO)

    def test_so_se_estiver_suspenso(self):
        outro = criar_pt("naosusp")
        self.assertEqual(self.reativar(outro).status_code, 409)

    def test_so_admin(self):
        self.client.force_authenticate(Utilizador.objects.create_user(username="norm", password="x", tipo="aluno", is_active=True))
        self.assertEqual(self.reativar().status_code, 403)

    def test_verificar_nao_levanta_suspensao(self):
        r = self.client.post(f"/api/v1/personal-trainers/{self.pt.id}/verificar/")
        self.assertEqual(r.status_code, 409)


class IntegracaoComEndpointTestCase(__import__("core.test_avaliacoes", fromlist=["AvaliacaoBase"]).AvaliacaoBase):
    def test_avaliacao_pelo_endpoint_dispara_suspensao(self):
        for _ in range(4):
            criar_avaliacao(self.pt, 1)
        self.realizar()
        self.assertEqual(self.avaliar(self.aluno.utilizador, 1).status_code, 201)
        self.pt.refresh_from_db()
        self.assertEqual(self.pt.estado_verificacao, E.SUSPENSO)
