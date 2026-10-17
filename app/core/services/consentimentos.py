"""Consentimento explicito para dados de saude (RGPD).

O texto abaixo e um RASCUNHO tecnico: tem de ser revisto e aprovado pelo juridico/DPO antes do lancamento.
Pode ser substituido sem mexer no codigo com HEALTH_CONSENT_TEXT; qualquer alteracao de texto deve vir com uma
nova HEALTH_CONSENT_VERSION, o que obriga todos os utilizadores a consentir de novo.
"""
import hashlib

from decouple import config
from django.db import transaction
from django.utils import timezone

from ..models import ConsentimentoDados
from .sessoes import ErroNegocio

TIPO = ConsentimentoDados.Tipo.SAUDE

TEXTO_RASCUNHO = (
    "Autorizo a Exercita a tratar os meus dados de saúde (medições corporais, histórico de treinos, registo de "
    "refeições e planos nutricionais) para me prestar o serviço de acompanhamento do meu progresso e para que o "
    "nutricionista que me atribuir um plano possa trabalhar com esses dados. Os dados são tratados apenas para esta "
    "finalidade. Posso retirar este consentimento a qualquer momento, sem afetar o tratamento já feito, e pedir o "
    "apagamento dos dados. [RASCUNHO — sujeito a validação jurídica]"
)


def versao_atual():
    return config("HEALTH_CONSENT_VERSION", default="1.0")


def texto_atual():
    return config("HEALTH_CONSENT_TEXT", default=TEXTO_RASCUNHO)


def hash_do_texto(texto=None):
    return hashlib.sha256((texto or texto_atual()).encode("utf-8")).hexdigest()


def consentimento_ativo(utilizador):
    """Consentimento em vigor: nao revogado e dado para a versao atual dos termos."""
    if not getattr(utilizador, "is_authenticated", False):
        return None
    return ConsentimentoDados.objects.filter(
        utilizador=utilizador, tipo=TIPO, data_revogacao__isnull=True, versao_termos=versao_atual()).first()


def tem_consentimento(utilizador):
    return consentimento_ativo(utilizador) is not None


@transaction.atomic
def conceder(utilizador, versao, aceito):
    """O aluno tem de enviar `aceito=true` e a versao exata que viu: sem caixas pre-selecionadas nem aceitacao implicita."""
    if aceito is not True:
        raise ErroNegocio("O consentimento tem de ser dado de forma explicita (aceito: true).")
    if str(versao) != versao_atual():
        raise ErroNegocio(f"Versao dos termos desatualizada: a atual e a {versao_atual()}.", 409)
    existente = consentimento_ativo(utilizador)
    if existente:
        return existente  # idempotente
    # consentimentos antigos (outras versoes) deixam de estar em vigor
    ConsentimentoDados.objects.filter(utilizador=utilizador, tipo=TIPO, data_revogacao__isnull=True).update(
        data_revogacao=timezone.now())
    return ConsentimentoDados.objects.create(
        utilizador=utilizador, tipo=TIPO, versao_termos=versao_atual(), texto_hash=hash_do_texto())


@transaction.atomic
def revogar(utilizador, apagar_dados=False):
    """Retira o consentimento. Com `apagar_dados`, apaga tambem os dados de saude ja recolhidos.
    Devolve o numero de registos de saude apagados (0 se nao se pediu o apagamento)."""
    agora = timezone.now()
    ConsentimentoDados.objects.filter(
        utilizador=utilizador, tipo=TIPO, data_revogacao__isnull=True).update(data_revogacao=agora)
    if not apagar_dados:
        return 0
    from .rgpd import apagar_dados_de_saude
    aluno = getattr(utilizador, "perfil_aluno", None)
    return apagar_dados_de_saude(aluno) if aluno is not None else 0


def utilizadores_com_consentimento():
    """Queryset de utilizadores com consentimento de saude em vigor (para filtrar o acesso de profissionais)."""
    from ..models import Utilizador
    return Utilizador.objects.filter(
        consentimentos__tipo=TIPO, consentimentos__data_revogacao__isnull=True,
        consentimentos__versao_termos=versao_atual())
