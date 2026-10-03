from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from .models import PlanoNutricional, Refeicao, RegistoRefeicao
from .test_nutricionista import criar_nutricionista
from .test_sessoes import criar_aluno

PLANOS = "/api/v1/nutrition/plans/"
REFEICOES = [
    {"nome": "Pequeno-almoco", "hora": "08:00", "calorias": 400, "proteinas_g": "20.5"},
    {"nome": "Almoco", "dia_semana": 0, "calorias": 700},
]


class PlanosTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.nutri = criar_nutricionista("nplanos")
        self.aluno = criar_aluno("aplanos")
        self.client.force_authenticate(self.nutri.utilizador)

    def criar(self, **extra):
        corpo = {"aluno_id": self.aluno.id, "titulo": "Definicao", "calorias_diarias": 2000, "refeicoes": REFEICOES}
        corpo.update(extra)
        return self.client.post(PLANOS, corpo, format="json")

    def test_nutricionista_cria_plano_com_refeicoes(self):
        r = self.criar()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["refeicoes"]), 2)
        plano = PlanoNutricional.objects.get()
        self.assertEqual(plano.nutricionista, self.nutri)
        self.assertEqual(plano.aluno, self.aluno)

    def test_nutricionista_nao_verificado_nao_cria(self):
        self.client.force_authenticate(criar_nutricionista("nverif", verificado=False).utilizador)
        self.assertEqual(self.criar().status_code, 403)

    def test_aluno_nao_cria(self):
        self.client.force_authenticate(self.aluno.utilizador)
        self.assertEqual(self.criar().status_code, 403)

    def test_exige_aluno(self):
        r = self.client.post(PLANOS, {"titulo": "x"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_aluno_ve_so_os_seus_planos_em_leitura(self):
        self.criar()
        outro = criar_aluno("aoutro")
        PlanoNutricional.objects.create(aluno=outro, nutricionista=self.nutri, titulo="Outro")
        self.client.force_authenticate(self.aluno.utilizador)
        r = self.client.get(PLANOS)
        self.assertEqual([p["titulo"] for p in r.data["results"]], ["Definicao"])
        pid = r.data["results"][0]["id"]
        self.assertEqual(self.client.patch(f"{PLANOS}{pid}/", {"titulo": "x"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(f"{PLANOS}{pid}/").status_code, 403)

    def test_nutricionista_so_ve_os_seus(self):
        self.criar()
        outra = criar_nutricionista("noutra")
        self.client.force_authenticate(outra.utilizador)
        self.assertEqual(self.client.get(PLANOS).data["count"], 0)
        pid = PlanoNutricional.objects.get().id
        self.assertEqual(self.client.patch(f"{PLANOS}{pid}/", {"titulo": "x"}, format="json").status_code, 404)

    def test_atualizar_substitui_refeicoes(self):
        pid = self.criar().data["id"]
        r = self.client.patch(f"{PLANOS}{pid}/", {"refeicoes": [{"nome": "Jantar", "calorias": 600}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([x["nome"] for x in r.data["refeicoes"]], ["Jantar"])
        self.assertEqual(Refeicao.objects.count(), 1)

    def test_patch_sem_refeicoes_mantem_as_existentes(self):
        pid = self.criar().data["id"]
        self.client.patch(f"{PLANOS}{pid}/", {"titulo": "Novo"}, format="json")
        self.assertEqual(Refeicao.objects.count(), 2)

    def test_nao_muda_aluno_do_plano(self):
        pid = self.criar().data["id"]
        outro = criar_aluno("atroca")
        r = self.client.patch(f"{PLANOS}{pid}/", {"aluno_id": outro.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_apagar_plano(self):
        pid = self.criar().data["id"]
        self.assertEqual(self.client.delete(f"{PLANOS}{pid}/").status_code, 204)
        self.assertEqual(Refeicao.objects.count(), 0)

    def test_dia_da_semana_invalido(self):
        r = self.criar(refeicoes=[{"nome": "x", "dia_semana": 9}])
        self.assertEqual(r.status_code, 400)


class RegistoDiarioTestCase(TestCase):
    url = "/api/v1/nutrition/logs/"

    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("alogs")
        self.nutri = criar_nutricionista("nlogs")
        self.plano = PlanoNutricional.objects.create(
            aluno=self.aluno, nutricionista=self.nutri, titulo="P", calorias_diarias=2000)
        self.refeicao = Refeicao.objects.create(plano=self.plano, nome="Almoco", calorias=700)
        self.client.force_authenticate(self.aluno.utilizador)

    def registar(self, dia="2026-10-05", calorias=500, **extra):
        return self.client.post(self.url, {"data": dia, "descricao": "Arroz", "calorias": calorias, **extra}, format="json")

    def test_regista_refeicao_livre_e_do_plano(self):
        self.assertEqual(self.registar().status_code, 201)
        self.assertEqual(self.registar(refeicao=self.refeicao.id).status_code, 201)

    def test_nao_regista_refeicao_de_plano_alheio(self):
        outro = criar_aluno("aalheio")
        alheia = Refeicao.objects.create(
            plano=PlanoNutricional.objects.create(aluno=outro, titulo="X"), nome="Y", calorias=1)
        self.assertEqual(self.registar(refeicao=alheia.id).status_code, 400)

    def test_filtros_por_data(self):
        self.registar("2026-10-05")
        self.registar("2026-10-06")
        self.registar("2026-10-08")
        self.assertEqual(self.client.get(self.url, {"data": "2026-10-06"}).data["count"], 1)
        self.assertEqual(self.client.get(self.url, {"de": "2026-10-06", "ate": "2026-10-08"}).data["count"], 2)
        self.assertEqual(self.client.get(self.url, {"data": "ontem"}).status_code, 400)

    def test_so_ve_os_proprios(self):
        self.registar()
        self.client.force_authenticate(criar_aluno("aoutro2").utilizador)
        self.assertEqual(self.client.get(self.url).data["count"], 0)

    def test_editar_e_apagar_proprio(self):
        rid = self.registar().data["id"]
        self.assertEqual(self.client.patch(f"{self.url}{rid}/", {"calorias": 450}, format="json").status_code, 200)
        self.assertEqual(RegistoRefeicao.objects.get().calorias, 450)
        self.assertEqual(self.client.delete(f"{self.url}{rid}/").status_code, 204)

    def test_resumo_diario(self):
        self.registar(calorias=500)
        self.registar(calorias=300)
        self.registar("2026-10-06", calorias=999)
        r = self.client.get(self.url + "resumo/", {"data": "2026-10-05"})
        self.assertEqual(r.data["total_calorias"], 800)
        self.assertEqual(r.data["objetivo_calorias"], 2000)
        self.assertEqual(r.data["restante"], 1200)

    def test_resumo_sem_plano(self):
        self.plano.delete()
        r = self.client.get(self.url + "resumo/", {"data": "2026-10-05"})
        self.assertIsNone(r.data["objetivo_calorias"])
        self.assertIsNone(r.data["restante"])

    def test_nutricionista_nao_usa_registos(self):
        self.client.force_authenticate(self.nutri.utilizador)
        self.assertEqual(self.client.get(self.url).status_code, 403)
