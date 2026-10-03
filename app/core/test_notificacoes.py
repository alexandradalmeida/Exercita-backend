from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Notificacao, SlotDisponibilidade
from .services.notificacoes import enviar_lembretes, notificar
from .services.sessoes import contratar_personal_trainer
from .test_contratar import proxima_data
from .test_libertacao import LibertacaoBase
from .test_marketplace import criar_pt
from .test_sessoes import criar_aluno


class EventosNotificacaoTestCase(LibertacaoBase):
    def msgs(self, utilizador):
        return list(Notificacao.objects.filter(utilizador=utilizador).values_list("mensagem", flat=True))

    def test_contratar_notifica_pt(self):
        self.assertTrue(any("Nova sessao agendada" in m for m in self.msgs(self.pt.utilizador)))

    def test_pagamento_aprovado_via_webhook_notifica_ambos(self):
        from .test_pagamentos import SEGREDO, segredo_de_teste
        from .services.multicaixa import assinar
        import json
        self.pag.refresh_from_db()
        self.pag.estado = "pendente"
        self.pag.referencia_multicaixa = "REF1"
        self.pag.save()
        Notificacao.objects.all().delete()
        corpo = json.dumps({"referencia": "REF1", "estado": "aprovado"}).encode()
        with patch("core.services.multicaixa.config", side_effect=segredo_de_teste):
            APIClient().post(f"/api/v1/payments/{self.pag.id}/webhook/", corpo, content_type="application/json",
                             HTTP_X_SIGNATURE=assinar(corpo, SEGREDO))
        self.assertTrue(any("aprovado" in m for m in self.msgs(self.aluno.utilizador)))
        self.assertTrue(any("aprovado" in m for m in self.msgs(self.pt.utilizador)))

    def test_ciclo_da_sessao_notifica_aluno_e_pt(self):
        self.realizar()
        self.assertTrue(any("confirmada" in m for m in self.msgs(self.aluno.utilizador)))
        self.assertTrue(any("realizada" in m for m in self.msgs(self.aluno.utilizador)))
        self.release()
        self.assertTrue(any("libertados" in m for m in self.msgs(self.pt.utilizador)))

    def test_cancelamento_notifica_a_outra_parte(self):
        Notificacao.objects.all().delete()
        c = APIClient()
        c.force_authenticate(self.aluno.utilizador)
        c.patch(f"/api/v1/sessions/{self.sessao.id}/", {"acao": "cancelar"}, format="json")
        self.assertTrue(any("cancelada" in m for m in self.msgs(self.pt.utilizador)))
        self.assertEqual(self.msgs(self.aluno.utilizador), [])

    def test_reagendamento_notifica_pt(self):
        Notificacao.objects.all().delete()
        slot2 = SlotDisponibilidade.objects.create(
            personal_trainer=self.pt, dia_semana=4, hora_inicio=time(8), hora_fim=time(9), capacidade=1)
        c = APIClient()
        c.force_authenticate(self.aluno.utilizador)
        r = c.patch(f"/api/v1/sessions/{self.sessao.id}/", {
            "acao": "reagendar", "slot_id": slot2.id,
            "data_hora": (proxima_data(4) + timedelta(weeks=1)).isoformat()}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(any("reagendou" in m for m in self.msgs(self.pt.utilizador)))


class EnvioTestCase(LibertacaoBase):
    def test_envia_email_depois_do_commit(self):
        self.aluno.utilizador.email = "aluno@example.com"
        self.aluno.utilizador.save()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            notificar(self.aluno.utilizador, "ola", "Assunto")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Assunto")

    def test_falha_no_email_nao_propaga(self):
        with patch("core.services.notificacoes.send_mail", side_effect=OSError("smtp")):
            with self.captureOnCommitCallbacks(execute=True):
                n = notificar(self.aluno.utilizador, "ola")
        self.assertTrue(Notificacao.objects.filter(pk=n.pk).exists())


class LembretesTestCase(LibertacaoBase):
    def test_lembra_sessoes_nas_proximas_24h_uma_vez(self):
        self.sessao.data_hora = timezone.now() + timedelta(hours=10)
        self.sessao.save()
        Notificacao.objects.all().delete()
        self.assertEqual(enviar_lembretes(), 1)
        self.assertEqual(Notificacao.objects.count(), 2)  # aluno + PT
        self.assertEqual(enviar_lembretes(), 0)

    def test_ignora_sessoes_distantes_ou_canceladas(self):
        self.assertEqual(enviar_lembretes(), 0)  # sessao daqui a >1 semana
        self.sessao.data_hora = timezone.now() + timedelta(hours=5)
        self.sessao.save()
        self.sessao.transitar("cancelada")
        self.assertEqual(enviar_lembretes(), 0)


class EndpointsNotificacaoTestCase(LibertacaoBase):
    def setUp(self):
        super().setUp()
        self.c = APIClient()
        self.c.force_authenticate(self.pt.utilizador)

    def test_lista_so_as_proprias(self):
        r = self.c.get("/api/v1/notifications/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["results"])
        self.assertEqual(Notificacao.objects.filter(utilizador=self.pt.utilizador).count(), r.data["count"])

    def test_marcar_lida_e_filtro(self):
        n = Notificacao.objects.filter(utilizador=self.pt.utilizador).first()
        r = self.c.patch(f"/api/v1/notifications/{n.id}/", {"lida": True}, format="json")
        self.assertTrue(r.data["lida"])
        nao_lidas = self.c.get("/api/v1/notifications/", {"lida": "false"}).data["results"]
        self.assertNotIn(n.id, [x["id"] for x in nao_lidas])

    def test_nao_altera_notificacao_alheia(self):
        n = Notificacao.objects.filter(utilizador=self.aluno.utilizador).first() or notificar(self.aluno.utilizador, "x")
        self.assertEqual(self.c.patch(f"/api/v1/notifications/{n.id}/", {"lida": True}, format="json").status_code, 404)

    def test_ler_todas(self):
        r = self.c.post("/api/v1/notifications/read-all/")
        self.assertGreaterEqual(r.data["marcadas"], 1)
        self.assertEqual(self.c.get("/api/v1/notifications/", {"lida": "false"}).data["count"], 0)

    def test_exige_autenticacao(self):
        self.assertEqual(APIClient().get("/api/v1/notifications/").status_code, 401)
