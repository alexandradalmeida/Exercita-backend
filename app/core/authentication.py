from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


class JWTAuthenticationSemSuspensos(JWTAuthentication):
    """Como o JWT normal, mas recusa de imediato tokens de utilizadores suspensos pela administracao
    (os access tokens ja emitidos deixam de valer sem esperar pela expiracao)."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if user.suspenso:
            raise AuthenticationFailed("Conta suspensa pela administracao.", code="user_suspended")
        return user
