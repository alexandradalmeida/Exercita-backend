"""Teste de carga concorrente (em processo): varios clientes em simultaneo sobre uma base com volume realista.

Nao substitui um teste de carga HTTP contra o ambiente real (ver loadtests/README.md), mas deteta
regressoes de desempenho, consultas N+1 e erros sob concorrencia (RNF-01 e RNF-05).
"""
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import time as hora

from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (
    Avaliacao, Notificacao, PersonalTrainer, Sessao, SlotDisponibilidade, Utilizador, UtilizadorAluno,
)
from .services.embeddings import HashEmbeddings

N_TRAINERS = 3000
N_ALUNOS = 200
N_PEDIDOS = 600
TRABALHADORES = 16
LIMITE_SEGUNDOS = 2.0  # RNF-01
ESPECIALIDADES = ["yoga", "musculacao", "pilates", "crossfit", "boxe", "natacao", "corrida", "nutricao"]
CIDADES = ["Luanda", "Benguela", "Huambo", "Lubango"]


class CargaConcorrenteTestCase(TransactionTestCase):
    def setUp(self):
        rnd = random.Random(1)
        gerador = HashEmbeddings()
        pts_u = Utilizador.objects.bulk_create([
            Utilizador(username=f"cpt{i}", email=f"cpt{i}@x.com", tipo="personal_trainer", is_active=True)
            for i in range(N_TRAINERS)])
        pts = PersonalTrainer.objects.bulk_create([
            PersonalTrainer(
                utilizador=u, estado_verificacao="verificado", especialidade=(e := rnd.choice(ESPECIALIDADES)),
                localizacao=rnd.choice(CIDADES), biografia=f"treinador de {e}", preco_hora=rnd.randint(2000, 9000),
                modalidades_pagamento=["multicaixa"], embedding=gerador.gerar(e), classificacao_media=rnd.randint(30, 50) / 10,
                total_avaliacoes=rnd.randint(0, 80))
            for u in pts_u])
        SlotDisponibilidade.objects.bulk_create([
            SlotDisponibilidade(personal_trainer=pt, dia_semana=d, hora_inicio=hora(8), hora_fim=hora(9),
                                capacidade=4, vagas_ocupadas=rnd.randint(0, 4)) for pt in pts for d in range(3)])
        alunos_u = Utilizador.objects.bulk_create([
            Utilizador(username=f"caluno{i}", email=f"caluno{i}@x.com", tipo="aluno", is_active=True)
            for i in range(N_ALUNOS)])
        UtilizadorAluno.objects.bulk_create([UtilizadorAluno(utilizador=u) for u in alunos_u])
        Notificacao.objects.bulk_create([Notificacao(utilizador=u, mensagem="ola") for u in alunos_u for _ in range(20)])
        self.alunos = alunos_u
        self.pt_ids = [pt.id for pt in pts]
        # Os testes anteriores deixam linhas mortas (transacoes revertidas) e estatisticas velhas; em producao
        # o autovacuum trata disso. Aqui faz-se a manutencao a mao para medir o desempenho da aplicacao.
        with connection.cursor() as cursor:
            cursor.execute("VACUUM ANALYZE")

    def pedido(self, i):
        rnd = random.Random(i)
        client = APIClient()
        client.force_authenticate(rnd.choice(self.alunos))
        escolha = rnd.random()
        if escolha < 0.4:
            alvo = ("/api/v1/trainers/", {"q": f"treino de {rnd.choice(ESPECIALIDADES)}",
                                          "localizacao": rnd.choice(CIDADES), "avaliacao_minima": "4"})
        elif escolha < 0.6:
            alvo = (f"/api/v1/trainers/{rnd.choice(self.pt_ids)}/profile/", None)
        elif escolha < 0.8:
            alvo = (f"/api/v1/trainers/{rnd.choice(self.pt_ids)}/availability/", None)
        else:
            alvo = ("/api/v1/notifications/", {"lida": "false"})
        inicio = time.perf_counter()
        try:
            resposta = client.get(*alvo)
            return time.perf_counter() - inicio, resposta.status_code
        finally:
            connection.close()

    def executar_rodada(self):
        with ThreadPoolExecutor(max_workers=TRABALHADORES) as pool:
            resultados = list(pool.map(self.pedido, range(N_PEDIDOS)))
        duracoes = sorted(d for d, _ in resultados)
        return resultados, duracoes, duracoes[int(len(duracoes) * 0.95) - 1]

    def test_carga_concorrente(self):
        # ate 2 rodadas: um pico passageiro da maquina (outros processos) nao deve dar falso alarme,
        # mas uma regressao real de desempenho falha as duas
        for rodada in (1, 2):
            resultados, duracoes, p95 = self.executar_rodada()
            print(f"\n[CARGA #{rodada}] {N_TRAINERS} PTs, {N_PEDIDOS} pedidos, {TRABALHADORES} em simultaneo: "
                  f"p50={duracoes[len(duracoes) // 2]:.3f}s p95={p95:.3f}s max={duracoes[-1]:.3f}s")
            self.assertEqual([c for _, c in resultados if c != 200], [])  # sem erros em nenhuma rodada
            if p95 < LIMITE_SEGUNDOS:
                return
        self.fail(f"p95={p95:.3f}s >= {LIMITE_SEGUNDOS}s em duas rodadas consecutivas (RNF-01)")
