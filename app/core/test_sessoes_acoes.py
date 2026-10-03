from datetime import time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Pagamento, Sessao, SlotDisponibilidade
from .services.sessoes import contratar_personal_trainer
from .test_contratar import proxima_data
from .test_marketplace import criar_pt
from .test_sessoes import criar_aluno


class AcoesSessaoTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = criar_aluno("acoes")
        self.pt = criar_pt("ptacoes", preco_hora=Decimal("5000"))
        self.slot = SlotDisponibilidade.objects.create(
            personal_trainer=self.pt, dia_semana=2, hora_inicio=time(8), hora_fim=time(9), capacidade=2)
        self.slot2 = SlotDisponibilidade.objects.create(
            personal_trainer=self.pt, dia_semana=4, hora_inicio=time(8), hora_fim=time(9), capacidade=1)
        self.sessao, self.pag = contratar_personal_trainer(
            self.aluno, self.pt, self.slot, proxima_data(2) + timedelta(weeks=1), "individual")

    def patch(self, user, **corpo):
        self.client.force_authenticate(user)
        return self.client.patch(f"/api/v1/sessions/{self.sessao.id}/", corpo, format="json")

    def pagar(self):
        self.pag.transitar("aprovado", data_aprovacao=timezone.now())

    def vagas(self, slot):
        slot.refresh_from_db()
        return slot.vagas_ocupadas

    # --- cancelamento ---
    def test_aluno_cancela_com_antecedencia_reembolsa(self):
        self.pagar()
        r = self.patch(self.aluno.utilizador, acao="cancelar")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["estado"], "cancelada")
        self.assertTrue(r.data["reembolsado"])
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.estado, "reembolsado")
        self.assertEqual(self.vagas(self.slot), 0)

    def test_aluno_cancela_fora_da_janela_nao_reembolsa(self):
        self.pagar()
        self.sessao.data_hora = timezone.now() + timedelta(hours=5)
        self.sessao.save()
        r = self.patch(self.aluno.utilizador, acao="cancelar")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["reembolsado"])
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.estado, "aprovado")

    def test_janela_definida_pelo_pt(self):
        self.pt.janela_cancelamento_horas = 1
        self.pt.save()
        self.pagar()
        self.sessao.data_hora = timezone.now() + timedelta(hours=5)
        self.sessao.save()
        self.assertTrue(self.patch(self.aluno.utilizador, acao="cancelar").data["reembolsado"])

    def test_pt_cancela_sempre_reembolsa(self):
        self.pagar()
        self.sessao.data_hora = timezone.now() + timedelta(hours=1)
        self.sessao.save()
        self.assertTrue(self.patch(self.pt.utilizador, acao="cancelar").data["reembolsado"])

    def test_cancelar_com_pagamento_pendente_recusa_pagamento(self):
        self.patch(self.aluno.utilizador, acao="cancelar")
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.estado, "recusado")

    def test_nao_cancela_duas_vezes(self):
        self.patch(self.aluno.utilizador, acao="cancelar")
        self.assertEqual(self.patch(self.aluno.utilizador, acao="cancelar").status_code, 409)

    def test_terceiro_nao_ve_sessao(self):
        self.assertEqual(self.patch(criar_aluno("intruso").utilizador, acao="cancelar").status_code, 404)

    # --- reagendamento ---
    def test_reagendar_muda_slot_e_vagas(self):
        nova = proxima_data(4) + timedelta(weeks=1)
        r = self.patch(self.aluno.utilizador, acao="reagendar", slot_id=self.slot2.id, data_hora=nova.isoformat())
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["slot"], self.slot2.id)
        self.assertEqual(self.vagas(self.slot), 0)
        self.assertEqual(self.vagas(self.slot2), 1)

    def test_reagendar_para_slot_lotado(self):
        self.slot2.vagas_ocupadas = 1
        self.slot2.save()
        r = self.patch(self.aluno.utilizador, acao="reagendar", slot_id=self.slot2.id,
                       data_hora=(proxima_data(4) + timedelta(weeks=1)).isoformat())
        self.assertEqual(r.status_code, 409)

    def test_reagendar_dentro_da_janela_recusado(self):
        self.sessao.data_hora = timezone.now() + timedelta(hours=3)
        self.sessao.save()
        r = self.patch(self.aluno.utilizador, acao="reagendar", slot_id=self.slot2.id,
                       data_hora=proxima_data(4).isoformat())
        self.assertEqual(r.status_code, 409)

    def test_reagendar_exige_campos(self):
        self.assertEqual(self.patch(self.aluno.utilizador, acao="reagendar").status_code, 400)

    def test_pt_nao_reagenda(self):
        r = self.patch(self.pt.utilizador, acao="reagendar", slot_id=self.slot2.id,
                       data_hora=proxima_data(4).isoformat())
        self.assertEqual(r.status_code, 403)

    # --- avanco pelo PT ---
    def test_pt_confirma_so_depois_de_pago(self):
        self.assertEqual(self.patch(self.pt.utilizador, acao="confirmar").status_code, 409)
        self.pagar()
        r = self.patch(self.pt.utilizador, acao="confirmar")
        self.assertEqual(r.data["estado"], "confirmada")

    def test_fluxo_completo_libera_vaga(self):
        self.pagar()
        for acao, estado in (("confirmar", "confirmada"), ("iniciar", "em_curso"), ("concluir", "realizada")):
            self.assertEqual(self.patch(self.pt.utilizador, acao=acao).data["estado"], estado)
        self.assertEqual(self.vagas(self.slot), 0)

    def test_nao_se_salta_estados(self):
        self.pagar()
        self.assertEqual(self.patch(self.pt.utilizador, acao="concluir").status_code, 409)

    def test_aluno_nao_avanca_sessao(self):
        self.pagar()
        self.assertEqual(self.patch(self.aluno.utilizador, acao="confirmar").status_code, 403)

    def test_acao_invalida(self):
        self.assertEqual(self.patch(self.aluno.utilizador, acao="apagar").status_code, 400)
