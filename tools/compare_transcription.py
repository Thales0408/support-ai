import argparse
import difflib
import mimetypes
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ai import (
    estimar_custo_transcricao,
    transcrever_bytes
)
from services.audio import preprocessar_audio_transcricao


MODELOS = [
    ("groq", "whisper-large-v3-turbo"),
    ("groq", "whisper-large-v3"),
    ("openai", "whisper-1")
]


def similaridade(a, b):

    return difflib.SequenceMatcher(
        None,
        str(a or "").split(),
        str(b or "").split()
    ).ratio()


def diferenca_resumida(textos):

    nomes = list(textos.keys())

    if len(nomes) < 2:

        return "Sem comparacao suficiente."

    linhas = []

    for indice, nome in enumerate(nomes):

        for outro in nomes[indice + 1:]:

            linhas.append(
                f"{nome} vs {outro}: similaridade "
                f"{similaridade(textos[nome], textos[outro]):.2%}"
            )

    return "\n".join(linhas)


def sinais_ruido(texto):

    texto = str(texto or "")
    palavras = re.findall(r"[A-Za-zÀ-ÿ0-9]+", texto.lower())
    repeticoes = sum(
        1
        for a, b in zip(palavras, palavras[1:])
        if a == b
    )
    tokens_suspeitos = sum(
        1
        for palavra in palavras
        if palavra.startswith(("trisk", "trish", "trist", "drishu"))
    )

    return repeticoes + tokens_suspeitos * 3


def melhor_aparente(resultados):

    validos = [
        item
        for item in resultados
        if item["texto"]
    ]

    if not validos:

        return "Nenhum modelo retornou transcricao."

    def pontuar(item):

        outros = [
            outro
            for outro in validos
            if outro is not item
            and outro["variante"] == item["variante"]
        ]

        consenso = (
            sum(
                similaridade(item["texto"], outro["texto"])
                for outro in outros
            ) / len(outros)
            if outros
            else 0
        )
        numeros = sum(
            1
            for char in item["texto"]
            if char.isdigit()
        )

        return (
            consenso * 100
            + min(numeros, 30) * 0.15
            - sinais_ruido(item["texto"]) * 4
        )

    melhor = max(validos, key=pontuar)

    return (
        f"{melhor['variante']} / "
        f"{melhor['provider']} {melhor['modelo']}"
    )


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument(
        "--duracao-segundos",
        type=float,
        default=60,
        help="Duracao real do audio usada apenas para estimativa de custo."
    )
    args = parser.parse_args()

    caminho = Path(args.audio)
    audio_original = caminho.read_bytes()
    mime_original = (
        mimetypes.guess_type(caminho.name)[0]
        or "audio/webm"
    )
    preprocessado = preprocessar_audio_transcricao(
        audio_original,
        caminho.name
    )

    variantes = [
        (
            "original",
            audio_original,
            caminho.name,
            mime_original
        )
    ]

    if preprocessado.get("audio_processado"):

        variantes.append(
            (
                "processado",
                preprocessado["audio_bytes"],
                preprocessado["nome"],
                preprocessado["mime"]
            )
        )

    resultados = []

    for variante, audio_bytes, nome, mime in variantes:

        for provider, modelo in MODELOS:

            inicio = time.perf_counter()

            try:

                texto = transcrever_bytes(
                    provider,
                    audio_bytes,
                    nome,
                    mime,
                    modelo=modelo
                )
                erro = ""

            except Exception as exc:

                texto = ""
                erro = str(exc)

            segundos_execucao = round(
                time.perf_counter() - inicio,
                2
            )
            custo = estimar_custo_transcricao(
                max(1, int(args.duracao_segundos)),
                provider
            )

            resultados.append({
                "variante": variante,
                "provider": provider,
                "modelo": modelo,
                "texto": texto,
                "tempo": segundos_execucao,
                "custo": custo,
                "erro": erro
            })

    print("Audio original:", caminho)
    print(
        "Audio processado:",
        preprocessado.get("audio_processado_path")
        or "nao processado"
    )
    print(
        "Duracao usada no custo:",
        f"{args.duracao_segundos:.1f}s"
    )
    print()

    for item in resultados:

        titulo = (
            f"{item['variante']} | "
            f"{item['provider']} {item['modelo']}"
        )
        print("=" * len(titulo))
        print(titulo)
        print("=" * len(titulo))
        print("Tempo:", item["tempo"], "s")
        print(
            "Custo estimado:",
            "US$",
            f"{item['custo']:.4f}"
        )

        if item["erro"]:

            print("Erro:", item["erro"])

        else:

            print(item["texto"])

        print()

    textos = {
        (
            f"{item['variante']} | "
            f"{item['provider']} {item['modelo']}"
        ): item["texto"]
        for item in resultados
        if item["texto"]
    }

    print("Diferencas principais")
    print("---------------------")
    print(diferenca_resumida(textos))
    print()
    print(
        "Melhor resultado aparente (heuristica):",
        melhor_aparente(resultados)
    )


if __name__ == "__main__":

    main()
