from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Ginasio, Utilizador
from .services.geocoding import GeocodingMock


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


# Distancias de referencia (aprox.): Luanda-Benguela ~ 420 km; Luanda centro - Talatona ~ 12 km
LUANDA = (-8.8383, 13.2344)
TALATONA = (-8.9167, 13.1833)
BENGUELA = (-12.5763, 13.4055)


class PesquisaProximidadeTestCase(TestCase):
    url = "/api/v1/gyms/"

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(criar_utilizador("buscador"))
        self.perto = criar_ginasio("Perto", *LUANDA, equipamentos=["halteres", "piscina"])
        self.medio = criar_ginasio("Medio", *TALATONA, equipamentos=["halteres"])
        self.longe = criar_ginasio("Longe", *BENGUELA)
        criar_ginasio("Pendente", *LUANDA, estado="pendente")
        criar_ginasio("Sem coords", None, None)

    def nomes(self, **params):
        r = self.client.get(self.url, params)
        self.assertEqual(r.status_code, 200, r.data)
        return [g["nome"] for g in r.data["results"]]

    def test_ordena_por_distancia_e_respeita_raio_por_omissao(self):
        self.assertEqual(self.nomes(lat=LUANDA[0], lng=LUANDA[1]), ["Perto"])  # 10 km por omissao

    def test_raio_maior_inclui_mais(self):
        self.assertEqual(self.nomes(lat=LUANDA[0], lng=LUANDA[1], raio_km=20), ["Perto", "Medio"])
        self.assertEqual(self.nomes(lat=LUANDA[0], lng=LUANDA[1], raio_km=500), ["Perto", "Medio", "Longe"])

    def test_distancia_calculada(self):
        r = self.client.get(self.url, {"lat": LUANDA[0], "lng": LUANDA[1], "raio_km": 500})
        d = {g["nome"]: g["distancia_km"] for g in r.data["results"]}
        self.assertAlmostEqual(d["Perto"], 0, places=2)
        self.assertTrue(8 < d["Medio"] < 14, d)
        self.assertTrue(400 < d["Longe"] < 440, d)

    def test_a_partir_de_outro_ponto(self):
        self.assertEqual(self.nomes(lat=BENGUELA[0], lng=BENGUELA[1], raio_km=5), ["Longe"])

    def test_sem_localizacao_lista_por_nome_incluindo_sem_coordenadas(self):
        self.assertEqual(self.nomes(), ["Longe", "Medio", "Perto", "Sem coords"])

    def test_filtros_de_equipamento_e_nome(self):
        self.assertEqual(self.nomes(equipamento="PISCINA"), ["Perto"])
        self.assertEqual(self.nomes(equipamento="halteres"), ["Medio", "Perto"])
        self.assertEqual(self.nomes(q="long"), ["Longe"])

    def test_combina_proximidade_e_equipamento(self):
        self.assertEqual(self.nomes(lat=LUANDA[0], lng=LUANDA[1], raio_km=20, equipamento="piscina"), ["Perto"])

    def test_parametros_invalidos(self):
        for params in ({"lat": "abc", "lng": "1"}, {"lat": "95", "lng": "1"}, {"lat": "1"}, {"raio_km": "5"},
                       {"lat": "1", "lng": "1", "raio_km": "-3"}, {"lat": "1", "lng": "1", "raio_km": "9999"}):
            self.assertEqual(self.client.get(self.url, params).status_code, 400, params)

    def test_raio_zero_so_o_proprio_ponto(self):
        self.assertEqual(self.nomes(lat=LUANDA[0], lng=LUANDA[1], raio_km=0), ["Perto"])

    def test_perto_do_antimeridiano_nao_rebenta(self):
        self.assertEqual(self.nomes(lat=0, lng=179.99, raio_km=50), [])


class GeocodingTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(criar_admin("geoadmin"))

    def criar(self, **extra):
        corpo = {"nome": "G", "morada": "Rua X, Luanda", "estado_parceria": "parceiro"}
        corpo.update(extra)
        return self.client.post("/api/v1/gyms/", corpo, format="json")

    def test_parceiro_sem_coordenadas_e_sem_geocoder_recusado(self):
        self.assertEqual(self.criar().status_code, 400)

    def test_pendente_pode_ficar_sem_coordenadas(self):
        self.assertEqual(self.criar(estado_parceria="pendente").status_code, 201)

    def test_geocodifica_a_morada_quando_falta_coordenadas(self):
        with patch("core.serializers.obter_geocoder", return_value=GeocodingMock()):
            r = self.criar()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(float(r.data["latitude"]), -8.8383)

    def test_coordenadas_explicitas_tem_prioridade(self):
        with patch("core.serializers.obter_geocoder", return_value=GeocodingMock()):
            r = self.criar(latitude="1.5", longitude="2.5")
        self.assertEqual(float(r.data["latitude"]), 1.5)

    def test_equipamentos_normalizados(self):
        r = self.criar(latitude="1", longitude="1", equipamentos=[" Halteres ", "", "PISCINA"])
        self.assertEqual(r.data["equipamentos"], ["halteres", "piscina"])
