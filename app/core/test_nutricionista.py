from django.test import TestCase
from rest_framework.test import APIClient

from .models import Nutricionista, Utilizador
from .permissions import IsNutricionistaVerificado


def criar_nutricionista(username="nutri", verificado=True):
    u = Utilizador.objects.create_user(
        username=username, email=f"{username}@example.com", password="SenhaForte123!",
        tipo="nutricionista", is_active=True, telefone="923000111")
    estado = Nutricionista.EstadoVerificacao.VERIFICADO if verificado else Nutricionista.EstadoVerificacao.PENDENTE
    return Nutricionista.objects.create(utilizador=u, estado_verificacao=estado)


class NutricionistaTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_registo_cria_perfil_pendente(self):
        r = self.client.post("/api/v1/users/", {
            "username": "novanutri", "email": "n@example.com", "password": "SenhaForte123!",
            "tipo": "nutricionista", "telefone": "923"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        n = Nutricionista.objects.get(utilizador__username="novanutri")
        self.assertEqual(n.estado_verificacao, "pendente")

    def test_perfil_get_e_put(self):
        n = criar_nutricionista()
        self.client.force_authenticate(n.utilizador)
        self.assertEqual(self.client.get("/api/v1/perfil/nutricionista/").status_code, 200)
        r = self.client.put("/api/v1/perfil/nutricionista/", {
            "telefone": "999", "cedula_profissional": "N-123", "especialidade": "Desportiva",
            "estado_verificacao": "verificado"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        n.refresh_from_db()
        self.assertEqual(n.cedula_profissional, "N-123")
        self.assertEqual(n.utilizador.telefone, "999")

    def test_nao_se_auto_verifica(self):
        n = criar_nutricionista("pendente_n", verificado=False)
        self.client.force_authenticate(n.utilizador)
        self.client.put("/api/v1/perfil/nutricionista/", {"telefone": "1", "estado_verificacao": "verificado"}, format="json")
        n.refresh_from_db()
        self.assertEqual(n.estado_verificacao, "pendente")

    def test_outros_tipos_nao_tem_perfil_nutricionista(self):
        u = Utilizador.objects.create_user(username="alu", password="x", tipo="aluno", is_active=True)
        self.client.force_authenticate(u)
        self.assertEqual(self.client.get("/api/v1/perfil/nutricionista/").status_code, 404)

    def test_admin_verifica(self):
        n = criar_nutricionista("porverificar", verificado=False)
        admin = Utilizador.objects.create_user(username="nadmin", password="x", tipo="aluno", is_staff=True, is_active=True)
        self.client.force_authenticate(admin)
        self.assertEqual(self.client.post(f"/api/v1/nutricionistas/{n.id}/verificar/").status_code, 200)
        n.refresh_from_db()
        self.assertEqual(n.estado_verificacao, "verificado")
        self.assertEqual(self.client.post("/api/v1/nutricionistas/9999/verificar/").status_code, 404)

    def test_so_admin_verifica(self):
        n = criar_nutricionista("naoverif", verificado=False)
        self.client.force_authenticate(n.utilizador)
        self.assertEqual(self.client.post(f"/api/v1/nutricionistas/{n.id}/verificar/").status_code, 403)

    def test_permissao_exige_verificado(self):
        pend = criar_nutricionista("p1", verificado=False)
        ok = criar_nutricionista("p2")
        req = lambda u: type("R", (), {"user": Utilizador.objects.get(pk=u.pk)})()
        self.assertFalse(IsNutricionistaVerificado().has_permission(req(pend.utilizador), None))
        self.assertTrue(IsNutricionistaVerificado().has_permission(req(ok.utilizador), None))
