import time
import jwt
from decouple import config


def gerar_apple_client_secret():
    """Gera o JWT que a Apple exige como 'client_secret' (expira em 6 meses no máximo)."""
    team_id = config("APPLE_TEAM_ID")
    client_id = config("APPLE_CLIENT_ID")
    key_id = config("APPLE_KEY_ID")
    private_key_path = config("APPLE_PRIVATE_KEY_PATH")

    with open(private_key_path, "r") as f:
        private_key = f.read()

    now = int(time.time())
    payload = {
        "iss": team_id,
        "iat": now,
        "exp": now + 3600,  # 1h de validade neste JWT específico (pode ir até 6 meses)
        "aud": "https://appleid.apple.com",
        "sub": client_id,
    }

    headers = {"kid": key_id, "alg": "ES256"}

    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)