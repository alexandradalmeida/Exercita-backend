from rest_framework.test import APIClient

from .test_libertacao import LibertacaoBase
from .test_sessoes import criar_aluno


class CalendarioTestCase(LibertacaoBase):
    def get(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c.get(f"/api/v1/sessions/{self.sessao.id}/calendar/")

    def test_ics_valido(self):
        r = self.get(self.aluno.utilizador)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/calendar; charset=utf-8")
        corpo = r.content.decode()
        for linha in ("BEGIN:VCALENDAR", "BEGIN:VEVENT", f"UID:sessao-{self.sessao.id}@exercita", "STATUS:CONFIRMED",
                      "END:VEVENT", "END:VCALENDAR"):
            self.assertIn(linha, corpo)
        self.assertIn("DTSTART:", corpo)
        self.assertTrue(corpo.endswith("\r\n"))

    def test_duracao_vem_do_slot(self):
        corpo = self.get(self.aluno.utilizador).content.decode()
        inicio = next(l for l in corpo.split("\r\n") if l.startswith("DTSTART:"))[8:]
        fim = next(l for l in corpo.split("\r\n") if l.startswith("DTEND:"))[6:]
        self.assertEqual(int(fim[9:11]) - int(inicio[9:11]), 1)  # slot 08:00-09:00

    def test_sessao_cancelada(self):
        self.sessao.transitar("cancelada")
        self.assertIn("STATUS:CANCELLED", self.get(self.aluno.utilizador).content.decode())

    def test_pt_tambem_exporta_e_terceiros_nao(self):
        self.assertEqual(self.get(self.pt.utilizador).status_code, 200)
        self.assertEqual(self.get(criar_aluno("alheio_c").utilizador).status_code, 404)
