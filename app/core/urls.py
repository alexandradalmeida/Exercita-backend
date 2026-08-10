from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    RegistoView, ConfirmarEmailView, LoginView, LogoutView,
    MeuPerfilAlunoView, MeuPerfilPersonalTrainerView,
    VerificarPersonalTrainerView,
    GoogleLoginView, GoogleCallbackView,
)

urlpatterns = [
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/google/", GoogleLoginView.as_view(), name="google_login"),
    path("auth/google/callback/", GoogleCallbackView.as_view(), name="google_callback"),
    path("users/", RegistoView.as_view(), name="registo"),
    path("users/confirm-email/", ConfirmarEmailView.as_view(), name="confirmar_email"),
    path("perfil/aluno/", MeuPerfilAlunoView.as_view(), name="perfil_aluno"),
    path("perfil/personal-trainer/", MeuPerfilPersonalTrainerView.as_view(), name="perfil_pt"),
    path("personal-trainers/<int:pk>/verificar/", VerificarPersonalTrainerView.as_view(), name="verificar_pt"),
]