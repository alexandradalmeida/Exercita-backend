from datetime import time

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .models import Certificacao, PersonalTrainer, SlotDisponibilidade, Utilizador


def criar_pt(username, verificado=True, **campos):
    utilizador = Utilizador.objects.create_user(
        username=username, email=f"{username}@example.com", password="SenhaForte123!",
        tipo="personal_trainer", is_active=True,
    )
    estado = PersonalTrainer.EstadoVerificacao.VERIFICADO if verificado else PersonalTrainer.EstadoVerificacao.PENDENTE
    return PersonalTrainer.objects.create(utilizador=utilizador, estado_verificacao=estado, **campos)


class CertificacoesTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.pt = criar_pt("pt1")
        self.client.force_authenticate(self.pt.utilizador)
        self.url = "/api/v1/perfil/personal-trainer/certificacoes/"

    def test_cria_e_lista_proprias(self):
        r = self.client.post(self.url, {"nome": "NSCA-CPT", "ano_obtencao": 2020}, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        outro = criar_pt("pt2")
        Certificacao.objects.create(personal_trainer=outro, nome="Outra")
        r = self.client.get(self.url)
        self.assertEqual([c["nome"] for c in r.data["results"]], ["NSCA-CPT"])

    def test_pt_nao_verificado_nao_pode(self):
        nv = criar_pt("pt3", verificado=False)
        self.client.force_authenticate(nv.utilizador)
        r = self.client.post(self.url, {"nome": "X"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_nao_edita_certificacao_de_outro(self):
        outro = criar_pt("pt2")
        c = Certificacao.objects.create(personal_trainer=outro, nome="Outra")
        r = self.client.delete(f"{self.url}{c.id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_aluno_nao_pode(self):
        aluno = Utilizador.objects.create_user(username="al", password="SenhaForte123!", tipo="aluno", is_active=True)
        self.client.force_authenticate(aluno)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)


class SlotsTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.pt = criar_pt("pt1")
        self.client.force_authenticate(self.pt.utilizador)
        self.url = "/api/v1/perfil/personal-trainer/slots/"

    def test_cria_slot(self):
        r = self.client.post(self.url, {
            "dia_semana": 0, "hora_inicio": "08:00", "hora_fim": "09:00", "capacidade": 3,
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["vagas_disponiveis"], 3)

    def test_hora_fim_tem_de_ser_posterior(self):
        r = self.client.post(self.url, {"dia_semana": 0, "hora_inicio": "09:00", "hora_fim": "08:00"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_vagas_ocupadas_nao_editavel(self):
        r = self.client.post(self.url, {
            "dia_semana": 1, "hora_inicio": "08:00", "hora_fim": "09:00", "capacidade": 2, "vagas_ocupadas": 2,
        }, format="json")
        self.assertEqual(r.data["vagas_ocupadas"], 0)

    def test_capacidade_nao_baixa_das_vagas_ocupadas(self):
        slot = SlotDisponibilidade.objects.create(
            personal_trainer=self.pt, dia_semana=2, hora_inicio=time(8), hora_fim=time(9), capacidade=3, vagas_ocupadas=2)
        r = self.client.patch(f"{self.url}{slot.id}/", {"capacidade": 1}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)