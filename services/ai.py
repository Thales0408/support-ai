from openai import OpenAI

import re

from config import (
    GROQ_API_KEY,
    GROQ_BASE_URL,
    OPENAI_API_KEY,
    SUMMARY_USD_POR_ATENDIMENTO,
    TRANSCRIBE_MODEL,
    TRANSCRIBE_PROVIDER,
    TRANSCRIBE_USD_HORA
)


summary_client = (
    OpenAI(api_key=OPENAI_API_KEY)
    if OPENAI_API_KEY
    else None
)


def cliente_resumo():

    if not summary_client:

        raise RuntimeError("OPENAI_API_KEY nao configurada")

    return summary_client


def cliente_transcricao():

    if TRANSCRIBE_PROVIDER == "groq":

        if not GROQ_API_KEY:

            raise RuntimeError("GROQ_API_KEY nao configurada")

        return OpenAI(
            api_key=GROQ_API_KEY,
            base_url=GROQ_BASE_URL
        )

    if not summary_client:

        raise RuntimeError("OPENAI_API_KEY nao configurada")

    return summary_client


def transcrever_chunk(arquivo):

    nome = arquivo.filename or "chunk.webm"
    mime = arquivo.mimetype or "audio/webm"

    resposta = cliente_transcricao().audio.transcriptions.create(
        model=TRANSCRIBE_MODEL,
        file=(
            nome,
            arquivo.stream,
            mime
        ),
        language="pt",
        prompt=(
            "Atendimento de suporte ERP em portugues do Brasil. "
            "Priorize termos de ERP, fiscal, nota fiscal, caixa, venda, "
            "cadastro, produto, cliente, financeiro, estoque, PDV, NFC-e, "
            "NF-e, SAT, boleto, XML, Zendesk, AnyDesk e TeamViewer. "
            "Nao invente palavras quando houver silencio, ruido, musica, "
            "eco ou fala inaudivel. Se um trecho estiver confuso, transcreva "
            "somente as palavras audiveis."
        )
    )

    return re.sub(
        r"\s+",
        " ",
        str(getattr(resposta, "text", "") or "")
    ).strip()


def estimar_custo_atendimento(segundos_transcritos, gerou_resumo=True):

    horas = max(0, int(segundos_transcritos or 0)) / 3600
    custo = horas * TRANSCRIBE_USD_HORA

    if gerou_resumo:

        custo += SUMMARY_USD_POR_ATENDIMENTO

    return round(custo, 4)
