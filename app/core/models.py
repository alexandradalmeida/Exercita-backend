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
        NUTRICIONISTA = "nutricionista", "Nutricionista"

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
        EM_ALERTA = "em_alerta", "Em Alerta"  # BR-02: media abaixo do limiar de alerta
        SUSPENSO = "suspenso", "Suspenso"  # BR-02: media abaixo do limiar de suspensao

    # estados em que o PT esta visivel e pode trabalhar (Em Alerta e apenas um aviso)
    ESTADOS_ATIVOS = ("verificado", "em_alerta")

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
    # reputacao: media das avaliacoes recebidas (so de sessoes realizadas), recalculada a cada avaliacao
    classificacao_media = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    total_avaliacoes = models.PositiveIntegerField(default=0)
    # BR-02: so contam para a qualidade as avaliacoes posteriores a ultima reativacao pelo admin
    avaliacoes_desde = models.DateTimeField(null=True, blank=True)
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
    class EstadoParceria(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        PARCEIRO = "parceiro", "Parceiro"
        INATIVO = "inativo", "Inativo"

    nome = models.CharField(max_length=255)
    morada = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    equipamentos = ArrayField(models.CharField(max_length=100), blank=True, default=list)
    # {"0": [["06:00", "22:00"]], ...} - chave = dia da semana (0 = segunda), valor = intervalos de abertura
    horarios = models.JSONField(blank=True, default=dict)
    estado_parceria = models.CharField(max_length=20, choices=EstadoParceria.choices, default=EstadoParceria.PENDENTE)
    personal_trainers = models.ManyToManyField(PersonalTrainer, blank=True, related_name="ginasios")

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
    encomenda = models.ForeignKey(
        "Encomenda", on_delete=models.CASCADE, related_name="pagamentos", null=True, blank=True)  # e-commerce (UC-12)
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
    nutricionista = models.ForeignKey(
        "Nutricionista", on_delete=models.SET_NULL, null=True, blank=True, related_name="planos")
    titulo = models.CharField(max_length=255)
    descricao = models.TextField(blank=True)
    calorias_diarias = models.PositiveIntegerField(null=True, blank=True)
    ativo = models.BooleanField(default=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.titulo


class Refeicao(models.Model):
    """Refeicao prevista num plano nutricional. `dia_semana` vazio = todos os dias."""
    plano = models.ForeignKey(PlanoNutricional, on_delete=models.CASCADE, related_name="refeicoes")
    nome = models.CharField(max_length=100)  # ex.: pequeno-almoco
    dia_semana = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(6)])
    hora = models.TimeField(null=True, blank=True)
    descricao = models.TextField(blank=True)
    calorias = models.PositiveIntegerField(default=0)
    proteinas_g = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    carboidratos_g = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    gorduras_g = models.DecimalField(max_digits=6, decimal_places=1, default=0)

    def __str__(self):
        return f"{self.nome} ({self.plano_id})"


class RegistoRefeicao(models.Model):
    """Registo diario feito pelo aluno do que comeu (UC-11)."""
    aluno = models.ForeignKey(UtilizadorAluno, on_delete=models.CASCADE, related_name="registos_refeicao")
    refeicao = models.ForeignKey(Refeicao, on_delete=models.SET_NULL, null=True, blank=True, related_name="registos")
    data = models.DateField()
    descricao = models.CharField(max_length=255)
    calorias = models.PositiveIntegerField(default=0)
    notas = models.TextField(blank=True)

    def __str__(self):
        return f"{self.aluno_id} {self.data} {self.descricao}"


class Produto(models.Model):
    class Categoria(models.TextChoices):
        SUPLEMENTO = "suplemento", "Suplemento"
        VESTUARIO = "vestuario", "Vestuário"

    nome = models.CharField(max_length=255)
    descricao = models.TextField(blank=True)
    categoria = models.CharField(max_length=20, choices=Categoria.choices, default=Categoria.SUPLEMENTO)
    preco = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    stock = models.PositiveIntegerField(default=0)
    imagem_url = models.URLField(blank=True)
    ativo = models.BooleanField(default=True)

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

class ReservaGinasio(models.Model):
    """Reserva de aula experimental ou visita a um ginasio parceiro (UC-10)."""

    class Tipo(models.TextChoices):
        AULA_EXPERIMENTAL = "aula_experimental", "Aula Experimental"
        VISITA = "visita", "Visita"

    class Estado(models.TextChoices):
        CONFIRMADA = "confirmada", "Confirmada"
        CANCELADA = "cancelada", "Cancelada"

    aluno = models.ForeignKey(UtilizadorAluno, on_delete=models.CASCADE, related_name="reservas_ginasio")
    ginasio = models.ForeignKey(Ginasio, on_delete=models.CASCADE, related_name="reservas")
    personal_trainer = models.ForeignKey(
        PersonalTrainer, on_delete=models.SET_NULL, null=True, blank=True, related_name="reservas_ginasio"
    )  # PT que acompanha a aula experimental (tem de trabalhar no ginasio)
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    data_hora = models.DateTimeField()
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.CONFIRMADA)
    notas = models.TextField(blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reserva {self.id} - {self.ginasio_id} ({self.estado})"


class Nutricionista(models.Model):
    """Nutricionista parceiro: cria planos nutricionais para alunos (UC-11). Verificado pelo admin."""

    class EstadoVerificacao(models.TextChoices):
        PENDENTE = "pendente", "Pendente de Verificação"
        VERIFICADO = "verificado", "Verificado"

    utilizador = models.OneToOneField(Utilizador, on_delete=models.CASCADE, related_name="perfil_nutricionista")
    estado_verificacao = models.CharField(
        max_length=20, choices=EstadoVerificacao.choices, default=EstadoVerificacao.PENDENTE)
    cedula_profissional = models.CharField(max_length=100, blank=True)
    especialidade = models.CharField(max_length=255, blank=True)
    biografia = models.TextField(blank=True)

    def __str__(self):
        return f"Nutricionista: {self.utilizador.username}"


class Carrinho(models.Model):
    aluno = models.OneToOneField(UtilizadorAluno, on_delete=models.CASCADE, related_name="carrinho")
    data_atualizacao = models.DateTimeField(auto_now=True)


class ItemCarrinho(models.Model):
    carrinho = models.ForeignKey(Carrinho, on_delete=models.CASCADE, related_name="itens")
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    quantidade = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["carrinho", "produto"], name="um_item_por_produto_no_carrinho")]


class Encomenda(models.Model):
    class Estado(models.TextChoices):
        PENDENTE_PAGAMENTO = "pendente_pagamento", "Pendente de Pagamento"
        PAGA = "paga", "Paga"
        EM_PREPARACAO = "em_preparacao", "Em Preparação"
        ENVIADA = "enviada", "Enviada"
        ENTREGUE = "entregue", "Entregue"
        CANCELADA = "cancelada", "Cancelada"

    TRANSICOES = {
        Estado.PENDENTE_PAGAMENTO: {Estado.PAGA, Estado.CANCELADA},
        Estado.PAGA: {Estado.EM_PREPARACAO, Estado.CANCELADA},
        Estado.EM_PREPARACAO: {Estado.ENVIADA, Estado.CANCELADA},
        Estado.ENVIADA: {Estado.ENTREGUE},
        Estado.ENTREGUE: set(),
        Estado.CANCELADA: set(),
    }

    aluno = models.ForeignKey(UtilizadorAluno, on_delete=models.CASCADE, related_name="encomendas")
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDENTE_PAGAMENTO)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    morada_entrega = models.CharField(max_length=255)
    codigo_rastreio = models.CharField(max_length=100, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)
    data_envio = models.DateTimeField(null=True, blank=True)
    data_entrega = models.DateTimeField(null=True, blank=True)

    def pode_transitar(self, novo_estado):
        return novo_estado in self.TRANSICOES[self.estado]

    def transitar(self, novo_estado, **campos):
        if not self.pode_transitar(novo_estado):
            raise TransicaoInvalida(f"Encomenda nao pode passar de '{self.estado}' para '{novo_estado}'.")
        self.estado = novo_estado
        for nome, valor in campos.items():
            setattr(self, nome, valor)
        self.save(update_fields=["estado", *campos])
        EventoEncomenda.objects.create(encomenda=self, estado=novo_estado)

    def __str__(self):
        return f"Encomenda {self.id} ({self.estado})"


class ItemEncomenda(models.Model):
    """Linha da encomenda com o nome e preco no momento da compra."""
    encomenda = models.ForeignKey(Encomenda, on_delete=models.CASCADE, related_name="itens")
    produto = models.ForeignKey(Produto, on_delete=models.SET_NULL, null=True, blank=True)
    nome = models.CharField(max_length=255)
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    quantidade = models.PositiveIntegerField()

    @property
    def subtotal(self):
        return self.preco_unitario * self.quantidade


class EventoEncomenda(models.Model):
    """Linha temporal de rastreamento: um registo por cada mudanca de estado da encomenda."""
    encomenda = models.ForeignKey(Encomenda, on_delete=models.CASCADE, related_name="eventos")
    estado = models.CharField(max_length=20, choices=Encomenda.Estado.choices)
    nota = models.CharField(max_length=255, blank=True)
    data = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["data", "id"]


class SequenciaDocumento(models.Model):
    """Contador de numeracao por tipo de documento e ano (sem falhas nem repeticoes)."""
    tipo = models.CharField(max_length=10)
    ano = models.PositiveIntegerField()
    ultimo = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tipo", "ano"], name="sequencia_unica_por_tipo_e_ano")]


class DocumentoFinanceiro(models.Model):
    """Fatura ou recibo emitido automaticamente quando um pagamento e aprovado.
    TODO: nao e um documento fiscalmente certificado; a emissao oficial (ex.: software certificado)
    depende de requisitos legais a confirmar."""

    class Tipo(models.TextChoices):
        FATURA = "FT", "Fatura"
        RECIBO = "RC", "Recibo"

    pagamento = models.ForeignKey(Pagamento, on_delete=models.PROTECT, related_name="documentos")
    cliente = models.ForeignKey(Utilizador, on_delete=models.PROTECT, related_name="documentos_financeiros")
    tipo = models.CharField(max_length=2, choices=Tipo.choices)
    numero = models.CharField(max_length=20, unique=True)  # ex.: FT 2026/0001
    linhas = models.JSONField(default=list)  # [{"descricao", "quantidade", "preco_unitario", "subtotal"}]
    total = models.DecimalField(max_digits=10, decimal_places=2)
    data_emissao = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["pagamento", "tipo"], name="um_documento_por_tipo_e_pagamento")]
        ordering = ["-data_emissao", "-id"]

    def __str__(self):
        return self.numero


class ParceriaPT(models.Model):
    """UC-13: Personal Trainer parceiro da plataforma, com remuneracao mensal fixa (BR-04)."""

    class Estado(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        ATIVA = "ativa", "Ativa"
        RECUSADA = "recusada", "Recusada"
        TERMINADA = "terminada", "Terminada"

    personal_trainer = models.OneToOneField(PersonalTrainer, on_delete=models.CASCADE, related_name="parceria")
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDENTE)
    mensagem = models.TextField(blank=True)  # apresentacao do PT na candidatura
    remuneracao_mensal = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])  # definida pelo admin
    data_candidatura = models.DateTimeField(auto_now_add=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Parceria {self.personal_trainer_id} ({self.estado})"


class RemuneracaoParceria(models.Model):
    """Registo da remuneracao mensal devida a um PT parceiro. So e registada: o pagamento efetivo
    e marcado manualmente pelo admin (TODO: transferencia automatica via gateway)."""

    class Estado(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        PAGA = "paga", "Paga"

    parceria = models.ForeignKey(ParceriaPT, on_delete=models.CASCADE, related_name="remuneracoes")
    mes = models.DateField()  # primeiro dia do mes de referencia
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDENTE)
    data_pagamento = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["parceria", "mes"], name="uma_remuneracao_por_mes")]
        ordering = ["-mes"]
