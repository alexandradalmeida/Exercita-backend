from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from .services.apple import AppleTokenInvalido
from .permissions import IsPersonalTrainerVerificado
from .models import Utilizador, UtilizadorAluno, PersonalTrainer


class RegistoTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_registo_cria_utilizador_inativo(self):
        response = self.client.post("/api/v1/users/", {
            "username": "testealuno",
            "email": "testealuno@example.com",
            "password": "SenhaForte123!",
            "tipo": "aluno",
            "telefone": "923000000",
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        utilizador = Utilizador.objects.get(username="testealuno")
        self.assertFalse(utilizador.is_active)
        self.assertTrue(UtilizadorAluno.objects.filter(utilizador=utilizador).exists())

    def test_registo_pt_cria_perfil_pt(self):
        response = self.client.post("/api/v1/users/", {
            "username": "testept",
            "email": "testept@example.com",
            "password": "SenhaForte123!",
            "tipo": "personal_trainer",
            "telefone": "923000001",
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        utilizador = Utilizador.objects.get(username="testept")
        pt = PersonalTrainer.objects.get(utilizador=utilizador)
        self.assertEqual(pt.estado_verificacao, PersonalTrainer.EstadoVerificacao.PENDENTE)

    @patch("core.views.config", side_effect=lambda k, default=None: "https://api.exercita.ao" if k == "BACKEND_URL" else default)
    def test_link_de_confirmacao_usa_backend_url(self, _config):
        self.client.post("/api/v1/users/", {
            "username": "linkteste",
            "email": "link@example.com",
            "password": "SenhaForte123!",
            "tipo": "aluno",
        })
        self.assertIn("https://api.exercita.ao/api/v1/users/confirm-email/", mail.outbox[0].body)

    def test_registo_com_username_duplicado_falha(self):
        Utilizador.objects.create_user(username="existente", email="a@a.com", password="SenhaForte123!")
        response = self.client.post("/api/v1/users/", {
            "username": "existente",
            "email": "outro@example.com",
            "password": "SenhaForte123!",
            "tipo": "aluno",
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LoginTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.utilizador = Utilizador.objects.create_user(
            username="loginuser", email="login@example.com", password="SenhaForte123!",
            tipo="aluno", is_active=True,
        )
        UtilizadorAluno.objects.create(utilizador=self.utilizador)

    def test_login_com_credenciais_corretas(self):
        response = self.client.post("/api/v1/auth/login/", {
            "username": "loginuser",
            "password": "SenhaForte123!",
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("session_token", response.data)
        self.assertIn("refresh_token", response.data)

    def test_login_com_password_errada_falha(self):
        response = self.client.post("/api/v1/auth/login/", {
            "username": "loginuser",
            "password": "senhaerrada",
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_com_conta_inativa_falha(self):
        self.utilizador.is_active = False
        self.utilizador.save()
        response = self.client.post("/api/v1/auth/login/", {
            "username": "loginuser",
            "password": "SenhaForte123!",
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_invalida_refresh_token(self):
        login_response = self.client.post("/api/v1/auth/login/", {
            "username": "loginuser",
            "password": "SenhaForte123!",
        })
        refresh_token = login_response.data["refresh_token"]

        logout_response = self.client.post("/api/v1/auth/logout/", {
            "refresh_token": refresh_token,
        })
        self.assertEqual(logout_response.status_code, status.HTTP_200_OK)


class PerfilTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.utilizador = Utilizador.objects.create_user(
            username="perfiluser", email="perfil@example.com", password="SenhaForte123!",
            tipo="aluno", is_active=True, telefone="923111222",
        )
        self.perfil = UtilizadorAluno.objects.create(utilizador=self.utilizador)
        self.client.force_authenticate(user=self.utilizador)

    def test_get_perfil_aluno(self):
        response = self.client.get("/api/v1/perfil/aluno/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "perfiluser")

    def test_put_perfil_aluno_atualiza_dados(self):
        response = self.client.put("/api/v1/perfil/aluno/", {
            "telefone": "924999888",
            "objetivo": "Ganhar massa muscular",
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.perfil.refresh_from_db()
        self.assertEqual(self.perfil.objetivo, "Ganhar massa muscular")

    def test_perfil_requer_autenticacao(self):
        client_sem_auth = APIClient()
        response = client_sem_auth.get("/api/v1/perfil/aluno/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class VerificacaoPTTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = Utilizador.objects.create_superuser(
            username="admintest", email="admin@example.com", password="SenhaForte123!"
        )
        self.pt_user = Utilizador.objects.create_user(
            username="ptuser", email="pt@example.com", password="SenhaForte123!",
            tipo="personal_trainer", is_active=True,
        )
        self.pt = PersonalTrainer.objects.create(utilizador=self.pt_user)

    def test_admin_pode_verificar_pt(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f"/api/v1/personal-trainers/{self.pt.id}/verificar/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.pt.refresh_from_db()
        self.assertEqual(self.pt.estado_verificacao, PersonalTrainer.EstadoVerificacao.VERIFICADO)

    def test_pt_nao_pode_se_autoverificar(self):
        self.client.force_authenticate(user=self.pt_user)
        response = self.client.post(f"/api/v1/personal-trainers/{self.pt.id}/verificar/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_utilizador_comum_nao_pode_verificar_pt(self):
        aluno = Utilizador.objects.create_user(
            username="alunocomum", email="alunocomum@example.com", password="SenhaForte123!",
            tipo="aluno", is_active=True,
        )
        self.client.force_authenticate(user=aluno)
        response = self.client.post(f"/api/v1/personal-trainers/{self.pt.id}/verificar/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

class GoogleStateTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()

    def test_login_google_devolve_state_guardado_em_cache(self):
        response = self.client.get("/api/v1/auth/google/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(cache.get("google_oauth_state:" + response.data["state"]))

    def test_callback_com_state_desconhecido_falha(self):
        response = self.client.get("/api/v1/auth/google/callback/", {"code": "x", "state": "inexistente"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("core.views.http_requests.post")
    def test_state_so_pode_ser_usado_uma_vez(self, mock_post):
        mock_post.return_value.status_code = 400
        mock_post.return_value.text = "erro"
        state = self.client.get("/api/v1/auth/google/").data["state"]

        primeira = self.client.get("/api/v1/auth/google/callback/", {"code": "x", "state": state})
        self.assertEqual(mock_post.call_count, 1)  # passou a validacao do state
        segunda = self.client.get("/api/v1/auth/google/callback/", {"code": "x", "state": state})
        self.assertEqual(mock_post.call_count, 1)  # state ja consumido
        self.assertEqual(segunda.status_code, status.HTTP_400_BAD_REQUEST)


class BR01PublicacaoTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.utilizador = Utilizador.objects.create_user(
            username="ptbr01", email="ptbr01@example.com", password="SenhaForte123!",
            tipo="personal_trainer", is_active=True, telefone="923444555",
        )
        self.pt = PersonalTrainer.objects.create(utilizador=self.utilizador)
        self.client.force_authenticate(self.utilizador)

    def test_pt_nao_verificado_nao_publica_preco(self):
        response = self.client.put("/api/v1/perfil/personal-trainer/", {
            "telefone": "923444555", "preco_hora": "5000.00", "modalidades_pagamento": ["multicaixa"],
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.pt.refresh_from_db()
        self.assertIsNone(self.pt.preco_hora)

    def test_pt_nao_verificado_edita_biografia(self):
        response = self.client.put("/api/v1/perfil/personal-trainer/", {
            "telefone": "923444555", "biografia": "Ola",
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_pt_verificado_publica_preco(self):
        self.pt.estado_verificacao = PersonalTrainer.EstadoVerificacao.VERIFICADO
        self.pt.save()
        response = self.client.put("/api/v1/perfil/personal-trainer/", {
            "telefone": "923444555", "preco_hora": "5000.00", "modalidades_pagamento": ["multicaixa"],
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.pt.refresh_from_db()
        self.assertEqual(self.pt.modalidades_pagamento, ["multicaixa"])

    def test_permissao_so_aceita_pt_verificado(self):
        request = type("R", (), {"user": self.utilizador})()
        self.assertFalse(IsPersonalTrainerVerificado().has_permission(request, None))
        self.pt.estado_verificacao = PersonalTrainer.EstadoVerificacao.VERIFICADO
        self.pt.save()
        request = type("R", (), {"user": Utilizador.objects.get(pk=self.utilizador.pk)})()
        self.assertTrue(IsPersonalTrainerVerificado().has_permission(request, None))


class AppleLoginTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("core.views.validar_id_token_apple")
    def test_cria_utilizador_novo(self, mock_validar):
        mock_validar.return_value = {"email": "apple@example.com", "email_verified": "true"}
        response = self.client.post("/api/v1/auth/apple/", {"id_token": "fake"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["novo_utilizador"])
        self.assertIn("session_token", response.data)
        utilizador = Utilizador.objects.get(email="apple@example.com")
        self.assertTrue(utilizador.is_active)
        self.assertTrue(UtilizadorAluno.objects.filter(utilizador=utilizador).exists())

    @patch("core.views.validar_id_token_apple")
    def test_reutiliza_utilizador_existente(self, mock_validar):
        Utilizador.objects.create_user(username="x", email="apple@example.com", password="SenhaForte123!", tipo="aluno")
        mock_validar.return_value = {"email": "apple@example.com", "email_verified": True}
        response = self.client.post("/api/v1/auth/apple/", {"id_token": "fake"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["novo_utilizador"])

    def test_sem_id_token_falha(self):
        response = self.client.post("/api/v1/auth/apple/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("core.views.validar_id_token_apple", side_effect=AppleTokenInvalido("assinatura invalida"))
    def test_token_invalido_falha(self, _):
        response = self.client.post("/api/v1/auth/apple/", {"id_token": "fake"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("core.views.validar_id_token_apple")
    def test_email_nao_verificado_falha(self, mock_validar):
        mock_validar.return_value = {"email": "apple@example.com", "email_verified": "false"}
        response = self.client.post("/api/v1/auth/apple/", {"id_token": "fake"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ValidarIdTokenAppleTestCase(TestCase):
    """Testa a validacao real do JWT com um par de chaves RSA local (sem rede)."""

    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        self.chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def _token(self, **extra):
        import time
        import jwt
        claims = {"iss": "https://appleid.apple.com", "aud": "com.exemplo.exercita",
                  "exp": int(time.time()) + 300, "email": "a@b.com"}
        claims.update(extra)
        return jwt.encode(claims, self.chave, algorithm="RS256")

    def _validar(self, token):
        from core.services import apple
        with patch.dict("os.environ", {"APPLE_CLIENT_ID": "com.exemplo.exercita"}), \
                patch.object(apple._jwks_client, "get_signing_key_from_jwt") as mock_key:
            mock_key.return_value.key = self.chave.public_key()
            return apple.validar_id_token_apple(token)

    def test_token_valido(self):
        self.assertEqual(self._validar(self._token())["email"], "a@b.com")

    def test_audience_errada(self):
        with self.assertRaises(AppleTokenInvalido):
            self._validar(self._token(aud="outra.app"))

    def test_issuer_errado(self):
        with self.assertRaises(AppleTokenInvalido):
            self._validar(self._token(iss="https://evil.example.com"))

    def test_token_expirado(self):
        with self.assertRaises(AppleTokenInvalido):
            self._validar(self._token(exp=1))
