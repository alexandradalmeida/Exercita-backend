from django.test import TestCase
from rest_framework.test import APIClient

from .test_ginasios import TALATONA, criar_admin, criar_ginasio, criar_utilizador
from .test_marketplace import criar_pt


class AssociacaoTrainersTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.g1 = criar_ginasio("G1")
        self.g2 = criar_ginasio("G2", *TALATONA)
        self.pt = criar_pt("ptg")
        self.pt2 = criar_pt("ptg2")

    def url(self, g=None, pt=None):
        base = f"/api/v1/gyms/{(g or self.g1).id}/trainers/"
        return base + (f"{pt.id}/" if pt else "")

    def associar(self, user, pt=None, g=None):
        self.client.force_authenticate(user)
        return self.client.post(self.url(g), {"trainer_id": (pt or self.pt).id}, format="json")

    def test_pt_associa_se_a_si_proprio(self):
        self.assertEqual(self.associar(self.pt.utilizador).status_code, 201)
        self.assertEqual(list(self.g1.personal_trainers.all()), [self.pt])

    def test_associacao_idempotente(self):
        self.associar(self.pt.utilizador)
        self.assertEqual(self.associar(self.pt.utilizador).status_code, 201)
        self.assertEqual(self.g1.personal_trainers.count(), 1)

    def test_pt_nao_associa_outro(self):
        self.assertEqual(self.associar(self.pt.utilizador, pt=self.pt2).status_code, 403)

    def test_admin_associa_qualquer(self):
        self.assertEqual(self.associar(criar_admin("assoc_admin"), pt=self.pt2).status_code, 201)

    def test_varios_para_varios(self):
        self.associar(self.pt.utilizador, g=self.g1)
        self.associar(self.pt.utilizador, g=self.g2)
        self.associar(self.pt2.utilizador, pt=self.pt2, g=self.g1)
        self.assertEqual(self.pt.ginasios.count(), 2)
        self.assertEqual(self.g1.personal_trainers.count(), 2)

    def test_so_ginasios_parceiros(self):
        pendente = criar_ginasio("P", estado="pendente")
        self.assertEqual(self.associar(self.pt.utilizador, g=pendente).status_code, 404)
        self.assertEqual(self.associar(criar_admin("assoc_admin2"), g=pendente).status_code, 409)

    def test_pt_suspenso_nao_associa(self):
        self.pt.estado_verificacao = "suspenso"
        self.pt.save()
        self.assertEqual(self.associar(self.pt.utilizador).status_code, 409)

    def test_aluno_nao_associa(self):
        self.assertEqual(self.associar(criar_utilizador("aluno_assoc")).status_code, 403)

    def test_lista_trainers_do_ginasio(self):
        self.g1.personal_trainers.add(self.pt)
        self.client.force_authenticate(criar_utilizador("lista_assoc"))
        r = self.client.get(self.url())
        self.assertEqual([t["id"] for t in r.data["results"]], [self.pt.id])

    def test_remove_associacao(self):
        self.g1.personal_trainers.add(self.pt)
        self.client.force_authenticate(self.pt.utilizador)
        self.assertEqual(self.client.delete(self.url(pt=self.pt)).status_code, 204)
        self.assertEqual(self.client.delete(self.url(pt=self.pt)).status_code, 404)

    def test_pt_nao_remove_associacao_alheia(self):
        self.g1.personal_trainers.add(self.pt2)
        self.client.force_authenticate(self.pt.utilizador)
        self.assertEqual(self.client.delete(self.url(pt=self.pt2)).status_code, 403)

    def test_perfil_publico_lista_ginasios_parceiros(self):
        self.g1.personal_trainers.add(self.pt)
        criar_ginasio("Inativo", estado="inativo").personal_trainers.add(self.pt)
        self.client.force_authenticate(criar_utilizador("ver_perfil"))
        r = self.client.get(f"/api/v1/trainers/{self.pt.id}/profile/")
        self.assertEqual([g["nome"] for g in r.data["ginasios"]], ["G1"])

    def test_trainer_id_invalido(self):
        self.client.force_authenticate(self.pt.utilizador)
        self.assertEqual(self.client.post(self.url(), {"trainer_id": "x"}, format="json").status_code, 400)
