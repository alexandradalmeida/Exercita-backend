from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
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