"""RGPD: direito de acesso/portabilidade (exportacao) e direito ao apagamento (anonimizacao)."""
from django.db import transaction
from django.utils import timezone

from ..models import (
    Avaliacao, Carrinho, Encomenda, Favorito, Notificacao, Pagamento, PersonalTrainer, ReservaGinasio, Sessao,
    HistoricoTreino, MetricaFisica, RegistoRefeicao, Utilizador,
)
from . import creditos
from .administracao import revogar_sessoes
from .sessoes import ErroNegocio


def _perfil_aluno(utilizador):
    return getattr(utilizador, "perfil_aluno", None)


def exportar_dados(utilizador):
    """Todos os dados pessoais do utilizador num dicionario serializavel (JSON)."""
    from ..serializers_progresso import HistoricoTreinoSerializer, MetricaFisicaSerializer
    from ..serializers import (
        AvaliacaoSerializer, DocumentoFinanceiroSerializer, EncomendaSerializer,
        NotificacaoSerializer, ParceriaSerializer, PlanoNutricionalSerializer,
        RegistoRefeicaoSerializer, ReservaGinasioSerializer, SessaoSerializer,
    )
    dados = {
        "exportado_em": timezone.now(),
        "conta": {
            "id": utilizador.id, "username": utilizador.username, "email": utilizador.email,
            "telefone": utilizador.telefone, "tipo": utilizador.tipo, "data_criacao": utilizador.data_criacao,
            "suspenso": utilizador.suspenso,
        },
        "consentimentos": [
            {"tipo": c.tipo, "versao_termos": c.versao_termos, "data_concessao": c.data_concessao,
             "data_revogacao": c.data_revogacao}
            for c in utilizador.consentimentos.all()],
        "notificacoes": NotificacaoSerializer(Notificacao.objects.filter(utilizador=utilizador), many=True).data,
        "avaliacoes_feitas": AvaliacaoSerializer(utilizador.avaliacoes_feitas.all(), many=True).data,
        "avaliacoes_recebidas": AvaliacaoSerializer(utilizador.avaliacoes_recebidas.all(), many=True).data,
        "documentos_financeiros": DocumentoFinanceiroSerializer(utilizador.documentos_financeiros.all(), many=True).data,
    }
    aluno = _perfil_aluno(utilizador)
    if aluno is not None:
        ctx = {"request": type("R", (), {"user": utilizador})()}
        dados["perfil_aluno"] = {"data_nascimento": aluno.data_nascimento, "objetivo": aluno.objetivo}
        dados["sessoes"] = SessaoSerializer(aluno.sessoes.prefetch_related("pagamentos"), many=True).data
        dados["encomendas"] = EncomendaSerializer(aluno.encomendas.all(), many=True).data
        dados["reservas_ginasio"] = ReservaGinasioSerializer(aluno.reservas_ginasio.all(), many=True).data
        dados["favoritos"] = [f.personal_trainer_id for f in aluno.favoritos.all()]
        dados["planos_nutricionais"] = PlanoNutricionalSerializer(aluno.planos_nutricionais.all(), many=True).data
        dados["registos_refeicao"] = RegistoRefeicaoSerializer(aluno.registos_refeicao.all(), many=True, context=ctx).data
        dados["metricas_fisicas"] = MetricaFisicaSerializer(aluno.metricas_fisicas.all(), many=True).data
        dados["historico_treinos"] = HistoricoTreinoSerializer(
            aluno.historico_treinos.all(), many=True, context=ctx).data
    pt = getattr(utilizador, "perfil_personal_trainer", None)
    if pt is not None:
        dados["perfil_personal_trainer"] = {
            "estado_verificacao": pt.estado_verificacao, "especialidade": pt.especialidade,
            "localizacao": pt.localizacao, "biografia": pt.biografia, "preco_hora": pt.preco_hora,
            "certificacoes": [{"nome": c.nome, "instituicao": c.instituicao, "ano": c.ano_obtencao}
                              for c in pt.certificacoes.all()],
            "sessoes_como_profissional": SessaoSerializer(pt.sessoes.prefetch_related("pagamentos"), many=True).data,
        }
        parceria = getattr(pt, "parceria", None)
        if parceria is not None:
            dados["parceria"] = ParceriaSerializer(parceria).data
    nutri = getattr(utilizador, "perfil_nutricionista", None)
    if nutri is not None:
        dados["perfil_nutricionista"] = {
            "estado_verificacao": nutri.estado_verificacao, "cedula_profissional": nutri.cedula_profissional,
            "especialidade": nutri.especialidade, "biografia": nutri.biografia,
        }
    return dados


def apagar_dados_de_saude(aluno):
    """Apaga medicoes, treinos, registos de refeicoes e planos nutricionais. Devolve quantos registos apagou."""
    total = 0
    for queryset in (MetricaFisica.objects.filter(aluno=aluno), HistoricoTreino.objects.filter(aluno=aluno),
                     RegistoRefeicao.objects.filter(aluno=aluno), aluno.planos_nutricionais.all()):
        total += queryset.count()
        queryset.delete()
    return total


def pendencias(utilizador):
    """Obrigacoes em aberto que impedem o apagamento (devolve lista de descricoes)."""
    ativas = [Sessao.EstadoSessao.AGENDADA, Sessao.EstadoSessao.CONFIRMADA, Sessao.EstadoSessao.EM_CURSO]
    sessoes = Sessao.objects.filter(estado__in=ativas)
    aluno = _perfil_aluno(utilizador)
    pt = getattr(utilizador, "perfil_personal_trainer", None)
    problemas = []
    if aluno is not None:
        if sessoes.filter(aluno=aluno).exists():
            problemas.append("Tem sessoes agendadas ou em curso.")
        if aluno.encomendas.exclude(estado__in=[Encomenda.Estado.ENTREGUE, Encomenda.Estado.CANCELADA]).exists():
            problemas.append("Tem encomendas por concluir.")
        if creditos.saldo(aluno) > 0:
            problemas.append("Tem credito por utilizar (sera perdido se apagar a conta; use-o primeiro).")
        if Pagamento.objects.filter(sessao__aluno=aluno, estado=Pagamento.EstadoPagamento.APROVADO,
                                    sessao__estado__in=Sessao.ESTADOS_REALIZADOS).exists():
            problemas.append("Tem pagamentos de sessoes realizadas por libertar.")
    if pt is not None:
        if sessoes.filter(personal_trainer=pt).exists():
            problemas.append("Tem sessoes agendadas ou em curso com alunos.")
        if Pagamento.objects.filter(sessao__personal_trainer=pt, estado=Pagamento.EstadoPagamento.APROVADO).exists():
            problemas.append("Tem pagamentos aprovados por libertar.")
    return problemas


@transaction.atomic
def apagar_conta(utilizador):
    """Anonimiza a conta. Dados pessoais e de saude sao apagados; registos financeiros e de sessoes
    ficam (obrigacao legal de conservacao) mas deixam de identificar a pessoa."""
    if utilizador.is_staff or utilizador.is_superuser:
        raise ErroNegocio("Contas de administracao nao podem ser apagadas por aqui.", 403)
    problemas = pendencias(utilizador)
    if problemas:
        raise ErroNegocio("Nao e possivel apagar a conta: " + " ".join(problemas), 409)

    revogar_sessoes(utilizador)
    aluno = _perfil_aluno(utilizador)
    if aluno is not None:
        # dados pessoais e de saude: apagados
        apagar_dados_de_saude(aluno)
        Favorito.objects.filter(aluno=aluno).delete()
        ReservaGinasio.objects.filter(aluno=aluno).delete()
        Carrinho.objects.filter(aluno=aluno).delete()
        aluno.data_nascimento, aluno.objetivo = None, ""
        aluno.save(update_fields=["data_nascimento", "objetivo"])
    pt = getattr(utilizador, "perfil_personal_trainer", None)
    if pt is not None:
        pt.biografia, pt.especialidade, pt.localizacao = "", "", ""
        pt.embedding, pt.preco_hora, pt.modalidades_pagamento = None, None, []
        pt.estado_verificacao = PersonalTrainer.EstadoVerificacao.PENDENTE  # deixa de ser visivel/contratavel
        pt.save()
        pt.certificacoes.all().delete()
        pt.slots_disponibilidade.all().delete()
        pt.ginasios.clear()
    nutri = getattr(utilizador, "perfil_nutricionista", None)
    if nutri is not None:
        nutri.cedula_profissional, nutri.especialidade, nutri.biografia = "", "", ""
        nutri.save()
    Notificacao.objects.filter(utilizador=utilizador).delete()
    utilizador.consentimentos.all().delete()
    # comentarios de avaliacoes feitas/recebidas podem conter dados pessoais
    Avaliacao.objects.filter(autor=utilizador).update(comentario="")

    utilizador.username = f"removido-{utilizador.pk}"
    utilizador.email, utilizador.telefone = "", ""
    utilizador.first_name = utilizador.last_name = ""
    utilizador.is_active = False
    utilizador.set_unusable_password()
    utilizador.save()
