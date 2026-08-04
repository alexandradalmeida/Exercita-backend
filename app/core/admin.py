from django.contrib import admin
from .models import (
    Utilizador, UtilizadorAluno, PersonalTrainer, Ginasio,
    Sessao, Avaliacao, Pagamento, PlanoNutricional, Produto, Notificacao,
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