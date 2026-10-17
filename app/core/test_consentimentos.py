import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import ConsentimentoDados, HistoricoTreino, MetricaFisica, PlanoNutricional, RegistoRefeicao, Utilizador
from .services import consentimentos
from .test_marketplace import criar_pt
from .test_nutricionista import criar_nutricionista
from .test_sessoes import criar_aluno, dar_consentimento

CONSENTIMENTO = "/api/v1/consents/health/"
SENHA = "SenhaForte123!"


def hoje():
    return timezone.localdate().isoformat()


class ConcederConsentimentoTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("cons_aluno")
        self.client.force_authenticate(self.aluno.utilizador)

    def conceder(self, **corpo):
        return self.client.post(CONSENTIMENTO, {"versao": consentimentos.versao_atual(), "aceito": True, **corpo}, format="json")

    def test_get_mostra_texto_versao_e_estado(self):
        r = self.client.get(CONSENTIMENTO)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["versao"], "1.0")
        self.assertIn("dados de saúde", r.data["texto"])
        self.assertFalse(r.data["consentido"])
        self.assertEqual(r.data["historico"], [])

    def test_consentimento_explicito_fica_registado_com_prova_do_texto(self):
        r = self.conceder()
        self.assertEqual(r.status_code, 201, r.data)
        c = ConsentimentoDados.objects.get()
        self.assertEqual((c.utilizador, c.tipo, c.versao_termos), (self.aluno.utilizador, "saude", "1.0"))
        self.assertEqual(c.texto_hash, consentimentos.hash_do_texto())
        self.assertEqual(len(c.texto_hash), 64)
        self.assertTrue(self.client.get(CONSENTIMENTO).data["consentido"])

    def test_nao_ha_aceitacao_implicita(self):
        for corpo in ({"versao": "1.0"}, {"versao": "1.0", "aceito": False}, {"versao": "1.0", "aceito": "sim"},
                      {"aceito": True}, {}):
            self.assertEqual(self.client.post(CONSENTIMENTO, corpo, format="json").status_code, 400, corpo)
        self.assertEqual(ConsentimentoDados.objects.count(), 0)

    def test_versao_desatualizada_e_recusada(self):
        r = self.conceder(versao="0.9")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(ConsentimentoDados.objects.count(), 0)

    def test_repetir_nao_duplica(self):
        self.conceder()
        self.assertEqual(self.conceder().status_code, 201)
        self.assertEqual(ConsentimentoDados.objects.count(), 1)

    def test_exige_autenticacao(self):
        self.assertEqual(APIClient().get(CONSENTIMENTO).status_code, 401)
        self.assertEqual(APIClient().post(CONSENTIMENTO, {"versao": "1.0", "aceito": True}, format="json").status_code, 401)

    def test_texto_configuravel_e_o_hash_acompanha(self):
        with patch("core.services.consentimentos.config",
                   side_effect=lambda k, default=None, **_: "Texto do juridico" if k == "HEALTH_CONSENT_TEXT" else default):
            self.assertEqual(self.client.get(CONSENTIMENTO).data["texto"], "Texto do juridico")
            self.conceder()
        self.assertEqual(ConsentimentoDados.objects.get().texto_hash, consentimentos.hash_do_texto("Texto do juridico"))


class SemConsentimentoTestCase(TestCase):
    """Sem consentimento explicito nenhum endpoint de dados de saude do aluno funciona."""

    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("sem_cons")
        self.client.force_authenticate(self.aluno.utilizador)

    def test_endpoints_de_saude_bloqueados(self):
        pedidos = [
            ("get", "/api/v1/progress/metrics/", None), ("post", "/api/v1/progress/metrics/", {"data": hoje(), "peso_kg": "80"}),
            ("get", "/api/v1/progress/workouts/", None),
            ("post", "/api/v1/progress/workouts/", {"data": hoje(), "tipo": "x", "duracao_minutos": 30}),
            ("get", "/api/v1/progress/summary/", None), ("post", "/api/v1/progress/wearables/ingest/", {}),
            ("get", "/api/v1/nutrition/logs/", None),
            ("post", "/api/v1/nutrition/logs/", {"data": hoje(), "descricao": "x", "calorias": 1}),
            ("get", "/api/v1/nutrition/logs/resumo/", None),
        ]
        for metodo, url, corpo in pedidos:
            r = getattr(self.client, metodo)(url, corpo, format="json") if corpo is not None else getattr(self.client, metodo)(url)
            self.assertEqual(r.status_code, 403, f"{metodo} {url}")
            self.assertIn("consentimento", json.dumps(r.data).lower())
        self.assertEqual(MetricaFisica.objects.count() + HistoricoTreino.objects.count() + RegistoRefeicao.objects.count(), 0)

    def test_funcionalidades_sem_dados_de_saude_continuam_a_funcionar(self):
        for url in ("/api/v1/trainers/", "/api/v1/shop/products/", "/api/v1/notifications/", "/api/v1/credits/",
                    "/api/v1/perfil/aluno/", "/api/v1/gyms/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_consentimento_de_outra_pessoa_nao_vale(self):
        dar_consentimento(criar_aluno("outro_cons").utilizador)
        self.assertEqual(self.client.get("/api/v1/progress/metrics/").status_code, 403)

    def test_depois_de_consentir_passa_a_funcionar(self):
        self.client.post(CONSENTIMENTO, {"versao": "1.0", "aceito": True}, format="json")
        self.assertEqual(self.client.get("/api/v1/progress/metrics/").status_code, 200)
        r = self.client.post("/api/v1/progress/metrics/", {"data": hoje(), "peso_kg": "80"}, format="json")
        self.assertEqual(r.status_code, 201)


class RevogarConsentimentoTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("rev_aluno")
        dar_consentimento(self.aluno.utilizador)
        self.client.force_authenticate(self.aluno.utilizador)
        MetricaFisica.objects.create(aluno=self.aluno, data=timezone.localdate(), peso_kg=Decimal("80"))
        HistoricoTreino.objects.create(aluno=self.aluno, data=timezone.localdate(), tipo="x", duracao_minutos=30)
        RegistoRefeicao.objects.create(aluno=self.aluno, data=timezone.localdate(), descricao="x", calorias=1)

    def test_revogar_bloqueia_o_acesso_mas_nao_apaga_os_dados_por_omissao(self):
        r = self.client.delete(CONSENTIMENTO)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["registos_apagados"], 0)
        self.assertEqual(self.client.get("/api/v1/progress/metrics/").status_code, 403)
        self.assertEqual(MetricaFisica.objects.count(), 1)

    def test_historico_conserva_a_prova(self):
        self.client.delete(CONSENTIMENTO)
        c = ConsentimentoDados.objects.get()
        self.assertIsNotNone(c.data_revogacao)
        self.assertFalse(self.client.get(CONSENTIMENTO).data["consentido"])
        self.assertEqual(len(self.client.get(CONSENTIMENTO).data["historico"]), 1)

    def test_revogar_com_apagamento_dos_dados(self):
        r = self.client.delete(CONSENTIMENTO, {"apagar_dados": True}, format="json")
        self.assertEqual(r.data["registos_apagados"], 3)
        self.assertEqual(MetricaFisica.objects.count() + HistoricoTreino.objects.count() + RegistoRefeicao.objects.count(), 0)

    def test_pode_consentir_de_novo_depois_de_revogar(self):
        self.client.delete(CONSENTIMENTO)
        self.client.post(CONSENTIMENTO, {"versao": "1.0", "aceito": True}, format="json")
        self.assertEqual(self.client.get("/api/v1/progress/metrics/").status_code, 200)
        self.assertEqual(ConsentimentoDados.objects.count(), 2)

    def test_revogar_sem_consentimento_e_404_mas_apagar_dados_e_sempre_possivel(self):
        self.client.delete(CONSENTIMENTO)
        self.assertEqual(self.client.delete(CONSENTIMENTO).status_code, 404)
        r = self.client.delete(CONSENTIMENTO, {"apagar_dados": True}, format="json")
        self.assertEqual((r.status_code, r.data["registos_apagados"]), (200, 3))

    def test_revogar_apaga_tambem_os_planos_nutricionais_se_pedido(self):
        nutri = criar_nutricionista("rev_nutri")
        PlanoNutricional.objects.create(aluno=self.aluno, nutricionista=nutri, titulo="P")
        r = self.client.delete(CONSENTIMENTO, {"apagar_dados": True}, format="json")
        self.assertEqual(r.data["registos_apagados"], 4)
        self.assertEqual(PlanoNutricional.objects.count(), 0)


class NovaVersaoDosTermosTestCase(TestCase):
    def test_nova_versao_obriga_a_consentir_de_novo(self):
        client = APIClient()
        aluno = criar_aluno("ver_aluno")
        dar_consentimento(aluno.utilizador)
        client.force_authenticate(aluno.utilizador)
        self.assertEqual(client.get("/api/v1/progress/metrics/").status_code, 200)

        def v2(chave, default=None, **_):
            return "2.0" if chave == "HEALTH_CONSENT_VERSION" else default
        with patch("core.services.consentimentos.config", side_effect=v2):
            self.assertFalse(client.get(CONSENTIMENTO).data["consentido"])
            self.assertEqual(client.get("/api/v1/progress/metrics/").status_code, 403)
            self.assertEqual(client.post(CONSENTIMENTO, {"versao": "1.0", "aceito": True}, format="json").status_code, 409)
            self.assertEqual(client.post(CONSENTIMENTO, {"versao": "2.0", "aceito": True}, format="json").status_code, 201)
            self.assertEqual(client.get("/api/v1/progress/metrics/").status_code, 200)
        # o consentimento antigo ficou revogado, nao apagado
        self.assertEqual(ConsentimentoDados.objects.filter(versao_termos="1.0", data_revogacao__isnull=False).count(), 1)


class NutricionistaEConsentimentoTestCase(TestCase):
    """O nutricionista so trata dados de saude de alunos que consentiram."""

    def setUp(self):
        self.client = APIClient()
        self.nutri = criar_nutricionista("cons_nutri")
        self.aluno = criar_aluno("cons_aluno_n")
        self.client.force_authenticate(self.nutri.utilizador)

    def criar_plano(self):
        return self.client.post("/api/v1/nutrition/plans/", {"aluno_id": self.aluno.id, "titulo": "Plano"}, format="json")

    def test_nao_cria_plano_sem_consentimento_do_aluno(self):
        r = self.criar_plano()
        self.assertEqual(r.status_code, 400)
        self.assertIn("consentimento", json.dumps(r.data).lower())
        self.assertEqual(PlanoNutricional.objects.count(), 0)

    def test_cria_plano_com_consentimento(self):
        dar_consentimento(self.aluno.utilizador)
        self.assertEqual(self.criar_plano().status_code, 201)

    def test_revogacao_tira_o_acesso_ao_nutricionista(self):
        dar_consentimento(self.aluno.utilizador)
        pid = self.criar_plano().data["id"]
        self.assertEqual(self.client.get("/api/v1/nutrition/plans/").data["count"], 1)
        consentimentos.revogar(self.aluno.utilizador)
        self.assertEqual(self.client.get("/api/v1/nutrition/plans/").data["count"], 0)
        self.assertEqual(self.client.patch(f"/api/v1/nutrition/plans/{pid}/", {"titulo": "x"}, format="json").status_code, 404)

    def test_aluno_continua_a_poder_ver_os_proprios_planos_apos_revogar(self):
        dar_consentimento(self.aluno.utilizador)
        self.criar_plano()
        consentimentos.revogar(self.aluno.utilizador)
        self.client.force_authenticate(self.aluno.utilizador)
        self.assertEqual(self.client.get("/api/v1/nutrition/plans/").data["count"], 1)  # direito de acesso


class RgpdEConsentimentoTestCase(TestCase):
    def test_exportacao_inclui_o_historico_de_consentimentos(self):
        client = APIClient()
        aluno = criar_aluno("exp_cons")
        dar_consentimento(aluno.utilizador)
        client.force_authenticate(aluno.utilizador)
        dados = json.loads(client.get("/api/v1/users/me/data-export/").content)
        self.assertEqual([c["tipo"] for c in dados["consentimentos"]], ["saude"])
        self.assertNotIn("texto_hash", json.dumps(dados["consentimentos"]))

    def test_apagar_conta_apaga_os_consentimentos(self):
        client = APIClient()
        aluno = criar_aluno("del_cons")
        aluno.utilizador.set_password(SENHA)
        aluno.utilizador.save()
        dar_consentimento(aluno.utilizador)
        client.force_authenticate(aluno.utilizador)
        self.assertEqual(client.delete("/api/v1/users/me/", {"password": SENHA}, format="json").status_code, 204)
        self.assertEqual(ConsentimentoDados.objects.count(), 0)
