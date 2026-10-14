"""Anotacoes OpenAPI (drf-spectacular) para as views que nao usam GenericAPIView/serializers.

Aplicadas depois da definicao das views (em `CoreConfig.ready`), para nao poluir a logica de negocio.
"""
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, inline_serializer
from rest_framework import serializers

OBJETO = OpenApiTypes.OBJECT


class JWTSemSuspensosScheme(OpenApiAuthenticationExtension):
    target_class = "core.authentication.JWTAuthenticationSemSuspensos"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                "description": "Token `session_token` devolvido por /auth/login/."}


def _corpo(nome, **campos):
    return inline_serializer(name=nome, fields=campos)


DATA = [OpenApiParameter("de", OpenApiTypes.DATE, description="Data inicial (AAAA-MM-DD), inclusiva."),
        OpenApiParameter("ate", OpenApiTypes.DATE, description="Data final (AAAA-MM-DD), inclusiva.")]


def aplicar():
    from . import views, views_admin, views_configuracao, views_loja, views_marketplace, views_notificacoes
    from . import views_parcerias, views_progresso, views_relatorios, views_sessoes
    from . import serializers as s
    from .serializers_progresso import WearableIngestaoSerializer

    def anotar(view, metodo, **kwargs):
        funcao = getattr(view, metodo)
        setattr(view, metodo, extend_schema(**kwargs)(funcao))

    # --- autenticacao ---
    anotar(views.LoginView, "post", request=s.LoginSerializer, responses=OBJETO, tags=["auth"],
           description="Devolve `session_token`, `refresh_token` e o utilizador.")
    anotar(views.LogoutView, "post", request=_corpo("LogoutPedido", refresh_token=serializers.CharField()),
           responses=OBJETO, tags=["auth"])
    anotar(views.GoogleLoginView, "get", responses=OBJETO, tags=["auth"],
           description="Devolve `auth_url` e `state` (CSRF, valido 10 minutos e de uso unico).")
    anotar(views.GoogleCallbackView, "get", responses=OBJETO, tags=["auth"], parameters=[
        OpenApiParameter("code", str), OpenApiParameter("state", str)])
    anotar(views.AppleLoginView, "post", request=_corpo("ApplePedido", id_token=serializers.CharField()),
           responses=OBJETO, tags=["auth"])
    anotar(views.ConfirmarEmailView, "get", responses=OBJETO, tags=["auth"], parameters=[
        OpenApiParameter("uid", str), OpenApiParameter("token", str)])
    anotar(views.VerificarPersonalTrainerView, "post", request=None, responses=OBJETO, tags=["admin"])
    anotar(views.ReativarPersonalTrainerView, "post", request=None, responses=OBJETO, tags=["admin"])

    # --- marketplace ---
    anotar(views_marketplace.FavoritoDetalheView, "delete", responses={204: None}, tags=["marketplace"])
    anotar(views_marketplace.FavoritosView, "post", request=_corpo("FavoritoPedido", trainer_id=serializers.IntegerField()),
           responses=OBJETO, tags=["marketplace"])

    # --- sessoes e pagamentos ---
    anotar(views_sessoes.IniciarPagamentoView, "post", request=_corpo(
        "IniciarPagamentoPedido", sessao_id=serializers.IntegerField(required=False),
        encomenda_id=serializers.IntegerField(required=False)), responses=s.PagamentoSerializer, tags=["pagamentos"])
    anotar(views_sessoes.LibertarPagamentoView, "post", request=None, responses=s.PagamentoSerializer, tags=["pagamentos"])
    anotar(views_sessoes.PagamentoWebhookView, "post", request=_corpo(
        "WebhookPedido", referencia=serializers.CharField(),
        estado=serializers.ChoiceField(choices=["aprovado", "recusado"])), responses=OBJETO, tags=["pagamentos"],
        description="Callback assincrono do gateway. Exige o cabecalho `X-Signature` (HMAC-SHA256 do corpo).")
    anotar(views_sessoes.SessaoCalendarioView, "get", responses={(200, "text/calendar"): OpenApiTypes.STR}, tags=["sessoes"])
    anotar(views_sessoes.SessaoAvaliacoesView, "get", responses=s.AvaliacaoSerializer(many=True), tags=["sessoes"])
    anotar(views_sessoes.SessaoAvaliacoesView, "post", request=s.CriarAvaliacaoSerializer,
           responses=s.AvaliacaoSerializer, tags=["sessoes"])

    # --- loja ---
    anotar(views_loja.CarrinhoView, "get", responses=OBJETO, tags=["loja"])
    anotar(views_loja.CarrinhoView, "delete", responses={204: None}, tags=["loja"])
    anotar(views_loja.CarrinhoItensView, "post", request=s.AdicionarItemSerializer,
           responses=s.ItemCarrinhoSerializer, tags=["loja"])
    anotar(views_loja.CarrinhoItemView, "patch", request=s.QuantidadeItemSerializer,
           responses=s.ItemCarrinhoSerializer, tags=["loja"])
    anotar(views_loja.CarrinhoItemView, "delete", responses={204: None}, tags=["loja"])
    anotar(views_loja.CheckoutView, "post", request=s.CheckoutSerializer, responses=s.EncomendaSerializer, tags=["loja"])

    # --- notificacoes, parcerias, progresso ---
    anotar(views_notificacoes.NotificacoesMarcarLidasView, "post", request=None, responses=OBJETO, tags=["notificacoes"])
    anotar(views_parcerias.MinhaParceriaView, "get", responses=s.ParceriaSerializer, tags=["parcerias"])
    anotar(views_parcerias.MinhaParceriaView, "post", request=_corpo("CandidaturaPedido", mensagem=serializers.CharField(required=False)),
           responses=s.ParceriaSerializer, tags=["parcerias"])
    anotar(views_parcerias.ParceriaAcaoView, "post", request=_corpo(
        "ParceriaAcaoPedido", remuneracao_mensal=serializers.DecimalField(max_digits=10, decimal_places=2, required=False)),
        responses=s.ParceriaSerializer, tags=["admin"], parameters=[
            OpenApiParameter("acao", str, OpenApiParameter.PATH, enum=["aprovar", "recusar", "terminar"])])
    anotar(views_parcerias.RemuneracaoPagaView, "post", request=None, responses=s.RemuneracaoParceriaSerializer, tags=["admin"])
    anotar(views_progresso.ResumoProgressoView, "get", responses=OBJETO, tags=["progresso"])
    anotar(views_progresso.WearableIngestaoView, "post", request=WearableIngestaoSerializer, responses=OBJETO, tags=["progresso"])
    anotar(views.VerificarPersonalTrainerView, "post", request=None, responses=OBJETO, tags=["admin"])

    # --- administracao ---
    from .views_nutricao import VerificarNutricionistaView
    anotar(VerificarNutricionistaView, "post", request=None, responses=OBJETO, tags=["admin"])
    anotar(views_configuracao.ConfiguracaoView, "get", responses=views_configuracao.ConfiguracaoSerializer, tags=["admin"])
    anotar(views_configuracao.ConfiguracaoView, "patch", request=views_configuracao.ConfiguracaoSerializer,
           responses=views_configuracao.ConfiguracaoSerializer, tags=["admin"])
    anotar(views_relatorios.RelatorioPlataformaView, "get", responses=OBJETO, parameters=DATA, tags=["admin"])
    anotar(views_relatorios.RelatorioFinanceiroView, "get", responses={(200, "text/csv"): OpenApiTypes.STR}, tags=["admin"],
           parameters=DATA + [OpenApiParameter("tipo", str, enum=["pagamentos", "parcerias"])])

    # --- campos calculados (SerializerMethodField) ---
    for serializer, nome, tipo in (
        (views_admin.UtilizadorAdminSerializer, "get_estado_perfil", OpenApiTypes.STR),
        (s.TrainerListaSerializer, "get_vagas_disponiveis", OpenApiTypes.INT),
        (s.TrainerListaSerializer, "get_lotacao_atingida", OpenApiTypes.BOOL),
        (s.TrainerPerfilPublicoSerializer, "get_avaliacoes", s.AvaliacaoPublicaSerializer(many=True)),
        (s.TrainerPerfilPublicoSerializer, "get_ginasios", OBJETO),
        (s.EncomendaSerializer, "get_rastreamento", s.EventoEncomendaSerializer(many=True)),
        (s.ProdutoSerializer, "get_em_stock", OpenApiTypes.BOOL),
    ):
        setattr(serializer, nome, extend_schema_field(tipo)(getattr(serializer, nome)))
    from .serializers_progresso import MetricaFisicaSerializer
    MetricaFisicaSerializer.get_imc = extend_schema_field(OpenApiTypes.FLOAT)(MetricaFisicaSerializer.get_imc)
    # --- RGPD ---
    from . import views_rgpd
    anotar(views_rgpd.ExportarDadosView, "get", responses={(200, "application/json"): OBJETO}, tags=["rgpd"],
           description="Descarrega todos os dados pessoais do utilizador (acesso e portabilidade).")
    anotar(views_rgpd.ApagarContaView, "delete", request=_corpo("ApagarContaPedido", password=serializers.CharField()),
           responses={204: None}, tags=["rgpd"],
           description="Apaga/anonimiza a conta. Exige a password e nenhuma obrigacao em aberto (409 se existir).")

    # campos calculados restantes
    s.ItemCarrinhoSerializer.get_subtotal = extend_schema_field(OpenApiTypes.DECIMAL)(s.ItemCarrinhoSerializer.get_subtotal)
    views_configuracao.ConfiguracaoSerializer.get_efetivos = extend_schema_field(OBJETO)(
        views_configuracao.ConfiguracaoSerializer.get_efetivos)
