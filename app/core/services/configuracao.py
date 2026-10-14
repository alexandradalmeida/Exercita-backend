from decimal import Decimal

from decouple import config

from ..models import ConfiguracaoPlataforma

# campo da configuracao -> (variavel de ambiente, valor por omissao, conversao)
PARAMETROS = {
    "comissao_percentagem": ("PLATFORM_COMMISSION_PERCENT", "15", Decimal),
    "qualidade_limiar_alerta": ("QUALITY_ALERT_THRESHOLD", "4.0", Decimal),
    "qualidade_limiar_suspensao": ("QUALITY_SUSPEND_THRESHOLD", "3.0", Decimal),
    "qualidade_minimo_avaliacoes": ("QUALITY_MIN_REVIEWS", "5", int),
}


def valor_efetivo(campo, configuracao=None):
    """Valor definido pelo admin, ou o do ambiente quando o campo esta vazio."""
    variavel, omissao, conversao = PARAMETROS[campo]
    definido = getattr(configuracao or ConfiguracaoPlataforma.obter(), campo)
    return conversao(definido) if definido is not None else conversao(config(variavel, default=omissao))


def valores_efetivos(configuracao=None):
    configuracao = configuracao or ConfiguracaoPlataforma.obter()
    return {campo: valor_efetivo(campo, configuracao) for campo in PARAMETROS}
