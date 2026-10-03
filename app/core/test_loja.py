from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Produto
from .test_ginasios import criar_admin, criar_utilizador

URL = "/api/v1/shop/products/"


def criar_produto(nome="Whey", preco="100.00", stock=10, categoria="suplemento", **extra):
    return Produto.objects.create(nome=nome, preco=Decimal(preco), stock=stock, categoria=categoria, **extra)


class CatalogoTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(criar_utilizador("comprador"))
        criar_produto("Whey Protein", "250.00", 5)
        criar_produto("Creatina", "120.00", 0)
        criar_produto("T-shirt", "60.00", 20, categoria="vestuario")
        criar_produto("Descontinuado", "10.00", 3, ativo=False)

    def nomes(self, **params):
        r = self.client.get(URL, params)
        self.assertEqual(r.status_code, 200, r.data)
        return [p["nome"] for p in r.data["results"]]

    def test_lista_so_ativos_ordenados(self):
        self.assertEqual(self.nomes(), ["Creatina", "T-shirt", "Whey Protein"])

    def test_filtros(self):
        self.assertEqual(self.nomes(categoria="vestuario"), ["T-shirt"])
        self.assertEqual(self.nomes(q="whey"), ["Whey Protein"])
        self.assertEqual(self.nomes(preco_min="100", preco_max="200"), ["Creatina"])
        self.assertEqual(self.nomes(em_stock="true"), ["T-shirt", "Whey Protein"])

    def test_preco_invalido(self):
        self.assertEqual(self.client.get(URL, {"preco_min": "x"}).status_code, 400)

    def test_em_stock_no_detalhe(self):
        pid = Produto.objects.get(nome="Creatina").id
        self.assertFalse(self.client.get(f"{URL}{pid}/").data["em_stock"])

    def test_inativo_invisivel_para_clientes_mas_visivel_ao_admin(self):
        pid = Produto.objects.get(nome="Descontinuado").id
        self.assertEqual(self.client.get(f"{URL}{pid}/").status_code, 404)
        self.client.force_authenticate(criar_admin("loja_admin"))
        self.assertEqual(self.client.get(f"{URL}{pid}/").status_code, 200)
        self.assertEqual(self.client.get(URL).data["count"], 4)

    def test_so_admin_gere(self):
        corpo = {"nome": "Novo", "preco": "10.00", "stock": 1}
        self.assertEqual(self.client.post(URL, corpo, format="json").status_code, 403)
        self.client.force_authenticate(criar_admin("loja_admin2"))
        self.assertEqual(self.client.post(URL, corpo, format="json").status_code, 201)

    def test_preco_negativo_recusado(self):
        self.client.force_authenticate(criar_admin("loja_admin3"))
        r = self.client.post(URL, {"nome": "x", "preco": "-1", "stock": 1}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_exige_autenticacao(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)
