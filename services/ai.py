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
        temperature=0,
        prompt=(
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
