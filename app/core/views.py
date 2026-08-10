import secrets
from urllib.parse import urlencode

import requests as http_requests
from decouple import config
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import PersonalTrainer, Utilizador, UtilizadorAluno
from .serializers import (
    LoginSerializer,
    PersonalTrainerSerializer,
    RegistoSerializer,
    UtilizadorAlunoSerializer,
)


class RegistoView(generics.CreateAPIView):
    queryset = Utilizador.objects.all()
    serializer_class = RegistoSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        utilizador = serializer.save()

        uid = urlsafe_base64_encode(force_bytes(utilizador.pk))
        token = default_token_generator.make_token(utilizador)
        link_confirmacao = f"http://localhost:8000/api/v1/users/confirm-email/?uid={uid}&token={token}"

        send_mail(
            subject="Confirme o seu email - Exercita",
            message=f"Ola {utilizador.username}, confirme o seu email clicando aqui: {link_confirmacao}",
            from_email=None,
            recipient_list=[utilizador.email],
        )


class ConfirmarEmailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        uid = request.query_params.get("uid")
        token = request.query_params.get("token")

        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            utilizador = Utilizador.objects.get(pk=user_id)
        except (TypeError, ValueError, OverflowError, Utilizador.DoesNotExist):
            return Response({"mensagem": "Link invalido."}, status=status.HTTP_400_BAD_REQUEST)

        if default_token_generator.check_token(utilizador, token):
            utilizador.is_active = True
            utilizador.save()
            return Response({"mensagem": "Email confirmado com sucesso."}, status=status.HTTP_200_OK)

        return Response({"mensagem": "Token invalido ou expirado."}, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        utilizador = serializer.validated_data["utilizador"]

        refresh = RefreshToken.for_user(utilizador)

        return Response({
            "session_token": str(refresh.access_token),
            "refresh_token": str(refresh),
            "utilizador": {
                "id": utilizador.id,
                "username": utilizador.username,
                "tipo": utilizador.tipo,
            }
        }, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            refresh_token = request.data["refresh_token"]
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception:
            return Response({"mensagem": "Token invalido."}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"mensagem": "Logout efetuado com sucesso."}, status=status.HTTP_200_OK)


class MeuPerfilAlunoView(generics.RetrieveUpdateAPIView):
    serializer_class = UtilizadorAlunoSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user.perfil_aluno


class MeuPerfilPersonalTrainerView(generics.RetrieveUpdateAPIView):
    serializer_class = PersonalTrainerSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user.perfil_personal_trainer


class VerificarPersonalTrainerView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            pt = PersonalTrainer.objects.get(pk=pk)
        except PersonalTrainer.DoesNotExist:
            return Response({"mensagem": "Personal Trainer nao encontrado."}, status=status.HTTP_404_NOT_FOUND)

        pt.estado_verificacao = PersonalTrainer.EstadoVerificacao.VERIFICADO
        pt.save()

        return Response({
            "mensagem": "Personal Trainer verificado com sucesso.",
            "id": pt.id,
            "estado_verificacao": pt.estado_verificacao,
        }, status=status.HTTP_200_OK)


GOOGLE_CLIENT_ID = config("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = config("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = config("GOOGLE_REDIRECT_URI")

# armazenamento simples em memória para os states (dev only)
# em produção isto deve usar cache (Redis) com expiração
_GOOGLE_STATES = set()


class GoogleLoginView(APIView):
    """Gera a URL de autorização do Google, com um 'state' único (protecao CSRF)."""
    permission_classes = [AllowAny]

    def get(self, request):
        state = secrets.token_urlsafe(32)
        _GOOGLE_STATES.add(state)

        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

        return Response({"auth_url": auth_url, "state": state}, status=status.HTTP_200_OK)


class GoogleCallbackView(APIView):
    """Recebe o 'code' e 'state' do Google, valida, troca por tokens,
    valida o id_token, e cria/autentica o utilizador."""
    permission_classes = [AllowAny]

    def get(self, request):
        code = request.query_params.get("code")
        state = request.query_params.get("state")

        if not code or not state:
            return Response({"mensagem": "code e state sao obrigatorios."}, status=status.HTTP_400_BAD_REQUEST)

        if state not in _GOOGLE_STATES:
            return Response({"mensagem": "State invalido (possivel CSRF)."}, status=status.HTTP_400_BAD_REQUEST)
        _GOOGLE_STATES.discard(state)  # state só pode ser usado uma vez

        # troca o code por tokens
        token_response = http_requests.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })

        if token_response.status_code != 200:
            return Response({"mensagem": "Falha ao trocar code por tokens.", "detalhe": token_response.text},
                             status=status.HTTP_400_BAD_REQUEST)

        tokens = token_response.json()
        raw_id_token = tokens.get("id_token")

        if not raw_id_token:
            return Response({"mensagem": "id_token nao recebido do Google."}, status=status.HTTP_400_BAD_REQUEST)

        # valida o id_token (assinatura RS256, issuer, audience)
        try:
            id_info = google_id_token.verify_oauth2_token(
                raw_id_token, google_requests.Request(), GOOGLE_CLIENT_ID
            )
        except ValueError as e:
            return Response({"mensagem": "id_token invalido.", "detalhe": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        email = id_info.get("email")
        if not email:
            return Response({"mensagem": "Email nao disponivel no id_token."}, status=status.HTTP_400_BAD_REQUEST)

        # cria o utilizador se nao existir, ou reutiliza o existente
        utilizador, criado = Utilizador.objects.get_or_create(
            email=email,
            defaults={
                "username": email.split("@")[0],
                "tipo": Utilizador.TipoUtilizador.ALUNO,  # padrão; pode ser ajustado depois via perfil
                "is_active": True,  # login social já vem com email verificado pelo Google
            }
        )

        if criado and utilizador.tipo == Utilizador.TipoUtilizador.ALUNO:
            UtilizadorAluno.objects.create(utilizador=utilizador)

        refresh = RefreshToken.for_user(utilizador)

        return Response({
            "session_token": str(refresh.access_token),
            "refresh_token": str(refresh),
            "novo_utilizador": criado,
            "utilizador": {
                "id": utilizador.id,
                "username": utilizador.username,
                "email": utilizador.email,
                "tipo": utilizador.tipo,
            }
        }, status=status.HTTP_200_OK)