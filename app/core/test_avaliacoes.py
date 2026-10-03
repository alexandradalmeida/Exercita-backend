from decimal import Decimal

from rest_framework.test import APIClient

from .models import Avaliacao, Notificacao, Utilizador
from .test_libertacao import LibertacaoBase
from .test_sessoes import criar_aluno


class AvaliacaoBase(LibertacaoBase):
    def avaliar(self, user, nota=5, comentario="", sessao=None, **extra):
        c = APIClient()
        c.force_authenticate(user)
        corpo = {"classificacao": nota, "comentario": comentario, **extra}
        return c.post(f"/api/v1/sessions/{(sessao or self.sessao).id}/reviews/", corpo, format="json")


class AvaliarSessaoTestCase(AvaliacaoBase):
    def test_br05_so_sessoes_realizadas(self):
        self.assertEqual(self.avaliar(self.aluno.utilizador).status_code, 409)

    def test_aluno_avalia_pt_e_sessao_fica_avaliada(self):
        self.realizar()
        r = self.avaliar(self.aluno.utilizador, 4, "Bom treino")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["avaliado"], self.pt.utilizador.username)
        self.sessao.refresh_from_db()
        self.assertEqual(self.sessao.estado, "avaliada")

    def test_pt_avalia_aluno_sem_mudar_estado(self):
        self.realizar()
        r = self.avaliar(self.pt.utilizador, 3)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["avaliado"], self.aluno.utilizador.username)
        self.sessao.refresh_from_db()
        self.assertEqual(self.sessao.estado, "realizada")

    def test_avaliacao_mutua_nas_duas_direcoes(self):
        self.realizar()
        self.avaliar(self.aluno.utilizador, 5)
        self.avaliar(self.pt.utilizador, 4)
        c = APIClient()
        c.force_authenticate(self.aluno.utilizador)
        r = c.get(f"/api/v1/sessions/{self.sessao.id}/reviews/")
        self.assertEqual(len(r.data), 2)

    def test_uma_avaliacao_por_autor(self):
        self.realizar()
        self.avaliar(self.aluno.utilizador)
        self.assertEqual(self.avaliar(self.aluno.utilizador).status_code, 409)
        self.assertEqual(Avaliacao.objects.count(), 1)

    def test_classificacao_entre_1_e_5(self):
        self.realizar()
        for nota in (0, 6, -1):
            self.assertEqual(self.avaliar(self.aluno.utilizador, nota).status_code, 400)

    def test_terceiro_nao_avalia(self):
        self.realizar()
        self.assertEqual(self.avaliar(criar_aluno("alheio_a").utilizador).status_code, 404)

    def test_avaliado_e_notificado(self):
        self.realizar()
        self.avaliar(self.aluno.utilizador, 2)
        self.assertTrue(Notificacao.objects.filter(utilizador=self.pt.utilizador, mensagem__contains="2/5").exists())


class ReputacaoTestCase(AvaliacaoBase):
    def test_media_do_pt_atualiza_automaticamente(self):
        from .test_marketplace import criar_avaliacao
        criar_avaliacao(self.pt, 5)
        self.realizar()
        self.avaliar(self.aluno.utilizador, 2)
        self.pt.refresh_from_db()
        self.assertEqual(self.pt.classificacao_media, Decimal("3.50"))
        self.assertEqual(self.pt.total_avaliacoes, 2)

    def test_avaliacao_do_pt_ao_aluno_nao_conta_para_o_pt(self):
        self.realizar()
        self.avaliar(self.pt.utilizador, 1)
        self.pt.refresh_from_db()
        self.assertIsNone(self.pt.classificacao_media)
        self.assertEqual(self.pt.total_avaliacoes, 0)

    def test_perfil_publico_so_mostra_avaliacoes_ao_pt(self):
        self.realizar()
        self.avaliar(self.aluno.utilizador, 5, "otimo")
        self.avaliar(self.pt.utilizador, 1, "faltou")
        c = APIClient()
        c.force_authenticate(self.aluno.utilizador)
        r = c.get(f"/api/v1/trainers/{self.pt.id}/profile/")
        self.assertEqual([a["comentario"] for a in r.data["avaliacoes"]], ["otimo"])
        self.assertEqual(r.data["avaliacao_media"], 5.0)
