from django.contrib import admin
from .models import (
    Utilizador, UtilizadorAluno, PersonalTrainer, Ginasio,
    Sessao, Avaliacao, Pagamento, PlanoNutricional, Produto, Notificacao,
    Certificacao, SlotDisponibilidade, Favorito, Nutricionista, ReservaGinasio, Refeicao, RegistoRefeicao, Encomenda, Carrinho, DocumentoFinanceiro,
)

admin.site.register(Utilizador)
admin.site.register(UtilizadorAluno)
admin.site.register(PersonalTrainer)
admin.site.register(Ginasio)
admin.site.register(Sessao)
admin.site.register(Avaliacao)
admin.site.register(Pagamento)
admin.site.register(PlanoNutricional)
admin.site.register(Produto)
admin.site.register(Notificacao)
admin.site.register(Certificacao)
admin.site.register(SlotDisponibilidade)
admin.site.register(Favorito)
admin.site.register(Nutricionista)
admin.site.register(ReservaGinasio)
admin.site.register(Refeicao)
admin.site.register(RegistoRefeicao)
admin.site.register(Encomenda)
admin.site.register(Carrinho)
admin.site.register(DocumentoFinanceiro)
