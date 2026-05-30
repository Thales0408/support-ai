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
from openai import OpenAI
from waitress import serve
from dotenv import load_dotenv
from datetime import datetime
from openpyxl import Workbook
from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)

import psycopg2
import os
import re
import uuid
import traceback


# =========================================
# ENV
# =========================================

load_dotenv()

def ler_env(nome, padrao=None):

    valor = (
        os.getenv(
            nome,
            padrao
        )
    )

    if valor is None:

        return None

    return str(valor).strip().strip('"').strip("'")


OPENAI_API_KEY = ler_env("OPENAI_API_KEY")
GROQ_API_KEY = (
    ler_env("GROQ_API_KEY")
    or ler_env("GROQ_API_TOKEN")
)
GROQ_BASE_URL = ler_env(
    "GROQ_BASE_URL",
    "https://api.groq.com/openai/v1"
)
DATABASE_URL = ler_env("DATABASE_URL")
DB_HOST = ler_env(
    "DB_HOST",
    "aws-1-sa-east-1.pooler.supabase.com"
)
DB_PORT = ler_env("DB_PORT", "6543")
DB_NAME = ler_env("DB_NAME", "postgres")
DB_USER = ler_env(
    "DB_USER",
    "postgres.epegojdxngrcwvzecupl"
)
DB_PASSWORD = ler_env("DB_PASSWORD")

ADMIN_USUARIO = ler_env("ADMIN_USUARIO", "admin")
ADMIN_SENHA = ler_env("ADMIN_SENHA", "123456")

TRANSCRIBE_PROVIDER = ler_env(
    "TRANSCRIBE_PROVIDER",
    "groq" if GROQ_API_KEY else "openai"
).lower()

DEFAULT_TRANSCRIBE_MODEL = (
    "whisper-large-v3-turbo"
    if TRANSCRIBE_PROVIDER == "groq"
    else "gpt-4o-mini-transcribe"
)

TRANSCRIBE_MODEL = ler_env(
    "TRANSCRIBE_MODEL",
    DEFAULT_TRANSCRIBE_MODEL
)

SUMMARY_MODEL = ler_env(
    "SUMMARY_MODEL",
    "gpt-4.1-mini"
)

TRANSCRIBE_USD_HORA = float(
    ler_env(
        "TRANSCRIBE_USD_HORA",
        "0.04" if TRANSCRIBE_PROVIDER == "groq" else "0.36"
    )
)

SUMMARY_USD_POR_ATENDIMENTO = float(
    ler_env(
        "SUMMARY_USD_POR_ATENDIMENTO",
        "0.003"
    )
)


# =========================================
# FLASK
# =========================================

app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "55pbx_ai"
)

CORS(app)


def metadados_railway():

    return {
        "service": ler_env("RAILWAY_SERVICE_NAME"),
        "environment": ler_env("RAILWAY_ENVIRONMENT_NAME"),
        "project": ler_env("RAILWAY_PROJECT_NAME"),
        "commit": ler_env("RAILWAY_GIT_COMMIT_SHA"),
        "public_domain": ler_env("RAILWAY_PUBLIC_DOMAIN")
    }


# =========================================
# IA
# =========================================

summary_client = (
    OpenAI(
        api_key=OPENAI_API_KEY
    )
    if OPENAI_API_KEY
    else None
)


def cliente_resumo():

    if not summary_client:

        raise RuntimeError(
            "OPENAI_API_KEY nao configurada"
        )

    return summary_client


def cliente_transcricao():

    if TRANSCRIBE_PROVIDER == "groq":

        if not GROQ_API_KEY:

            raise RuntimeError(
                "GROQ_API_KEY nao configurada"
            )

        return OpenAI(
            api_key=GROQ_API_KEY,
            base_url=GROQ_BASE_URL
        )

    if not summary_client:

        raise RuntimeError(
            "OPENAI_API_KEY nao configurada"
        )

    return summary_client


# =========================================
# POSTGRES
# =========================================

def conectar_banco():

    db_password = DB_PASSWORD

    if (
        not db_password
        and DATABASE_URL
        and "postgres:@" in DATABASE_URL
        and "@db." in DATABASE_URL
    ):

        db_password = DATABASE_URL.split(
            "postgres:@",
            1
        )[1].split(
            "@db.",
            1
        )[0]

    if db_password:

        return psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=db_password,
            sslmode="require"
        )

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL ou DB_PASSWORD nao configurada"
        )

    return psycopg2.connect(
        DATABASE_URL
    )


def diagnostico_banco():

    db_password = DB_PASSWORD

    if (
        not db_password
        and DATABASE_URL
        and "postgres:@" in DATABASE_URL
        and "@db." in DATABASE_URL
    ):

        db_password = DATABASE_URL.split(
            "postgres:@",
            1
        )[1].split(
            "@db.",
            1
        )[0]

    if db_password:

        return {
            "modo": "variaveis_db",
            "host": DB_HOST,
            "port": DB_PORT,
            "user": DB_USER,
            "password_configurada": True
        }

    return {
        "modo": "database_url",
        "host": "DATABASE_URL",
        "port": "DATABASE_URL",
        "user": "DATABASE_URL",
        "password_configurada": False
    }


def inicializar_banco():

    with conectar_banco() as conn:

        with conn.cursor() as cursor:

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS usuarios (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    usuario TEXT UNIQUE NOT NULL,
                    senha TEXT NOT NULL,
                    criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )

            cursor.execute(
                """
                ALTER TABLE usuarios
                ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE
                """
            )

            cursor.execute(
                """
                ALTER TABLE usuarios
                ADD COLUMN IF NOT EXISTS ativo BOOLEAN DEFAULT TRUE
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS atendimentos (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    usuario_id BIGINT REFERENCES usuarios(id) ON DELETE CASCADE,
                    arquivo TEXT,
                    conteudo TEXT,
                    data TEXT
                )
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'finalizado'
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ALTER COLUMN data TYPE TEXT
                USING data::TEXT
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS transcricao_completa TEXT
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS inicio_em TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS fim_em TIMESTAMP WITH TIME ZONE
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS duracao_segundos INTEGER
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS chunks_total INTEGER DEFAULT 0
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS chunks_falhos INTEGER DEFAULT 0
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS chunks_ignorados INTEGER DEFAULT 0
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS segundos_transcritos INTEGER DEFAULT 0
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS custo_estimado_usd NUMERIC(10, 4) DEFAULT 0
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS ticket_zendesk TEXT
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS resumo_editado BOOLEAN DEFAULT FALSE
                """
            )

            cursor.execute(
                """
                ALTER TABLE atendimentos
                ADD COLUMN IF NOT EXISTS resumo_editado_em TIMESTAMP WITH TIME ZONE
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS transcricoes_chunks (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    atendimento_id BIGINT REFERENCES atendimentos(id) ON DELETE CASCADE,
                    usuario_id BIGINT REFERENCES usuarios(id) ON DELETE CASCADE,
                    ordem INTEGER NOT NULL,
                    texto TEXT,
                    criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
                """
            )

            cursor.execute(
                """
                ALTER TABLE transcricoes_chunks
                ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'transcrito'
                """
            )

            cursor.execute(
                """
                ALTER TABLE transcricoes_chunks
                ADD COLUMN IF NOT EXISTS erro TEXT
                """
            )

            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_atendimento_ordem
                ON transcricoes_chunks (atendimento_id, ordem)
                """
            )

            admin_hash = generate_password_hash(
                ADMIN_SENHA
            )

            cursor.execute(
                """
                INSERT INTO usuarios (usuario, senha, is_admin, ativo)
                VALUES (%s, %s, TRUE, TRUE)
                ON CONFLICT (usuario) DO NOTHING
                """,
                (
                    ADMIN_USUARIO,
                    admin_hash
                )
            )

            cursor.execute(
                """
                UPDATE usuarios
                SET is_admin = TRUE,
                    ativo = TRUE
                WHERE usuario = %s
                """,
                (
                    ADMIN_USUARIO,
                )
            )


try:

    inicializar_banco()

except Exception as e:

    print("ERRO AO INICIALIZAR BANCO:", e)


# =========================================
# HELPERS
# =========================================

def limpar_texto(texto):

    texto = re.sub(
        r"\s+",
        " ",
        texto or ""
    )

    return texto.strip()


def usuario_logado():

    return session.get("usuario_id")


def usuario_admin():

    return bool(
        session.get("is_admin")
    )


def senha_valida(senha_digitada, senha_salva):

    if not senha_salva:

        return False

    try:

        if check_password_hash(
            senha_salva,
            senha_digitada
        ):

            return True

    except Exception:

        pass

    return senha_digitada == senha_salva


def senha_esta_em_hash(senha_salva):

    return (
        senha_salva.startswith("scrypt:")
        or senha_salva.startswith("pbkdf2:")
    )


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
            "NF-e, SAT, boleto, XML e Zendesk."
        )
    )

    return limpar_texto(
        getattr(resposta, "text", "")
    )


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


def estimar_custo_atendimento(segundos_transcritos, gerou_resumo=True):

    horas = (
        max(
            0,
            int(segundos_transcritos or 0)
        ) / 3600
    )

    custo = (
        horas * TRANSCRIBE_USD_HORA
    )

    if gerou_resumo:

        custo += SUMMARY_USD_POR_ATENDIMENTO

    return round(
        custo,
        4
    )


def analisar_com_ia(transcricao):

    prompt = f"""
Voce e um analista senior de suporte ERP.

Gere uma documentacao objetiva, profissional e pronta para colar no Zendesk.

Regras:
- Nao invente dados.
- Se nao encontrar uma informacao, escreva "Nao informado".
- Mantenha linguagem profissional.
- Preserve termos tecnicos do ERP quando aparecerem.
- Diferencie claramente problema, orientacao e pendencias.
- Extraia tags curtas, em minusculas e separadas por virgula.

Formato:
Empresa:
Cliente:
Telefone:
Email:
Problema:
Diagnostico:
Acao realizada:
Orientacao ao cliente:
Pendencias/proximos passos:
Resultado:
Tags:

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

    return resposta.choices[0].message.content


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

        usuario = request.form["usuario"]
        senha = request.form["senha"]

        with conectar_banco() as conn:

            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT id, senha, is_admin, ativo
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
                    session["is_admin"] = bool(user[2])
                    session["usuario_nome"] = usuario

                    return redirect("/")

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
        is_admin=usuario_admin(),
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

    if not usuario_admin():

        return redirect("/")

    mensagem = None
    erro = None

    if request.method == "POST":

        usuario = limpar_texto(
            request.form.get("usuario")
        )
        senha = request.form.get("senha") or ""
        is_admin = request.form.get("is_admin") == "on"

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
                                ativo
                            )
                            VALUES (%s, %s, %s, TRUE)
                            """,
                            (
                                usuario,
                                generate_password_hash(
                                    senha
                                ),
                                is_admin
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

    if not usuario_admin():

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

    if not usuario_admin():

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

    if not usuario_admin():

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
    "/admin/usuarios/<int:usuario_id>/excluir",
    methods=["POST"]
)
def admin_excluir_usuario(usuario_id):

    if not usuario_logado():

        return redirect("/login")

    if not usuario_admin():

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

        return jsonify({
            "status": "chunk_transcrito",
            "texto": texto
        })

    except Exception as e:

        print("ERRO AO TRANSCREVER CHUNK:", e)
        traceback.print_exc()

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

    if transcricao:

        resultado = analisar_com_ia(
            transcricao
        )

        if chunks_falhos:

            resultado += (
                "\n\nAviso interno: "
                f"{chunks_falhos} trecho(s) de audio falharam "
                "na transcricao. Revise a ligacao antes de fechar "
                "o ticket se a informacao parecer incompleta."
            )

    else:

        resultado = (
            "Nao foi possivel gerar resumo: "
            "nenhuma transcricao foi capturada."
        )

    custo_estimado = estimar_custo_atendimento(
        segundos_transcritos,
        bool(transcricao)
    )

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
                    custo_estimado_usd = %s
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
                    atendimento_id,
                    usuario_id
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

    data = datetime.now().strftime(
        "%d/%m/%Y %H:%M"
    )

    arquivo = request.files["audio"]
    texto = transcrever_chunk(arquivo)
    resultado = analisar_com_ia(texto)

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
                    chunks_falhos
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s)
                """,
                (
                    usuario_id,
                    str(uuid.uuid4()) + ".webm",
                    resultado,
                    data,
                    "finalizado",
                    texto,
                    1,
                    0
                )
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
        and usuario_admin()
    )

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
            "conteudo": row[2],
            "data": row[3],
            "status": row[4],
            "chunks_total": row[5] or 0,
            "chunks_falhos": row[6] or 0,
            "duracao_segundos": row[7] or 0,
            "transcricao_completa": row[8] or "",
            "ticket_zendesk": row[9] or "",
            "chunks_ignorados": row[10] or 0,
            "segundos_transcritos": row[11] or 0,
            "custo_estimado_usd": float(row[12] or 0),
            "resumo_editado": bool(row[13]),
            "usuario": row[14] or "Nao informado"
        }

        itens.append(item)

        if row[4] != "finalizado":

            processando.append(str(row[0]))

    return jsonify({
        "resultados": itens,
        "processando": processando,
        "escopo": "todos" if ver_todos else "meus",
        "is_admin": usuario_admin()
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

            if usuario_admin():

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
        "conteudo": row[1] or "",
        "transcricao_completa": row[2] or "",
        "data": row[3],
        "status": row[4],
        "duracao_segundos": row[5] or 0,
        "chunks_total": row[6] or 0,
        "chunks_falhos": row[7] or 0,
        "ticket_zendesk": row[8] or "",
        "chunks_ignorados": row[9] or 0,
        "segundos_transcritos": row[10] or 0,
        "custo_estimado_usd": float(row[11] or 0),
        "resumo_editado": bool(row[12]),
        "usuario": row[13] or "Nao informado"
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
    resumo = limpar_texto(
        dados.get("resumo", "")
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
                    usuario_admin()
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
                SELECT transcricao_completa, segundos_transcritos
                FROM atendimentos
                WHERE id = %s
                AND (
                    usuario_id = %s
                    OR %s
                )
                """,
                (
                    atendimento_id,
                    usuario_id,
                    usuario_admin()
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

            resumo = analisar_com_ia(
                transcricao
            )

            custo_estimado = estimar_custo_atendimento(
                row[1] or 0,
                True
            )

            cursor.execute(
                """
                UPDATE atendimentos
                SET
                    conteudo = %s,
                    resumo_editado = FALSE,
                    resumo_editado_em = NULL,
                    custo_estimado_usd = %s
                WHERE id = %s
                """,
                (
                    resumo,
                    custo_estimado,
                    atendimento_id
                )
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
                    custo_estimado_usd
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
        "Resumo",
        "Transcricao",
        "Trechos",
        "Trechos com falha",
        "Trechos ignorados",
        "Segundos transcritos",
        "Custo estimado USD"
    ])

    for row in rows:

        ws.append(row)

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
