from django.urls import include, path
from rest_framework.routers import SimpleRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views_marketplace import CertificacaoViewSet, SlotDisponibilidadeViewSet, FavoritoDetalheView, FavoritosView, TrainerDisponibilidadeView, TrainerListView, TrainerPerfilView
from .views import (
    RegistoView, ConfirmarEmailView, LoginView, LogoutView,
    MeuPerfilAlunoView, MeuPerfilPersonalTrainerView,
    VerificarPersonalTrainerView,
    GoogleLoginView, GoogleCallbackView,
    AppleLoginView,
)

router = SimpleRouter()
router.register("perfil/personal-trainer/certificacoes", CertificacaoViewSet, basename="certificacao")
router.register("perfil/personal-trainer/slots", SlotDisponibilidadeViewSet, basename="slot")

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
    path("trainers/", TrainerListView.as_view(), name="trainers"),
    path("trainers/<int:pk>/profile/", TrainerPerfilView.as_view(), name="trainer_profile"),
    path("trainers/<int:pk>/availability/", TrainerDisponibilidadeView.as_view(), name="trainer_availability"),
    path("favorites/", FavoritosView.as_view(), name="favoritos"),
    path("favorites/<int:pk>/", FavoritoDetalheView.as_view(), name="favorito_detalhe"),
    path("", include(router.urls)),
]
