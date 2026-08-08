from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.core.mail import send_mail
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated
from .serializers import UtilizadorAlunoSerializer, PersonalTrainerSerializer
from .models import UtilizadorAluno, PersonalTrainer
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import LoginSerializer
from rest_framework.permissions import IsAdminUser


from .models import Utilizador
from .serializers import RegistoSerializer


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