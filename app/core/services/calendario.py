"""Integracao com calendarios.

- Apple Calendar / Google Calendar (importacao): exportacao em formato iCalendar (.ics, RFC 5545),
  que nao precisa de credenciais.
- TODO: sincronizacao automatica com a API do Google Calendar exige OAuth do utilizador (scope de
  calendario) e credenciais; `GoogleCalendarGateway` define o contrato e fica por implementar.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

DURACAO_SESSAO = timedelta(hours=1)  # o modelo ainda nao guarda a duracao; usa-se a do slot quando existe


class GoogleCalendarGateway:
    def criar_evento(self, utilizador, sessao):
        raise NotImplementedError("TODO: integrar com a API do Google Calendar (requer OAuth).")


def _escape(texto):
    return (texto.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n"))


def _utc(dt):
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sessao_para_ics(sessao):
    inicio = sessao.data_hora
    fim = inicio + DURACAO_SESSAO
    if sessao.slot is not None:
        fim = inicio + (datetime.combine(inicio.date(), sessao.slot.hora_fim)
                        - datetime.combine(inicio.date(), sessao.slot.hora_inicio))
    estado = "CANCELLED" if sessao.estado == "cancelada" else "CONFIRMED"
    linhas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Exercita//Sessoes//PT",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:sessao-{sessao.pk}@exercita",
        f"DTSTAMP:{_utc(datetime.now(dt_timezone.utc))}",
        f"DTSTART:{_utc(inicio)}",
        f"DTEND:{_utc(fim)}",
        f"SUMMARY:{_escape('Sessao Exercita com ' + sessao.personal_trainer.utilizador.username)}",
        f"DESCRIPTION:{_escape('Modalidade: ' + sessao.get_modalidade_display())}",
        f"STATUS:{estado}",
        "BEGIN:VALARM",
        "TRIGGER:-PT1H",
        "ACTION:DISPLAY",
        "DESCRIPTION:Sessao Exercita dentro de 1 hora",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(linhas) + "\r\n"
