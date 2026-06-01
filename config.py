from dotenv import load_dotenv

import os


load_dotenv()


def ler_env(nome, padrao=None):

    valor = os.getenv(nome, padrao)

    if valor is None:

        return None

    return str(valor).strip().strip('"').strip("'")


def exigir_env(nome):

    valor = ler_env(nome)

    if not valor:

        raise RuntimeError(
            f"{nome} precisa estar configurada nas variaveis de ambiente"
        )

    return valor


def exigir_secret_key():

    valor = exigir_env("SECRET_KEY")

    valores_inseguros = {
        "55pbx_ai",
        "troque_por_uma_chave_grande_e_aleatoria",
        "gere_uma_chave_aleatoria_com_mais_de_32_caracteres",
        "COLE_UMA_CHAVE_GRANDE_ALEATORIA_AQUI"
    }

    if valor in valores_inseguros or len(valor) < 32:

        raise RuntimeError(
            "SECRET_KEY precisa ser uma chave aleatoria com pelo menos 32 caracteres"
        )

    return valor


def exigir_admin_senha():

    valor = exigir_env("ADMIN_SENHA")

    valores_inseguros = {
        "123456",
        "admin",
        "senha",
        "password",
        "troque_por_uma_senha_forte"
    }

    if valor in valores_inseguros or len(valor) < 8:

        raise RuntimeError(
            "ADMIN_SENHA precisa ser definida no ambiente e nao pode ser uma senha padrao"
        )

    return valor


def ler_float(nome, padrao):

    return float(
        ler_env(nome, padrao)
    )


def ler_int(nome, padrao):

    return int(
        ler_env(nome, padrao)
    )


OPENAI_API_KEY = ler_env("OPENAI_API_KEY")
GROQ_API_KEY = ler_env("GROQ_API_KEY") or ler_env("GROQ_API_TOKEN")
GROQ_BASE_URL = ler_env("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

DATABASE_URL = ler_env("DATABASE_URL")
DB_HOST = ler_env("DB_HOST")
DB_PORT = ler_env("DB_PORT")
DB_NAME = ler_env("DB_NAME")
DB_USER = ler_env("DB_USER")
DB_PASSWORD = ler_env("DB_PASSWORD")

ADMIN_USUARIO = exigir_env("ADMIN_USUARIO")
ADMIN_SENHA = exigir_admin_senha()
SECRET_KEY = exigir_secret_key()

TRANSCRIBE_PROVIDER = ler_env(
    "TRANSCRIBE_PROVIDER",
    "groq" if GROQ_API_KEY else "openai"
).lower()

DEFAULT_TRANSCRIBE_MODEL = (
    "whisper-large-v3-turbo"
    if TRANSCRIBE_PROVIDER == "groq"
    else "gpt-4o-mini-transcribe"
)

TRANSCRIBE_MODEL = ler_env("TRANSCRIBE_MODEL", DEFAULT_TRANSCRIBE_MODEL)
SUMMARY_MODEL = ler_env("SUMMARY_MODEL", "gpt-4.1-mini")

TRANSCRIBE_USD_HORA = ler_float(
    "TRANSCRIBE_USD_HORA",
    "0.04" if TRANSCRIBE_PROVIDER == "groq" else "0.36"
)

SUMMARY_USD_POR_ATENDIMENTO = ler_float(
    "SUMMARY_USD_POR_ATENDIMENTO",
    "0.003"
)

USD_BRL_RATE = ler_float("USD_BRL_RATE", "5.00")

MAX_CALLS_PER_DAY = ler_int("MAX_CALLS_PER_DAY", "5")
MAX_AUDIO_MINUTES_PER_DAY = ler_int("MAX_AUDIO_MINUTES_PER_DAY", "50")
MAX_SUMMARIES_PER_DAY = ler_int("MAX_SUMMARIES_PER_DAY", "10")
MAX_COST_PER_USER_PER_DAY = ler_float("MAX_COST_PER_USER_PER_DAY", "1.00")
MAX_SYSTEM_COST_PER_DAY = ler_float("MAX_SYSTEM_COST_PER_DAY", "5.00")
MAX_CALL_DURATION_MINUTES = ler_int("MAX_CALL_DURATION_MINUTES", "20")
MAX_CHUNKS_PER_CALL = ler_int("MAX_CHUNKS_PER_CALL", "999")
LOGIN_MAX_ATTEMPTS = ler_int("LOGIN_MAX_ATTEMPTS", "5")
LOGIN_BLOCK_MINUTES = ler_int("LOGIN_BLOCK_MINUTES", "15")

CORS_ORIGINS = [
    origem.strip()
    for origem in (ler_env("CORS_ORIGINS") or "").split(",")
    if origem.strip()
]
