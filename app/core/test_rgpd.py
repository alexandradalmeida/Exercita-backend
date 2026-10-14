import json
from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    Avaliacao, DocumentoFinanceiro, Favorito, HistoricoTreino, MetricaFisica, Notificacao, PersonalTrainer,
    Sessao, SlotDisponibilidade, Utilizador, UtilizadorAluno,
)
from .services.faturacao import emitir_documentos
from .services.multicaixa import assinar
from .test_contratar import proxima_data
from .test_marketplace import criar_avaliacao, criar_pt
from .test_pagamentos import SEGREDO, segredo_de_teste

SENHA = "SenhaForte123!"
EXPORT = "/api/v1/users/me/data-export/"
APAGAR = "/api/v1/users/me/"


def aluno_completo(username="rgpd_aluno"):
    u = Utilizador.objects.create_user(
        username=username, email=f"{username}@example.com", password=SENHA, tipo="aluno", is_active=True,
        telefone="923111222")
    aluno = UtilizadorAluno.objects.create(utilizador=u, objetivo="Perder peso")
    MetricaFisica.objects.create(aluno=aluno, data=timezone.localdate(), peso_kg=Decimal("80"))
    HistoricoTreino.objects.create(aluno=aluno, data=timezone.localdate(), tipo="corrida", duracao_minutos=30)
    Notificacao.objects.create(utilizador=u, mensagem="ola")
    return aluno


class ExportarDadosTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = aluno_completo()
        self.client.force_authenticate(self.aluno.utilizador)

    def test_exporta_json_para_download(self):
        r = self.client.get(EXPORT)
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        dados = json.loads(r.content)
        self.assertEqual(dados["conta"]["email"], "rgpd_aluno@example.com")
        self.assertEqual(dados["conta"]["telefone"], "923111222")  # desencriptado para o titular
        self.assertEqual(dados["perfil_aluno"]["objetivo"], "Perder peso")
        self.assertEqual(len(dados["metricas_fisicas"]), 1)
        self.assertEqual(len(dados["historico_treinos"]), 1)
        self.assertEqual(len(dados["notificacoes"]), 1)

    def test_nao_inclui_password_nem_dados_de_outros(self):
        outro = aluno_completo("rgpd_outro")
        texto = self.client.get(EXPORT).content.decode()
        self.assertNotIn("password", texto)
        self.assertNotIn(outro.utilizador.email, texto)

    def test_inclui_sessoes_pagamentos_e_documentos(self):
        from .services.sessoes import contratar_personal_trainer
        pt = criar_pt("rgpd_pt", preco_hora=Decimal("1000"))
        slot = SlotDisponibilidade.objects.create(personal_trainer=pt, dia_semana=2, hora_inicio=time(8), hora_fim=time(9))
        _, pag = contratar_personal_trainer(self.aluno, pt, slot, proxima_data(2) + timedelta(weeks=1), "individual")
        pag.transitar("aprovado", data_aprovacao=timezone.now())
        emitir_documentos(pag)
        dados = json.loads(self.client.get(EXPORT).content)
        self.assertEqual(len(dados["sessoes"]), 1)
        self.assertEqual(dados["sessoes"][0]["pagamentos"][0]["estado"], "aprovado")
        self.assertEqual(len(dados["documentos_financeiros"]), 2)

    def test_pt_exporta_perfil_e_sessoes_como_profissional(self):
        pt = criar_pt("rgpd_pt2", especialidade="Yoga")
        self.client.force_authenticate(pt.utilizador)
        dados = json.loads(self.client.get(EXPORT).content)
        self.assertEqual(dados["perfil_personal_trainer"]["especialidade"], "Yoga")
        self.assertNotIn("perfil_aluno", dados)

    def test_exige_autenticacao(self):
        self.assertEqual(APIClient().get(EXPORT).status_code, 401)


class ApagarContaTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.aluno = aluno_completo()
        self.u = self.aluno.utilizador
        self.client.force_authenticate(self.u)

    def apagar(self, password=SENHA):
        return self.client.delete(APAGAR, {"password": password}, format="json")

    def test_exige_password_correta(self):
        self.assertEqual(self.apagar("errada").status_code, 403)
        self.assertEqual(self.client.delete(APAGAR).status_code, 403)
        self.u.refresh_from_db()
        self.assertTrue(self.u.is_active)

    def test_anonimiza_conta_e_apaga_dados_pessoais(self):
        refresh = RefreshToken.for_user(self.u)
        Favorito.objects.create(aluno=self.aluno, personal_trainer=criar_pt("rgpd_fav"))
        self.assertEqual(self.apagar().status_code, 204)
        self.u.refresh_from_db()
        self.assertEqual((self.u.email, self.u.telefone), ("", ""))
        self.assertEqual(self.u.username, f"removido-{self.u.id}")
        self.assertFalse(self.u.is_active)
        self.assertFalse(self.u.has_usable_password())
        self.assertEqual(MetricaFisica.objects.count(), 0)
        self.assertEqual(HistoricoTreino.objects.count(), 0)
        self.assertEqual(Notificacao.objects.filter(utilizador=self.u).count(), 0)
        self.assertEqual(Favorito.objects.count(), 0)
        self.aluno.refresh_from_db()
        self.assertEqual(self.aluno.objetivo, "")
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=refresh["jti"]).exists())

    def test_nao_consegue_voltar_a_entrar(self):
        self.apagar()
        r = APIClient().post("/api/v1/auth/login/", {"username": "rgpd_aluno", "password": SENHA}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_o_username_fica_livre_para_novo_registo(self):
        self.apagar()
        r = APIClient().post("/api/v1/users/", {
            "username": "rgpd_aluno", "email": "rgpd_aluno@example.com", "password": SENHA, "tipo": "aluno"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_documentos_financeiros_ficam_mas_anonimizados(self):
        from .services.sessoes import contratar_personal_trainer
        pt = criar_pt("rgpd_pt3", preco_hora=Decimal("1000"))
        slot = SlotDisponibilidade.objects.create(personal_trainer=pt, dia_semana=2, hora_inicio=time(8), hora_fim=time(9))
        sessao, pag = contratar_personal_trainer(self.aluno, pt, slot, proxima_data(2) + timedelta(weeks=1), "individual")
        pag.transitar("aprovado", data_aprovacao=timezone.now())
        emitir_documentos(pag)
        sessao.transitar("cancelada")
        pag.transitar("reembolsado")
        self.assertEqual(self.apagar().status_code, 204)
        docs = DocumentoFinanceiro.objects.all()
        self.assertEqual(docs.count(), 2)  # conservacao legal
        self.assertTrue(all(d.cliente.email == "" for d in docs))

    def test_bloqueia_com_sessao_ativa(self):
        from .services.sessoes import contratar_personal_trainer
        pt = criar_pt("rgpd_pt4", preco_hora=Decimal("1000"))
        slot = SlotDisponibilidade.objects.create(personal_trainer=pt, dia_semana=2, hora_inicio=time(8), hora_fim=time(9))
        contratar_personal_trainer(self.aluno, pt, slot, proxima_data(2) + timedelta(weeks=1), "individual")
        r = self.apagar()
        self.assertEqual(r.status_code, 409)
        self.assertIn("sessoes", r.data["mensagem"])
        self.u.refresh_from_db()
        self.assertTrue(self.u.is_active)

    def test_bloqueia_com_encomenda_por_concluir(self):
        from .services.loja import adicionar_ao_carrinho, checkout
        from .test_loja import criar_produto
        produto = criar_produto("Whey", "10", 5)
        adicionar_ao_carrinho(self.aluno, produto.id, 1)
        checkout(self.aluno, "Rua X")
        self.assertEqual(self.apagar().status_code, 409)

    def test_pt_apagado_desaparece_do_marketplace_e_nao_e_contratavel(self):
        pt = criar_pt("rgpd_pt5", especialidade="Boxe", preco_hora=Decimal("1000"))
        slot = SlotDisponibilidade.objects.create(personal_trainer=pt, dia_semana=2, hora_inicio=time(8), hora_fim=time(9))
        Avaliacao  # noqa: B018  (import usado noutros testes)
        c = APIClient()
        c.force_authenticate(pt.utilizador)
        self.assertEqual(c.delete(APAGAR, {"password": SENHA}, format="json").status_code, 204)
        pt.refresh_from_db()
        self.assertEqual((pt.biografia, pt.especialidade, pt.preco_hora), ("", "", None))
        self.assertEqual(pt.certificacoes.count() + pt.slots_disponibilidade.count(), 0)
        self.client.force_authenticate(self.u)
        ids = [t["id"] for t in self.client.get("/api/v1/trainers/").data["results"]]
        self.assertNotIn(pt.id, ids)
        self.assertEqual(self.client.get(f"/api/v1/trainers/{pt.id}/profile/").status_code, 404)

    def test_pt_com_sessao_ativa_nao_apaga(self):
        from .services.sessoes import contratar_personal_trainer
        pt = criar_pt("rgpd_pt6", preco_hora=Decimal("1000"))
        slot = SlotDisponibilidade.objects.create(personal_trainer=pt, dia_semana=2, hora_inicio=time(8), hora_fim=time(9))
        contratar_personal_trainer(self.aluno, pt, slot, proxima_data(2) + timedelta(weeks=1), "individual")
        c = APIClient()
        c.force_authenticate(pt.utilizador)
        self.assertEqual(c.delete(APAGAR, {"password": SENHA}, format="json").status_code, 409)

    def test_admin_nao_se_apaga_por_aqui(self):
        staff = Utilizador.objects.create_user(username="rgpd_staff", password=SENHA, tipo="aluno", is_active=True, is_staff=True)
        self.client.force_authenticate(staff)
        self.assertEqual(self.apagar().status_code, 403)

    def test_comentarios_das_avaliacoes_feitas_sao_limpos(self):
        pt = criar_pt("rgpd_pt7")
        av = criar_avaliacao(pt, 4)
        autor = av.autor
        autor.set_password(SENHA)
        autor.save()
        UtilizadorAluno.objects.get(utilizador=autor)
        c = APIClient()
        c.force_authenticate(autor)
        self.assertEqual(c.delete(APAGAR, {"password": SENHA}, format="json").status_code, 204)
        av.refresh_from_db()
        self.assertEqual(av.comentario, "")
        self.assertEqual(av.classificacao, 4)  # a nota fica (reputacao do PT)


class SaudeTestCase(TestCase):
    def test_liveness_e_readiness(self):
        self.assertEqual(self.client.get("/api/health/").json(), {"estado": "ok"})
        r = self.client.get("/api/health/ready/")
        self.assertEqual((r.status_code, r.json()["base_de_dados"]), (200, "ok"))

    def test_readiness_devolve_503_sem_base_de_dados(self):
        with patch("core.views_saude.connection") as ligacao:
            ligacao.cursor.side_effect = Exception("db em baixo")
            r = self.client.get("/api/health/ready/")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["estado"], "indisponivel")

    def test_so_get(self):
        self.assertEqual(self.client.post("/api/health/").status_code, 405)


class ApagarContaComCreditoTestCase(TestCase):
    def test_bloqueia_com_credito_por_utilizar(self):
        from .models import CreditoAluno
        aluno = aluno_completo("rgpd_credito")
        CreditoAluno.objects.create(
            aluno=aluno, origem="cancelamento_tardio", valor=Decimal("1000"), valor_restante=Decimal("1000"),
            data_expiracao=timezone.now() + timedelta(days=30))
        c = APIClient()
        c.force_authenticate(aluno.utilizador)
        r = c.delete(APAGAR, {"password": SENHA}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("credito", r.data["mensagem"])

    def test_credito_expirado_nao_bloqueia(self):
        from .models import CreditoAluno
        aluno = aluno_completo("rgpd_credito2")
        CreditoAluno.objects.create(
            aluno=aluno, origem="cancelamento_tardio", valor=Decimal("1000"), valor_restante=Decimal("1000"),
            data_expiracao=timezone.now() - timedelta(days=1))
        c = APIClient()
        c.force_authenticate(aluno.utilizador)
        self.assertEqual(c.delete(APAGAR, {"password": SENHA}, format="json").status_code, 204)
