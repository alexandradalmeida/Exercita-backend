from django.db import models
from django.contrib.auth.models import AbstractUser


class Utilizador(AbstractUser):
    class TipoUtilizador(models.TextChoices):
        ALUNO = "aluno", "Aluno"
        PERSONAL_TRAINER = "personal_trainer", "Personal Trainer"

    tipo = models.CharField(max_length=20, choices=TipoUtilizador.choices)
    telefone = models.CharField(max_length=20, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.username


class UtilizadorAluno(models.Model):
    utilizador = models.OneToOneField(
        Utilizador, on_delete=models.CASCADE, related_name="perfil_aluno"
    )
    data_nascimento = models.DateField(null=True, blank=True)
    objetivo = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Aluno: {self.utilizador.username}"


class PersonalTrainer(models.Model):
    class EstadoVerificacao(models.TextChoices):
        PENDENTE = "pendente", "Pendente de Verificação"
        VERIFICADO = "verificado", "Verificado"

    utilizador = models.OneToOneField(
        Utilizador, on_delete=models.CASCADE, related_name="perfil_personal_trainer"
    )
    estado_verificacao = models.CharField(
        max_length=20, choices=EstadoVerificacao.choices,
        default=EstadoVerificacao.PENDENTE
    )
    especialidade = models.CharField(max_length=255, blank=True)
    biografia = models.TextField(blank=True)

    def __str__(self):
        return f"PT: {self.utilizador.username}"


class Ginasio(models.Model):
    nome = models.CharField(max_length=255)
    morada = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    def __str__(self):
        return self.nome


class Sessao(models.Model):
    class EstadoSessao(models.TextChoices):
        AGENDADA = "agendada", "Agendada"
        REALIZADA = "realizada", "Realizada"
        CANCELADA = "cancelada", "Cancelada"

    aluno = models.ForeignKey(UtilizadorAluno, on_delete=models.CASCADE, related_name="sessoes")
    personal_trainer = models.ForeignKey(PersonalTrainer, on_delete=models.CASCADE, related_name="sessoes")
    ginasio = models.ForeignKey(Ginasio, on_delete=models.SET_NULL, null=True, blank=True)
    data_hora = models.DateTimeField()
    estado = models.CharField(max_length=20, choices=EstadoSessao.choices, default=EstadoSessao.AGENDADA)
    notas = models.TextField(blank=True)

    def __str__(self):
        return f"Sessao {self.id} - {self.estado}"


class Avaliacao(models.Model):
    sessao = models.OneToOneField(Sessao, on_delete=models.CASCADE, related_name="avaliacao")
    classificacao = models.PositiveSmallIntegerField()
    comentario = models.TextField(blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Avaliacao Sessao {self.sessao_id}"


class Pagamento(models.Model):
    class EstadoPagamento(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        CONCLUIDO = "concluido", "Concluído"
        FALHADO = "falhado", "Falhado"

    sessao = models.ForeignKey(Sessao, on_delete=models.CASCADE, related_name="pagamentos", null=True, blank=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=20, choices=EstadoPagamento.choices, default=EstadoPagamento.PENDENTE)
    referencia_multicaixa = models.CharField(max_length=255, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Pagamento {self.id} - {self.estado}"


class PlanoNutricional(models.Model):
    aluno = models.ForeignKey(UtilizadorAluno, on_delete=models.CASCADE, related_name="planos_nutricionais")
    personal_trainer = models.ForeignKey(PersonalTrainer, on_delete=models.SET_NULL, null=True, blank=True)
    titulo = models.CharField(max_length=255)
    descricao = models.TextField(blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.titulo


class Produto(models.Model):
    nome = models.CharField(max_length=255)
    descricao = models.TextField(blank=True)
    preco = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.nome


class Notificacao(models.Model):
    utilizador = models.ForeignKey(Utilizador, on_delete=models.CASCADE, related_name="notificacoes")
    mensagem = models.TextField()
    lida = models.BooleanField(default=False)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notificacao {self.id} - {self.utilizador}"