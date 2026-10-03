from datetime import time, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from .models import Notificacao, ReservaGinasio
from .test_contratar import proxima_data
from .test_ginasios import criar_ginasio, criar_utilizador
from .test_marketplace import criar_pt
from .test_sessoes import criar_aluno

SEGUNDA_6_22 = {"0": [["06:00", "22:00"]]}


class ReservaGinasioTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("reserva_aluno")
        self.client.force_authenticate(self.aluno.utilizador)
        self.g = criar_ginasio("Fit", horarios=SEGUNDA_6_22)
        self.url = f"/api/v1/gyms/{self.g.id}/bookings/"
        self.segunda_10h = proxima_data(0, time(10, 0))

    def reservar(self, **extra):
        corpo = {"tipo": "aula_experimental", "data_hora": self.segunda_10h.isoformat()}
        corpo.update(extra)
        return self.client.post(self.url, corpo, format="json")

    def test_reserva_aula_experimental(self):
        r = self.reservar()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["estado"], "confirmada")
        self.assertEqual(r.data["ginasio_nome"], "Fit")
        self.assertTrue(Notificacao.objects.filter(utilizador=self.aluno.utilizador).exists())

    def test_visita_nao_tem_limite_de_uma(self):
        self.assertEqual(self.reservar(tipo="visita").status_code, 201)
        outra = self.segunda_10h + timedelta(weeks=1)
        self.assertEqual(self.reservar(tipo="visita", data_hora=outra.isoformat()).status_code, 201)

    def test_so_uma_aula_experimental_ativa_por_ginasio(self):
        self.reservar()
        outra = self.segunda_10h + timedelta(weeks=1)
        self.assertEqual(self.reservar(data_hora=outra.isoformat()).status_code, 409)

    def test_mesma_hora_duplicada(self):
        self.reservar(tipo="visita")
        self.assertEqual(self.reservar(tipo="visita").status_code, 409)

    def test_fora_do_horario(self):
        noite = proxima_data(0, time(23, 0))
        self.assertEqual(self.reservar(data_hora=noite.isoformat()).status_code, 400)
        terca = proxima_data(1, time(10, 0))  # sem horario definido para terca = fechado
        self.assertEqual(self.reservar(data_hora=terca.isoformat()).status_code, 400)

    def test_fecho_e_exclusivo(self):
        self.assertEqual(self.reservar(data_hora=proxima_data(0, time(22, 0)).isoformat()).status_code, 400)
        self.assertEqual(self.reservar(data_hora=proxima_data(0, time(6, 0)).isoformat()).status_code, 201)

    def test_sem_horarios_definidos_aceita_qualquer_hora(self):
        g = criar_ginasio("Aberto sempre")
        r = self.client.post(f"/api/v1/gyms/{g.id}/bookings/", {
            "tipo": "visita", "data_hora": proxima_data(3, time(3, 0)).isoformat()}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_data_no_passado(self):
        passado = self.segunda_10h - timedelta(weeks=3)
        self.assertEqual(self.reservar(data_hora=passado.isoformat()).status_code, 400)

    def test_ginasio_nao_parceiro(self):
        g = criar_ginasio("Pend", estado="pendente")
        r = self.client.post(f"/api/v1/gyms/{g.id}/bookings/", {
            "tipo": "visita", "data_hora": self.segunda_10h.isoformat()}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_tipo_invalido(self):
        self.assertEqual(self.reservar(tipo="spa").status_code, 400)

    def test_pt_acompanhante_tem_de_trabalhar_no_ginasio(self):
        pt = criar_pt("ptreserva")
        self.assertEqual(self.reservar(personal_trainer=pt.id).status_code, 400)
        self.g.personal_trainers.add(pt)
        r = self.reservar(personal_trainer=pt.id)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(Notificacao.objects.filter(utilizador=pt.utilizador).exists())

    def test_so_alunos_reservam(self):
        pt = criar_pt("ptnaoreserva")
        self.client.force_authenticate(pt.utilizador)
        self.assertEqual(self.reservar().status_code, 403)


class MinhasReservasTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("reservas_lista")
        self.g = criar_ginasio("Fit")
        self.reserva = ReservaGinasio.objects.create(
            aluno=self.aluno, ginasio=self.g, tipo="visita", data_hora=proxima_data(0) + timedelta(weeks=1))
        self.client.force_authenticate(self.aluno.utilizador)

    def test_lista_so_as_proprias(self):
        outro = criar_aluno("outro_reservas")
        ReservaGinasio.objects.create(
            aluno=outro, ginasio=self.g, tipo="visita", data_hora=proxima_data(1) + timedelta(weeks=1))
        r = self.client.get("/api/v1/gym-bookings/")
        self.assertEqual([x["id"] for x in r.data["results"]], [self.reserva.id])

    def test_cancelar(self):
        r = self.client.patch(f"/api/v1/gym-bookings/{self.reserva.id}/", {"acao": "cancelar"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["estado"], "cancelada")
        self.assertEqual(self.client.patch(
            f"/api/v1/gym-bookings/{self.reserva.id}/", {"acao": "cancelar"}, format="json").status_code, 409)

    def test_cancelar_liberta_a_regra_da_aula_experimental(self):
        self.reserva.tipo = "aula_experimental"
        self.reserva.save()
        self.client.patch(f"/api/v1/gym-bookings/{self.reserva.id}/", {"acao": "cancelar"}, format="json")
        r = self.client.post(f"/api/v1/gyms/{self.g.id}/bookings/", {
            "tipo": "aula_experimental", "data_hora": (proxima_data(2) + timedelta(weeks=1)).isoformat()},
            format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_nao_cancela_reserva_passada(self):
        from django.utils import timezone
        self.reserva.data_hora = timezone.now() - timedelta(hours=1)
        self.reserva.save()
        r = self.client.patch(f"/api/v1/gym-bookings/{self.reserva.id}/", {"acao": "cancelar"}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_acao_invalida_e_reserva_alheia(self):
        self.assertEqual(self.client.patch(
            f"/api/v1/gym-bookings/{self.reserva.id}/", {"acao": "x"}, format="json").status_code, 400)
        self.client.force_authenticate(criar_aluno("intruso_reserva").utilizador)
        self.assertEqual(self.client.patch(
            f"/api/v1/gym-bookings/{self.reserva.id}/", {"acao": "cancelar"}, format="json").status_code, 404)
