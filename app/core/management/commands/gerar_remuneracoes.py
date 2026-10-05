from django.core.management.base import BaseCommand

from core.services.parcerias import gerar_remuneracoes


class Command(BaseCommand):
    help = "Regista a remuneracao mensal fixa dos PTs parceiros com parceria ativa (BR-04)."

    def handle(self, *args, **options):
        self.stdout.write(f"{gerar_remuneracoes()} remuneracao(oes) registada(s).")
