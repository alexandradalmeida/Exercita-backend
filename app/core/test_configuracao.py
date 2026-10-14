from datetime import time, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from .models import ConfiguracaoPlataforma, PersonalTrainer, SlotDisponibilidade
from .services.pagamentos import calcular_comissao
from .services.sessoes import contratar_personal_trainer
from .test_admin_utilizadores import criar_staff
from .test_contratar import proxima_data
from .test_marketplace import criar_pt
from .test_qualidade import dar_notas
from .test_sessoes import criar_aluno

URL = "/api/v1/admin/config/"


class ConfiguracaoApiTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(criar_staff("cfg_admin"))

    def test_sem_overrides_mostra_valores_do_ambiente(self):
        r = self.client.get(URL)
        self.assertIsNone(r.data["comissao_percentagem"])
        self.assertEqual(Decimal(str(r.data["efetivos"]["comissao_percentagem"])), Decimal("15"))
        self.assertEqual(r.data["efetivos"]["qualidade_minimo_avaliacoes"], 5)

    def test_admin_altera_e_registo_fica_guardado(self):
        r = self.client.patch(URL, {"comissao_percentagem": "12.5"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(str(r.data["efetivos"]["comissao_percentagem"])), Decimal("12.5"))
        cfg = ConfiguracaoPlataforma.obter()
        self.assertEqual(cfg.comissao_percentagem, Decimal("12.50"))
        self.assertIsNotNone(cfg.atualizado_por)

    def test_null_volta_ao_valor_do_ambiente(self):
        self.client.patch(URL, {"comissao_percentagem": "30"}, format="json")
        r = self.client.patch(URL, {"comissao_percentagem": None}, format="json")
        self.assertEqual(Decimal(str(r.data["efetivos"]["comissao_percentagem"])), Decimal("15"))

    def test_validacoes(self):
        for corpo in ({"comissao_percentagem": "101"}, {"comissao_percentagem": "-1"},
                      {"qualidade_limiar_alerta": "6"}, {"qualidade_minimo_avaliacoes": 0},
                      {"qualidade_limiar_alerta": "3.0", "qualidade_limiar_suspensao": "3.5"}):
            self.assertEqual(self.client.patch(URL, corpo, format="json").status_code, 400, corpo)

    def test_suspensao_validada_contra_o_alerta_ja_guardado(self):
        self.client.patch(URL, {"qualidade_limiar_alerta": "3.0"}, format="json")
        self.assertEqual(self.client.patch(URL, {"qualidade_limiar_suspensao": "3.5"}, format="json").status_code, 400)

    def test_so_admin(self):
        c = APIClient()
        c.force_authenticate(criar_aluno("cfg_aluno").utilizador)
        self.assertEqual(c.get(URL).status_code, 403)
        self.assertEqual(c.patch(URL, {"comissao_percentagem": "1"}, format="json").status_code, 403)


class EfeitoDaConfiguracaoTestCase(TestCase):
    def test_nova_comissao_aplica_se_so_a_pagamentos_futuros(self):
        aluno = criar_aluno("cfg_cliente")
        pt = criar_pt("cfg_pt", preco_hora=Decimal("1000"))
        slot = SlotDisponibilidade.objects.create(
            personal_trainer=pt, dia_semana=2, hora_inicio=time(8), hora_fim=time(9), capacidade=5)
        _, antes = contratar_personal_trainer(aluno, pt, slot, proxima_data(2) + timedelta(weeks=1), "individual")
        ConfiguracaoPlataforma.objects.update_or_create(pk=1, defaults={"comissao_percentagem": Decimal("20")})
        _, depois = contratar_personal_trainer(
            criar_aluno("cfg_cliente2"), pt, slot, proxima_data(2) + timedelta(weeks=2), "individual")
        antes.refresh_from_db()
        self.assertEqual(antes.comissao_plataforma, Decimal("150.00"))
        self.assertEqual(depois.comissao_plataforma, Decimal("200.00"))

    def test_calcular_comissao_usa_a_configuracao(self):
        ConfiguracaoPlataforma.objects.update_or_create(pk=1, defaults={"comissao_percentagem": Decimal("0")})
        self.assertEqual(calcular_comissao("500"), (Decimal("0.00"), Decimal("500")))

    def test_limiares_de_qualidade_vem_da_configuracao(self):
        ConfiguracaoPlataforma.objects.update_or_create(pk=1, defaults={
            "qualidade_limiar_alerta": Decimal("4.5"), "qualidade_limiar_suspensao": Decimal("4.0"),
            "qualidade_minimo_avaliacoes": 2})
        pt = criar_pt("cfg_pt2")
        self.assertEqual(dar_notas(pt, [4, 3]), PersonalTrainer.EstadoVerificacao.SUSPENSO)
