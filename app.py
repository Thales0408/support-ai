from flask import (
    Flask,
    request,
    jsonify,
    send_from_directory,
    render_template
)

from flask_cors import CORS
from faster_whisper import WhisperModel
from openai import OpenAI
from pydub import AudioSegment
from pydub.silence import split_on_silence
from waitress import serve

import sqlite3
import threading
import uuid
import os
import re
from dotenv import load_dotenv

from datetime import datetime
load_dotenv()

# =========================================
# CONFIG
# =========================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

UPLOAD_FOLDER = "uploads"

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)

# =========================================
# FLASK
# =========================================

app = Flask(__name__)

CORS(app)

# =========================================
# OPENAI
# =========================================

client = OpenAI(
    api_key=OPENAI_API_KEY
)

# =========================================
# WHISPER
# =========================================

print("Carregando Whisper...")

model = WhisperModel(

    "base",

    device="cpu",

    compute_type="int8"
)

print("Whisper carregado!")

# =========================================
# SQLITE
# =========================================

conn = sqlite3.connect(
    "historico.db",
    check_same_thread=False
)

cursor = conn.cursor()

cursor.execute("""

CREATE TABLE IF NOT EXISTS atendimentos (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    arquivo TEXT,

    conteudo TEXT,

    data TEXT

)

""")

conn.commit()

# =========================================
# FILA
# =========================================

processando = []

# =========================================
# LIMPAR TEXTO
# =========================================

def limpar_texto(texto):

    texto = re.sub(
        r'\s+',
        ' ',
        texto
    )

    return texto.strip()

# =========================================
# REMOVER SILENCIO
# =========================================

def remover_silencio(caminho_audio):

    print("Removendo silêncio...")

    audio = AudioSegment.from_file(
        caminho_audio
    )

    # melhora áudio telefonia
    audio = audio.set_channels(1)
    audio = audio.set_frame_rate(16000)

    chunks = split_on_silence(

        audio,

        min_silence_len=800,

        silence_thresh=audio.dBFS - 16,

        keep_silence=250
    )

    if not chunks:

        return caminho_audio

    audio_final = AudioSegment.empty()

    for chunk in chunks:

        audio_final += chunk

    novo_arquivo = caminho_audio.replace(
        ".webm",
        "_limpo.wav"
    )

    audio_final.export(

        novo_arquivo,

        format="wav"
    )

    print("Silêncio removido!")

    return novo_arquivo

# =========================================
# TRANSCREVER
# =========================================

def transcrever_audio(caminho):

    print("Iniciando transcrição...")

    caminho_limpo = remover_silencio(
        caminho
    )

    segments, info = model.transcribe(

        caminho_limpo,

        language="pt",

        vad_filter=True,

        beam_size=5,

        condition_on_previous_text=False
    )

    texto = ""

    for segment in segments:

        texto += (
            segment.text + " "
        )

    texto = limpar_texto(texto)

    print("Transcrição finalizada!")

    try:

        if os.path.exists(caminho):
            os.remove(caminho)

        if os.path.exists(caminho_limpo):
            os.remove(caminho_limpo)

    except:
        pass

    return texto

# =========================================
# IA
# =========================================

def analisar_com_ia(transcricao):

    prompt = f"""

Você é um analista de suporte ERP.

A transcrição abaixo pode conter
erros de reconhecimento de fala.

Corrija termos prováveis de ERP,
nomes de empresas, CNPJ,
telefones e contexto do atendimento.

Não invente informações.

EXTRAIA:

- Nome da empresa
- Empresa/Loja
- CNPJ
- Nome do Cliente
- Telefone
- E-mail
- Analista responsável
- Resumo curto do problema

REGRAS:

- resumo curto
- máximo 3 linhas
- direto
- profissional
- sem inventar dados
- se não encontrar:
Não informado

GERAR TAMBÉM:

Tags:
3 palavras-chave curtas

FORMATO EXATO:

Nome da empresa:
Empresa/Loja:
CNPJ:
Nome do Cliente:
Telefone de contato:
E-mail Solicitante:
Analista responsável:
Descritivo da ocorrência do atendimento:
Tags:

LIGAÇÃO:
{transcricao}

"""

    resposta = client.chat.completions.create(

        model="gpt-4.1-mini",

        messages=[

            {
                "role": "user",
                "content": prompt
            }

        ]

    )

    return resposta.choices[0].message.content

# =========================================
# PROCESSAR
# =========================================

def processar_em_background(
    caminho_audio,
    nome_arquivo
):

    try:

        texto = transcrever_audio(
            caminho_audio
        )

        resultado = analisar_com_ia(
            texto
        )

        data = datetime.now().strftime(
            "%d/%m/%Y %H:%M"
        )

        cursor.execute(

            """

            INSERT INTO atendimentos (
                arquivo,
                conteudo,
                data
            )

            VALUES (?, ?, ?)

            """,

            (
                nome_arquivo,
                resultado,
                data
            )
        )

        conn.commit()

        print("Atendimento salvo!")

    except Exception as e:

        print("ERRO:", e)

    finally:

        if nome_arquivo in processando:

            processando.remove(
                nome_arquivo
            )

# =========================================
# TRANSCREVER
# =========================================

@app.route(
    "/transcrever",
    methods=["POST"]
)

def transcrever():

    if "audio" not in request.files:

        return jsonify({
            "erro": "Sem áudio"
        })

    arquivo = request.files["audio"]

    nome_arquivo = (
        str(uuid.uuid4()) +
        ".webm"
    )

    caminho_audio = os.path.join(

        UPLOAD_FOLDER,
        nome_arquivo
    )

    arquivo.save(
        caminho_audio
    )

    print(
        "Audio salvo:",
        caminho_audio
    )

    processando.append(
        nome_arquivo
    )

    thread = threading.Thread(

        target=processar_em_background,

        args=(
            caminho_audio,
            nome_arquivo
        )
    )

    thread.start()

    return jsonify({

        "status": "processando"

    })

# =========================================
# RESULTADOS
# =========================================

@app.route("/resultados")

def resultados():

    busca = request.args.get(
        "busca",
        ""
    )

    if busca:

        cursor.execute(

            """

            SELECT *
            FROM atendimentos

            WHERE
                conteudo LIKE ?

            ORDER BY id DESC

            """,

            (
                f"%{busca}%",
            )
        )

    else:

        cursor.execute(

            """

            SELECT *
            FROM atendimentos

            ORDER BY id DESC

            LIMIT 100

            """
        )

    rows = cursor.fetchall()

    resultados = []

    for row in rows:

        resultados.append({

            "id": row[0],

            "arquivo": row[1],

            "conteudo": row[2],

            "data": row[3]
        })

    return jsonify({

        "resultados": resultados,

        "processando": processando

    })

# =========================================
# INDEX
# =========================================

@app.route("/")

def index():

    return render_template(
        "index.html"
    )

# =========================================
# POPUP JS
# =========================================

@app.route("/popup.js")

def popup():

    return send_from_directory(
        "static",
        "popup.js"
    )

# =========================================
# START
# =========================================

if __name__ == "__main__":

    serve(

        app,

        host="0.0.0.0",

        port=8080,

        threads=8
    )