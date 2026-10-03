from django.core.management.base import BaseCommand

from core.services.notificacoes import enviar_lembretes


class Command(BaseCommand):
    help = "Envia lembretes das sessoes que comecam nas proximas 24h."

    def handle(self, *args, **options):
        self.stdout.write(f"{enviar_lembretes()} lembrete(s) enviado(s).")
