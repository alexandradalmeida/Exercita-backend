from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .models import Pagamento, PersonalTrainer, Sessao, TransicaoInvalida, Utilizador, UtilizadorAluno
from .services.pagamentos import calcular_comissao
from .test_marketplace import criar_pt

E = Sessao.EstadoSessao


def criar_aluno(username="aluno_s"):
    u = Utilizador.objects.create_user(username=username, password="SenhaForte123!", tipo="aluno", is_active=True)
    return UtilizadorAluno.objects.create(utilizador=u)


class MaquinaEstadosSessaoTestCase(TestCase):
    def setUp(self):
        self.sessao = Sessao.objects.create(
            aluno=criar_aluno(), personal_trainer=criar_pt("ptsm"), data_hora=timezone.now())

    def test_estado_inicial_agendada(self):
        self.assertEqual(self.sessao.estado, E.AGENDADA)

    def test_fluxo_completo(self):
        for novo in (E.CONFIRMADA, E.EM_CURSO, E.REALIZADA, E.AVALIADA):
            self.sessao.transitar(novo)
        self.sessao.refresh_from_db()
        self.assertEqual(self.sessao.estado, E.AVALIADA)

    def test_cancelar_so_antes_de_em_curso(self):
        self.sessao.transitar(E.CONFIRMADA)
        self.sessao.transitar(E.CANCELADA)
        self.assertEqual(self.sessao.estado, E.CANCELADA)

    def test_transicoes_invalidas(self):
        for destino in (E.EM_CURSO, E.REALIZADA, E.AVALIADA):
            with self.assertRaises(TransicaoInvalida):
                self.sessao.transitar(destino)
        self.sessao.transitar(E.CANCELADA)
        with self.assertRaises(TransicaoInvalida):
            self.sessao.transitar(E.CONFIRMADA)

    def test_nao_se_cancela_sessao_em_curso_ou_realizada(self):
        self.sessao.transitar(E.CONFIRMADA)
        self.sessao.transitar(E.EM_CURSO)
        self.assertFalse(self.sessao.pode_transitar(E.CANCELADA))

    def test_janela_cancelamento_por_omissao(self):
        self.assertEqual(self.sessao.personal_trainer.janela_cancelamento_horas, 24)


class MaquinaEstadosPagamentoTestCase(TestCase):
    def setUp(self):
        self.P = Pagamento
        self.pag = Pagamento.objects.create(valor=Decimal("1000"))

    def test_aprovado_e_libertado(self):
        self.pag.transitar(self.P.EstadoPagamento.APROVADO)
        self.pag.transitar(self.P.EstadoPagamento.LIBERTADO)
        self.assertEqual(self.pag.estado, "libertado")

    def test_aprovado_pode_ser_reembolsado(self):
        self.pag.transitar(self.P.EstadoPagamento.APROVADO)
        self.pag.transitar(self.P.EstadoPagamento.REEMBOLSADO)

    def test_transicoes_invalidas(self):
        for destino in ("libertado", "reembolsado"):
            with self.assertRaises(TransicaoInvalida):
                self.pag.transitar(destino)
        self.pag.transitar("recusado")
        with self.assertRaises(TransicaoInvalida):
            self.pag.transitar("aprovado")

    def test_transitar_grava_campos_extra(self):
        agora = timezone.now()
        self.pag.transitar("aprovado", data_aprovacao=agora)
        self.pag.refresh_from_db()
        self.assertEqual(self.pag.data_aprovacao, agora)


class ComissaoTestCase(TestCase):
    def test_comissao_por_omissao_15_por_cento(self):
        comissao, liquido = calcular_comissao("5000")
        self.assertEqual(comissao, Decimal("750.00"))
        self.assertEqual(liquido, Decimal("4250.00"))

    def test_arredondamento_e_soma_exata(self):
        comissao, liquido = calcular_comissao("33.33")
        self.assertEqual(comissao, Decimal("5.00"))
        self.assertEqual(comissao + liquido, Decimal("33.33"))

    @patch("core.services.pagamentos.config", return_value="10")
    def test_percentagem_configuravel(self, _):
        self.assertEqual(calcular_comissao("200")[0], Decimal("20.00"))
