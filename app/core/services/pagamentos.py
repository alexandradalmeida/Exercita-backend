from decimal import ROUND_HALF_UP, Decimal

from decouple import config

CENTIMO = Decimal("0.01")


def percentagem_comissao():
    """BR-06: percentagem retida pela plataforma (por omissao 15%)."""
    return Decimal(config("PLATFORM_COMMISSION_PERCENT", default="15"))


def calcular_comissao(valor):
    """Devolve (comissao_plataforma, valor_liquido_pt) para um valor bruto."""
    valor = Decimal(valor)
    comissao = (valor * percentagem_comissao() / Decimal("100")).quantize(CENTIMO, rounding=ROUND_HALF_UP)
    return comissao, valor - comissao

class PagamentoErro(Exception):
    def __init__(self, mensagem, codigo=400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo
