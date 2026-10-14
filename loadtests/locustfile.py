"""Teste de carga HTTP com Locust contra um ambiente real (staging).

    pip install locust
    locust -f loadtests/locustfile.py --host https://staging.exemplo.ao --users 1000 --spawn-rate 50

Variaveis de ambiente: LOAD_USERNAME / LOAD_PASSWORD (conta de aluno de teste ja confirmada).
NAO apontar para producao: o fluxo de escrita cria sessoes reais.
"""
import os
import random

from locust import HttpUser, between, task

ESPECIALIDADES = ["yoga", "musculacao", "pilates", "crossfit", "boxe"]


class AlunoTipico(HttpUser):
    wait_time = between(1, 5)

    def on_start(self):
        r = self.client.post("/api/v1/auth/login/", json={
            "username": os.environ["LOAD_USERNAME"], "password": os.environ["LOAD_PASSWORD"]})
        r.raise_for_status()
        self.client.headers["Authorization"] = f"Bearer {r.json()['session_token']}"
        self.trainers = []

    @task(5)
    def pesquisar_trainers(self):
        r = self.client.get("/api/v1/trainers/", params={"q": f"quero treinar {random.choice(ESPECIALIDADES)}"},
                            name="/trainers/?q")
        if r.ok:
            self.trainers = [t["id"] for t in r.json().get("results", [])]

    @task(3)
    def ver_perfil_e_disponibilidade(self):
        if self.trainers:
            pid = random.choice(self.trainers)
            self.client.get(f"/api/v1/trainers/{pid}/profile/", name="/trainers/[id]/profile/")
            self.client.get(f"/api/v1/trainers/{pid}/availability/", name="/trainers/[id]/availability/")

    @task(2)
    def notificacoes(self):
        self.client.get("/api/v1/notifications/", params={"lida": "false"}, name="/notifications/")

    @task(1)
    def catalogo_loja(self):
        self.client.get("/api/v1/shop/products/", name="/shop/products/")

    @task(1)
    def ginasios_perto(self):
        self.client.get("/api/v1/gyms/", params={"lat": -8.8383, "lng": 13.2344, "raio_km": 15}, name="/gyms/?lat&lng")
