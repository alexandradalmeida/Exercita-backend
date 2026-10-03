from django.test import TestCase
from rest_framework.test import APIClient

from .models import Ginasio, Utilizador


def criar_ginasio(nome="Gym", lat=-8.8383, lng=13.2344, estado="parceiro", **extra):
    return Ginasio.objects.create(nome=nome, latitude=lat, longitude=lng, estado_parceria=estado, **extra)


def criar_admin(username="gadmin"):
    return Utilizador.objects.create_user(username=username, password="x", tipo="aluno", is_staff=True, is_active=True)


def criar_utilizador(username="gutil"):
    return Utilizador.objects.create_user(username=username, password="x", tipo="aluno", is_active=True)


class GestaoGinasioTestCase(TestCase):
    url = "/api/v1/gyms/"

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(criar_admin())

    def corpo(self, **extra):
        corpo = {"nome": "Fit Luanda", "morada": "Rua A", "latitude": "-8.838300", "longitude": "13.234400",
                 "equipamentos": ["halteres", "passadeiras"], "horarios": {"0": [["06:00", "22:00"]]},
                 "estado_parceria": "parceiro"}
        corpo.update(extra)
        return corpo

    def test_admin_cria_ginasio_completo(self):
        r = self.client.post(self.url, self.corpo(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        g = Ginasio.objects.get()
        self.assertEqual(g.equipamentos, ["halteres", "passadeiras"])
        self.assertEqual(g.estado_parceria, "parceiro")

    def test_utilizador_normal_nao_cria(self):
        self.client.force_authenticate(criar_utilizador())
        self.assertEqual(self.client.post(self.url, self.corpo(), format="json").status_code, 403)

    def test_utilizador_so_ve_parceiros(self):
        criar_ginasio("Parceiro")
        criar_ginasio("Pendente", estado="pendente")
        self.client.force_authenticate(criar_utilizador())
        nomes = [g["nome"] for g in self.client.get(self.url).data["results"]]
        self.assertEqual(nomes, ["Parceiro"])
        self.client.force_authenticate(criar_admin("outro_admin"))
        self.assertEqual(self.client.get(self.url).data["count"], 2)

    def test_pendente_nao_acessivel_a_utilizador(self):
        g = criar_ginasio("Pendente", estado="pendente")
        self.client.force_authenticate(criar_utilizador())
        self.assertEqual(self.client.get(f"{self.url}{g.id}/").status_code, 404)

    def test_coordenadas_invalidas(self):
        self.assertEqual(self.client.post(self.url, self.corpo(latitude="91"), format="json").status_code, 400)
        self.assertEqual(self.client.post(self.url, self.corpo(longitude="-181"), format="json").status_code, 400)

    def test_horarios_invalidos(self):
        for horarios in ({"7": [["06:00", "22:00"]]}, {"0": [["22:00", "06:00"]]}, {"0": [["xx", "22:00"]]},
                         {"0": "aberto"}, ["0"]):
            r = self.client.post(self.url, self.corpo(horarios=horarios), format="json")
            self.assertEqual(r.status_code, 400, horarios)

    def test_exige_autenticacao(self):
        self.assertEqual(APIClient().get(self.url).status_code, 401)
