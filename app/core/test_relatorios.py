import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from .models import Encomenda, Pagamento, ParceriaPT, RemuneracaoParceria
from .services.faturacao import emitir_documentos
from .test_admin_utilizadores import criar_staff
from .test_carrinho import LojaBase
from .test_marketplace import criar_pt
from .test_pagamentos import PagamentoBase
from .test_sessoes import criar_aluno

PLATAFORMA = "/api/v1/admin/reports/platform/"
FINANCEIRO = "/api/v1/admin/reports/financial/"


class RelatorioBase(PagamentoBase):
    """Uma sessao paga (5000 Kz, comissao 750) + uma encomenda paga (500 Kz) + uma sessao reembolsada."""

    def setUp(self):
        super().setUp()
        agora = timezone.now()
        self.pag.transitar("aprovado", data_aprovacao=agora)
        emitir_documentos(self.pag)

        from .models import Sessao, SlotDisponibilidade
        from .test_contratar import proxima_data
        from .services.sessoes import contratar_personal_trainer
        self.sessao2, self.pag2 = contratar_personal_trainer(
            criar_aluno("rel_aluno2"), self.pt, self.slot, proxima_data(2) + timedelta(weeks=2), "individual")
        self.pag2.transitar("aprovado", data_aprovacao=agora)
        self.pag2.transitar("reembolsado")

        from .test_loja import criar_produto
        self.aluno_loja = criar_aluno("rel_loja")
        produto = criar_produto("Whey", "250.00", 10)
        from .services.loja import adicionar_ao_carrinho, checkout
        adicionar_ao_carrinho(self.aluno_loja, produto.id, 2)
        self.enc = checkout(self.aluno_loja, "Rua X")
        self.pag_enc = self.enc.pagamentos.get()
        self.pag_enc.transitar("aprovado", data_aprovacao=agora)
        emitir_documentos(self.pag_enc)

        self.admin = APIClient()
        self.admin.force_authenticate(criar_staff("rel_admin"))


class RelatorioPlataformaTestCase(RelatorioBase):
    def test_receita(self):
        r = self.admin.get(PLATAFORMA).data["receita"]
        self.assertEqual(Decimal(str(r["pagamentos_sessoes_bruto"])), Decimal("5000"))
        self.assertEqual(Decimal(str(r["comissoes_plataforma"])), Decimal("750"))
        self.assertEqual(Decimal(str(r["liquido_devido_a_pts"])), Decimal("4250"))
        self.assertEqual(Decimal(str(r["vendas_loja"])), Decimal("500"))
        self.assertEqual(Decimal(str(r["reembolsado"])), Decimal("5000"))  # sessao2 reembolsada
        self.assertEqual(Decimal(str(r["receita_plataforma"])), Decimal("1250"))

    def test_parcerias_entram_no_resultado(self):
        parceria = ParceriaPT.objects.create(personal_trainer=self.pt, estado="ativa",
                                             remuneracao_mensal=Decimal("300"), data_inicio=date(2026, 1, 1))
        RemuneracaoParceria.objects.create(parceria=parceria, mes=date(2026, 10, 1), valor=Decimal("300"))
        r = self.admin.get(PLATAFORMA).data["receita"]
        self.assertEqual(Decimal(str(r["custo_parcerias_registado"])), Decimal("300"))
        self.assertEqual(Decimal(str(r["resultado_apos_parcerias"])), Decimal("950"))

    def test_utilizadores_sessoes_e_encomendas(self):
        d = self.admin.get(PLATAFORMA).data
        self.assertEqual(d["utilizadores"]["por_tipo"]["aluno"], 4)  # pagador, rel_aluno2, rel_loja + o admin
        self.assertEqual(d["utilizadores"]["por_tipo"]["personal_trainer"], 1)
        self.assertEqual(d["utilizadores"]["suspensos"], 0)
        self.assertEqual(d["sessoes"]["total"], 2)
        self.assertEqual(d["sessoes"]["por_estado"], {"agendada": 2})
        self.assertEqual(d["encomendas"]["por_estado"], {"pendente_pagamento": 1})
        self.assertEqual(d["personal_trainers"]["por_estado"], {"verificado": 1})
        self.assertEqual(d["pagamentos_por_estado"], {"aprovado": 2, "reembolsado": 1})

    def test_suspensos_contados(self):
        u = criar_aluno("rel_susp").utilizador
        u.suspenso = True
        u.save()
        self.assertEqual(self.admin.get(PLATAFORMA).data["utilizadores"]["suspensos"], 1)

    def test_filtro_de_periodo(self):
        hoje = timezone.localdate()
        passado = self.admin.get(PLATAFORMA, {"de": "2020-01-01", "ate": "2020-12-31"}).data
        self.assertEqual(Decimal(str(passado["receita"]["receita_plataforma"])), Decimal("0"))
        self.assertEqual(passado["utilizadores"]["novos_no_periodo"], 0)
        self.assertEqual(passado["sessoes"]["total"], 0)
        self.assertGreater(passado["utilizadores"]["total"], 0)  # total e sempre o atual
        atual = self.admin.get(PLATAFORMA, {"de": hoje.isoformat(), "ate": hoje.isoformat()}).data
        self.assertEqual(Decimal(str(atual["receita"]["receita_plataforma"])), Decimal("1250"))

    def test_periodo_inclui_o_ultimo_dia(self):
        hoje = timezone.localdate().isoformat()
        d = self.admin.get(PLATAFORMA, {"ate": hoje}).data
        self.assertEqual(Decimal(str(d["receita"]["receita_plataforma"])), Decimal("1250"))

    def test_parametros_invalidos(self):
        self.assertEqual(self.admin.get(PLATAFORMA, {"de": "ontem"}).status_code, 400)
        self.assertEqual(self.admin.get(PLATAFORMA, {"de": "2026-10-10", "ate": "2026-10-01"}).status_code, 400)

    def test_so_admin(self):
        c = APIClient()
        c.force_authenticate(self.aluno.utilizador)
        self.assertEqual(c.get(PLATAFORMA).status_code, 403)
        self.assertEqual(APIClient().get(PLATAFORMA).status_code, 401)


class RelatorioFinanceiroTestCase(RelatorioBase):
    def linhas(self, **params):
        r = self.admin.get(FINANCEIRO, params)
        self.assertEqual(r.status_code, 200)
        return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))

    def test_csv_de_pagamentos(self):
        r = self.admin.get(FINANCEIRO)
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("relatorio-pagamentos.csv", r["Content-Disposition"])
        linhas = self.linhas()
        self.assertEqual(len(linhas), 3)
        sessao = next(l for l in linhas if l["pagamento_id"] == str(self.pag.id))
        self.assertEqual((sessao["tipo"], sessao["cliente"], sessao["personal_trainer"]), ("sessao", "pagador", "ptpag"))
        self.assertEqual((sessao["valor"], sessao["comissao_plataforma"], sessao["valor_liquido_pt"]),
                         ("5000.00", "750.00", "4250.00"))
        self.assertTrue(sessao["fatura"].startswith("FT "))
        loja = next(l for l in linhas if l["tipo"] == "encomenda")
        self.assertEqual((loja["cliente"], loja["comissao_plataforma"], loja["personal_trainer"]), ("rel_loja", "0.00", ""))

    def test_filtro_de_periodo(self):
        self.assertEqual(self.linhas(de="2020-01-01", ate="2020-12-31"), [])
        self.assertEqual(len(self.linhas(de=timezone.localdate().isoformat())), 3)

    def test_csv_de_parcerias(self):
        parceria = ParceriaPT.objects.create(personal_trainer=self.pt, estado="ativa", remuneracao_mensal=Decimal("300"))
        RemuneracaoParceria.objects.create(parceria=parceria, mes=date(2026, 10, 1), valor=Decimal("300"))
        linhas = self.linhas(tipo="parcerias")
        self.assertEqual(len(linhas), 1)
        self.assertEqual((linhas[0]["personal_trainer"], linhas[0]["mes"], linhas[0]["valor"]), ("ptpag", "2026-10", "300.00"))

    def test_tipo_invalido(self):
        self.assertEqual(self.admin.get(FINANCEIRO, {"tipo": "tudo"}).status_code, 400)

    def test_neutraliza_formulas_em_folhas_de_calculo(self):
        from .services.relatorios import _celula
        for perigoso in ("=1+1", "+cmd", "-2", "@SUM(A1)"):
            self.assertTrue(_celula(perigoso).startswith("'"))
        self.assertEqual(_celula("normal"), "normal")
        self.assertEqual(_celula(None), "")

    def test_username_malicioso_nao_vira_formula(self):
        u = self.aluno.utilizador
        u.username = "=HYPERLINK(1)"
        u.save()
        self.assertTrue(any(l["cliente"] == "'=HYPERLINK(1)" for l in self.linhas()))

    def test_so_admin(self):
        c = APIClient()
        c.force_authenticate(self.aluno.utilizador)
        self.assertEqual(c.get(FINANCEIRO).status_code, 403)
