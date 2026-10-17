from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import HistoricoTreino, MetricaFisica, Sessao
from .test_marketplace import criar_pt
from .test_sessoes import criar_aluno_com_consentimento as criar_aluno

METRICAS = "/api/v1/progress/metrics/"
TREINOS = "/api/v1/progress/workouts/"


def dia(offset=0):
    return (timezone.localdate() + timedelta(days=offset)).isoformat()


class MetricasTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("progresso")
        self.client.force_authenticate(self.aluno.utilizador)

    def test_regista_medicao_com_imc(self):
        r = self.client.post(METRICAS, {"data": dia(), "peso_kg": "80", "altura_cm": "180", "gordura_percentagem": "18.5"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["imc"], 24.7)
        self.assertEqual(r.data["fonte"], "manual")

    def test_exige_pelo_menos_uma_medida(self):
        self.assertEqual(self.client.post(METRICAS, {"data": dia()}, format="json").status_code, 400)

    def test_valores_fora_de_limites(self):
        for corpo in ({"peso_kg": "0"}, {"peso_kg": "900"}, {"altura_cm": "10"}, {"gordura_percentagem": "90"},
                      {"cintura_cm": "-5"}):
            r = self.client.post(METRICAS, {"data": dia(), **corpo}, format="json")
            self.assertEqual(r.status_code, 400, corpo)

    def test_data_no_futuro(self):
        self.assertEqual(self.client.post(METRICAS, {"data": dia(2), "peso_kg": "80"}, format="json").status_code, 400)

    def test_cliente_nao_forca_a_fonte(self):
        r = self.client.post(METRICAS, {"data": dia(), "peso_kg": "80", "fonte": "wearable"}, format="json")
        self.assertEqual(r.data["fonte"], "manual")

    def test_lista_ordenada_e_filtrada_por_datas(self):
        for offset, peso in ((-10, "82"), (-5, "81"), (0, "80")):
            self.client.post(METRICAS, {"data": dia(offset), "peso_kg": peso}, format="json")
        r = self.client.get(METRICAS)
        self.assertEqual([m["peso_kg"] for m in r.data["results"]], ["80.00", "81.00", "82.00"])
        self.assertEqual(self.client.get(METRICAS, {"de": dia(-6)}).data["count"], 2)
        self.assertEqual(self.client.get(METRICAS, {"de": dia(-6), "ate": dia(-1)}).data["count"], 1)
        self.assertEqual(self.client.get(METRICAS, {"de": "ontem"}).status_code, 400)

    def test_editar_e_apagar(self):
        mid = self.client.post(METRICAS, {"data": dia(), "peso_kg": "80"}, format="json").data["id"]
        self.assertEqual(self.client.patch(f"{METRICAS}{mid}/", {"peso_kg": "79"}, format="json").status_code, 200)
        self.assertEqual(self.client.delete(f"{METRICAS}{mid}/").status_code, 204)

    def test_isolamento_entre_alunos(self):
        mid = self.client.post(METRICAS, {"data": dia(), "peso_kg": "80"}, format="json").data["id"]
        self.client.force_authenticate(criar_aluno("outro_prog").utilizador)
        self.assertEqual(self.client.get(METRICAS).data["count"], 0)
        self.assertEqual(self.client.delete(f"{METRICAS}{mid}/").status_code, 404)

    def test_so_alunos(self):
        self.client.force_authenticate(criar_pt("pt_prog").utilizador)
        self.assertEqual(self.client.get(METRICAS).status_code, 403)


class TreinosTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("treinos")
        self.client.force_authenticate(self.aluno.utilizador)

    def treino(self, **extra):
        corpo = {"data": dia(), "tipo": "Musculacao", "duracao_minutos": 60, "calorias_gastas": 400}
        corpo.update(extra)
        return self.client.post(TREINOS, corpo, format="json")

    def test_regista_treino(self):
        r = self.treino()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["fonte"], "manual")

    def test_validacoes(self):
        self.assertEqual(self.treino(duracao_minutos=0).status_code, 400)
        self.assertEqual(self.treino(duracao_minutos=2000).status_code, 400)
        self.assertEqual(self.treino(data=dia(1)).status_code, 400)
        self.assertEqual(self.treino(tipo="").status_code, 400)

    def test_filtro_por_tipo_e_datas(self):
        self.treino(tipo="Corrida", data=dia(-3))
        self.treino(tipo="Musculacao")
        self.assertEqual(self.client.get(TREINOS, {"tipo": "corrida"}).data["count"], 1)
        self.assertEqual(self.client.get(TREINOS, {"de": dia(-1)}).data["count"], 1)

    def test_associar_a_sessao_propria_realizada(self):
        pt = criar_pt("pt_treino")
        sessao = Sessao.objects.create(aluno=self.aluno, personal_trainer=pt, data_hora=timezone.now(), estado="realizada")
        self.assertEqual(self.treino(sessao=sessao.id).status_code, 201)

    def test_nao_associa_sessao_alheia_ou_nao_realizada(self):
        pt = criar_pt("pt_treino2")
        agendada = Sessao.objects.create(aluno=self.aluno, personal_trainer=pt, data_hora=timezone.now())
        alheia = Sessao.objects.create(aluno=criar_aluno("alheio_t"), personal_trainer=pt,
                                       data_hora=timezone.now(), estado="realizada")
        self.assertEqual(self.treino(sessao=agendada.id).status_code, 400)
        self.assertEqual(self.treino(sessao=alheia.id).status_code, 400)

    def test_isolamento(self):
        self.treino()
        self.client.force_authenticate(criar_aluno("outro_treino").utilizador)
        self.assertEqual(self.client.get(TREINOS).data["count"], 0)


class ResumoTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("resumo")
        self.client.force_authenticate(self.aluno.utilizador)

    def test_sem_dados(self):
        r = self.client.get("/api/v1/progress/summary/")
        self.assertIsNone(r.data["ultima_medicao"])
        self.assertIsNone(r.data["variacao_peso_kg"])
        self.assertEqual(r.data["treinos_ultimos_30_dias"], {"total": 0, "minutos": 0, "calorias": 0})

    def test_variacao_de_peso_e_treinos_recentes(self):
        for offset, peso in ((-40, "90"), (-20, "86"), (0, "84.5")):
            self.client.post(METRICAS, {"data": dia(offset), "peso_kg": peso}, format="json")
        self.client.post(TREINOS, {"data": dia(-2), "tipo": "x", "duracao_minutos": 30, "calorias_gastas": 200}, format="json")
        self.client.post(TREINOS, {"data": dia(-1), "tipo": "y", "duracao_minutos": 45}, format="json")
        self.client.post(TREINOS, {"data": dia(-60), "tipo": "z", "duracao_minutos": 99}, format="json")
        r = self.client.get("/api/v1/progress/summary/").data
        self.assertEqual(Decimal(r["peso_inicial_kg"]), Decimal("90"))
        self.assertEqual(Decimal(r["peso_atual_kg"]), Decimal("84.5"))
        self.assertEqual(Decimal(r["variacao_peso_kg"]), Decimal("-5.5"))
        self.assertEqual(r["treinos_ultimos_30_dias"], {"total": 2, "minutos": 75, "calorias": 200})


class WearablesTestCase(TestCase):
    url = "/api/v1/progress/wearables/ingest/"

    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("wear")
        self.client.force_authenticate(self.aluno.utilizador)
        self.corpo = {
            "metricas": [{"origem_externa_id": "m1", "data": dia(-1), "peso_kg": "80"}],
            "treinos": [{"origem_externa_id": "t1", "data": dia(-1), "tipo": "corrida", "duracao_minutos": 30}],
        }

    def test_ingere_e_marca_fonte_wearable(self):
        r = self.client.post(self.url, self.corpo, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["criados"], {"metricas": 1, "treinos": 1})
        self.assertEqual(MetricaFisica.objects.get().fonte, "wearable")
        self.assertEqual(HistoricoTreino.objects.get().fonte, "wearable")

    def test_reenvio_nao_duplica(self):
        self.client.post(self.url, self.corpo, format="json")
        r = self.client.post(self.url, self.corpo, format="json")
        self.assertEqual(r.data["criados"], {"metricas": 0, "treinos": 0})
        self.assertEqual(r.data["ignorados"], {"metricas": 1, "treinos": 1})
        self.assertEqual(MetricaFisica.objects.count(), 1)

    def test_mesmo_id_de_alunos_diferentes_nao_colide(self):
        self.client.post(self.url, self.corpo, format="json")
        self.client.force_authenticate(criar_aluno("wear2").utilizador)
        self.assertEqual(self.client.post(self.url, self.corpo, format="json").data["criados"]["metricas"], 1)

    def test_lote_invalido_nao_grava_nada(self):
        self.corpo["treinos"][0]["duracao_minutos"] = 0
        self.assertEqual(self.client.post(self.url, self.corpo, format="json").status_code, 400)
        self.assertEqual(MetricaFisica.objects.count(), 0)

    def test_origem_externa_obrigatoria(self):
        del self.corpo["metricas"][0]["origem_externa_id"]
        self.assertEqual(self.client.post(self.url, self.corpo, format="json").status_code, 400)

    def test_dados_wearable_aparecem_na_listagem(self):
        self.client.post(self.url, self.corpo, format="json")
        self.assertEqual(self.client.get(METRICAS).data["results"][0]["fonte"], "wearable")
