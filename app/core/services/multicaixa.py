"""Camada de integracao com o Multicaixa Express.

TODO: ainda nao ha documentacao oficial nem credenciais do gateway. Nada aqui assume URLs ou
formatos reais: `MulticaixaGateway` define o contrato que a app precisa e `MulticaixaMock`
(por omissao) permite desenvolver e testar. A assinatura do webhook (HMAC-SHA256 do corpo,
cabecalho X-Signature) e uma convencao provisoria a substituir pela do gateway.
"""
import hashlib
import hmac
import uuid

from decouple import config


class GatewayErro(Exception):
    pass


class MulticaixaGateway:
    def iniciar_transacao(self, pagamento):
        """Inicia a cobranca e devolve a referencia do gateway (str)."""
        raise NotImplementedError

    def reembolsar(self, pagamento):
        """Pede o estorno de um pagamento aprovado. Levanta GatewayErro se falhar."""
        raise NotImplementedError


class MulticaixaReal(MulticaixaGateway):
    def iniciar_transacao(self, pagamento):
        raise NotImplementedError("TODO: integrar com a API oficial do Multicaixa Express.")

    def reembolsar(self, pagamento):
        raise NotImplementedError("TODO: integrar com a API oficial do Multicaixa Express.")


class MulticaixaMock(MulticaixaGateway):
    def iniciar_transacao(self, pagamento):
        return f"MOCK-{uuid.uuid4().hex[:16].upper()}"

    def reembolsar(self, pagamento):
        return True


def obter_gateway():
    return MulticaixaReal() if config("MULTICAIXA_BACKEND", default="mock") == "real" else MulticaixaMock()


def assinar(corpo_bytes, segredo=None):
    segredo = segredo if segredo is not None else config("MULTICAIXA_WEBHOOK_SECRET", default="")
    return hmac.new(segredo.encode(), corpo_bytes, hashlib.sha256).hexdigest()


def assinatura_valida(corpo_bytes, assinatura_recebida):
    segredo = config("MULTICAIXA_WEBHOOK_SECRET", default="")
    if not segredo or not assinatura_recebida:
        return False  # sem segredo configurado nunca se aceitam callbacks
    return hmac.compare_digest(assinar(corpo_bytes, segredo), assinatura_recebida)
