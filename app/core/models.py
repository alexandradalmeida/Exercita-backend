from pgvector.django import HnswIndex, VectorField
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.contrib.auth.models import AbstractUser
from .fields import EncryptedCharField


class Utilizador(AbstractUser):
    class TipoUtilizador(models.TextChoices):
        ALUNO = "aluno", "Aluno"
        PERSONAL_TRAINER = "personal_trainer", "Personal Trainer"

    tipo = models.CharField(max_length=20, choices=TipoUtilizador.choices)
    telefone = EncryptedCharField(blank=True)
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

    class ModalidadePagamento(models.TextChoices):
        MULTICAIXA = "multicaixa", "Multicaixa Express"
        DINHEIRO = "dinheiro", "Dinheiro"
        TRANSFERENCIA = "transferencia", "Transferência Bancária"

    utilizador = models.OneToOneField(
        Utilizador, on_delete=models.CASCADE, related_name="perfil_personal_trainer"
    )
    estado_verificacao = models.CharField(
        max_length=20, choices=EstadoVerificacao.choices,
        default=EstadoVerificacao.PENDENTE
    )
    especialidade = models.CharField(max_length=255, blank=True)
    localizacao = models.CharField(max_length=255, blank=True)
    biografia = models.TextField(blank=True)
    preco_hora = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # UC-08: ate quantas horas antes da sessao o aluno pode cancelar com reembolso total
    janela_cancelamento_horas = models.PositiveIntegerField(default=24)
    modalidades_pagamento = ArrayField(
        models.CharField(max_length=20, choices=ModalidadePagamento.choices),
        blank=True, default=list,
    )
    embedding = VectorField(dimensions=1536, null=True, blank=True)

    class Meta:
        indexes = [
            HnswIndex(
                name="pt_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self):
        return f"PT: {self.utilizador.username}"

class Ginasio(models.Model):
    nome = models.CharField(max_length=255)
    morada = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    def __str__(self):
        return self.nome


class TransicaoInvalida(Exception):
    """Mudanca de estado nao permitida pela maquina de estados."""


class Sessao(models.Model):
    class EstadoSessao(models.TextChoices):
        AGENDADA = "agendada", "Agendada"
        CONFIRMADA = "confirmada", "Confirmada"
        EM_CURSO = "em_curso", "Em Curso"
        REALIZADA = "realizada", "Realizada"
        AVALIADA = "avaliada", "Avaliada"
        CANCELADA = "cancelada", "Cancelada"

    class Modalidade(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        PACOTE = "pacote", "Pacote"
        PLANO_MENSAL = "plano_mensal", "Plano Mensal"

    # estado atual -> estados para onde pode evoluir
    TRANSICOES = {
        EstadoSessao.AGENDADA: {EstadoSessao.CONFIRMADA, EstadoSessao.CANCELADA},
        EstadoSessao.CONFIRMADA: {EstadoSessao.EM_CURSO, EstadoSessao.CANCELADA},
        EstadoSessao.EM_CURSO: {EstadoSessao.REALIZADA},
        EstadoSessao.REALIZADA: {EstadoSessao.AVALIADA},
        EstadoSessao.AVALIADA: set(),
        EstadoSessao.CANCELADA: set(),
    }
    ESTADOS_REALIZADOS = (EstadoSessao.REALIZADA, EstadoSessao.AVALIADA)

    aluno = models.ForeignKey(UtilizadorAluno, on_delete=models.CASCADE, related_name="sessoes")
    personal_trainer = models.ForeignKey(PersonalTrainer, on_delete=models.CASCADE, related_name="sessoes")
    ginasio = models.ForeignKey(Ginasio, on_delete=models.SET_NULL, null=True, blank=True)
    slot = models.ForeignKey(
        "SlotDisponibilidade", on_delete=models.SET_NULL, null=True, blank=True, related_name="sessoes"
    )
    data_hora = models.DateTimeField()
    modalidade = models.CharField(max_length=20, choices=Modalidade.choices, default=Modalidade.INDIVIDUAL)
    quantidade_sessoes = models.PositiveIntegerField(default=1)
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estado = models.CharField(max_length=20, choices=EstadoSessao.choices, default=EstadoSessao.AGENDADA)
    cancelada_por = models.ForeignKey(
        Utilizador, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    data_cancelamento = models.DateTimeField(null=True, blank=True)
    data_realizacao = models.DateTimeField(null=True, blank=True)
    reclamacao = models.TextField(blank=True)  # BR-03: uma reclamacao bloqueia a libertacao automatica
    lembrete_enviado = models.BooleanField(default=False)
    notas = models.TextField(blank=True)

    def pode_transitar(self, novo_estado):
        return novo_estado in self.TRANSICOES[self.estado]

    def transitar(self, novo_estado):
        """Muda o estado respeitando a maquina de estados; guarda a sessao."""
        if not self.pode_transitar(novo_estado):
            raise TransicaoInvalida(f"Sessao nao pode passar de '{self.estado}' para '{novo_estado}'.")
        self.estado = novo_estado
        self.save(update_fields=["estado"])

    def __str__(self):
        return f"Sessao {self.id} - {self.estado}"


class Avaliacao(models.Model):
    """Avaliacao mutua de uma sessao realizada (BR-05): aluno -> PT e PT -> aluno.
    Apenas as avaliacoes recebidas por um PT contam para a sua reputacao publica."""
    sessao = models.ForeignKey(Sessao, on_delete=models.CASCADE, related_name="avaliacoes")
    autor = models.ForeignKey(Utilizador, on_delete=models.CASCADE, related_name="avaliacoes_feitas")
    avaliado = models.ForeignKey(Utilizador, on_delete=models.CASCADE, related_name="avaliacoes_recebidas")
    classificacao = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comentario = models.TextField(blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["sessao", "autor"], name="uma_avaliacao_por_autor_e_sessao")]

    def __str__(self):
        return f"Avaliacao Sessao {self.sessao_id} por {self.autor_id}"


class Pagamento(models.Model):
    class EstadoPagamento(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        APROVADO = "aprovado", "Aprovado"  # pago pelo aluno, retido pela plataforma
        RECUSADO = "recusado", "Recusado"
        LIBERTADO = "libertado", "Libertado"  # entregue ao PT (BR-03)
        REEMBOLSADO = "reembolsado", "Reembolsado"

    TRANSICOES = {
        EstadoPagamento.PENDENTE: {EstadoPagamento.APROVADO, EstadoPagamento.RECUSADO},
        EstadoPagamento.APROVADO: {EstadoPagamento.LIBERTADO, EstadoPagamento.REEMBOLSADO},
        EstadoPagamento.RECUSADO: set(),
        EstadoPagamento.LIBERTADO: set(),
        EstadoPagamento.REEMBOLSADO: set(),
    }

    sessao = models.ForeignKey(Sessao, on_delete=models.CASCADE, related_name="pagamentos", null=True, blank=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    comissao_plataforma = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # BR-06
    valor_liquido_pt = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estado = models.CharField(max_length=20, choices=EstadoPagamento.choices, default=EstadoPagamento.PENDENTE)
    referencia_multicaixa = models.CharField(max_length=255, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_aprovacao = models.DateTimeField(null=True, blank=True)
    data_libertacao = models.DateTimeField(null=True, blank=True)

    def pode_transitar(self, novo_estado):
        return novo_estado in self.TRANSICOES[self.estado]

    def transitar(self, novo_estado, **campos):
        """Muda o estado respeitando a maquina de estados; `campos` sao gravados na mesma operacao."""
        if not self.pode_transitar(novo_estado):
            raise TransicaoInvalida(f"Pagamento nao pode passar de '{self.estado}' para '{novo_estado}'.")
        self.estado = novo_estado
        for nome, valor in campos.items():
            setattr(self, nome, valor)
        self.save(update_fields=["estado", *campos])

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


class Certificacao(models.Model):
    personal_trainer = models.ForeignKey(
        PersonalTrainer, on_delete=models.CASCADE, related_name="certificacoes"
    )
    nome = models.CharField(max_length=255)
    instituicao = models.CharField(max_length=255, blank=True)
    ano_obtencao = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.nome} ({self.personal_trainer.utilizador.username})"


class SlotDisponibilidade(models.Model):
    class DiaSemana(models.IntegerChoices):
        SEGUNDA = 0, "Segunda-feira"
        TERCA = 1, "Terça-feira"
        QUARTA = 2, "Quarta-feira"
        QUINTA = 3, "Quinta-feira"
        SEXTA = 4, "Sexta-feira"
        SABADO = 5, "Sábado"
        DOMINGO = 6, "Domingo"

    personal_trainer = models.ForeignKey(
        PersonalTrainer, on_delete=models.CASCADE, related_name="slots_disponibilidade"
    )
    dia_semana = models.IntegerField(choices=DiaSemana.choices)
    hora_inicio = models.TimeField()
    hora_fim = models.TimeField()
    capacidade = models.PositiveIntegerField(default=1)
    vagas_ocupadas = models.PositiveIntegerField(default=0)

    @property
    def vagas_disponiveis(self):
        return max(self.capacidade - self.vagas_ocupadas, 0)

    def __str__(self):
        return f"{self.get_dia_semana_display()} {self.hora_inicio}-{self.hora_fim} ({self.personal_trainer.utilizador.username})"


class Favorito(models.Model):
    aluno = models.ForeignKey(UtilizadorAluno, on_delete=models.CASCADE, related_name="favoritos")
    personal_trainer = models.ForeignKey(PersonalTrainer, on_delete=models.CASCADE, related_name="favoritado_por")
    data_criacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["aluno", "personal_trainer"]

    def __str__(self):
        return f"{self.aluno.utilizador.username} -> {self.personal_trainer.utilizador.username}"