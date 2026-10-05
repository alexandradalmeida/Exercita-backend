from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Notificacao, ParceriaPT, RemuneracaoParceria
from .services.parcerias import gerar_remuneracoes
from .test_ginasios import criar_admin, criar_utilizador
from .test_marketplace import criar_pt


class CandidaturaTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.pt = criar_pt("parceiro1")
        self.client.force_authenticate(self.pt.utilizador)

    def candidatar(self, mensagem="Quero ser parceiro"):
        return self.client.post("/api/v1/partnerships/apply/", {"mensagem": mensagem}, format="json")

    def test_pt_candidata_se(self):
        r = self.candidatar()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["estado"], "pendente")
        self.assertIsNone(r.data["remuneracao_mensal"])

    def test_nao_candidata_duas_vezes(self):
        self.candidatar()
        self.assertEqual(self.candidatar().status_code, 409)

    def test_pt_nao_define_a_propria_remuneracao(self):
        self.client.post("/api/v1/partnerships/apply/", {"mensagem": "x", "remuneracao_mensal": "999999"}, format="json")
        self.assertIsNone(ParceriaPT.objects.get().remuneracao_mensal)

    def test_so_pt_ativo(self):
        self.pt.estado_verificacao = "suspenso"
        self.pt.save()
        self.assertEqual(self.candidatar().status_code, 403)
        self.client.force_authenticate(criar_pt("pendente_p", verificado=False).utilizador)
        self.assertEqual(self.candidatar().status_code, 403)

    def test_aluno_nao_candidata(self):
        self.client.force_authenticate(criar_utilizador("aluno_parc"))
        self.assertEqual(self.candidatar().status_code, 403)

    def test_minha_parceria(self):
        self.assertEqual(self.client.get("/api/v1/partnerships/me/").status_code, 404)
        self.candidatar()
        r = self.client.get("/api/v1/partnerships/me/")
        self.assertEqual(r.data["estado"], "pendente")
        self.assertEqual(r.data["remuneracoes"], [])


class GestaoAdminTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.pt = criar_pt("parceiro2")
        self.parceria = ParceriaPT.objects.create(personal_trainer=self.pt, mensagem="x")
        self.admin = APIClient()
        self.admin.force_authenticate(criar_admin("parc_admin"))

    def acao(self, acao, client=None, **corpo):
        return (client or self.admin).post(f"/api/v1/partnerships/{self.parceria.id}/{acao}/", corpo, format="json")

    def test_aprovar_define_remuneracao_e_notifica(self):
        r = self.acao("aprovar", remuneracao_mensal="150000.00")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["estado"], "ativa")
        self.assertEqual(Decimal(r.data["remuneracao_mensal"]), Decimal("150000.00"))
        self.assertIsNotNone(r.data["data_inicio"])
        self.assertTrue(Notificacao.objects.filter(utilizador=self.pt.utilizador, mensagem__contains="150000").exists())

    def test_aprovar_exige_remuneracao_positiva(self):
        self.assertEqual(self.acao("aprovar").status_code, 400)
        self.assertEqual(self.acao("aprovar", remuneracao_mensal="abc").status_code, 400)
        self.assertEqual(self.acao("aprovar", remuneracao_mensal="0").status_code, 400)

    def test_nao_aprova_duas_vezes(self):
        self.acao("aprovar", remuneracao_mensal="1000")
        self.assertEqual(self.acao("aprovar", remuneracao_mensal="1000").status_code, 409)

    def test_recusar_e_recandidatura(self):
        self.assertEqual(self.acao("recusar").data["estado"], "recusada")
        c = APIClient()
        c.force_authenticate(self.pt.utilizador)
        r = c.post("/api/v1/partnerships/apply/", {"mensagem": "outra vez"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["estado"], "pendente")

    def test_terminar_so_se_ativa(self):
        self.assertEqual(self.acao("terminar").status_code, 409)
        self.acao("aprovar", remuneracao_mensal="1000")
        r = self.acao("terminar")
        self.assertEqual(r.data["estado"], "terminada")
        self.assertIsNotNone(r.data["data_fim"])

    def test_acao_desconhecida(self):
        self.assertEqual(self.acao("apagar").status_code, 404)

    def test_so_admin(self):
        c = APIClient()
        c.force_authenticate(self.pt.utilizador)
        self.assertEqual(self.acao("aprovar", client=c, remuneracao_mensal="1").status_code, 403)
        self.assertEqual(c.get("/api/v1/partnerships/").status_code, 403)

    def test_admin_lista_com_filtro(self):
        self.assertEqual(self.admin.get("/api/v1/partnerships/").data["count"], 1)
        self.assertEqual(self.admin.get("/api/v1/partnerships/", {"estado": "ativa"}).data["count"], 0)


class RemuneracaoMensalTestCase(TestCase):
    def setUp(self):
        self.pt = criar_pt("parceiro3")
        self.parceria = ParceriaPT.objects.create(
            personal_trainer=self.pt, estado="ativa", remuneracao_mensal=Decimal("90000"), data_inicio=date(2026, 9, 15))

    def test_gera_para_o_mes_e_e_idempotente(self):
        self.assertEqual(gerar_remuneracoes(date(2026, 10, 3)), 1)
        self.assertEqual(gerar_remuneracoes(date(2026, 10, 20)), 0)
        r = RemuneracaoParceria.objects.get()
        self.assertEqual((r.mes, r.valor, r.estado), (date(2026, 10, 1), Decimal("90000"), "pendente"))

    def test_nao_gera_antes_do_inicio_nem_para_parcerias_inativas(self):
        self.assertEqual(gerar_remuneracoes(date(2026, 8, 1)), 0)
        self.parceria.estado = "terminada"
        self.parceria.save()
        self.assertEqual(gerar_remuneracoes(date(2026, 10, 1)), 0)

    def test_inicio_no_fim_do_mes_conta_nesse_mes(self):
        self.parceria.data_inicio = date(2026, 10, 31)
        self.parceria.save()
        self.assertEqual(gerar_remuneracoes(date(2026, 10, 1)), 1)

    def test_virada_de_ano(self):
        self.assertEqual(gerar_remuneracoes(date(2026, 12, 10)), 1)
        self.assertEqual(gerar_remuneracoes(date(2027, 1, 5)), 1)

    def test_valor_registado_nao_muda_se_a_remuneracao_mudar_depois(self):
        gerar_remuneracoes(date(2026, 10, 1))
        self.parceria.remuneracao_mensal = Decimal("1")
        self.parceria.save()
        self.assertEqual(RemuneracaoParceria.objects.get().valor, Decimal("90000"))

    def test_comando_de_gestao(self):
        out = StringIO()
        call_command("gerar_remuneracoes", stdout=out)
        self.assertIn("registada(s)", out.getvalue())

    def test_admin_marca_paga_e_pt_ve_historico(self):
        gerar_remuneracoes(date(2026, 10, 1))
        rem = RemuneracaoParceria.objects.get()
        admin = APIClient()
        admin.force_authenticate(criar_admin("rem_admin"))
        r = admin.post(f"/api/v1/partnerships/payouts/{rem.id}/pay/")
        self.assertEqual(r.data["estado"], "paga")
        self.assertEqual(admin.post(f"/api/v1/partnerships/payouts/{rem.id}/pay/").status_code, 409)
        pt = APIClient()
        pt.force_authenticate(self.pt.utilizador)
        hist = pt.get("/api/v1/partnerships/me/").data["remuneracoes"]
        self.assertEqual([h["estado"] for h in hist], ["paga"])
        self.assertTrue(Notificacao.objects.filter(utilizador=self.pt.utilizador, mensagem__contains="paga").exists())

    def test_so_admin_marca_paga(self):
        gerar_remuneracoes(date(2026, 10, 1))
        rem = RemuneracaoParceria.objects.get()
        c = APIClient()
        c.force_authenticate(self.pt.utilizador)
        self.assertEqual(c.post(f"/api/v1/partnerships/payouts/{rem.id}/pay/").status_code, 403)
