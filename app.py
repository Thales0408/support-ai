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
        **limite["resposta"]
    )


def erro_limite(mensagem, **dados):

    return jsonify({
        "erro": mensagem,
        "limite": True,
        **dados
    }), 429


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


def normalizar_cnpj(valor):

    texto = str(valor or "")
    digitos = re.sub(
        r"\D",
        "",
        texto
    )

    if len(digitos) != 14:

        return "Não informado"

    return (
        f"{digitos[0:2]}.{digitos[2:5]}.{digitos[5:8]}/"
        f"{digitos[8:12]}-{digitos[12:14]}"
    )


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

        return "Não informado"

    if texto.lower() in [
        "nao informado",
        "não informado"
    ]:

        return "Não informado"

    return texto[:1200]


def resumo_zendesk_exato(
    nome_empresa=None,
    empresa_loja=None,
    cnpj=None,
    cliente=None,
    telefone=None,
    email=None,
    analista=None,
    descritivo=None
):

    return "\n\n".join([
        "Nome da empresa: " + normalizar_campo_zendesk(nome_empresa, limite=160),
        "Empresa/Loja: " + normalizar_campo_zendesk(empresa_loja, limite=160),
        "CNPJ: " + normalizar_cnpj(cnpj),
        "Nome do Cliente: " + normalizar_campo_zendesk(cliente, limite=120),
        "Telefone de contato: " + normalizar_campo_zendesk(telefone, limite=80),
        "E-mail Solicitante: " + normalizar_campo_zendesk(email, limite=120),
        "Analista responsável: " + normalizar_campo_zendesk(analista, limite=120),
        (
            "Descritivo da ocorrência do atendimento:\n"
            + normalizar_descritivo_zendesk(descritivo)
        )
    ])


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

    if (
        "Nome da empresa:" in texto
        and "Descritivo da ocorrência do atendimento:" in texto
        and "\n\nEmpresa/Loja:" in texto
        and "Descritivo da ocorrência do atendimento:\n" in texto
    ):

        return texto

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
        cliente=cliente,
        telefone=telefone,
        email=email,
        analista=analista,
        descritivo=descritivo_final
    )


def analisar_com_ia(transcricao, analista_responsavel=None):

    prompt = f"""
Voce e um analista senior de suporte ERP.

Gere um JSON valido para um atendimento de suporte ERP.

O texto final para Zendesk DEVE seguir exatamente este formato, mantendo quebras de linha e linhas em branco entre campos:

Nome da empresa: [se nao informado, usar "Não informado"]

Empresa/Loja: [se nao informado, usar "Não informado"]

CNPJ: [se nao informado, usar "Não informado"]

Nome do Cliente: [se nao informado, usar "Não informado"]

Telefone de contato: [se nao informado, usar "Não informado"]

E-mail Solicitante: [se nao informado, usar "Não informado"]

Analista responsável: [nome do analista logado, se disponivel]

Descritivo da ocorrência do atendimento:
[Explique de forma clara o problema relatado, o que foi analisado, quais orientacoes foram passadas e o status final.]

Regras:
- Nao escrever tudo em uma linha.
- Nao inventar CNPJ, telefone, e-mail, empresa, cliente, erro, solucao ou status.
- Se nao tiver a informacao na transcricao, escrever "Não informado".
- Escrever como documentacao para colar no Zendesk.
- Nao usar markdown.
- Nao usar bullets se nao houver passo a passo.
- Se houver procedimento, separar em passos numerados.
- Preserve termos tecnicos do ERP quando aparecerem.
- Use somente uma categoria principal.
- O campo descritivo_atendimento deve conter apenas o texto do descritivo, sem repetir os demais campos.
- Se o CNPJ nao tiver exatamente 14 digitos claros, retorne "Não informado".
- Se a transcricao estiver confusa, curta ou cheia de ruido, escreva isso no descritivo de forma objetiva e nao transforme suposicoes em fatos.
- Nao diga "foi identificado", "foi analisado", "foi orientado" ou "status final" se a transcricao nao mostrar isso claramente.
- Se so houver pedido de acesso remoto, registre apenas que foi solicitado acesso remoto para verificacao.
- Se a ligacao estiver em andamento ou sem conclusao clara, o status final deve ser "Não informado".

Analista logado:
{normalizar_campo_zendesk(analista_responsavel, limite=120)}

Formato JSON:
{{
  "resumo_zendesk": "texto final no formato exato acima",
  "nome_empresa": "...",
  "empresa_loja": "...",
  "cnpj": "...",
  "nome_cliente": "...",
  "telefone_contato": "...",
  "email_solicitante": "...",
  "analista_responsavel": "...",
  "descritivo_atendimento": "...",
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
        dados.get("descritivo_atendimento")
    )

    resumo = resumo_zendesk_exato(
        nome_empresa=dados.get("nome_empresa"),
        empresa_loja=dados.get("empresa_loja"),
        cnpj=dados.get("cnpj"),
        cliente=dados.get("nome_cliente"),
        telefone=dados.get("telefone_contato"),
        email=dados.get("email_solicitante"),
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
        usuario_nome=session.get("usuario_nome")
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

        texto = transcrever_chunk(arquivo)

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

    transcricao = limpar_texto(
        " ".join(textos)
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
                chunks_total * 30
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
            chunks_total=chunks_total,
            limite_chunks=MAX_CHUNKS_PER_CALL
        )

    segundos_dia_total = (
        uso["segundos"]
        + segundos_transcritos
    )

    if segundos_dia_total > MAX_AUDIO_MINUTES_PER_DAY * 60:

        log_evento(
            "limite_minutos_finalizar",
            usuario_id=usuario_id,
            atendimento_id=atendimento_id,
            segundos_dia_total=segundos_dia_total,
            limite_segundos=MAX_AUDIO_MINUTES_PER_DAY * 60
        )

        return erro_limite(
            "Limite diario de minutos de audio atingido.",
            minutos_hoje=round(segundos_dia_total / 60, 2),
            limite_minutos=MAX_AUDIO_MINUTES_PER_DAY
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

    return jsonify({
        "status": "finalizado",
        "resultado": resultado,
        "chunks_total": chunks_total,
        "chunks_falhos": chunks_falhos,
        "chunks_ignorados": chunks_ignorados,
        "segundos_transcritos": segundos_transcritos,
        "custo_estimado_usd": custo_estimado
    })


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

    texto = transcrever_chunk(arquivo)
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

    escopo = request.args.get(
        "escopo",
        "meus"
    )

    ver_todos = (
        escopo == "todos"
        and usuario_supervisor()
    )

    mostrar_custo = usuario_admin_tecnico()

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            if ver_todos:

                cursor.execute(
                    """
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
                        u.usuario
                    FROM atendimentos a
                    LEFT JOIN usuarios u
                    ON u.id = a.usuario_id
                    ORDER BY a.id DESC
                    LIMIT 300
                    """
                )

            else:

                cursor.execute(
                    """
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
                        u.usuario
                    FROM atendimentos a
                    LEFT JOIN usuarios u
                    ON u.id = a.usuario_id
                    WHERE a.usuario_id = %s
                    ORDER BY a.id DESC
                    LIMIT 300
                    """,
                    (
                        usuario_id,
                    )
                )

            rows = cursor.fetchall()

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
            "custo_estimado_usd": (
                float(row[12] or 0)
                if mostrar_custo
                else 0
            ),
            "resumo_editado": bool(row[13]),
            "sentimento_cliente": row[14] or "neutro",
            "urgencia": row[15] or "media",
            "categoria": row[16] or "outro",
            "problema_principal": row[17] or "",
            "tags": row[18] or "",
            "usuario": row[19] or "Nao informado"
        }

        itens.append(item)

        if row[4] != "finalizado":

            processando.append(str(row[0]))

    return jsonify({
        "resultados": itens,
        "processando": processando,
        "escopo": "todos" if ver_todos else "meus",
        "is_admin": usuario_admin_tecnico(),
        "is_supervisor": usuario_supervisor(),
        "mostrar_custo": mostrar_custo,
        "perfil": perfil_usuario()
    })


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

    return jsonify({
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
        "custo_estimado_usd": (
            float(row[11] or 0)
            if usuario_admin_tecnico()
            else 0
        ),
        "resumo_editado": bool(row[12]),
        "sentimento_cliente": row[13] or "neutro",
        "urgencia": row[14] or "media",
        "categoria": row[15] or "outro",
        "problema_principal": row[16] or "",
        "tags": row[17] or "",
        "usuario": row[18] or "Nao informado"
    })


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
                limpar_texto(row[0] or "")
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

    return jsonify({
        "status": "resumo_reprocessado",
        "resumo": resumo,
        "custo_estimado_usd": custo_estimado
    })


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

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    data,
                    ticket_zendesk,
                    conteudo,
                    transcricao_completa,
                    chunks_total,
                    chunks_falhos,
                    chunks_ignorados,
                    segundos_transcritos,
                    sentimento_cliente,
                    urgencia,
                    categoria,
                    problema_principal,
                    tags
                FROM atendimentos
                WHERE usuario_id = %s
                ORDER BY id DESC
                """,
                (
                    usuario_id,
                )
            )

            rows = cursor.fetchall()

    wb = Workbook()
    ws = wb.active

    ws.append([
        "Data",
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

        ws.insert_cols(9)
        ws.cell(
            row=1,
            column=9,
            value="Custo estimado USD"
        )

    for row in rows:

        linha = list(row)
        linha[2] = texto_zendesk_formatado(
            linha[2]
        )

        if mostrar_custo:

            custo_estimado = estimar_custo_atendimento(
                linha[7] or 0,
                bool(linha[2])
            )
            linha.insert(
                8,
                custo_estimado
            )

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
