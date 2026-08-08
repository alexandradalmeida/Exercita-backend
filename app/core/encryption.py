import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from decouple import config

_KEY = base64.urlsafe_b64decode(config("FIELD_ENCRYPTION_KEY"))


def encrypt_value(plaintext: str) -> str:
    if plaintext is None or plaintext == "":
        return plaintext

    aesgcm = AESGCM(_KEY)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()


def decrypt_value(token: str) -> str:
    if token is None or token == "":
        return token

    aesgcm = AESGCM(_KEY)
    raw = base64.urlsafe_b64decode(token)
    nonce, ciphertext = raw[:12], raw[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode()