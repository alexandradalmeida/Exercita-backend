import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from .test_sessoes import criar_aluno

APP_DIR = Path(__file__).resolve().parent.parent
CHAVE_FORTE = "k" * 25 + "Z" * 25 + "9q8w7e6r5t4y3u2i1o0p"  # >= 50 caracteres e variada


def verificar_producao(**env):
    """Corre `manage.py check --deploy` com as definicoes de producao num processo isolado."""
    ambiente = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.production"}
    ambiente.pop("PYTHONPATH", None)
    ambiente.update(env)
    return subprocess.run([sys.executable, "manage.py", "check", "--deploy"], cwd=APP_DIR, env=ambiente,
                          capture_output=True, text=True, timeout=120)


class DefinicoesDeProducaoTestCase(TestCase):
    def test_recusa_arrancar_sem_allowed_hosts(self):
        r = verificar_producao(ALLOWED_HOSTS="", DJANGO_SECRET_KEY=CHAVE_FORTE)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ALLOWED_HOSTS", r.stderr)

    def test_recusa_asterisco_em_allowed_hosts(self):
        r = verificar_producao(ALLOWED_HOSTS="*", DJANGO_SECRET_KEY=CHAVE_FORTE)
        self.assertNotEqual(r.returncode, 0)

    def test_recusa_chave_secreta_fraca(self):
        for chave in ("curta", "troque-esta-chave-" + "x" * 40, "django-insecure-" + "x" * 60):
            r = verificar_producao(ALLOWED_HOSTS="api.exercita.ao", DJANGO_SECRET_KEY=chave)
            self.assertNotEqual(r.returncode, 0, chave)
            self.assertIn("DJANGO_SECRET_KEY", r.stderr)

    def test_configuracao_correta_so_deixa_o_aviso_opcional_do_hsts_preload(self):
        r = verificar_producao(ALLOWED_HOSTS="api.exercita.ao", DJANGO_SECRET_KEY=CHAVE_FORTE)
        self.assertEqual(r.returncode, 0, r.stderr)
        avisos = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith("?:")]
        self.assertEqual(len(avisos), 1, avisos)
        self.assertIn("W021", avisos[0])  # preload e opt-in consciente (SECURE_HSTS_PRELOAD)


class ThrottlingTestCase(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = APIClient()

    def limites(self, **taxas):
        base = {"anon": "100000/min", "user": "100000/min", "auth": "100000/min"}
        base.update(taxas)
        return patch.object(SimpleRateThrottle, "THROTTLE_RATES", base)

    def tentar_login(self):
        return self.client.post("/api/v1/auth/login/", {"username": "x", "password": "y"}, format="json")

    def test_login_limitado_contra_forca_bruta(self):
        with self.limites(auth="3/min"):
            codigos = [self.tentar_login().status_code for _ in range(5)]
        self.assertEqual(codigos[:3], [400, 400, 400])
        self.assertEqual(codigos[3:], [429, 429])

    def test_registo_tambem_limitado(self):
        with self.limites(auth="2/min"):
            codigos = [self.client.post("/api/v1/users/", {}, format="json").status_code for _ in range(3)]
        self.assertEqual(codigos[-1], 429)

    def test_limite_de_utilizador_autenticado(self):
        aluno = criar_aluno("throttle_u")
        self.client.force_authenticate(aluno.utilizador)
        with self.limites(user="2/min"):
            codigos = [self.client.get("/api/v1/notifications/").status_code for _ in range(3)]
        self.assertEqual(codigos, [200, 200, 429])

    def test_webhook_do_gateway_nao_e_limitado(self):
        with self.limites(anon="1/min", auth="1/min"):
            codigos = [self.client.post("/api/v1/payments/1/webhook/", {}, format="json").status_code for _ in range(4)]
        self.assertNotIn(429, codigos)  # 401 por assinatura em falta, nunca 429

    def test_resposta_429_traz_retry_after(self):
        with self.limites(auth="1/min"):
            self.tentar_login()
            r = self.tentar_login()
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r)
