"""Testes end-to-end dos fluxos criticos, usando apenas a API HTTP (sem tocar nos modelos para preparar estado)."""
import json
import re
from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Utilizador
from .services.multicaixa import assinar
from .test_contratar import proxima_data
from .test_pagamentos import SEGREDO, segredo_de_teste

SENHA = "SenhaForte123!"
V1 = "/api/v1"


class ClienteApi:
    """Pequeno cliente que guarda o token de sessao, como faria a app movel."""

    def __init__(self):
        self.http = APIClient()
        self.refresh = None

    def autenticar(self, token):
        self.http.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def __getattr__(self, metodo):
        if metodo in ("get", "post", "put", "patch", "delete"):
            def chamar(caminho, dados=None, **extra):
                if metodo in ("get", "delete") and dados is not None and metodo == "get":
                    return self.http.get(V1 + caminho, dados, **extra)
                return getattr(self.http, metodo)(V1 + caminho, dados, format="json", **extra)
            return chamar
        raise AttributeError(metodo)


class E2EBase(TestCase):
    def registar_e_entrar(self, username, tipo):
        api = ClienteApi()
        r = api.post("/users/", {"username": username, "email": f"{username}@example.com", "password": SENHA,
                                 "tipo": tipo, "telefone": "923000000"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(api.post("/auth/login/", {"username": username, "password": SENHA}).status_code, 400)  # por confirmar
        mensagem = next(m for m in mail.outbox if username in m.body)
        link = re.search(r"http://\S+/api/v1/users/confirm-email/\?uid=\S+&token=\S+", mensagem.body).group(0)
        self.assertEqual(self.client.get(link.replace("http://localhost:8000", "")).status_code, 200)
        r = api.post("/auth/login/", {"username": username, "password": SENHA})
        self.assertEqual(r.status_code, 200, r.data)
        api.autenticar(r.data["session_token"])
        api.refresh = r.data["refresh_token"]
        return api, r.data["utilizador"]["id"]


class FluxoCompletoTestCase(E2EBase):
    """registo -> verificacao -> publicacao -> marketplace -> agendamento -> pagamento -> sessao -> avaliacao."""

    def test_fluxo_critico_ponta_a_ponta(self):
        pt, pt_user_id = self.registar_e_entrar("e2e_pt", "personal_trainer")
        aluno, _ = self.registar_e_entrar("e2e_aluno", "aluno")

        admin_u = Utilizador.objects.create_user(username="e2e_admin", password=SENHA, tipo="aluno", is_staff=True, is_active=True)
        admin = ClienteApi()
        admin.autenticar(admin.post("/auth/login/", {"username": "e2e_admin", "password": SENHA}).data["session_token"])

        # 1. PT nao verificado nao consegue publicar (BR-01) nem aparece no marketplace
        pt_id = pt.get("/perfil/personal-trainer/").data["id"]
        r = pt.put("/perfil/personal-trainer/", {"telefone": "923000000", "preco_hora": "5000.00"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(pt.post("/perfil/personal-trainer/slots/", {
            "dia_semana": 2, "hora_inicio": "08:00", "hora_fim": "09:00", "capacidade": 2}).status_code, 403)
        self.assertEqual(aluno.get("/trainers/").data["count"], 0)

        # 2. o admin verifica e o PT publica perfil, certificacao e horario
        self.assertEqual(admin.post(f"/personal-trainers/{pt_id}/verificar/").status_code, 200)
        r = pt.put("/perfil/personal-trainer/", {
            "telefone": "923000000", "especialidade": "Yoga", "localizacao": "Luanda",
            "biografia": "Aulas de yoga para todos os niveis", "preco_hora": "5000.00",
            "modalidades_pagamento": ["multicaixa"]})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(pt.post("/perfil/personal-trainer/certificacoes/", {"nome": "RYT-200"}).status_code, 201)
        r = pt.post("/perfil/personal-trainer/slots/", {
            "dia_semana": 2, "hora_inicio": "08:00", "hora_fim": "09:00", "capacidade": 2})
        self.assertEqual(r.status_code, 201, r.data)
        slot_id = r.data["id"]

        # 3. o aluno encontra o PT (filtros e matching) e consulta o perfil publico
        r = aluno.get("/trainers/", {"especialidade": "yoga", "localizacao": "luanda", "com_vagas": "true"})
        self.assertEqual([t["id"] for t in r.data["results"]], [pt_id])
        self.assertEqual(r.data["results"][0]["vagas_disponiveis"], 2)
        self.assertEqual(aluno.get("/trainers/", {"q": "quero fazer yoga"}).data["results"][0]["id"], pt_id)
        perfil = aluno.get(f"/trainers/{pt_id}/profile/").data
        self.assertEqual(perfil["certificacoes"][0]["nome"], "RYT-200")
        self.assertNotIn("telefone", perfil)
        self.assertEqual(aluno.post("/favorites/", {"trainer_id": pt_id}).status_code, 201)

        # 4. agendamento: sessao agendada + pagamento pendente com comissao
        data = proxima_data(2, time(8, 0)) + timedelta(weeks=1)
        r = aluno.post("/sessions/", {"trainer_id": pt_id, "slot_id": slot_id, "data_hora": data.isoformat()})
        self.assertEqual(r.status_code, 201, r.data)
        sessao_id, pagamento = r.data["id"], r.data["pagamentos"][0]
        self.assertEqual((r.data["estado"], pagamento["estado"]), ("agendada", "pendente"))
        self.assertEqual(Decimal(pagamento["comissao_plataforma"]), Decimal("750.00"))
        self.assertEqual(aluno.get(f"/trainers/{pt_id}/availability/").data[0]["vagas_disponiveis"], 1)

        # 5. o PT nao pode confirmar antes do pagamento
        self.assertEqual(pt.patch(f"/sessions/{sessao_id}/", {"acao": "confirmar"}).status_code, 409)

        # 6. pagamento: o aluno inicia, o gateway chama o webhook (assinado)
        r = aluno.post("/payments/", {"sessao_id": sessao_id})
        self.assertEqual(r.status_code, 201, r.data)
        referencia = r.data["referencia_multicaixa"]
        corpo = json.dumps({"referencia": referencia, "estado": "aprovado"}).encode()
        with patch("core.services.multicaixa.config", side_effect=segredo_de_teste):
            r = APIClient().post(f"{V1}/payments/{pagamento['id']}/webhook/", corpo, content_type="application/json",
                                 HTTP_X_SIGNATURE=assinar(corpo, SEGREDO))
        self.assertEqual(r.status_code, 200, r.content)
        faturas = aluno.get("/billing/documents/").data
        self.assertEqual(sorted(d["tipo"] for d in faturas["results"]), ["FT", "RC"])

        # 7. ciclo da sessao pelo PT; pagamento so e libertado depois de realizada
        self.assertEqual(aluno.post(f"/payments/{pagamento['id']}/release/").status_code, 409)
        for acao, estado in (("confirmar", "confirmada"), ("iniciar", "em_curso"), ("concluir", "realizada")):
            self.assertEqual(pt.patch(f"/sessions/{sessao_id}/", {"acao": acao}).data["estado"], estado)
        self.assertEqual(aluno.get(f"/sessions/{sessao_id}/calendar/").status_code, 200)

        # 8. o aluno confirma a realizacao: libertacao ao PT (BR-03)
        r = aluno.post(f"/payments/{pagamento['id']}/release/")
        self.assertEqual((r.status_code, r.data["estado"]), (200, "libertado"))

        # 9. avaliacao mutua e reputacao (BR-05)
        self.assertEqual(aluno.post(f"/sessions/{sessao_id}/reviews/", {"classificacao": 5, "comentario": "Excelente"}).status_code, 201)
        self.assertEqual(pt.post(f"/sessions/{sessao_id}/reviews/", {"classificacao": 4}).status_code, 201)
        self.assertEqual(aluno.get(f"/sessions/{sessao_id}/").data["estado"], "avaliada")
        perfil = aluno.get(f"/trainers/{pt_id}/profile/").data
        self.assertEqual(perfil["avaliacao_media"], 5.0)  # so conta a avaliacao recebida pelo PT
        self.assertEqual([a["comentario"] for a in perfil["avaliacoes"]], ["Excelente"])

        # 10. notificacoes geradas ao longo do fluxo; relatorio do admin reflete a receita
        self.assertTrue(pt.get("/notifications/").data["count"] >= 4)
        receita = admin.get("/admin/reports/platform/").data["receita"]
        self.assertEqual(Decimal(str(receita["comissoes_plataforma"])), Decimal("750"))

        # 11. logout invalida o refresh token
        self.assertEqual(aluno.post("/auth/logout/", {"refresh_token": aluno.refresh}).status_code, 200)
        self.assertEqual(APIClient().post(f"{V1}/auth/refresh/", {"refresh": aluno.refresh}, format="json").status_code, 401)


class FluxoCancelamentoComReembolsoTestCase(E2EBase):
    """Cancelamento pelo aluno com reembolso, e libertacao do slot para outro aluno."""

    def test_cancelar_sessao_paga_reembolsa_e_liberta_vaga(self):
        pt, _ = self.registar_e_entrar("e2e_pt2", "personal_trainer")
        aluno, _ = self.registar_e_entrar("e2e_aluno2", "aluno")
        outro, _ = self.registar_e_entrar("e2e_aluno3", "aluno")
        Utilizador.objects.create_user(username="e2e_admin2", password=SENHA, tipo="aluno", is_staff=True, is_active=True)
        admin = ClienteApi()
        admin.autenticar(admin.post("/auth/login/", {"username": "e2e_admin2", "password": SENHA}).data["session_token"])
        pt_id = pt.get("/perfil/personal-trainer/").data["id"]
        admin.post(f"/personal-trainers/{pt_id}/verificar/")
        pt.put("/perfil/personal-trainer/", {"telefone": "1", "preco_hora": "3000.00"})
        slot_id = pt.post("/perfil/personal-trainer/slots/", {
            "dia_semana": 4, "hora_inicio": "10:00", "hora_fim": "11:00", "capacidade": 1}).data["id"]
        data = (proxima_data(4, time(10, 0)) + timedelta(weeks=1)).isoformat()

        sessao = aluno.post("/sessions/", {"trainer_id": pt_id, "slot_id": slot_id, "data_hora": data}).data
        self.assertEqual(outro.post("/sessions/", {"trainer_id": pt_id, "slot_id": slot_id, "data_hora": data}).status_code, 409)

        referencia = aluno.post("/payments/", {"sessao_id": sessao["id"]}).data["referencia_multicaixa"]
        corpo = json.dumps({"referencia": referencia, "estado": "aprovado"}).encode()
        with patch("core.services.multicaixa.config", side_effect=segredo_de_teste):
            APIClient().post(f"{V1}/payments/{sessao['pagamentos'][0]['id']}/webhook/", corpo,
                             content_type="application/json", HTTP_X_SIGNATURE=assinar(corpo, SEGREDO))

        r = aluno.patch(f"/sessions/{sessao['id']}/", {"acao": "cancelar"})
        self.assertEqual((r.data["estado"], r.data["reembolsado"]), ("cancelada", True))
        self.assertEqual(r.data["pagamentos"][0]["estado"], "reembolsado")
        # a vaga ficou livre para outro aluno
        self.assertEqual(outro.post("/sessions/", {"trainer_id": pt_id, "slot_id": slot_id, "data_hora": data}).status_code, 201)


class FluxoLojaTestCase(E2EBase):
    """catalogo -> carrinho -> checkout -> pagamento -> envio -> entrega, com a administracao."""

    def test_compra_completa(self):
        aluno, _ = self.registar_e_entrar("e2e_cliente", "aluno")
        Utilizador.objects.create_user(username="e2e_admin3", password=SENHA, tipo="aluno", is_staff=True, is_active=True)
        admin = ClienteApi()
        admin.autenticar(admin.post("/auth/login/", {"username": "e2e_admin3", "password": SENHA}).data["session_token"])
        produto = admin.post("/shop/products/", {"nome": "Whey 1kg", "preco": "250.00", "stock": 3, "categoria": "suplemento"}).data

        self.assertEqual(aluno.post("/shop/cart/items/", {"produto_id": produto["id"], "quantidade": 4}).status_code, 409)
        self.assertEqual(aluno.post("/shop/cart/items/", {"produto_id": produto["id"], "quantidade": 2}).status_code, 201)
        enc = aluno.post("/shop/checkout/", {"morada_entrega": "Rua da Missao 1, Luanda"}).data
        self.assertEqual(Decimal(enc["total"]), Decimal("500.00"))
        self.assertEqual(aluno.get(f"/shop/products/{produto['id']}/").data["stock"], 1)

        referencia = aluno.post("/payments/", {"encomenda_id": enc["id"]}).data["referencia_multicaixa"]
        corpo = json.dumps({"referencia": referencia, "estado": "aprovado"}).encode()
        with patch("core.services.multicaixa.config", side_effect=segredo_de_teste):
            APIClient().post(f"{V1}/payments/{enc['pagamentos'][0]['id']}/webhook/", corpo,
                             content_type="application/json", HTTP_X_SIGNATURE=assinar(corpo, SEGREDO))
        self.assertEqual(aluno.get(f"/shop/orders/{enc['id']}/").data["estado"], "paga")

        admin.patch(f"/shop/orders/{enc['id']}/", {"acao": "preparar"})
        admin.patch(f"/shop/orders/{enc['id']}/", {"acao": "enviar", "codigo_rastreio": "AO-777"})
        final = admin.patch(f"/shop/orders/{enc['id']}/", {"acao": "entregar"}).data
        self.assertEqual(final["estado"], "entregue")
        detalhe = aluno.get(f"/shop/orders/{enc['id']}/").data
        self.assertEqual([e["estado"] for e in detalhe["rastreamento"]],
                         ["pendente_pagamento", "paga", "em_preparacao", "enviada", "entregue"])
        self.assertEqual(sorted(d["tipo"] for d in aluno.get("/billing/documents/").data["results"]), ["FT", "RC"])
