from datetime import datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import PersonalTrainer, Sessao, SlotDisponibilidade
from .test_marketplace import criar_pt
from .test_sessoes import criar_aluno


def proxima_data(dia_semana, hora=time(8, 0)):
    """Proxima ocorrencia futura do dia da semana, na hora indicada (fuso local)."""
    agora = timezone.localtime()
    dias = (dia_semana - agora.weekday()) % 7 or 7
    dia = (agora + timedelta(days=dias)).date()
    return timezone.make_aware(datetime.combine(dia, hora))


class ContratarSessaoTestCase(TestCase):
    url = "/api/v1/sessions/"

    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("contrata")
        self.client.force_authenticate(self.aluno.utilizador)
        self.pt = criar_pt("ptc", preco_hora=Decimal("5000"))
        self.slot = SlotDisponibilidade.objects.create(
            personal_trainer=self.pt, dia_semana=2, hora_inicio=time(8), hora_fim=time(9), capacidade=1)
        self.data = proxima_data(2)

    def corpo(self, **extra):
        corpo = {"trainer_id": self.pt.id, "slot_id": self.slot.id, "data_hora": self.data.isoformat()}
        corpo.update(extra)
        return corpo

    def test_contrata_sessao_individual(self):
        r = self.client.post(self.url, self.corpo(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["estado"], "agendada")
        self.assertEqual(Decimal(r.data["valor_total"]), Decimal("5000"))
        pag = r.data["pagamentos"][0]
        self.assertEqual(pag["estado"], "pendente")
        self.assertEqual(Decimal(pag["comissao_plataforma"]), Decimal("750.00"))
        self.assertEqual(Decimal(pag["valor_liquido_pt"]), Decimal("4250.00"))
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.vagas_ocupadas, 1)

    def test_pacote_multiplica_preco(self):
        self.slot.capacidade = 2
        self.slot.save()
        r = self.client.post(self.url, self.corpo(modalidade="pacote", quantidade_sessoes=4), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data["valor_total"]), Decimal("20000"))

    def test_pacote_exige_quantidade(self):
        r = self.client.post(self.url, self.corpo(modalidade="pacote"), format="json")
        self.assertEqual(r.status_code, 400)

    def test_lotacao_atingida(self):
        self.client.post(self.url, self.corpo(), format="json")
        outro = criar_aluno("contrata2")
        self.client.force_authenticate(outro.utilizador)
        r = self.client.post(self.url, self.corpo(), format="json")
        self.assertEqual(r.status_code, 409)

    def test_nao_duplica_mesmo_horario(self):
        self.slot.capacidade = 3
        self.slot.save()
        self.client.post(self.url, self.corpo(), format="json")
        r = self.client.post(self.url, self.corpo(), format="json")
        self.assertEqual(r.status_code, 409)

    def test_data_nao_corresponde_ao_slot(self):
        r = self.client.post(self.url, self.corpo(data_hora=proxima_data(3).isoformat()), format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(self.url, self.corpo(data_hora=proxima_data(2, time(10)).isoformat()), format="json")
        self.assertEqual(r.status_code, 400)

    def test_data_no_passado(self):
        passado = self.data - timedelta(weeks=3)
        r = self.client.post(self.url, self.corpo(data_hora=passado.isoformat()), format="json")
        self.assertEqual(r.status_code, 400)

    def test_slot_de_outro_pt(self):
        outro = criar_pt("ptc2", preco_hora=Decimal("1000"))
        slot = SlotDisponibilidade.objects.create(
            personal_trainer=outro, dia_semana=2, hora_inicio=time(8), hora_fim=time(9))
        r = self.client.post(self.url, self.corpo(slot_id=slot.id), format="json")
        self.assertEqual(r.status_code, 400)

    def test_pt_nao_verificado_ou_sem_preco(self):
        self.pt.preco_hora = None
        self.pt.save()
        self.assertEqual(self.client.post(self.url, self.corpo(), format="json").status_code, 400)
        self.pt.preco_hora = Decimal("5000")
        self.pt.estado_verificacao = PersonalTrainer.EstadoVerificacao.PENDENTE
        self.pt.save()
        self.assertEqual(self.client.post(self.url, self.corpo(), format="json").status_code, 404)

    def test_so_alunos_contratam(self):
        self.client.force_authenticate(self.pt.utilizador)
        self.assertEqual(self.client.post(self.url, self.corpo(), format="json").status_code, 403)

    def test_lista_sessoes_do_proprio_utilizador(self):
        self.client.post(self.url, self.corpo(), format="json")
        self.assertEqual(len(self.client.get(self.url).data["results"]), 1)
        self.client.force_authenticate(self.pt.utilizador)
        self.assertEqual(len(self.client.get(self.url).data["results"]), 1)
        self.client.force_authenticate(criar_aluno("outro").utilizador)
        self.assertEqual(self.client.get(self.url).data["results"], [])
