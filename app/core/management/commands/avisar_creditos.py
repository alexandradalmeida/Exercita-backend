from django.core.management.base import BaseCommand

from core.services.creditos import expirar_e_avisar


class Command(BaseCommand):
    help = "Avisa os alunos dos creditos que expiram nos proximos 7 dias."

    def handle(self, *args, **options):
        avisados, expirados = expirar_e_avisar()
        self.stdout.write(f"{avisados} aviso(s) enviado(s); {expirados} credito(s) expirado(s) com saldo por usar.")
