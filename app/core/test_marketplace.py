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

def criar_avaliacao(pt, nota, n=[0]):
    from django.utils import timezone
    from .models import Avaliacao, Sessao, UtilizadorAluno
    n[0] += 1
    u = Utilizador.objects.create_user(username=f"aluno{n[0]}", password="SenhaForte123!", tipo="aluno", is_active=True)
    aluno = UtilizadorAluno.objects.create(utilizador=u)
    sessao = Sessao.objects.create(aluno=aluno, personal_trainer=pt, data_hora=timezone.now(), estado="realizada")
    return Avaliacao.objects.create(sessao=sessao, classificacao=nota, comentario="ok")


class PesquisaTrainersTestCase(TestCase):
    url = "/api/v1/trainers/"

    def setUp(self):
        self.client = APIClient()
        self.aluno = Utilizador.objects.create_user(username="procura", password="SenhaForte123!", tipo="aluno", is_active=True)
        self.client.force_authenticate(self.aluno)
        self.a = criar_pt("a", especialidade="Musculacao", localizacao="Luanda",
                          preco_hora=5000, modalidades_pagamento=["multicaixa"])
        self.b = criar_pt("b", especialidade="Yoga", localizacao="Benguela",
                          preco_hora=3000, modalidades_pagamento=["dinheiro"])
        self.nv = criar_pt("nv", verificado=False, especialidade="Musculacao", localizacao="Luanda")

    def ids(self, **params):
        r = self.client.get(self.url, params)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        return {x["id"] for x in r.data["results"]}

    def test_so_lista_verificados(self):
        self.assertEqual(self.ids(), {self.a.id, self.b.id})

    def test_filtros_especialidade_localizacao_modalidade(self):
        self.assertEqual(self.ids(especialidade="yoga"), {self.b.id})
        self.assertEqual(self.ids(localizacao="luanda"), {self.a.id})
        self.assertEqual(self.ids(modalidade_pagamento="dinheiro"), {self.b.id})

    def test_avaliacao_minima(self):
        criar_avaliacao(self.a, 5)
        criar_avaliacao(self.a, 4)
        criar_avaliacao(self.b, 2)
        self.assertEqual(self.ids(avaliacao_minima="4"), {self.a.id})
        r = self.client.get(self.url, {"especialidade": "musc"})
        self.assertEqual(r.data["results"][0]["avaliacao_media"], 4.5)
        self.assertEqual(r.data["results"][0]["total_avaliacoes"], 2)

    def test_vagas_e_lotacao(self):
        SlotDisponibilidade.objects.create(personal_trainer=self.a, dia_semana=0, hora_inicio=time(8), hora_fim=time(9), capacidade=2, vagas_ocupadas=2)
        SlotDisponibilidade.objects.create(personal_trainer=self.b, dia_semana=1, hora_inicio=time(8), hora_fim=time(9), capacidade=3, vagas_ocupadas=1)
        SlotDisponibilidade.objects.create(personal_trainer=self.b, dia_semana=2, hora_inicio=time(8), hora_fim=time(9), capacidade=1)
        r = {x["id"]: x for x in self.client.get(self.url).data["results"]}
        self.assertTrue(r[self.a.id]["lotacao_atingida"])
        self.assertEqual(r[self.a.id]["vagas_disponiveis"], 0)
        self.assertFalse(r[self.b.id]["lotacao_atingida"])
        self.assertEqual(r[self.b.id]["vagas_disponiveis"], 3)  # 4 - 1 ocupada
        self.assertEqual(self.ids(com_vagas="true"), {self.b.id})
        self.assertEqual(self.ids(dia_semana="0"), set())
        self.assertEqual(self.ids(dia_semana="1"), {self.b.id})

    def test_parametro_invalido(self):
        self.assertEqual(self.client.get(self.url, {"avaliacao_minima": "abc"}).status_code, 400)

    def test_exige_autenticacao(self):
        self.assertEqual(APIClient().get(self.url).status_code, 401)


class PerfilPublicoTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = Utilizador.objects.create_user(username="ver", password="SenhaForte123!", tipo="aluno", is_active=True)
        self.client.force_authenticate(self.aluno)
        self.pt = criar_pt("pub", especialidade="Pilates", preco_hora=4000)
        Certificacao.objects.create(personal_trainer=self.pt, nome="Pilates Mat")

    def test_perfil_publico_com_certificacoes_e_avaliacoes(self):
        criar_avaliacao(self.pt, 5)
        r = self.client.get(f"/api/v1/trainers/{self.pt.id}/profile/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["certificacoes"][0]["nome"], "Pilates Mat")
        self.assertEqual(r.data["avaliacao_media"], 5.0)
        self.assertEqual(len(r.data["avaliacoes"]), 1)
        self.assertNotIn("telefone", r.data)
        self.assertNotIn("email", r.data)

    def test_avaliacao_de_sessao_nao_realizada_nao_conta(self):
        av = criar_avaliacao(self.pt, 1)
        av.sessao.estado = "cancelada"
        av.sessao.save()
        r = self.client.get(f"/api/v1/trainers/{self.pt.id}/profile/")
        self.assertEqual(r.data["avaliacoes"], [])
        self.assertIsNone(r.data["avaliacao_media"])

    def test_pt_nao_verificado_nao_tem_perfil_publico(self):
        nv = criar_pt("nv2", verificado=False)
        self.assertEqual(self.client.get(f"/api/v1/trainers/{nv.id}/profile/").status_code, 404)

    def test_put_so_no_proprio_perfil(self):
        r = self.client.put(f"/api/v1/trainers/{self.pt.id}/profile/", {"telefone": "1", "biografia": "x"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_put_proprio_perfil(self):
        self.client.force_authenticate(self.pt.utilizador)
        r = self.client.put(f"/api/v1/trainers/{self.pt.id}/profile/",
                            {"telefone": "923", "biografia": "Nova bio", "localizacao": "Luanda"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.pt.refresh_from_db()
        self.assertEqual(self.pt.localizacao, "Luanda")

    def test_disponibilidade(self):
        SlotDisponibilidade.objects.create(personal_trainer=self.pt, dia_semana=3, hora_inicio=time(7), hora_fim=time(8), capacidade=2, vagas_ocupadas=1)
        r = self.client.get(f"/api/v1/trainers/{self.pt.id}/availability/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data[0]["vagas_disponiveis"], 1)

    def test_disponibilidade_de_nao_verificado_404(self):
        nv = criar_pt("nv3", verificado=False)
        self.assertEqual(self.client.get(f"/api/v1/trainers/{nv.id}/availability/").status_code, 404)
