import json

from django.test import TestCase


class DocumentacaoApiTestCase(TestCase):
    def test_schema_e_valido_e_sem_avisos(self):
        from io import StringIO

        from django.core.management import call_command
        saida = StringIO()
        # --fail-on-warn: qualquer endpoint sem documentacao adequada faz o teste falhar
        call_command("spectacular", "--validate", "--fail-on-warn", "--format", "openapi-json", stdout=saida, stderr=StringIO())
        self.schema = json.loads(saida.getvalue())
        self.assertGreater(len(self.schema["paths"]), 60)

    def test_endpoints_publicos(self):
        r = self.client.get("/api/schema/?format=json")
        self.assertEqual(r.status_code, 200)
        schema = r.json()
        self.assertEqual(schema["info"]["title"], "Exercita API")
        self.assertIn("bearerAuth", schema["components"]["securitySchemes"])
        self.assertEqual(self.client.get("/api/docs/").status_code, 200)
        self.assertEqual(self.client.get("/api/redoc/").status_code, 200)

    def test_endpoints_principais_documentados(self):
        paths = self.client.get("/api/schema/?format=json").json()["paths"]
        for caminho in ("/api/v1/auth/login/", "/api/v1/trainers/", "/api/v1/sessions/", "/api/v1/payments/",
                        "/api/v1/sessions/{id}/reviews/", "/api/v1/gyms/", "/api/v1/shop/checkout/",
                        "/api/v1/admin/reports/platform/", "/api/v1/progress/summary/"):
            self.assertIn(caminho, paths)
