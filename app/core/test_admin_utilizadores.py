from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Notificacao, PersonalTrainer, Utilizador
from .test_nutricionista import criar_nutricionista
from .test_sessoes import criar_aluno
from .test_marketplace import criar_pt

USERS = "/api/v1/admin/users/"


def criar_staff(username="gestor", superuser=False):
    return Utilizador.objects.create_user(
        username=username, password="SenhaForte123!", tipo="aluno", is_active=True,
        is_staff=True, is_superuser=superuser)


class AdminBase(TestCase):
    def setUp(self):
        self.admin = APIClient()
        self.staff = criar_staff()
        self.admin.force_authenticate(self.staff)
        self.alvo = criar_aluno("alvo").utilizador

    def acao(self, nome, user=None, client=None, **corpo):
        return (client or self.admin).post(f"{USERS}{(user or self.alvo).id}/{nome}/", corpo, format="json")


class ListagemTestCase(AdminBase):
    def test_lista_com_filtros(self):
        criar_pt("pt_adm")
        self.assertEqual(self.admin.get(USERS, {"tipo": "personal_trainer"}).data["count"], 1)
        self.assertEqual(self.admin.get(USERS, {"q": "ALV"}).data["count"], 1)
        self.assertEqual(self.admin.get(USERS, {"suspenso": "true"}).data["count"], 0)

    def test_nao_expoe_telefone_nem_password(self):
        dados = self.admin.get(f"{USERS}{self.alvo.id}/").data
        self.assertNotIn("telefone", dados)
        self.assertNotIn("password", dados)

    def test_estado_do_perfil(self):
        pt = criar_pt("pt_estado")
        self.assertEqual(self.admin.get(f"{USERS}{pt.utilizador.id}/").data["estado_perfil"], "verificado")

    def test_so_admin(self):
        c = APIClient()
        c.force_authenticate(self.alvo)
        self.assertEqual(c.get(USERS).status_code, 403)
        self.assertEqual(APIClient().get(USERS).status_code, 401)


class SuspensaoTestCase(AdminBase):
    def test_suspende_revoga_sessoes_e_notifica(self):
        refresh = RefreshToken.for_user(self.alvo)
        r = self.acao("suspend", motivo="Comportamento abusivo")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["suspenso"])
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=refresh["jti"]).exists())
        self.assertTrue(Notificacao.objects.filter(utilizador=self.alvo, mensagem__contains="suspensa").exists())

    def test_suspenso_nao_faz_login(self):
        self.acao("suspend", motivo="x")
        r = APIClient().post("/api/v1/auth/login/", {"username": "alvo", "password": "SenhaForte123!"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("suspensa", str(r.data))

    def test_access_token_ja_emitido_deixa_de_valer(self):
        token = str(RefreshToken.for_user(self.alvo).access_token)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(c.get("/api/v1/perfil/aluno/").status_code, 200)
        self.acao("suspend", motivo="x")
        self.assertEqual(c.get("/api/v1/perfil/aluno/").status_code, 401)

    def test_refresh_token_revogado(self):
        refresh = str(RefreshToken.for_user(self.alvo))
        self.acao("suspend", motivo="x")
        self.assertEqual(APIClient().post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json").status_code, 401)

    def test_confirmar_email_nao_levanta_a_suspensao(self):
        self.acao("suspend", motivo="x")
        self.alvo.refresh_from_db()
        self.assertTrue(self.alvo.is_active and self.alvo.suspenso)

    def test_reativa(self):
        self.acao("suspend", motivo="x")
        r = self.acao("reactivate")
        self.assertFalse(r.data["suspenso"])
        self.assertEqual(r.data["motivo_suspensao"], "")
        login = APIClient().post("/api/v1/auth/login/", {"username": "alvo", "password": "SenhaForte123!"}, format="json")
        self.assertEqual(login.status_code, 200)

    def test_exige_motivo(self):
        self.assertEqual(self.acao("suspend").status_code, 400)
        self.assertEqual(self.acao("suspend", motivo="  ").status_code, 400)

    def test_estados_incoerentes(self):
        self.assertEqual(self.acao("reactivate").status_code, 409)
        self.acao("suspend", motivo="x")
        self.assertEqual(self.acao("suspend", motivo="y").status_code, 409)

    def test_nao_suspende_a_si_proprio_nem_superutilizadores(self):
        self.assertEqual(self.acao("suspend", user=self.staff, motivo="x").status_code, 409)
        root = criar_staff("root", superuser=True)
        self.assertEqual(self.acao("suspend", user=root, motivo="x").status_code, 403)

    def test_utilizador_inexistente(self):
        self.assertEqual(self.admin.post(f"{USERS}9999/suspend/", {"motivo": "x"}, format="json").status_code, 404)

    def test_login_social_recusa_suspensos(self):
        self.alvo.email = "social@example.com"
        self.alvo.save()
        self.acao("suspend", motivo="x")
        with patch("core.views.validar_id_token_apple", return_value={"email": "social@example.com", "email_verified": "true"}):
            r = APIClient().post("/api/v1/auth/apple/", {"id_token": "t"}, format="json")
        self.assertEqual(r.status_code, 403)


class PermissoesETestCase(AdminBase):
    def test_so_superutilizador_altera_permissoes(self):
        self.assertEqual(self.acao("permissions", is_staff=True).status_code, 403)
        root = APIClient()
        root.force_authenticate(criar_staff("root2", superuser=True))
        r = self.acao("permissions", client=root, is_staff=True)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["is_staff"])
        self.assertFalse(self.acao("permissions", client=root, is_staff=False).data["is_staff"])

    def test_valor_tem_de_ser_booleano(self):
        root = APIClient()
        root.force_authenticate(criar_staff("root3", superuser=True))
        self.assertEqual(self.acao("permissions", client=root, is_staff="sim").status_code, 400)
        self.assertEqual(self.acao("permissions", client=root).status_code, 400)


class VerificarPerfilTestCase(AdminBase):
    def test_verifica_pt_pendente(self):
        pt = criar_pt("pt_ver", verificado=False)
        self.assertEqual(self.acao("verify", user=pt.utilizador).data["estado_perfil"], "verificado")

    def test_verifica_nutricionista(self):
        n = criar_nutricionista("nutri_ver", verificado=False)
        self.assertEqual(self.acao("verify", user=n.utilizador).data["estado_perfil"], "verificado")

    def test_nao_levanta_suspensao_por_qualidade(self):
        pt = criar_pt("pt_susp")
        pt.estado_verificacao = PersonalTrainer.EstadoVerificacao.SUSPENSO
        pt.save()
        self.assertEqual(self.acao("verify", user=pt.utilizador).status_code, 409)

    def test_aluno_nao_tem_perfil_a_verificar(self):
        self.assertEqual(self.acao("verify").status_code, 400)
