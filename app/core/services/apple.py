import jwt
from decouple import config

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"

_jwks_client = jwt.PyJWKClient(APPLE_JWKS_URL, cache_keys=True)


class AppleTokenInvalido(Exception):
    pass


def validar_id_token_apple(raw_id_token):
    """Valida o id_token da Apple (assinatura RS256 via JWKS, issuer, audience, expiracao)
    e devolve os claims. Levanta AppleTokenInvalido se algo falhar."""
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(raw_id_token)
        return jwt.decode(
            raw_id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=config("APPLE_CLIENT_ID"),
            issuer=APPLE_ISSUER,
        )
    except jwt.PyJWTError as e:
        raise AppleTokenInvalido(str(e))