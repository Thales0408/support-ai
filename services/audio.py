from pathlib import Path

import subprocess
import time
import uuid

from config import (
    AUDIO_DIAGNOSTICS_DIR,
    AUDIO_PREPROCESS_ENABLED,
    FFMPEG_PATH
)


def extensao_audio(nome):

    sufixo = Path(str(nome or "")).suffix.lower()

    if sufixo and len(sufixo) <= 8:

        return sufixo

    return ".webm"


def preprocessar_audio_transcricao(audio_bytes, nome="chunk.webm"):

    inicio = time.perf_counter()
    audio_bytes = audio_bytes or b""
    identificador = uuid.uuid4().hex
    pasta = Path(AUDIO_DIAGNOSTICS_DIR)
    pasta.mkdir(parents=True, exist_ok=True)

    caminho_original = pasta / f"{identificador}_original{extensao_audio(nome)}"
    caminho_processado = pasta / f"{identificador}_processado.wav"
    caminho_original.write_bytes(audio_bytes)

    resultado = {
        "audio_bytes": audio_bytes,
        "nome": "chunk.webm",
        "mime": "audio/webm",
        "audio_processado": False,
        "audio_original_path": str(caminho_original),
        "audio_processado_path": "",
        "tamanho_audio_original": len(audio_bytes),
        "tamanho_audio_processado": len(audio_bytes),
        "tempo_preprocessamento_segundos": 0,
        "erro_preprocessamento": ""
    }

    if not AUDIO_PREPROCESS_ENABLED:

        return resultado

    comando = [
        FFMPEG_PATH,
        "-y",
        "-i",
        str(caminho_original),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-af",
        (
            "highpass=f=80,"
            "lowpass=f=7800,"
            "afftdn=nf=-25,"
            "loudnorm=I=-18:TP=-2:LRA=11"
        ),
        "-acodec",
        "pcm_s16le",
        str(caminho_processado)
    ]

    try:

        subprocess.run(
            comando,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )

        processado = caminho_processado.read_bytes()

        resultado.update({
            "audio_bytes": processado,
            "nome": "chunk-processado.wav",
            "mime": "audio/wav",
            "audio_processado": True,
            "audio_processado_path": str(caminho_processado),
            "tamanho_audio_processado": len(processado)
        })

    except Exception as exc:

        resultado["erro_preprocessamento"] = str(exc)[:500]

    finally:

        resultado["tempo_preprocessamento_segundos"] = round(
            time.perf_counter() - inicio,
            4
        )

    return resultado
