from django.core.management.base import BaseCommand

from core.services.transacoes import libertar_pagamentos_elegiveis


class Command(BaseCommand):
    help = "Liberta os pagamentos de sessoes realizadas ha mais de 24h sem reclamacao (BR-03)."

    def handle(self, *args, **options):
        total = libertar_pagamentos_elegiveis()
        self.stdout.write(f"{total} pagamento(s) libertado(s).")
