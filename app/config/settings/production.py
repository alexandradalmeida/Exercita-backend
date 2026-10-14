from decouple import Csv, config
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEBUG = False

# --- configuracao obrigatoria: falha no arranque em vez de correr de forma insegura ---
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="", cast=Csv())
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Defina ALLOWED_HOSTS com os dominios reais (sem '*').")
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("django-insecure-") or "troque" in SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY tem de ter pelo menos 50 caracteres e ser unica de producao.")

# --- encriptacao em transito (RNF-02) ---
# o TLS termina no load balancer/proxy, que tem de enviar X-Forwarded-Proto
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=31536000, cast=int)  # 1 ano
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=False, cast=bool)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# ligacao a base de dados tambem encriptada (disable|require|verify-full ...)
DATABASES["default"]["OPTIONS"] = {"sslmode": config("POSTGRES_SSLMODE", default="require")}  # noqa: F405
DATABASES["default"]["CONN_MAX_AGE"] = config("DB_CONN_MAX_AGE", default=60, cast=int)  # noqa: F405

# --- email real ---
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@exercita.com")

# --- cache partilhada entre instancias (state do OAuth, limites de pedidos) ---
# Com varias instancias a cache local por processo nao serve: usar Redis (REDIS_URL).
if config("REDIS_URL", default=""):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": config("REDIS_URL")}}

# --- logs para stdout (recolhidos pela plataforma de monitorizacao) ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simples": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"consola": {"class": "logging.StreamHandler", "formatter": "simples"}},
    "root": {"handlers": ["consola"], "level": config("LOG_LEVEL", default="INFO")},
}
