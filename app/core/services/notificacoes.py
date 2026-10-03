"""Notificacoes in-app + email + push.

TODO: o envio push (FCM/APNs) depende de credenciais e de tokens de dispositivo que ainda nao
existem; `PushMock` apenas regista em log. Trocar `obter_push()` quando houver integracao real.
"""
import logging

from django.core.mail import send_mail
from django.db import transaction

from ..models import Notificacao

logger = logging.getLogger(__name__)


class PushGateway:
    def enviar(self, utilizador, mensagem):
        raise NotImplementedError


class PushMock(PushGateway):
    def enviar(self, utilizador, mensagem):
        logger.info("push (mock) para %s: %s", utilizador.pk, mensagem)


def obter_push():
    return PushMock()


def notificar(utilizador, mensagem, assunto="Exercita"):
    """Cria a Notificacao e, depois do commit, envia email e push. Falhas de envio nao propagam."""
    notificacao = Notificacao.objects.create(utilizador=utilizador, mensagem=mensagem)

    def enviar():
        if utilizador.email:
            try:
                send_mail(assunto, mensagem, None, [utilizador.email])
            except Exception:
                logger.exception("falha ao enviar email de notificacao %s", notificacao.pk)
        try:
            obter_push().enviar(utilizador, mensagem)
        except Exception:
            logger.exception("falha ao enviar push da notificacao %s", notificacao.pk)

    transaction.on_commit(enviar)
    return notificacao


def _fmt(sessao):
    from django.utils import timezone
    return timezone.localtime(sessao.data_hora).strftime("%d/%m/%Y as %H:%M")


# --- eventos de dominio ---
def sessao_contratada(sessao):
    notificar(sessao.personal_trainer.utilizador,
              f"Nova sessao agendada com {sessao.aluno.utilizador.username} para {_fmt(sessao)}.",
              "Nova sessao agendada")


def pagamento_aprovado(pagamento):
    s = pagamento.sessao
    notificar(s.aluno.utilizador, f"Pagamento de {pagamento.valor} Kz aprovado para a sessao de {_fmt(s)}.",
              "Pagamento aprovado")
    notificar(s.personal_trainer.utilizador,
              f"O pagamento da sessao de {_fmt(s)} foi aprovado. Pode confirmar a sessao.", "Pagamento aprovado")


def pagamento_recusado(pagamento):
    s = pagamento.sessao
    notificar(s.aluno.utilizador, f"O pagamento da sessao de {_fmt(s)} foi recusado.", "Pagamento recusado")


def sessao_confirmada(sessao):
    notificar(sessao.aluno.utilizador, f"A sua sessao de {_fmt(sessao)} foi confirmada.", "Sessao confirmada")


def sessao_realizada(sessao):
    notificar(sessao.aluno.utilizador,
              f"A sessao de {_fmt(sessao)} foi dada como realizada. Confirme a realizacao para libertar o pagamento "
              "ou reclame nas proximas 24h.", "Sessao realizada")


def sessao_cancelada(sessao, cancelada_por, reembolsado):
    aluno_u, pt_u = sessao.aluno.utilizador, sessao.personal_trainer.utilizador
    destinatario = pt_u if cancelada_por.id == aluno_u.id else aluno_u
    extra = " O pagamento foi reembolsado." if reembolsado else ""
    notificar(destinatario, f"A sessao de {_fmt(sessao)} foi cancelada por {cancelada_por.username}.{extra}",
              "Sessao cancelada")


def sessao_reagendada(sessao):
    notificar(sessao.personal_trainer.utilizador,
              f"{sessao.aluno.utilizador.username} reagendou a sessao para {_fmt(sessao)}.", "Sessao reagendada")


def pagamento_libertado(pagamento):
    notificar(pagamento.sessao.personal_trainer.utilizador,
              f"Foram libertados {pagamento.valor_liquido_pt} Kz referentes a sessao de {_fmt(pagamento.sessao)}.",
              "Pagamento libertado")


def lembrete_sessao(sessao):
    for u in (sessao.aluno.utilizador, sessao.personal_trainer.utilizador):
        notificar(u, f"Lembrete: tem uma sessao marcada para {_fmt(sessao)}.", "Lembrete de sessao")


def enviar_lembretes(agora=None, antecedencia_horas=24):
    """Envia lembrete as sessoes confirmadas/agendadas que comecam nas proximas `antecedencia_horas`.
    Para correr periodicamente (`manage.py enviar_lembretes`). Devolve a contagem."""
    from datetime import timedelta

    from django.utils import timezone

    from ..models import Sessao
    agora = agora or timezone.now()
    sessoes = Sessao.objects.filter(
        estado__in=[Sessao.EstadoSessao.AGENDADA, Sessao.EstadoSessao.CONFIRMADA],
        lembrete_enviado=False, data_hora__gt=agora, data_hora__lte=agora + timedelta(hours=antecedencia_horas),
    ).select_related("aluno__utilizador", "personal_trainer__utilizador")
    total = 0
    for sessao in sessoes:
        lembrete_sessao(sessao)
        sessao.lembrete_enviado = True
        sessao.save(update_fields=["lembrete_enviado"])
        total += 1
    return total


def nova_avaliacao(avaliacao):
    notificar(avaliacao.avaliado,
              f"{avaliacao.autor.username} avaliou a sessao com {avaliacao.classificacao}/5.", "Nova avaliacao")


def estado_qualidade_alterado(pt, media):
    mensagens = {
        "em_alerta": f"O seu perfil entrou em alerta: a media das avaliacoes ({media}) esta abaixo do limiar de qualidade.",
        "suspenso": f"O seu perfil foi suspenso: a media das avaliacoes ({media}) esta abaixo do limiar minimo. "
                    "Contacte a administracao.",
        "verificado": "O seu perfil esta verificado e ativo.",
    }
    notificar(pt.utilizador, mensagens[pt.estado_verificacao], "Estado do seu perfil")
