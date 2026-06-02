from io import BytesIO

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError
)

import re

from config import (
    GROQ_API_KEY,
    GROQ_BASE_URL,
    OPENAI_API_KEY,
    OPENAI_TRANSCRIBE_MODEL,
    SUMMARY_USD_POR_ATENDIMENTO,
    TRANSCRIBE_FALLBACK_PROVIDER,
    TRANSCRIBE_MODEL,
    TRANSCRIBE_PROVIDER,
    TRANSCRIBE_USD_HORA,
    TRANSCRIBE_USD_HORA_GROQ,
    TRANSCRIBE_USD_MINUTO_OPENAI
)


class LimiteCustoFallbackTranscricao(Exception):

    def __init__(self, limite_resposta):

        super().__init__("Limite de custo para fallback de transcricao")
        self.limite_resposta = limite_resposta


summary_client = (
    OpenAI(api_key=OPENAI_API_KEY)
    if OPENAI_API_KEY
    else None
)


def cliente_resumo():

    if not summary_client:

        raise RuntimeError("OPENAI_API_KEY nao configurada")

    return summary_client


PROMPT_TRANSCRICAO = (
    "Transcreva em portugues do Brasil. "
    "Contexto: atendimento de suporte tecnico para ERP, emissao de "
    "nota fiscal, NFS-e, NF-e, NFC-e, ISSQN, Simples Nacional, "
    "retencao de ISS, CNPJ, loja, cliente, certificado digital, XML, "
    "Zendesk, AnyDesk, TeamViewer, caixa, venda, cadastro, produto, "
    "financeiro, estoque, PDV, SAT e boleto. "
    "Preserve numeros, CNPJ, nomes de empresa e termos fiscais. "
    "Nao invente palavras quando houver silencio, ruido, musica, "
    "eco ou fala inaudivel. Se um trecho estiver confuso, transcreva "
    "somente as palavras audiveis."
)


def cliente_transcricao(provider):

    if provider == "groq":

        if not GROQ_API_KEY:

            raise RuntimeError("GROQ_API_KEY nao configurada")

        return OpenAI(
            api_key=GROQ_API_KEY,
            base_url=GROQ_BASE_URL
        )

    if provider == "openai":

        if not summary_client:

            raise RuntimeError("OPENAI_API_KEY nao configurada")

        return summary_client

    raise RuntimeError(f"Provedor de transcricao invalido: {provider}")


def modelo_transcricao(provider):

    if provider == "openai":

        return OPENAI_TRANSCRIBE_MODEL

    return TRANSCRIBE_MODEL


def erro_permite_fallback(e):

    status_code = getattr(e, "status_code", None)
    texto = str(e).lower()

    if status_code == 400:

        return False

    return (
        isinstance(e, (RateLimitError, APITimeoutError, APIConnectionError))
        or status_code == 429
        or (status_code is not None and int(status_code) >= 500)
        or "rate limit" in texto
        or "too many requests" in texto
        or "timeout" in texto
        or "timed out" in texto
        or "connection" in texto
        or "unavailable" in texto
        or "requests per day" in texto
    )


def transcrever_bytes(provider, audio_bytes, nome, mime):

    resposta = cliente_transcricao(provider).audio.transcriptions.create(
        model=modelo_transcricao(provider),
        file=(
            nome,
            BytesIO(audio_bytes),
            mime
        ),
        language="pt",
        temperature=0,
        prompt=PROMPT_TRANSCRICAO
    )

    return re.sub(
        r"\s+",
        " ",
        str(getattr(resposta, "text", "") or "")
    ).strip()


def transcrever_chunk(arquivo, validar_fallback=None):

    nome = arquivo.filename or "chunk.webm"
    mime = arquivo.mimetype or "audio/webm"
    audio_bytes = arquivo.read()
    provider_tentado = TRANSCRIBE_PROVIDER
    fallback_provider = TRANSCRIBE_FALLBACK_PROVIDER

    try:

        texto = transcrever_bytes(
            provider_tentado,
            audio_bytes,
            nome,
            mime
        )

        return {
            "texto": texto,
            "provider_tentado": provider_tentado,
            "provider_usado": provider_tentado,
            "fallback_usado": False
        }

    except Exception as e:

        if (
            provider_tentado != "groq"
            or fallback_provider != "openai"
            or not erro_permite_fallback(e)
        ):

            raise

        if validar_fallback:

            validar_fallback()

        texto = transcrever_bytes(
            fallback_provider,
            audio_bytes,
            nome,
            mime
        )

        return {
            "texto": texto,
            "provider_tentado": provider_tentado,
            "provider_usado": fallback_provider,
            "fallback_usado": True,
            "erro_provider_principal": str(e)[:500]
        }


def estimar_custo_transcricao(segundos_transcritos, provider="groq"):

    segundos = max(0, int(segundos_transcritos or 0))

    if provider == "openai":

        return round(
            (segundos / 60) * TRANSCRIBE_USD_MINUTO_OPENAI,
            4
        )

    if provider == "groq":

        return round(
            (segundos / 3600) * TRANSCRIBE_USD_HORA_GROQ,
            4
        )

    horas = segundos / 3600

    return round(horas * TRANSCRIBE_USD_HORA, 4)


def estimar_custo_transcricao_por_provedor(contagem_provedores):

    custo = 0

    for provider, segundos in contagem_provedores.items():

        custo += estimar_custo_transcricao(segundos, provider)

    return round(custo, 4)


def estimar_custo_atendimento(segundos_transcritos, gerou_resumo=True):

    custo = estimar_custo_transcricao(
        segundos_transcritos,
        TRANSCRIBE_PROVIDER
    )

    if gerou_resumo:

        custo += SUMMARY_USD_POR_ATENDIMENTO

    return round(custo, 4)
