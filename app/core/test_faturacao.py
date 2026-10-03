import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from .models import DocumentoFinanceiro, Encomenda
from .services.faturacao import emitir_documentos
from .services.multicaixa import assinar
from .test_carrinho import LojaBase
from .test_ginasios import criar_admin
from .test_pagamentos import SEGREDO, PagamentoBase, segredo_de_teste

DOCS = "/api/v1/billing/documents/"


def webhook(pagamento, estado="aprovado"):
    corpo = json.dumps({"referencia": pagamento.referencia_multicaixa, "estado": estado}).encode()
    with patch("core.services.multicaixa.config", side_effect=segredo_de_teste):
        return APIClient().post(f"/api/v1/payments/{pagamento.id}/webhook/", corpo,
                                content_type="application/json", HTTP_X_SIGNATURE=assinar(corpo, SEGREDO))


class FaturacaoSessaoTestCase(PagamentoBase):
    def setUp(self):
        super().setUp()
        self.pag.referencia_multicaixa = "REF-S"
        self.pag.save()

    def test_aprovacao_emite_fatura_e_recibo(self):
        self.assertEqual(self.pag.documentos.count(), 0)
        webhook(self.pag)
        docs = {d.tipo: d for d in self.pag.documentos.all()}
        self.assertEqual(set(docs), {"FT", "RC"})
        self.assertEqual(docs["FT"].cliente, self.aluno.utilizador)
        self.assertEqual(docs["FT"].total, Decimal("5000.00"))
        self.assertIn("ptpag", docs["FT"].linhas[0]["descricao"])

    def test_pagamento_recusado_nao_emite(self):
        webhook(self.pag, "recusado")
        self.assertEqual(DocumentoFinanceiro.objects.count(), 0)

    def test_webhook_repetido_nao_duplica(self):
        webhook(self.pag)
        webhook(self.pag)
        self.assertEqual(DocumentoFinanceiro.objects.count(), 2)

    def test_emitir_e_idempotente(self):
        self.pag.transitar("aprovado")
        emitir_documentos(self.pag)
        emitir_documentos(self.pag)
        self.assertEqual(DocumentoFinanceiro.objects.count(), 2)

    def test_numeracao_sequencial_por_tipo(self):
        self.pag.transitar("aprovado")
        docs = {d.tipo: d.numero for d in emitir_documentos(self.pag)}
        ano = docs["FT"].split()[1].split("/")[0]
        self.assertEqual(docs["FT"], f"FT {ano}/0001")
        self.assertEqual(docs["RC"], f"RC {ano}/0001")


class FaturacaoEncomendaTestCase(LojaBase):
    def test_encomenda_paga_emite_documentos_com_linhas(self):
        self.adicionar(self.whey, 2)
        self.adicionar(self.tshirt, 1)
        enc = Encomenda.objects.get(pk=self.checkout().data["id"])
        pag = enc.pagamentos.get()
        pag.referencia_multicaixa = "REF-E"
        pag.save()
        webhook(pag)
        fatura = pag.documentos.get(tipo="FT")
        self.assertEqual([l["descricao"] for l in fatura.linhas], ["Whey", "T-shirt"])
        self.assertEqual(fatura.total, Decimal("560.00"))
        self.assertEqual(fatura.linhas[0]["subtotal"], "500.00")


class DocumentosApiTestCase(PagamentoBase):
    def setUp(self):
        super().setUp()
        self.pag.referencia_multicaixa = "REF-A"
        self.pag.save()
        webhook(self.pag)

    def test_aluno_lista_os_seus_documentos_e_filtra_por_tipo(self):
        r = self.client.get(DOCS)
        self.assertEqual(r.data["count"], 2)
        self.assertEqual(self.client.get(DOCS, {"tipo": "rc"}).data["count"], 1)

    def test_detalhe(self):
        doc = DocumentoFinanceiro.objects.get(tipo="FT")
        r = self.client.get(f"{DOCS}{doc.id}/")
        self.assertEqual(r.data["numero"], doc.numero)
        self.assertEqual(r.data["pagamento_id"], self.pag.id)

    def test_nao_ve_documentos_alheios(self):
        from .test_sessoes import criar_aluno
        outro = APIClient()
        outro.force_authenticate(criar_aluno("alheio_fatura").utilizador)
        self.assertEqual(outro.get(DOCS).data["count"], 0)
        doc = DocumentoFinanceiro.objects.first()
        self.assertEqual(outro.get(f"{DOCS}{doc.id}/").status_code, 404)

    def test_admin_ve_todos(self):
        admin = APIClient()
        admin.force_authenticate(criar_admin("fat_admin"))
        self.assertEqual(admin.get(DOCS).data["count"], 2)

    def test_somente_leitura_e_autenticado(self):
        self.assertEqual(self.client.post(DOCS, {}, format="json").status_code, 405)
        self.assertEqual(APIClient().get(DOCS).status_code, 401)
