import random
import time
from datetime import time as hora

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Avaliacao, PersonalTrainer, Sessao, SlotDisponibilidade, Utilizador, UtilizadorAluno
from .services.avaliacoes import recalcular_reputacao
from .services.embeddings import HashEmbeddings

N_TRAINERS = 2000
N_PEDIDOS = 100
LIMITE_SEGUNDOS = 2.0  # RNF-01: < 2 s em 95% dos pedidos

ESPECIALIDADES = ["yoga", "musculacao", "pilates", "crossfit", "boxe", "natacao", "corrida", "nutricao"]
CIDADES = ["Luanda", "Benguela", "Huambo", "Lubango"]


class DesempenhoPesquisaTestCase(TestCase):
    """RNF-01: pesquisa de trainers (filtros + matching por embeddings) em < 2 s para 95% dos pedidos."""

    @classmethod
    def setUpTestData(cls):
        rnd = random.Random(42)
        gerador = HashEmbeddings()
        utilizadores = Utilizador.objects.bulk_create([
            Utilizador(username=f"perf{i}", email=f"perf{i}@example.com", tipo="personal_trainer", is_active=True)
            for i in range(N_TRAINERS)
        ])
        pts = []
        for u in utilizadores:
            esp = rnd.choice(ESPECIALIDADES)
            bio = f"treinador de {esp} com {rnd.randint(1, 20)} anos de experiencia"
            pts.append(PersonalTrainer(
                utilizador=u, estado_verificacao="verificado", especialidade=esp,
                localizacao=rnd.choice(CIDADES), biografia=bio, preco_hora=rnd.randint(2000, 9000),
                modalidades_pagamento=["multicaixa"], embedding=gerador.gerar(f"{esp} {bio}"),
            ))
        pts = PersonalTrainer.objects.bulk_create(pts)

        SlotDisponibilidade.objects.bulk_create([
            SlotDisponibilidade(personal_trainer=pt, dia_semana=d, hora_inicio=hora(8), hora_fim=hora(9),
                                capacidade=4, vagas_ocupadas=rnd.randint(0, 4))
            for pt in pts for d in range(3)
        ])

        aluno_u = Utilizador.objects.create_user(username="perfaluno", password="x", tipo="aluno", is_active=True)
        aluno = UtilizadorAluno.objects.create(utilizador=aluno_u)
        sessoes = Sessao.objects.bulk_create([
            Sessao(aluno=aluno, personal_trainer=pt, data_hora=timezone.now(), estado="realizada")
            for pt in pts for _ in range(2)
        ])
        Avaliacao.objects.bulk_create([
            Avaliacao(sessao=s, autor=aluno_u, avaliado=s.personal_trainer.utilizador, classificacao=rnd.randint(1, 5))
            for s in sessoes
        ])
        for pt in pts:
            recalcular_reputacao(pt)
        cls.aluno_u = aluno_u

    def test_p95_abaixo_de_2_segundos(self):
        client = APIClient()
        client.force_authenticate(self.aluno_u)
        rnd = random.Random(7)
        duracoes = []
        for _ in range(N_PEDIDOS):
            params = {"q": f"quero treinar {rnd.choice(ESPECIALIDADES)} em {rnd.choice(CIDADES)}"}
            if rnd.random() < 0.5:
                params["localizacao"] = rnd.choice(CIDADES)
            if rnd.random() < 0.5:
                params["avaliacao_minima"] = "3"
            if rnd.random() < 0.3:
                params["com_vagas"] = "true"
            inicio = time.perf_counter()
            r = client.get("/api/v1/trainers/", params)
            duracoes.append(time.perf_counter() - inicio)
            self.assertEqual(r.status_code, 200)

        duracoes.sort()
        p95 = duracoes[int(len(duracoes) * 0.95) - 1]
        print(f"\n[RNF-01] {N_TRAINERS} trainers, {N_PEDIDOS} pedidos: p95={p95:.3f}s max={duracoes[-1]:.3f}s")
        self.assertLess(p95, LIMITE_SEGUNDOS)