from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    redirect,
    session,
    send_file
)

from flask_cors import CORS
from waitress import serve
from datetime import datetime
from openpyxl import Workbook
from werkzeug.security import generate_password_hash

import os
import psycopg2
import re
import uuid
import traceback
import json
import logging
import unicodedata

from auth import (
    perfil_usuario,
    perfil_valido,
    senha_esta_em_hash,
    senha_valida,
    usuario_admin_tecnico,
    usuario_logado,
    usuario_supervisor
)
from config import (
    CHUNK_SECONDS,
    CORS_ORIGINS,
    GROQ_API_KEY,
    LOGIN_BLOCK_MINUTES,
    LOGIN_MAX_ATTEMPTS,
    MAX_AUDIO_MINUTES_PER_DAY,
    MAX_CALL_DURATION_MINUTES,
    MAX_CALLS_PER_DAY,
    MAX_CHUNKS_PER_CALL,
    SECRET_KEY,
    SUMMARY_MODEL,
    TRANSCRIBE_MODEL,
    TRANSCRIBE_PROVIDER,
    USD_BRL_RATE,
    ler_env
)
from services.ai import (
    cliente_resumo,
    estimar_custo_atendimento,
    transcrever_chunk
)
from services.database import (
    conectar_banco,
    diagnostico_banco,
    inicializar_banco
)
from services.usage import (
    avaliar_limites_custo_resumo,
    custo_brl,
    registrar_uso_evento,
    uso_diario_usuario
)


# =========================================
# FLASK
# =========================================

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger("support_ai")

app = Flask(__name__)

app.secret_key = SECRET_KEY

if CORS_ORIGINS:

    CORS(
        app,
        origins=CORS_ORIGINS,
        supports_credentials=True
    )


def metadados_railway():

    return {
        "service": ler_env("RAILWAY_SERVICE_NAME"),
        "environment": ler_env("RAILWAY_ENVIRONMENT_NAME"),
        "project": ler_env("RAILWAY_PROJECT_NAME"),
        "commit": ler_env("RAILWAY_GIT_COMMIT_SHA"),
        "public_domain": ler_env("RAILWAY_PUBLIC_DOMAIN")
    }


# =========================================
# STARTUP
# =========================================

try:

    inicializar_banco()

except Exception as e:

    print("ERRO AO INICIALIZAR BANCO:", e)


# =========================================
# HELPERS
# =========================================

def log_evento(evento, **dados):

    logger.info(
        json.dumps(
            {
                "evento": evento,
                **dados
            },
            ensure_ascii=False,
            default=str
        )
    )


def limpar_texto(texto):

    texto = re.sub(
        r"\s+",
        " ",
        texto or ""
    )

    return texto.strip()


def limpar_vazamento_prompt_transcricao(texto):

    texto_limpo = str(texto or "")
    frases_prompt = [
        "Transcreva em português do Brasil",
        "Transcreva em portugues do Brasil",
        "Texto e atendimento de suporte",
        "Atendimento de suporte ERP",
        "Contexto: atendimento de suporte tecnico",
        "Contexto: atendimento de suporte técnico",
        "Não invente palavras quando houver silêncio",
        "Nao invente palavras quando houver silencio",
        "Não invente palavras quando houver silencio",
        "Nao invente palavras quando houver silêncio"
    ]

    for frase in frases_prompt:

        texto_limpo = re.sub(
            re.escape(frase),
            "",
            texto_limpo,
            flags=re.IGNORECASE
        )

    texto_limpo = re.sub(
        r"\s+",
        " ",
        texto_limpo
    )

    return texto_limpo.strip(" .:-")


def tamanho_arquivo_upload(arquivo):

    posicao_atual = (
        arquivo.stream.tell()
    )

    arquivo.stream.seek(
        0,
        os.SEEK_END
    )

    tamanho = (
        arquivo.stream.tell()
    )

    arquivo.stream.seek(
        posicao_atual
    )

    return tamanho


def ip_requisicao():

    encaminhado = request.headers.get("X-Forwarded-For", "")

    if encaminhado:

        return encaminhado.split(",")[0].strip()

    return request.remote_addr or "desconhecido"


def login_bloqueado(usuario, ip):

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT tentativas, bloqueado_ate
                FROM login_tentativas
                WHERE usuario = %s
                AND ip = %s
                """,
                (
                    usuario,
                    ip
                )
            )

            row = cursor.fetchone()

            if not row:

                return False

            tentativas, bloqueado_ate = row

            if bloqueado_ate:

                cursor.execute(
                    "SELECT NOW() < %s",
                    (
                        bloqueado_ate,
                    )
                )

                if cursor.fetchone()[0]:

                    log_evento(
                        "login_bloqueado",
                        usuario=usuario,
                        ip=ip,
                        tentativas=tentativas,
                        bloqueado_ate=bloqueado_ate
                    )

                    return True

    return False


def registrar_login_falho(usuario, ip):

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO login_tentativas (
                    usuario,
                    ip,
                    tentativas,
                    bloqueado_ate,
                    atualizado_em
                )
                VALUES (%s, %s, 1, NULL, NOW())
                ON CONFLICT (usuario, ip)
                DO UPDATE SET
                    tentativas = login_tentativas.tentativas + 1,
                    bloqueado_ate = CASE
                        WHEN login_tentativas.tentativas + 1 >= %s
                        THEN NOW() + (%s || ' minutes')::interval
                        ELSE login_tentativas.bloqueado_ate
                    END,
                    atualizado_em = NOW()
                RETURNING tentativas, bloqueado_ate
                """,
                (
                    usuario,
                    ip,
                    LOGIN_MAX_ATTEMPTS,
                    LOGIN_BLOCK_MINUTES
                )
            )

            tentativas, bloqueado_ate = cursor.fetchone()

    log_evento(
        "login_falhou",
        usuario=usuario,
        ip=ip,
        tentativas=tentativas,
        bloqueado_ate=bloqueado_ate
    )


def limpar_tentativas_login(usuario, ip):

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM login_tentativas
                WHERE usuario = %s
                AND ip = %s
                """,
                (
                    usuario,
                    ip
                )
            )


def validar_limites_custo_resumo(
    cursor,
    usuario_id,
    atendimento_id,
    custo_estimado_usd
):

    limite = avaliar_limites_custo_resumo(
        cursor,
        usuario_id,
        atendimento_id,
        custo_estimado_usd
    )

    if not limite:

        return None

    log_evento(
        limite["evento"],
        **limite["log"]
    )

    return erro_limite(
        limite["mensagem"],
        tipo=limite["evento"],
        deve_parar_gravacao=True,
        **limite["resposta"]
    )


def usuario_filtro_atendimentos():

    usuario_id = usuario_logado()
    analista = request.args.get("analista_id") or request.args.get("escopo")

    if not usuario_supervisor():

        return {
            "where": "a.usuario_id = %s",
            "params": [usuario_id],
            "escopo": "meus",
            "analista_id": usuario_id
        }

    if analista in [
        "todos",
        "all"
    ]:

        return {
            "where": "1 = 1",
            "params": [],
            "escopo": "todos",
            "analista_id": None
        }

    if (
        not analista
        or analista == "meus"
    ):

        return {
            "where": "a.usuario_id = %s",
            "params": [usuario_id],
            "escopo": "meus",
            "analista_id": usuario_id
        }

    try:

        analista_id = int(analista)

    except (TypeError, ValueError):

        analista_id = usuario_id

    return {
        "where": "a.usuario_id = %s",
        "params": [analista_id],
        "escopo": "analista",
        "analista_id": analista_id
    }


def erro_limite(
    mensagem,
    tipo="limite_uso",
    deve_parar_gravacao=True,
    **dados
):

    return jsonify({
        "erro": "limite_atingido",
        "limite": True,
        "tipo": tipo,
        "mensagem": mensagem,
        "deve_parar_gravacao": deve_parar_gravacao,
        **dados
    }), 403


def extrair_json_objeto(texto):

    bruto = (
        str(texto or "").strip()
    )

    if bruto.startswith("```"):

        bruto = (
            re.sub(
                r"^```(?:json)?",
                "",
                bruto,
                flags=re.IGNORECASE
            ).strip()
        )

        bruto = (
            re.sub(
                r"```$",
                "",
                bruto
            ).strip()
        )

    inicio = (
        bruto.find("{")
    )

    fim = (
        bruto.rfind("}")
    )

    if inicio >= 0 and fim > inicio:

        bruto = (
            bruto[inicio:fim + 1]
        )

    return json.loads(bruto)


def normalizar_campo(valor, padrao="Nao informado", limite=300):

    texto = (
        limpar_texto(valor or "")
    )

    if not texto:

        texto = padrao

    return texto[:limite]


def normalizar_campo_zendesk(valor, padrao="Não informado", limite=300):

    texto = normalizar_campo(
        valor,
        padrao,
        limite
    )

    if texto.lower() in [
        "nao informado",
        "não informado",
        "nao informada",
        "não informada"
    ]:

        return padrao

    return texto


def remover_acentos(texto):

    return "".join(
        caractere
        for caractere in unicodedata.normalize(
            "NFD",
            str(texto or "")
        )
        if unicodedata.category(caractere) != "Mn"
    )


def validar_cnpj_digitos(digitos):

    if (
        len(digitos) != 14
        or len(set(digitos)) == 1
    ):

        return False

    pesos_primeiro = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos_segundo = [6] + pesos_primeiro

    def calcular(posicoes, pesos):

        soma = sum(
            int(digito) * peso
            for digito, peso in zip(posicoes, pesos)
        )
        resto = soma % 11

        return "0" if resto < 2 else str(11 - resto)

    primeiro = calcular(digitos[:12], pesos_primeiro)
    segundo = calcular(digitos[:12] + primeiro, pesos_segundo)

    return digitos[-2:] == primeiro + segundo


def formatar_cnpj(digitos):

    return (
        f"{digitos[0:2]}.{digitos[2:5]}.{digitos[5:8]}/"
        f"{digitos[8:12]}-{digitos[12:14]}"
    )


def normalizar_cnpj(valor, permitir_possivel=False):

    texto = str(valor or "")

    if texto.lower().startswith("possível cnpj informado:"):

        return texto[:120]

    digitos = re.sub(
        r"\D",
        "",
        texto
    )

    if len(digitos) == 14 and validar_cnpj_digitos(digitos):

        return formatar_cnpj(digitos)

    if permitir_possivel and len(digitos) == 14:

        return (
            "Possível CNPJ informado: "
            + formatar_cnpj(digitos)
            + " — confirmar com cliente"
        )

    return "Não informado"


def possivel_cnpj_formatado(digitos):

    return (
        "Possível CNPJ informado: "
        + formatar_cnpj(digitos)
        + " — confirmar com cliente"
    )


def texto_para_digitos_cnpj(texto):

    palavras_numero = {
        "zero": "0",
        "um": "1",
        "uma": "1",
        "hum": "1",
        "dois": "2",
        "duas": "2",
        "tres": "3",
        "quatro": "4",
        "cinco": "5",
        "seis": "6",
        "meia": "6",
        "sete": "7",
        "oito": "8",
        "nove": "9",
        "mil": "000"
    }

    tokens = re.findall(
        r"\d+|[A-Za-zÀ-ÿ]+",
        str(texto or "").lower()
    )
    partes = []

    for token in tokens:

        token_limpo = remover_acentos(token)

        if token.isdigit():

            partes.append(token)

        elif token_limpo in palavras_numero:

            partes.append(palavras_numero[token_limpo])

    return "".join(partes)


def grupos_numericos_cnpj(texto):

    return re.findall(
        r"\d+",
        str(texto or "")
    )


def candidatos_cnpj_por_grupos(fragmento):

    grupos = grupos_numericos_cnpj(fragmento)
    candidatos = []

    if len(grupos) >= 5:

        base = "".join(grupos[:3])
        bloco = grupos[3]
        final = grupos[4]

        if (
            len(base) == 8
            and len(bloco) == 4
            and len(final) >= 2
        ):

            if bloco == "1000" and len(final) >= 3:

                candidatos.append(
                    (
                        base + "0001" + final[-2:],
                        True
                    )
                )
                candidatos.append(
                    (
                        base + bloco + final[:2],
                        True
                    )
                )

            candidatos.append(
                (
                    base + bloco + final[-2:],
                    False
                )
            )

    return [
        candidato
        for candidato in candidatos
        if len(candidato[0]) == 14
    ]


def fragmentos_com_evidencia_cnpj(texto):

    texto = str(texto or "")
    evidencias = [
        "cnpj",
        "c n p j",
        "cadastro nacional",
        "barra",
        "traco",
        "traço",
        "contrario",
        "contrário",
        "contra"
    ]

    for match in re.finditer(
        "|".join(re.escape(evidencia) for evidencia in evidencias),
        texto,
        flags=re.IGNORECASE
    ):

        inicio = max(0, match.start() - 80)
        fim = min(len(texto), match.end() + 140)

        yield texto[inicio:fim]

    for match in re.finditer(
        r"\d[\d\s.,/\-]{12,}\d",
        texto
    ):

        inicio = max(0, match.start() - 30)
        fim = min(len(texto), match.end() + 30)

        yield texto[inicio:fim]


def extrair_possivel_cnpj(texto):

    melhor_possivel = ""

    for fragmento in fragmentos_com_evidencia_cnpj(texto):

        digitos = texto_para_digitos_cnpj(fragmento)
        candidatos = candidatos_cnpj_por_grupos(fragmento)

        for inicio in range(0, max(1, len(digitos) - 13)):

            candidato = digitos[inicio:inicio + 14]

            if len(candidato) == 14:

                candidatos.append((candidato, False))

        if (
            len(digitos) == 13
            and digitos[8:11] == "000"
        ):

            candidatos.append(
                (
                    digitos[:11] + "1" + digitos[11:],
                    True
                )
            )

        for candidato, inferido in dict.fromkeys(candidatos):

            if validar_cnpj_digitos(candidato):

                if inferido:

                    return possivel_cnpj_formatado(candidato)

                return formatar_cnpj(candidato)

            if not melhor_possivel:

                melhor_possivel = candidato

    if melhor_possivel:

        return possivel_cnpj_formatado(melhor_possivel)

    return "Não informado"


def normalizar_descritivo_zendesk(valor):

    texto = str(valor or "").strip()

    texto = re.sub(
        r"\*\*|__|`",
        "",
        texto
    )

    texto = re.sub(
        r"(?m)^\s*[-*]\s+",
        "",
        texto
    )

    texto = re.sub(
        r"[ \t]+",
        " ",
        texto
    )

    texto = re.sub(
        r"\n{3,}",
        "\n\n",
        texto
    ).strip()

    if not texto:

        return "Resumo não disponível pela transcrição."

    if texto.lower() in [
        "nao informado",
        "não informado"
    ]:

        return "Resumo não disponível pela transcrição."

    return texto[:1200]


def campo_zendesk_informado(valor):

    texto = limpar_texto(valor or "")

    if not texto:

        return False

    return texto.lower() not in [
        "nao informado",
        "não informado",
        "nao informada",
        "não informada",
        "null",
        "none",
        "n/a",
        "...",
        "-"
    ]


def valor_obrigatorio_zendesk(valor):

    texto = limpar_valor_estruturado(valor, limite=160)

    if campo_zendesk_informado(texto):

        return texto

    return ""


def limpar_valor_estruturado(valor, limite=160):

    texto = normalizar_campo_zendesk(
        valor,
        padrao="",
        limite=limite
    )
    texto = re.sub(
        r"\s+",
        " ",
        texto
    ).strip()

    rotulos = [
        "Nome da empresa",
        "Empresa/Loja",
        "CNPJ",
        "Nome do Cliente",
        "Telefone de contato",
        "E-mail Solicitante",
        "Email Solicitante",
        "Analista responsável",
        "Analista responsavel",
        "Descritivo da ocorrência do atendimento",
        "Descritivo da ocorrencia do atendimento"
    ]

    for rotulo in rotulos:

        if re.fullmatch(
            re.escape(rotulo) + r"\s*:?",
            texto,
            flags=re.IGNORECASE
        ):

            return ""

        texto = re.sub(
            r"^" + re.escape(rotulo) + r"\s*:\s*",
            "",
            texto,
            flags=re.IGNORECASE
        ).strip()

    if re.fullmatch(r"[A-Za-zÀ-ÿ /-]{2,45}\s*:", texto):

        return ""

    return texto[:limite]


def normalizar_email_zendesk(valor):

    texto = limpar_valor_estruturado(
        valor,
        limite=120
    )

    if not campo_zendesk_informado(texto):

        return ""

    match = re.search(
        r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}",
        texto,
        flags=re.IGNORECASE
    )

    if not match:

        return ""

    email = match.group(0)
    dominio = email.split("@", 1)[1]

    if (
        not dominio
        or "." not in dominio
        or dominio.startswith(".")
        or dominio.endswith(".")
    ):

        return ""

    return email


def remover_rotulos_do_descritivo(valor):

    texto = str(valor or "")
    rotulos = [
        "Nome da empresa",
        "Empresa/Loja",
        "CNPJ",
        "Nome do Cliente",
        "Telefone de contato",
        "E-mail Solicitante",
        "Email Solicitante",
        "Analista responsável",
        "Analista responsavel",
        "Descritivo da ocorrência do atendimento",
        "Descritivo da ocorrencia do atendimento"
    ]

    for rotulo in rotulos:

        texto = re.sub(
            r"(?im)^\s*" + re.escape(rotulo) + r"\s*:.*$",
            "",
            texto
        )

    return texto.strip()


def resumo_zendesk_exato(
    nome_empresa=None,
    empresa_loja=None,
    cnpj=None,
    cnpj_contexto=None,
    cliente=None,
    telefone=None,
    email=None,
    analista=None,
    descritivo=None
):

    cnpj_final = normalizar_cnpj(cnpj, permitir_possivel=True)

    if cnpj_final == "Não informado":

        cnpj_final = extrair_possivel_cnpj(
            " ".join([
                str(cnpj or ""),
                str(cnpj_contexto or "")
            ])
        )

    if not campo_zendesk_informado(cnpj_final):

        cnpj_final = ""

    campos = [
        "Nome da empresa: " + valor_obrigatorio_zendesk(nome_empresa),
        "Empresa/Loja: " + valor_obrigatorio_zendesk(empresa_loja),
        "CNPJ: " + cnpj_final,
        "Nome do Cliente: " + valor_obrigatorio_zendesk(cliente),
        "Telefone de contato: " + valor_obrigatorio_zendesk(telefone),
        "E-mail Solicitante: " + normalizar_email_zendesk(email)
    ]

    campos.extend([
        "Analista responsável: " + normalizar_campo_zendesk(analista, limite=120),
        (
            "Descritivo da ocorrência do atendimento:\n"
            + normalizar_descritivo_zendesk(
                remover_rotulos_do_descritivo(descritivo)
            )
        )
    ])

    return "\n\n".join(campos)


def extrair_secao_texto(texto, rotulos):

    for rotulo in rotulos:

        padrao = (
            r"(?:^|\n)\s*"
            + re.escape(rotulo)
            + r"\s*:\s*(.*?)(?=\n\s*[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ /-]{1,45}\s*:|\Z)"
        )

        match = re.search(
            padrao,
            texto,
            flags=re.IGNORECASE | re.DOTALL
        )

        if match:

            return limpar_texto(
                match.group(1)
            )

    return ""


def texto_zendesk_formatado(conteudo):

    texto = (
        str(conteudo or "").strip()
    )

    if not texto:

        return ""

    texto_extracao = re.sub(
        (
            r"\s+("
            r"Empresa/Loja:|"
            r"CNPJ:|"
            r"Nome do Cliente:|"
            r"Telefone de contato:|"
            r"E-mail Solicitante:|"
            r"Analista responsável:|"
            r"Analista responsavel:|"
            r"Descritivo da ocorrência do atendimento:|"
            r"Descritivo da ocorrencia do atendimento:|"
            r"Descritivo do atendimento:"
            r")"
        ),
        r"\n\1",
        texto
    )

    nome_empresa = (
        extrair_secao_texto(
            texto_extracao,
            [
                "Nome da empresa",
                "Empresa"
            ]
        )
    )

    empresa_loja = (
        extrair_secao_texto(
            texto_extracao,
            [
                "Empresa/Loja",
                "Loja"
            ]
        )
    )

    cnpj = (
        extrair_secao_texto(
            texto_extracao,
            [
                "CNPJ"
            ]
        )
    )

    cliente = (
        extrair_secao_texto(
            texto_extracao,
            [
                "Nome do Cliente",
                "Cliente"
            ]
        )
    )

    telefone = (
        extrair_secao_texto(
            texto_extracao,
            [
                "Telefone de contato",
                "Telefone"
            ]
        )
    )

    email = (
        extrair_secao_texto(
            texto_extracao,
            [
                "E-mail Solicitante",
                "Email",
                "E-mail"
            ]
        )
    )

    descritivo = (
        extrair_secao_texto(
            texto_extracao,
            [
                "Descritivo do atendimento",
                "Descritivo da ocorrência do atendimento",
                "Descritivo da ocorrencia do atendimento",
                "Resumo do atendimento",
                "Problema"
            ]
        )
    )

    acao = (
        extrair_secao_texto(
            texto_extracao,
            [
                "Acao realizada",
                "Ação realizada",
                "Acao realizada/orientacao",
                "Acao realizada/orientação"
            ]
        )

    )

    orientacao = (
        extrair_secao_texto(
            texto_extracao,
            [
                "Orientacao ao cliente",
                "Orientação ao cliente"
            ]
        )

    )

    resultado = (
        extrair_secao_texto(
            texto_extracao,
            [
                "Resultado"
            ]
        )

    )

    partes_descritivo = [
        parte for parte in [
            descritivo,
            acao,
            orientacao,
            resultado
        ]
        if parte and parte.lower() != "nao informado"
    ]

    if not partes_descritivo:

        partes_descritivo = [
            re.sub(
                r"(?:^|\n)\s*Tags\s*:.*$",
                "",
                texto_extracao,
                flags=re.IGNORECASE | re.DOTALL
            )
        ]

    descritivo_final = " ".join(partes_descritivo)

    analista = (
        extrair_secao_texto(
            texto_extracao,
            [
                "Analista responsável",
                "Analista responsavel",
                "Analista"
            ]
        )
    )

    return resumo_zendesk_exato(
        nome_empresa=nome_empresa,
        empresa_loja=empresa_loja,
        cnpj=cnpj,
        cnpj_contexto=texto_extracao,
        cliente=cliente,
        telefone=telefone,
        email=email,
        analista=analista,
        descritivo=descritivo_final
    )


def analisar_com_ia(transcricao, analista_responsavel=None):

    prompt = f"""
Voce e um analista senior de suporte ERP.

Gere apenas um JSON valido para um atendimento de suporte ERP.
Nao gere o texto final do Zendesk.
O backend montara o texto final em ordem fixa.
Quando um campo nao for identificado na transcricao, retorne string vazia.
Nao use "Não informado", "Não identificado na ligação", null ou rotulos como valor.

Regras:
- Nao escrever tudo em uma linha.
- Nao inventar CNPJ, telefone, e-mail, empresa, cliente, erro, solucao ou status.
- Se nao tiver a informacao na transcricao, retorne string vazia no JSON.
- Escrever como documentacao para colar no Zendesk.
- Nao usar markdown.
- Nao usar bullets se nao houver passo a passo.
- Se houver procedimento, separar em passos numerados.
- Preserve termos tecnicos do ERP quando aparecerem.
- Use somente uma categoria principal.
- O campo descritivo deve conter apenas o texto do descritivo, sem repetir os demais campos.
- Nunca coloque rotulos de campos dentro do descritivo.
- Nunca deixe um rotulo virar valor de outro campo.
- Se o valor de um campo seria apenas "Telefone de contato:" ou "E-mail Solicitante:", retorne string vazia.
- Se o CNPJ nao tiver exatamente 14 digitos claros, retorne vazio no JSON, exceto quando houver sequencia parecida com CNPJ.
- Nao considerar e-mail valido sem @.
- Nao preencher e-mail com dominio incompleto.
- Para CNPJ, quando houver ambiguidade, sinalizar confirmacao em vez de afirmar.
- Se a transcricao estiver confusa, curta ou cheia de ruido, escreva isso no descritivo de forma objetiva e nao transforme suposicoes em fatos.
- Nao diga "foi identificado", "foi analisado", "foi orientado" ou "status final" se a transcricao nao mostrar isso claramente.
- Se so houver pedido de acesso remoto, registre apenas que foi solicitado acesso remoto para verificacao.
- Se a ligacao estiver em andamento ou sem conclusao clara, registre no descritivo que nao houve conclusao clara.

- Corrija termos fiscais comuns quando o contexto confirmar: ISDS-QN, ISQN ou ISS QN = ISSQN; Sintes Nacional ou Sintese Nacional = Simples Nacional; nota de servico = NFS-e; retencao de IS = retencao de ISS.
- Use correcoes de termos apenas para vocabulario tecnico. Nao use isso para inventar CNPJ, telefone, e-mail, empresa, loja ou nome de cliente.
- Nunca ignore um CNPJ parcialmente identificado.
- Se houver uma sequencia parecida com CNPJ, mas incerta, informe como "Possível CNPJ informado" e peça confirmacao.

Analista logado:
{normalizar_campo_zendesk(analista_responsavel, limite=120)}

Formato JSON:
{{
  "nome_empresa": "...",
  "empresa_loja": "...",
  "cnpj": "...",
  "nome_cliente": "...",
  "telefone": "...",
  "email": "...",
  "analista_responsavel": "...",
  "descritivo": "...",
  "sentimento_cliente": "positivo|neutro|negativo|frustrado",
  "urgencia": "baixa|media|alta|critica",
  "categoria": "fiscal|pdv|financeiro|estoque|cadastro|acesso|vendas|relatorios|integracao|outro",
  "problema_principal": "...",
  "tags": ["tag1", "tag2"]
}}

Transcricao:
{transcricao}
"""

    resposta = cliente_resumo().chat.completions.create(
        model=SUMMARY_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    try:

        dados = (
            extrair_json_objeto(
                resposta.choices[0].message.content
            )
        )

    except Exception:

        descritivo = (
            normalizar_campo(
                resposta.choices[0].message.content,
                limite=700
            )
        )

        dados = {
            "nome_empresa": "Nao informado",
            "empresa_loja": "Nao informado",
            "cnpj": "Nao informado",
            "nome_cliente": "Nao informado",
            "telefone_contato": "Nao informado",
            "email_solicitante": "Nao informado",
            "analista_responsavel": analista_responsavel or "Nao informado",
            "descritivo_atendimento": descritivo,
            "sentimento_cliente": "neutro",
            "urgencia": "media",
            "categoria": "outro",
            "problema_principal": descritivo[:180],
            "tags": []
        }

    descritivo = normalizar_descritivo_zendesk(
        dados.get("descritivo")
        or dados.get("descritivo_atendimento")
    )

    resumo = resumo_zendesk_exato(
        nome_empresa=dados.get("nome_empresa"),
        empresa_loja=dados.get("empresa_loja"),
        cnpj=dados.get("cnpj"),
        cnpj_contexto=transcricao,
        cliente=dados.get("nome_cliente"),
        telefone=(
            dados.get("telefone")
            or dados.get("telefone_contato")
        ),
        email=(
            dados.get("email")
            or dados.get("email_solicitante")
        ),
        analista=(
            analista_responsavel
            or dados.get("analista_responsavel")
        ),
        descritivo=descritivo
    )

    tags = (
        dados.get("tags") or []
    )

    if isinstance(tags, list):

        tags = (
            ", ".join(
                limpar_texto(tag).lower()
                for tag in tags
                if limpar_texto(tag)
            )
        )

    return {
        "resumo_zendesk": resumo[:1800],
        "sentimento_cliente": normalizar_campo(
            dados.get("sentimento_cliente"),
            "neutro",
            40
        ).lower(),
        "urgencia": normalizar_campo(
            dados.get("urgencia"),
            "media",
            40
        ).lower(),
        "categoria": normalizar_campo(
            dados.get("categoria"),
            "outro",
            80
        ).lower(),
        "problema_principal": normalizar_campo(
            dados.get("problema_principal"),
            descritivo,
            220
        ),
        "tags": normalizar_campo(
            tags,
            "",
            300
        )
    }


# =========================================
# LOGIN
# =========================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    erro = None

    if request.method == "POST":

        usuario = limpar_texto(request.form["usuario"])
        senha = request.form["senha"]
        ip = ip_requisicao()

        if login_bloqueado(usuario, ip):

            erro = (
                "Muitas tentativas de login. "
                f"Tente novamente em {LOGIN_BLOCK_MINUTES} minutos."
            )

            return render_template(
                "login.html",
                erro=erro
            ), 429

        with conectar_banco() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT id, senha, is_admin, ativo, perfil
                    FROM usuarios
                    WHERE usuario = %s
                    """,
                    (
                        usuario,
                    )
                )

                user = cursor.fetchone()

                if (
                    user
                    and user[3]
                    and senha_valida(
                        senha,
                        user[1]
                    )
                ):

                    if not senha_esta_em_hash(
                        user[1]
                    ):

                        cursor.execute(
                            """
                            UPDATE usuarios
                            SET senha = %s
                            WHERE id = %s
                            """,
                            (
                                generate_password_hash(
                                    senha
                                ),
                                user[0]
                            )
                        )

                    session["usuario_id"] = user[0]
                    perfil = (
                        user[4]
                        or (
                            "admin_tecnico"
                            if user[2]
                            else "analista"
                        )
                    )
                    session["perfil"] = perfil
                    session["is_admin"] = (
                        perfil == "admin_tecnico"
                    )
                    session["usuario_nome"] = usuario

                    limpar_tentativas_login(usuario, ip)

                    log_evento(
                        "login_sucesso",
                        usuario_id=user[0],
                        usuario=usuario,
                        perfil=perfil,
                        ip=ip
                    )

                    return redirect("/")

        registrar_login_falho(usuario, ip)

        erro = "Usuario ou senha invalidos."

    return render_template(
        "login.html",
        erro=erro
    )


@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")


@app.route("/")
def home():

    if not usuario_logado():

        return redirect("/login")

    return render_template(
        "index.html",
        is_admin=usuario_admin_tecnico(),
        is_supervisor=usuario_supervisor(),
        mostrar_custo=usuario_admin_tecnico(),
        perfil=perfil_usuario(),
        usuario_nome=session.get("usuario_nome"),
        chunk_seconds=CHUNK_SECONDS
    )


# =========================================
# ADMIN
# =========================================

@app.route(
    "/admin",
    methods=["GET", "POST"]
)
def admin_usuarios():

    if not usuario_logado():

        return redirect("/login")

    if not usuario_admin_tecnico():

        return redirect("/")

    mensagem = None
    erro = None

    if request.method == "POST":

        usuario = limpar_texto(
            request.form.get("usuario")
        )
        senha = request.form.get("senha") or ""
        perfil = request.form.get(
            "perfil",
            "analista"
        )

        if not perfil_valido(perfil):

            perfil = "analista"

        is_admin = (
            perfil == "admin_tecnico"
        )

        if not usuario or not senha:

            erro = "Informe usuario e senha."

        else:

            try:

                with conectar_banco() as conn:

                    with conn.cursor() as cursor:

                        cursor.execute(
                            """
                            INSERT INTO usuarios (
                                usuario,
                                senha,
                                is_admin,
                                perfil,
                                ativo
                            )
                            VALUES (%s, %s, %s, %s, TRUE)
                            """,
                            (
                                usuario,
                                generate_password_hash(
                                    senha
                                ),
                                is_admin,
                                perfil
                            )
                        )

                mensagem = "Usuario criado com sucesso."

            except psycopg2.errors.UniqueViolation:

                erro = "Esse usuario ja existe."

            except Exception as e:

                erro = f"Erro ao criar usuario: {e}"

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    usuario,
                    is_admin,
                    perfil,
                    ativo,
                    criado_em
                FROM usuarios
                ORDER BY usuario
                """
            )

            usuarios = cursor.fetchall()

    return render_template(
        "admin.html",
        usuarios=usuarios,
        mensagem=mensagem,
        erro=erro,
        usuario_id=usuario_logado()
    )


@app.route(
    "/admin/usuarios/<int:usuario_id>/status",
    methods=["POST"]
)
def admin_alterar_status(usuario_id):

    if not usuario_logado():

        return redirect("/login")

    if not usuario_admin_tecnico():

        return redirect("/")

    if usuario_id == usuario_logado():

        return redirect("/admin")

    ativo = request.form.get("ativo") == "true"

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                UPDATE usuarios
                SET ativo = %s
                WHERE id = %s
                """,
                (
                    ativo,
                    usuario_id
                )
            )

    return redirect("/admin")


@app.route(
    "/admin/usuarios/<int:usuario_id>/senha",
    methods=["POST"]
)
def admin_alterar_senha(usuario_id):

    if not usuario_logado():

        return redirect("/login")

    if not usuario_admin_tecnico():

        return redirect("/")

    senha = request.form.get("senha") or ""

    if senha:

        with conectar_banco() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    UPDATE usuarios
                    SET senha = %s
                    WHERE id = %s
                    """,
                    (
                        generate_password_hash(
                            senha
                        ),
                        usuario_id
                    )
                )

    return redirect("/admin")


@app.route(
    "/admin/usuarios/<int:usuario_id>/nome",
    methods=["POST"]
)
def admin_alterar_nome(usuario_id):

    if not usuario_logado():

        return redirect("/login")

    if not usuario_admin_tecnico():

        return redirect("/")

    novo_usuario = limpar_texto(
        request.form.get("usuario")
    )

    if not novo_usuario:

        return redirect("/admin")

    try:

        with conectar_banco() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    UPDATE usuarios
                    SET usuario = %s
                    WHERE id = %s
                    """,
                    (
                        novo_usuario,
                        usuario_id
                    )
                )

        if usuario_id == usuario_logado():

            session["usuario_nome"] = novo_usuario

    except psycopg2.errors.UniqueViolation:

        pass

    return redirect("/admin")


@app.route(
    "/admin/usuarios/<int:usuario_id>/perfil",
    methods=["POST"]
)
def admin_alterar_perfil(usuario_id):

    if not usuario_logado():

        return redirect("/login")

    if not usuario_admin_tecnico():

        return redirect("/")

    perfil = request.form.get(
        "perfil",
        "analista"
    )

    if not perfil_valido(perfil):

        perfil = "analista"

    is_admin = (
        perfil == "admin_tecnico"
    )

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                UPDATE usuarios
                SET
                    perfil = %s,
                    is_admin = %s
                WHERE id = %s
                """,
                (
                    perfil,
                    is_admin,
                    usuario_id
                )
            )

    if usuario_id == usuario_logado():

        session["perfil"] = perfil
        session["is_admin"] = is_admin

    return redirect("/admin")


@app.route(
    "/admin/usuarios/<int:usuario_id>/excluir",
    methods=["POST"]
)
def admin_excluir_usuario(usuario_id):

    if not usuario_logado():

        return redirect("/login")

    if not usuario_admin_tecnico():

        return redirect("/")

    if usuario_id == usuario_logado():

        return redirect("/admin")

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM usuarios
                WHERE id = %s
                """,
                (
                    usuario_id,
                )
            )

    return redirect("/admin")


# =========================================
# HEALTH
# =========================================

@app.route("/health")
def health():

    try:

        with conectar_banco() as conn:

            with conn.cursor() as cursor:

                cursor.execute("SELECT 1")

        return jsonify({
            "status": "ok",
            "database": "ok",
            "db_config": diagnostico_banco(),
            "transcribe_provider": TRANSCRIBE_PROVIDER,
            "transcribe_model": TRANSCRIBE_MODEL,
            "groq_configurado": bool(GROQ_API_KEY),
            "openai_configurado": bool(OPENAI_API_KEY),
            "railway": metadados_railway()
        })

    except Exception as e:

        return jsonify({
            "status": "erro",
            "database": str(e),
            "db_config": diagnostico_banco()
        }), 500


# =========================================
# ATENDIMENTOS EM CHUNKS
# =========================================

@app.route(
    "/atendimentos/iniciar",
    methods=["POST"]
)
def iniciar_atendimento():

    usuario_id = usuario_logado()

    if not usuario_id:

        return jsonify({
            "erro": "Nao autenticado"
        }), 401

    dados = request.get_json(silent=True) or {}
    ticket_zendesk = limpar_texto(
        dados.get("ticket_zendesk", "")
    )[:80]

    data = datetime.now().strftime(
        "%d/%m/%Y %H:%M"
    )

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            uso = uso_diario_usuario(
                cursor,
                usuario_id
            )

            if uso["chamadas"] >= MAX_CALLS_PER_DAY:

                log_evento(
                    "limite_chamadas_dia",
                    usuario_id=usuario_id,
                    chamadas=uso["chamadas"],
                    limite=MAX_CALLS_PER_DAY
                )

                return erro_limite(
                    "Limite diario de atendimentos atingido.",
                    tipo="limite_chamadas_dia",
                    deve_parar_gravacao=False,
                    chamadas_hoje=uso["chamadas"],
                    limite_chamadas=MAX_CALLS_PER_DAY
                )

            if uso["segundos"] >= MAX_AUDIO_MINUTES_PER_DAY * 60:

                log_evento(
                    "limite_minutos_dia",
                    usuario_id=usuario_id,
                    segundos=uso["segundos"],
                    limite_segundos=MAX_AUDIO_MINUTES_PER_DAY * 60
                )

                return erro_limite(
                    "Limite diario de minutos de audio atingido.",
                    tipo="limite_minutos_dia",
                    deve_parar_gravacao=False,
                    minutos_hoje=round(uso["segundos"] / 60, 2),
                    limite_minutos=MAX_AUDIO_MINUTES_PER_DAY
                )

            cursor.execute(
                """
                INSERT INTO atendimentos (
                    usuario_id,
                    arquivo,
                    conteudo,
                    data,
                    status,
                    ticket_zendesk,
                    inicio_em
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (
                    usuario_id,
                    "streaming",
                    "Transcricao em andamento...",
                    data,
                    "gravando",
                    ticket_zendesk or None
                )
            )

            atendimento_id = cursor.fetchone()[0]

    log_evento(
        "atendimento_iniciado",
        usuario_id=usuario_id,
        atendimento_id=atendimento_id,
        ticket_zendesk=bool(ticket_zendesk)
    )

    return jsonify({
        "atendimento_id": atendimento_id,
        "status": "gravando"
    })


@app.route(
    "/atendimentos/chunk",
    methods=["POST"]
)
def receber_chunk():

    usuario_id = usuario_logado()

    if not usuario_id:

        return jsonify({
            "erro": "Nao autenticado"
        }), 401

    if "audio" not in request.files:

        return jsonify({
            "erro": "Sem audio"
        }), 400

    atendimento_id = request.form.get("atendimento_id")
    ordem = request.form.get("ordem")

    if not atendimento_id or ordem is None:

        return jsonify({
            "erro": "Atendimento ou ordem ausente"
        }), 400

    try:

        ordem_int = int(ordem)

    except ValueError:

        return jsonify({
            "erro": "Ordem invalida"
        }), 400

    if ordem_int >= MAX_CHUNKS_PER_CALL:

        log_evento(
            "limite_chunks_atendimento",
            usuario_id=usuario_id,
            atendimento_id=atendimento_id,
            ordem=ordem_int,
            limite=MAX_CHUNKS_PER_CALL
        )

        return erro_limite(
            "Limite de trechos por atendimento atingido.",
            tipo="limite_chunks_atendimento",
            deve_parar_gravacao=True,
            limite_chunks=MAX_CHUNKS_PER_CALL
        )

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT 1
                FROM atendimentos
                WHERE id = %s
                AND usuario_id = %s
                """,
                (
                    atendimento_id,
                    usuario_id
                )
            )

            if not cursor.fetchone():

                return jsonify({
                    "erro": "Atendimento nao encontrado"
                }), 404

    arquivo = request.files["audio"]

    try:

        tamanho_audio = (
            tamanho_arquivo_upload(arquivo)
        )

        if (
            tamanho_audio < 1024
        ):

            log_evento(
                "chunk_ignorado",
                usuario_id=usuario_id,
                atendimento_id=atendimento_id,
                ordem=ordem_int,
                tamanho_audio=tamanho_audio,
                motivo="audio_muito_curto"
            )

            return jsonify({
                "status": "chunk_ignorado",
                "motivo": "audio_muito_curto"
            })

        texto = limpar_vazamento_prompt_transcricao(
            transcrever_chunk(arquivo)
        )

        with conectar_banco() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    INSERT INTO transcricoes_chunks (
                        atendimento_id,
                        usuario_id,
                        ordem,
                        texto,
                        status,
                        erro
                    )
                    VALUES (%s, %s, %s, %s, 'transcrito', NULL)
                    ON CONFLICT (atendimento_id, ordem)
                    DO UPDATE SET
                        texto = EXCLUDED.texto,
                        status = 'transcrito',
                        erro = NULL
                    """,
                    (
                        atendimento_id,
                        usuario_id,
                        ordem_int,
                        texto
                    )
                )

                cursor.execute(
                    """
                    UPDATE atendimentos
                    SET status = 'transcrevendo'
                    WHERE id = %s
                    AND usuario_id = %s
                    """,
                    (
                        atendimento_id,
                        usuario_id
                    )
                )

        log_evento(
            "chunk_transcrito",
            usuario_id=usuario_id,
            atendimento_id=atendimento_id,
            ordem=ordem_int,
            tamanho_audio=tamanho_audio,
            caracteres=len(texto)
        )

        return jsonify({
            "status": "chunk_transcrito",
            "texto": texto
        })

    except Exception as e:

        logger.exception("ERRO AO TRANSCREVER CHUNK")

        with conectar_banco() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    INSERT INTO transcricoes_chunks (
                        atendimento_id,
                        usuario_id,
                        ordem,
                        texto,
                        status,
                        erro
                    )
                    VALUES (%s, %s, %s, %s, 'erro', %s)
                    ON CONFLICT (atendimento_id, ordem)
                    DO UPDATE SET
                        texto = EXCLUDED.texto,
                        status = 'erro',
                        erro = EXCLUDED.erro
                    """,
                    (
                        atendimento_id,
                        usuario_id,
                        ordem_int,
                        "",
                        str(e)[:500]
                    )
                )

                cursor.execute(
                    """
                    UPDATE atendimentos
                    SET status = 'erro_chunk'
                    WHERE id = %s
                    AND usuario_id = %s
                    """,
                    (
                        atendimento_id,
                        usuario_id
                    )
                )

        log_evento(
            "chunk_erro",
            usuario_id=usuario_id,
            atendimento_id=atendimento_id,
            ordem=ordem_int,
            erro=str(e)[:500]
        )

        return jsonify({
            "erro": "Falha ao transcrever este trecho",
            "status": "erro_chunk"
        }), 500


@app.route(
    "/atendimentos/finalizar",
    methods=["POST"]
)
def finalizar_atendimento():

    usuario_id = usuario_logado()

    if not usuario_id:

        return jsonify({
            "erro": "Nao autenticado"
        }), 401

    dados = request.get_json(silent=True) or {}

    atendimento_id = dados.get("atendimento_id")
    duracao_segundos = dados.get("duracao_segundos")
    chunks_total_cliente = dados.get("chunks_total") or 0
    chunks_falhos_cliente = dados.get("chunks_falhos") or 0
    chunks_ignorados_cliente = dados.get("chunks_ignorados") or 0
    segundos_transcritos_cliente = dados.get("segundos_transcritos") or 0

    if not atendimento_id:

        return jsonify({
            "erro": "Atendimento ausente"
        }), 400

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT texto, status
                FROM transcricoes_chunks
                WHERE atendimento_id = %s
                AND usuario_id = %s
                ORDER BY ordem
                """,
                (
                    atendimento_id,
                    usuario_id
                )
            )

            textos = [
                row[0]
                for row in cursor.fetchall()
                if row[0]
            ]

            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    SUM(
                        CASE
                            WHEN status = 'erro' THEN 1
                            ELSE 0
                        END
                    )
                FROM transcricoes_chunks
                WHERE atendimento_id = %s
                AND usuario_id = %s
                """,
                (
                    atendimento_id,
                    usuario_id
                )
            )

            total_banco, falhos_banco = cursor.fetchone()

            uso = uso_diario_usuario(
                cursor,
                usuario_id,
                atendimento_id
            )

    transcricao = limpar_vazamento_prompt_transcricao(
        limpar_texto(
            " ".join(textos)
        )
    )

    chunks_total = max(
        int(chunks_total_cliente or 0),
        int(total_banco or 0)
    )

    chunks_falhos = max(
        int(chunks_falhos_cliente or 0),
        int(falhos_banco or 0)
    )

    chunks_ignorados = (
        int(chunks_ignorados_cliente or 0)
    )

    segundos_transcritos = (
        int(segundos_transcritos_cliente or 0)
    )

    if not segundos_transcritos:

        segundos_transcritos = (
            min(
                int(duracao_segundos or 0),
                chunks_total * CHUNK_SECONDS
            )
        )

    if int(duracao_segundos or 0) > MAX_CALL_DURATION_MINUTES * 60:

        log_evento(
            "limite_duracao_atendimento",
            usuario_id=usuario_id,
            atendimento_id=atendimento_id,
            duracao_segundos=duracao_segundos,
            limite_segundos=MAX_CALL_DURATION_MINUTES * 60
        )

        return erro_limite(
            "Limite de duracao por atendimento atingido.",
            tipo="limite_duracao_atendimento",
            deve_parar_gravacao=True,
            duracao_minutos=round(int(duracao_segundos or 0) / 60, 2),
            limite_minutos=MAX_CALL_DURATION_MINUTES
        )

    if chunks_total > MAX_CHUNKS_PER_CALL:

        log_evento(
            "limite_chunks_finalizar",
            usuario_id=usuario_id,
            atendimento_id=atendimento_id,
            chunks_total=chunks_total,
            limite=MAX_CHUNKS_PER_CALL
        )

        return erro_limite(
            "Limite de trechos por atendimento atingido.",
            tipo="limite_chunks_atendimento",
            deve_parar_gravacao=True,
            chunks_total=chunks_total,
            limite_chunks=MAX_CHUNKS_PER_CALL
        )

    segundos_dia_total = (
        uso["segundos"]
        + segundos_transcritos
    )

    if segundos_dia_total > MAX_AUDIO_MINUTES_PER_DAY * 60:

        log_evento(
            "limite_minutos_finalizar_permitido",
            usuario_id=usuario_id,
            atendimento_id=atendimento_id,
            segundos_dia_total=segundos_dia_total,
            limite_segundos=MAX_AUDIO_MINUTES_PER_DAY * 60
        )

    custo_estimado = estimar_custo_atendimento(
        segundos_transcritos,
        bool(transcricao)
    )

    if transcricao:

        with conectar_banco() as conn:

            with conn.cursor() as cursor:

                limite_resposta = validar_limites_custo_resumo(
                    cursor,
                    usuario_id,
                    atendimento_id,
                    custo_estimado
                )

                if limite_resposta:

                    return limite_resposta

    if transcricao:

        analise = analisar_com_ia(
            transcricao,
            session.get("usuario_nome")
        )

        resultado = analise["resumo_zendesk"]

    else:

        resultado = resumo_zendesk_exato(
            analista=session.get("usuario_nome"),
            descritivo=(
                "Não foi possível gerar resumo: "
                "nenhuma transcrição foi capturada."
            )
        )
        analise = {
            "sentimento_cliente": "neutro",
            "urgencia": "baixa",
            "categoria": "outro",
            "problema_principal": "Transcricao nao capturada",
            "tags": ""
        }

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                UPDATE atendimentos
                SET
                    conteudo = %s,
                    transcricao_completa = %s,
                    status = 'finalizado',
                    fim_em = NOW(),
                    duracao_segundos = %s,
                    chunks_total = %s,
                    chunks_falhos = %s,
                    chunks_ignorados = %s,
                    segundos_transcritos = %s,
                    custo_estimado_usd = %s,
                    sentimento_cliente = %s,
                    urgencia = %s,
                    categoria = %s,
                    problema_principal = %s,
                    tags = %s
                WHERE id = %s
                AND usuario_id = %s
                """,
                (
                    resultado,
                    transcricao,
                    duracao_segundos,
                    chunks_total,
                    chunks_falhos,
                    chunks_ignorados,
                    segundos_transcritos,
                    custo_estimado,
                    analise["sentimento_cliente"],
                    analise["urgencia"],
                    analise["categoria"],
                    analise["problema_principal"],
                    analise["tags"],
                    atendimento_id,
                    usuario_id
                )
            )

            if transcricao:

                registrar_uso_evento(
                    cursor,
                    usuario_id,
                    atendimento_id,
                    "resumo",
                    custo_estimado
                )

    log_evento(
        "atendimento_finalizado",
        usuario_id=usuario_id,
        atendimento_id=atendimento_id,
        chunks_total=chunks_total,
        chunks_falhos=chunks_falhos,
        chunks_ignorados=chunks_ignorados,
        segundos_transcritos=segundos_transcritos,
        custo_estimado_usd=custo_estimado,
        custo_estimado_brl=custo_brl(custo_estimado),
        custo_dia_estimado_usd=round(
            uso["custo"] + float(custo_estimado or 0),
            4
        )
    )

    resposta = {
        "status": "finalizado",
        "resultado": resultado,
        "chunks_total": chunks_total,
        "chunks_falhos": chunks_falhos,
        "chunks_ignorados": chunks_ignorados,
        "segundos_transcritos": segundos_transcritos
    }

    if usuario_admin_tecnico():

        resposta["custo_estimado_usd"] = custo_estimado
        resposta["custo_estimado_brl"] = custo_brl(custo_estimado)

    return jsonify(resposta)


# =========================================
# ROTA ANTIGA - COMPATIBILIDADE
# =========================================

@app.route(
    "/transcrever",
    methods=["POST"]
)
def transcrever_arquivo_unico():

    usuario_id = usuario_logado()

    if not usuario_id:

        return jsonify({
            "erro": "Nao autenticado"
        }), 401

    if "audio" not in request.files:

        return jsonify({
            "erro": "Sem audio"
        }), 400

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            uso = uso_diario_usuario(
                cursor,
                usuario_id
            )

            if uso["chamadas"] >= MAX_CALLS_PER_DAY:

                log_evento(
                    "limite_chamadas_upload_unico",
                    usuario_id=usuario_id,
                    chamadas=uso["chamadas"],
                    limite=MAX_CALLS_PER_DAY
                )

                return erro_limite(
                    "Limite diario de atendimentos atingido.",
                    tipo="limite_chamadas_dia",
                    deve_parar_gravacao=False,
                    chamadas_hoje=uso["chamadas"],
                    limite_chamadas=MAX_CALLS_PER_DAY
                )

            if uso["segundos"] >= MAX_AUDIO_MINUTES_PER_DAY * 60:

                log_evento(
                    "limite_minutos_upload_unico",
                    usuario_id=usuario_id,
                    segundos=uso["segundos"],
                    limite_segundos=MAX_AUDIO_MINUTES_PER_DAY * 60
                )

                return erro_limite(
                    "Limite diario de minutos de audio atingido.",
                    tipo="limite_minutos_dia",
                    deve_parar_gravacao=False,
                    minutos_hoje=round(uso["segundos"] / 60, 2),
                    limite_minutos=MAX_AUDIO_MINUTES_PER_DAY
                )

    data = datetime.now().strftime(
        "%d/%m/%Y %H:%M"
    )

    arquivo = request.files["audio"]
    custo_estimado = estimar_custo_atendimento(
        30,
        True
    )

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            limite_resposta = validar_limites_custo_resumo(
                cursor,
                usuario_id,
                None,
                custo_estimado
            )

            if limite_resposta:

                return limite_resposta

    texto = limpar_vazamento_prompt_transcricao(
        transcrever_chunk(arquivo)
    )
    analise = analisar_com_ia(
        texto,
        session.get("usuario_nome")
    )
    resultado = analise["resumo_zendesk"]

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO atendimentos (
                    usuario_id,
                    arquivo,
                    conteudo,
                    data,
                    status,
                    transcricao_completa,
                    fim_em,
                    chunks_total,
                    chunks_falhos,
                    sentimento_cliente,
                    urgencia,
                    categoria,
                    problema_principal,
                    tags
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    usuario_id,
                    str(uuid.uuid4()) + ".webm",
                    resultado,
                    data,
                    "finalizado",
                    texto,
                    1,
                    0,
                    analise["sentimento_cliente"],
                    analise["urgencia"],
                    analise["categoria"],
                    analise["problema_principal"],
                    analise["tags"]
                )
            )

            atendimento_id = cursor.fetchone()[0]

            registrar_uso_evento(
                cursor,
                usuario_id,
                atendimento_id,
                "resumo",
                custo_estimado
            )

    log_evento(
        "atendimento_upload_unico_finalizado",
        usuario_id=usuario_id,
        atendimento_id=atendimento_id,
        caracteres_transcricao=len(texto),
        categoria=analise["categoria"],
        urgencia=analise["urgencia"],
        custo_estimado_usd=custo_estimado,
        custo_estimado_brl=custo_brl(custo_estimado)
    )

    return jsonify({
        "status": "finalizado",
        "resultado": resultado
    })


# =========================================
# RESULTADOS
# =========================================

@app.route("/resultados")
def resultados():

    usuario_id = usuario_logado()

    if not usuario_id:

        return jsonify({
            "resultados": [],
            "processando": []
        })

    mostrar_custo = usuario_admin_tecnico()
    filtro_usuario = usuario_filtro_atendimentos()

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                f"""
                SELECT
                    a.id,
                    a.arquivo,
                    a.conteudo,
                    a.data,
                    a.status,
                    a.chunks_total,
                    a.chunks_falhos,
                    a.duracao_segundos,
                    a.transcricao_completa,
                    a.ticket_zendesk,
                    a.chunks_ignorados,
                    a.segundos_transcritos,
                    a.custo_estimado_usd,
                    a.resumo_editado,
                    a.sentimento_cliente,
                    a.urgencia,
                    a.categoria,
                    a.problema_principal,
                    a.tags,
                    u.usuario,
                    a.usuario_id
                FROM atendimentos a
                LEFT JOIN usuarios u
                ON u.id = a.usuario_id
                WHERE {filtro_usuario["where"]}
                ORDER BY a.id DESC
                LIMIT 300
                """,
                filtro_usuario["params"]
            )

            rows = cursor.fetchall()

            usuarios = []

            if usuario_supervisor():

                cursor.execute(
                    """
                    SELECT id, usuario
                    FROM usuarios
                    WHERE ativo = TRUE
                    ORDER BY usuario
                    """
                )

                usuarios = [
                    {
                        "id": row[0],
                        "usuario": row[1]
                    }
                    for row in cursor.fetchall()
                ]

    itens = []
    processando = []

    for row in rows:

        item = {
            "id": row[0],
            "arquivo": row[1],
            "conteudo": texto_zendesk_formatado(row[2]),
            "data": row[3],
            "status": row[4],
            "chunks_total": row[5] or 0,
            "chunks_falhos": row[6] or 0,
            "duracao_segundos": row[7] or 0,
            "transcricao_completa": row[8] or "",
            "ticket_zendesk": row[9] or "",
            "chunks_ignorados": row[10] or 0,
            "segundos_transcritos": row[11] or 0,
            "resumo_editado": bool(row[13]),
            "sentimento_cliente": row[14] or "neutro",
            "urgencia": row[15] or "media",
            "categoria": row[16] or "outro",
            "problema_principal": row[17] or "",
            "tags": row[18] or "",
            "usuario": row[19] or "Nao informado",
            "usuario_id": row[20]
        }

        if mostrar_custo:

            item["custo_estimado_usd"] = float(row[12] or 0)
            item["custo_estimado_brl"] = custo_brl(
                item["custo_estimado_usd"]
            )

        itens.append(item)

        if row[4] != "finalizado":

            processando.append(str(row[0]))

    resposta = {
        "resultados": itens,
        "processando": processando,
        "escopo": filtro_usuario["escopo"],
        "analista_id": filtro_usuario["analista_id"],
        "usuarios": usuarios,
        "is_admin": usuario_admin_tecnico(),
        "is_supervisor": usuario_supervisor(),
        "mostrar_custo": mostrar_custo,
        "perfil": perfil_usuario()
    }

    if mostrar_custo:

        resposta["usd_brl_rate"] = USD_BRL_RATE

    return jsonify(resposta)


@app.route("/atendimentos/<int:atendimento_id>")
def detalhe_atendimento(atendimento_id):

    usuario_id = usuario_logado()

    if not usuario_id:

        return jsonify({
            "erro": "Nao autenticado"
        }), 401

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            if usuario_supervisor():

                cursor.execute(
                    """
                    SELECT
                        a.id,
                        a.conteudo,
                        a.transcricao_completa,
                        a.data,
                        a.status,
                        a.duracao_segundos,
                        a.chunks_total,
                        a.chunks_falhos,
                        a.ticket_zendesk,
                        a.chunks_ignorados,
                        a.segundos_transcritos,
                        a.custo_estimado_usd,
                        a.resumo_editado,
                        a.sentimento_cliente,
                        a.urgencia,
                        a.categoria,
                        a.problema_principal,
                        a.tags,
                        u.usuario
                    FROM atendimentos a
                    LEFT JOIN usuarios u
                    ON u.id = a.usuario_id
                    WHERE a.id = %s
                    """,
                    (
                        atendimento_id,
                    )
                )

            else:

                cursor.execute(
                    """
                    SELECT
                        a.id,
                        a.conteudo,
                        a.transcricao_completa,
                        a.data,
                        a.status,
                        a.duracao_segundos,
                        a.chunks_total,
                        a.chunks_falhos,
                        a.ticket_zendesk,
                        a.chunks_ignorados,
                        a.segundos_transcritos,
                        a.custo_estimado_usd,
                        a.resumo_editado,
                        a.sentimento_cliente,
                        a.urgencia,
                        a.categoria,
                        a.problema_principal,
                        a.tags,
                        u.usuario
                    FROM atendimentos a
                    LEFT JOIN usuarios u
                    ON u.id = a.usuario_id
                    WHERE a.id = %s
                    AND a.usuario_id = %s
                    """,
                    (
                        atendimento_id,
                        usuario_id
                    )
                )

            row = cursor.fetchone()

    if not row:

        return jsonify({
            "erro": "Atendimento nao encontrado"
        }), 404

    resposta = {
        "id": row[0],
        "conteudo": texto_zendesk_formatado(row[1]),
        "transcricao_completa": row[2] or "",
        "data": row[3],
        "status": row[4],
        "duracao_segundos": row[5] or 0,
        "chunks_total": row[6] or 0,
        "chunks_falhos": row[7] or 0,
        "ticket_zendesk": row[8] or "",
        "chunks_ignorados": row[9] or 0,
        "segundos_transcritos": row[10] or 0,
        "resumo_editado": bool(row[12]),
        "sentimento_cliente": row[13] or "neutro",
        "urgencia": row[14] or "media",
        "categoria": row[15] or "outro",
        "problema_principal": row[16] or "",
        "tags": row[17] or "",
        "usuario": row[18] or "Nao informado"
    }

    if usuario_admin_tecnico():

        resposta["custo_estimado_usd"] = float(row[11] or 0)
        resposta["custo_estimado_brl"] = custo_brl(float(row[11] or 0))

    return jsonify(resposta)


@app.route(
    "/atendimentos/<int:atendimento_id>/resumo",
    methods=["POST"]
)
def salvar_resumo_atendimento(atendimento_id):

    usuario_id = usuario_logado()

    if not usuario_id:

        return jsonify({
            "erro": "Nao autenticado"
        }), 401

    dados = request.get_json(silent=True) or {}
    resumo = str(
        dados.get("resumo", "") or ""
    ).strip()
    resumo = texto_zendesk_formatado(
        resumo
    )
    ticket_zendesk = limpar_texto(
        dados.get("ticket_zendesk", "")
    )[:80]

    if not resumo:

        return jsonify({
            "erro": "Resumo vazio"
        }), 400

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                UPDATE atendimentos
                SET
                    conteudo = %s,
                    ticket_zendesk = %s,
                    resumo_editado = TRUE,
                    resumo_editado_em = NOW()
                WHERE id = %s
                AND (
                    usuario_id = %s
                    OR %s
                )
                """,
                (
                    resumo,
                    ticket_zendesk or None,
                    atendimento_id,
                    usuario_id,
                    usuario_supervisor()
                )
            )

            if cursor.rowcount == 0:

                return jsonify({
                    "erro": "Atendimento nao encontrado"
                }), 404

    return jsonify({
        "status": "resumo_salvo",
        "resumo": resumo,
        "ticket_zendesk": ticket_zendesk
    })


@app.route(
    "/atendimentos/<int:atendimento_id>/reprocessar-resumo",
    methods=["POST"]
)
def reprocessar_resumo_atendimento(atendimento_id):

    usuario_id = usuario_logado()

    if not usuario_id:

        return jsonify({
            "erro": "Nao autenticado"
        }), 401

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    a.transcricao_completa,
                    a.segundos_transcritos,
                    a.usuario_id,
                    u.usuario
                FROM atendimentos a
                LEFT JOIN usuarios u
                ON u.id = a.usuario_id
                WHERE a.id = %s
                AND (
                    a.usuario_id = %s
                    OR %s
                )
                """,
                (
                    atendimento_id,
                    usuario_id,
                    usuario_supervisor()
                )
            )

            row = cursor.fetchone()

            if not row:

                return jsonify({
                    "erro": "Atendimento nao encontrado"
                }), 404

            transcricao = (
                limpar_vazamento_prompt_transcricao(
                    limpar_texto(row[0] or "")
                )
            )

            if not transcricao:

                return jsonify({
                    "erro": "Transcricao nao disponivel"
                }), 400

            custo_estimado = estimar_custo_atendimento(
                row[1] or 0,
                True
            )
            usuario_custo_id = row[2] or usuario_id

            limite_resposta = validar_limites_custo_resumo(
                cursor,
                usuario_custo_id,
                atendimento_id,
                custo_estimado
            )

            if limite_resposta:

                return limite_resposta

            analise = analisar_com_ia(
                transcricao,
                row[3] or session.get("usuario_nome")
            )
            resumo = analise["resumo_zendesk"]

            cursor.execute(
                """
                UPDATE atendimentos
                SET
                    conteudo = %s,
                    resumo_editado = FALSE,
                    resumo_editado_em = NULL,
                    custo_estimado_usd = %s,
                    sentimento_cliente = %s,
                    urgencia = %s,
                    categoria = %s,
                    problema_principal = %s,
                    tags = %s
                WHERE id = %s
                """,
                (
                    resumo,
                    custo_estimado,
                    analise["sentimento_cliente"],
                    analise["urgencia"],
                    analise["categoria"],
                    analise["problema_principal"],
                    analise["tags"],
                    atendimento_id
                )
            )

            registrar_uso_evento(
                cursor,
                usuario_custo_id,
                atendimento_id,
                "resumo",
                custo_estimado
            )

    resposta = {
        "status": "resumo_reprocessado",
        "resumo": resumo
    }

    if usuario_admin_tecnico():

        resposta["custo_estimado_usd"] = custo_estimado
        resposta["custo_estimado_brl"] = custo_brl(custo_estimado)

    return jsonify(resposta)


@app.route(
    "/conta/senha",
    methods=["POST"]
)
def alterar_minha_senha():

    usuario_id = usuario_logado()

    if not usuario_id:

        return jsonify({
            "erro": "Nao autenticado"
        }), 401

    dados = request.get_json(silent=True) or {}
    senha_atual = dados.get("senha_atual", "")
    nova_senha = dados.get("nova_senha", "")

    if len(nova_senha) < 6:

        return jsonify({
            "erro": "A nova senha deve ter pelo menos 6 caracteres"
        }), 400

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT senha
                FROM usuarios
                WHERE id = %s
                """,
                (
                    usuario_id,
                )
            )

            row = cursor.fetchone()

            if (
                not row
                or not senha_valida(senha_atual, row[0])
            ):

                return jsonify({
                    "erro": "Senha atual invalida"
                }), 400

            cursor.execute(
                """
                UPDATE usuarios
                SET senha = %s
                WHERE id = %s
                """,
                (
                    generate_password_hash(nova_senha),
                    usuario_id
                )
            )

    return jsonify({
        "status": "senha_alterada"
    })


# =========================================
# EXPORTAR
# =========================================

@app.route("/exportar")
def exportar():

    usuario_id = usuario_logado()

    if not usuario_id:

        return redirect("/login")

    mostrar_custo = usuario_admin_tecnico()
    filtro_usuario = usuario_filtro_atendimentos()
    ids = [
        int(valor)
        for valor in re.findall(
            r"\d+",
            request.args.get("ids", "")
        )
    ]

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            where = filtro_usuario["where"]
            params = list(filtro_usuario["params"])

            if ids:

                where += " AND a.id = ANY(%s)"
                params.append(ids)

            cursor.execute(
                f"""
                SELECT
                    a.data,
                    u.usuario,
                    a.ticket_zendesk,
                    a.conteudo,
                    a.transcricao_completa,
                    a.chunks_total,
                    a.chunks_falhos,
                    a.chunks_ignorados,
                    a.segundos_transcritos,
                    a.custo_estimado_usd,
                    a.sentimento_cliente,
                    a.urgencia,
                    a.categoria,
                    a.problema_principal,
                    a.tags
                FROM atendimentos a
                LEFT JOIN usuarios u
                ON u.id = a.usuario_id
                WHERE {where}
                ORDER BY a.id DESC
                """,
                params
            )

            rows = cursor.fetchall()

    wb = Workbook()
    ws = wb.active

    ws.append([
        "Data",
        "Analista",
        "Ticket Zendesk",
        "Texto Zendesk",
        "Transcricao",
        "Trechos",
        "Trechos com falha",
        "Trechos ignorados",
        "Segundos transcritos",
        "Sentimento",
        "Urgencia",
        "Categoria",
        "Problema principal",
        "Tags internas"
    ])

    if mostrar_custo:

        ws.insert_cols(10)
        ws.cell(
            row=1,
            column=10,
            value="Custo estimado USD"
        )
        ws.insert_cols(11)
        ws.cell(
            row=1,
            column=11,
            value="Custo estimado BRL"
        )

    for row in rows:

        linha = list(row)
        linha[3] = texto_zendesk_formatado(
            linha[3]
        )

        if mostrar_custo:

            custo_estimado_usd = float(
                linha[9] or 0
            )
            linha[9] = custo_estimado_usd
            linha.insert(
                10,
                custo_brl(custo_estimado_usd)
            )
        else:

            linha.pop(9)

        ws.append(linha)

    nome = "atendimentos.xlsx"
    wb.save(nome)

    return send_file(
        nome,
        as_attachment=True
    )


# =========================================
# START
# =========================================

if __name__ == "__main__":

    serve(
        app,
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "8080"
            )
        ),
        threads=16
    )
