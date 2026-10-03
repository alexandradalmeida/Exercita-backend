from django.db import transaction
from django.utils import timezone

from ..models import DocumentoFinanceiro, SequenciaDocumento


def _proximo_numero(tipo):
    ano = timezone.localdate().year
    sequencia, _ = SequenciaDocumento.objects.select_for_update().get_or_create(tipo=tipo, ano=ano)
    sequencia.ultimo += 1
    sequencia.save(update_fields=["ultimo"])
    return f"{tipo} {ano}/{sequencia.ultimo:04d}"


def _linhas(pagamento):
    if pagamento.encomenda_id:
        return [
            {"descricao": i.nome, "quantidade": i.quantidade, "preco_unitario": str(i.preco_unitario),
             "subtotal": str(i.subtotal)}
            for i in pagamento.encomenda.itens.all()
        ]
    s = pagamento.sessao
    quando = timezone.localtime(s.data_hora).strftime("%d/%m/%Y %H:%M")
    descricao = f"Sessao de {s.get_modalidade_display().lower()} com {s.personal_trainer.utilizador.username} ({quando})"
    return [{"descricao": descricao, "quantidade": s.quantidade_sessoes,
             "preco_unitario": str(pagamento.valor / s.quantidade_sessoes), "subtotal": str(pagamento.valor)}]


def _cliente(pagamento):
    origem = pagamento.encomenda if pagamento.encomenda_id else pagamento.sessao
    return origem.aluno.utilizador


@transaction.atomic
def emitir_documentos(pagamento):
    """Emite fatura e recibo de um pagamento aprovado. Idempotente: chamar duas vezes nao duplica."""
    existentes = {d.tipo: d for d in pagamento.documentos.all()}
    linhas, cliente = _linhas(pagamento), _cliente(pagamento)
    for tipo in (DocumentoFinanceiro.Tipo.FATURA, DocumentoFinanceiro.Tipo.RECIBO):
        if tipo not in existentes:
            existentes[tipo] = DocumentoFinanceiro.objects.create(
                pagamento=pagamento, cliente=cliente, tipo=tipo, numero=_proximo_numero(tipo),
                linhas=linhas, total=pagamento.valor)
    return list(existentes.values())
