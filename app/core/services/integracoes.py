"""Estado das integracoes externas, para a lista de verificacao de lancamento (Fase 9)."""
from decouple import config

ATIVA, SIMULADA, EM_FALTA = "ativa", "simulada", "em_falta"


def _estado(backend, simulados, em_falta=()):
    if backend in em_falta:
        return EM_FALTA
    return SIMULADA if backend in simulados else ATIVA


def estado_das_integracoes():
    """Cada integracao: modo configurado, estado (ativa/simulada/em_falta) e o que falta para ficar ativa."""
    multicaixa = config("MULTICAIXA_BACKEND", default="mock")
    embeddings = config("EMBEDDINGS_BACKEND", default="")
    chave_openai = config("OPENAI_API_KEY", default="")
    geocoding = config("GEOCODING_BACKEND", default="none")
    google = bool(config("GOOGLE_CLIENT_ID", default="")) and not config("GOOGLE_CLIENT_ID", default="").startswith("google-client-id")
    apple = bool(config("APPLE_CLIENT_ID", default="")) and not config("APPLE_CLIENT_ID", default="").startswith("com.exemplo")
    email = config("EMAIL_HOST", default="")

    return {
        "multicaixa_express": {
            "modo": multicaixa,
            # a implementacao real ainda nao existe: com `real` os pagamentos falham de forma controlada (502)
            "estado": EM_FALTA if multicaixa == "real" else SIMULADA,
            "falta": "Contrato/credenciais do Multicaixa Express e implementacao de MulticaixaReal "
                     "(iniciar_transacao, reembolsar, transferir_para_pt, formato e assinatura do webhook).",
            "webhook_secret_definido": bool(config("MULTICAIXA_WEBHOOK_SECRET", default="")),
        },
        "google_oauth": {
            "modo": "configurado" if google else "nao_configurado",
            "estado": ATIVA if google else EM_FALTA,
            "falta": "" if google else "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI de producao.",
        },
        "apple_sign_in": {
            "modo": "configurado" if apple else "nao_configurado",
            "estado": ATIVA if apple else EM_FALTA,
            "falta": "" if apple else "APPLE_CLIENT_ID (e TEAM_ID/KEY_ID/chave .p8 para o fluxo web).",
        },
        "email": {
            "modo": "smtp" if email else "consola",
            "estado": ATIVA if email else EM_FALTA,
            "falta": "" if email else "EMAIL_HOST / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD (confirmacao de conta e notificacoes).",
        },
        "push_fcm_apns": {
            "modo": "mock", "estado": SIMULADA,
            "falta": "Credenciais FCM/APNs, tokens de dispositivo e implementacao de PushGateway.",
        },
        "geocodificacao": {
            "modo": geocoding, "estado": _estado(geocoding, ("mock",), ("none", "google")),
            "falta": "" if geocoding == "mock" else "Chave da API de mapas e implementacao de GeocodingGoogle "
                                                    "(ate la, ginasios precisam de latitude/longitude manuais).",
        },
        "embeddings_matching": {
            "modo": embeddings or ("openai" if chave_openai and not chave_openai.startswith("sk-ficticia") else "hash"),
            "estado": ATIVA if (embeddings == "openai" or (not embeddings and chave_openai and not chave_openai.startswith("sk-ficticia"))) else SIMULADA,
            "falta": "OPENAI_API_KEY valida (sem ela o matching usa um gerador local lexical).",
        },
        "google_calendar": {
            "modo": "ics", "estado": SIMULADA,
            "falta": "OAuth de calendario para sincronizacao automatica (a exportacao .ics ja funciona).",
        },
        "wearables": {
            "modo": "estrutura", "estado": SIMULADA,
            "falta": "Conectores Apple Health / Google Fit e autenticacao de dispositivo.",
        },
        "faturacao_certificada": {
            "modo": "interna", "estado": SIMULADA,
            "falta": "Software de faturacao certificado (as faturas atuais nao tem valor fiscal).",
        },
    }


def pronto_para_lancamento(estado=None):
    """Lista de bloqueios (integracoes criticas que nao estao ativas)."""
    estado = estado or estado_das_integracoes()
    criticas = ("multicaixa_express", "email", "google_oauth")
    return [nome for nome in criticas if estado[nome]["estado"] != ATIVA]
