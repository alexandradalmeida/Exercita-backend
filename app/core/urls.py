from django.urls import include, path
from rest_framework.routers import SimpleRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views_notificacoes import NotificacaoDetalheView, NotificacaoListView, NotificacoesMarcarLidasView
from .views_ginasios import GinasioViewSet
from .views_reservas import MinhasReservasView, ReservaDetalheView, ReservarGinasioView
from .views_ginasios_trainers import GinasioTrainerDetalheView, GinasioTrainersView
from .views_sessoes import (
    IniciarPagamentoView, LibertarPagamentoView, PagamentoWebhookView, SessaoAvaliacoesView, SessaoCalendarioView, SessaoDetalheView, SessaoListCreateView,
)
from .views_marketplace import CertificacaoViewSet, SlotDisponibilidadeViewSet, FavoritoDetalheView, FavoritosView, TrainerDisponibilidadeView, TrainerListView, TrainerPerfilView
from .views import (
    RegistoView, ConfirmarEmailView, LoginView, LogoutView,
    MeuPerfilAlunoView, MeuPerfilPersonalTrainerView,
    VerificarPersonalTrainerView, ReativarPersonalTrainerView,
    GoogleLoginView, GoogleCallbackView,
    AppleLoginView,
)

router = SimpleRouter()
router.register("perfil/personal-trainer/certificacoes", CertificacaoViewSet, basename="certificacao")
router.register("perfil/personal-trainer/slots", SlotDisponibilidadeViewSet, basename="slot")
router.register("gyms", GinasioViewSet, basename="ginasio")

urlpatterns = [
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/google/", GoogleLoginView.as_view(), name="google_login"),
    path("auth/google/callback/", GoogleCallbackView.as_view(), name="google_callback"),
    path("auth/apple/", AppleLoginView.as_view(), name="apple_login"),
    path("users/", RegistoView.as_view(), name="registo"),
    path("users/confirm-email/", ConfirmarEmailView.as_view(), name="confirmar_email"),
    path("perfil/aluno/", MeuPerfilAlunoView.as_view(), name="perfil_aluno"),
    path("perfil/personal-trainer/", MeuPerfilPersonalTrainerView.as_view(), name="perfil_pt"),
    path("personal-trainers/<int:pk>/verificar/", VerificarPersonalTrainerView.as_view(), name="verificar_pt"),
    path("personal-trainers/<int:pk>/reativar/", ReativarPersonalTrainerView.as_view(), name="reativar_pt"),
    path("trainers/", TrainerListView.as_view(), name="trainers"),
    path("trainers/<int:pk>/profile/", TrainerPerfilView.as_view(), name="trainer_profile"),
    path("trainers/<int:pk>/availability/", TrainerDisponibilidadeView.as_view(), name="trainer_availability"),
    path("gyms/<int:pk>/trainers/", GinasioTrainersView.as_view(), name="ginasio_trainers"),
    path("gyms/<int:pk>/trainers/<int:trainer_id>/", GinasioTrainerDetalheView.as_view(), name="ginasio_trainer"),
    path("gyms/<int:pk>/bookings/", ReservarGinasioView.as_view(), name="ginasio_reservar"),
    path("gym-bookings/", MinhasReservasView.as_view(), name="reservas_ginasio"),
    path("gym-bookings/<int:pk>/", ReservaDetalheView.as_view(), name="reserva_ginasio"),
    path("favorites/", FavoritosView.as_view(), name="favoritos"),
    path("favorites/<int:pk>/", FavoritoDetalheView.as_view(), name="favorito_detalhe"),
    path("sessions/", SessaoListCreateView.as_view(), name="sessoes"),
    path("sessions/<int:pk>/", SessaoDetalheView.as_view(), name="sessao_detalhe"),
    path("sessions/<int:pk>/calendar/", SessaoCalendarioView.as_view(), name="sessao_calendario"),
    path("sessions/<int:pk>/reviews/", SessaoAvaliacoesView.as_view(), name="sessao_avaliacoes"),
    path("payments/", IniciarPagamentoView.as_view(), name="pagamento_iniciar"),
    path("notifications/", NotificacaoListView.as_view(), name="notificacoes"),
    path("notifications/read-all/", NotificacoesMarcarLidasView.as_view(), name="notificacoes_ler_todas"),
    path("notifications/<int:pk>/", NotificacaoDetalheView.as_view(), name="notificacao_detalhe"),
    path("payments/<int:pk>/webhook/", PagamentoWebhookView.as_view(), name="pagamento_webhook"),
    path("payments/<int:pk>/release/", LibertarPagamentoView.as_view(), name="pagamento_release"),
    path("", include(router.urls)),
]
