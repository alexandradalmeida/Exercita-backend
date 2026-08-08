from django.db import models
from .encryption import encrypt_value, decrypt_value


class EncryptedCharField(models.TextField):
    """Campo de texto que encripta o valor antes de gravar no banco (AES-256-GCM)
    e desencripta automaticamente ao ler."""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return encrypt_value(value)

    def from_db_value(self, value, expression, connection):
        return decrypt_value(value)

    def to_python(self, value):
        return value