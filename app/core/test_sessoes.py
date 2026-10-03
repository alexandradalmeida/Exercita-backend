from django.test import TestCase
from django.utils import timezone

from .models import PersonalTrainer, Sessao, TransicaoInvalida, Utilizador, UtilizadorAluno
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