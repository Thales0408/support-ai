import argparse
import difflib
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


def diferenca_resumida(textos):

    nomes = list(textos.keys())

    if len(nomes) < 2:

        return "Sem comparacao suficiente."

    base = textos[nomes[0]].split()
    linhas = []

    for nome in nomes[1:]:

        comparado = textos[nome].split()
        similaridade = difflib.SequenceMatcher(
            None,
            base,
            comparado
        ).ratio()
        linhas.append(
            f"{nomes[0]} vs {nome}: similaridade {similaridade:.2%}"
        )

    return "\n".join(linhas)


def melhor_aparente(resultados):

    validos = [
        item
        for item in resultados
        if item["texto"]
    ]

    if not validos:

        return "Nenhum modelo retornou transcricao."

    def pontuar(item):

        texto = item["texto"]
        palavras = texto.split()
        numeros = sum(1 for char in texto if char.isdigit())
        repeticoes = sum(
            1
            for a, b in zip(palavras, palavras[1:])
            if a.lower() == b.lower()
        )

        return (
            len(palavras)
            + numeros * 0.3
            - repeticoes * 2
        )

    melhor = max(validos, key=pontuar)

    return f"{melhor['provider']} {melhor['modelo']}"


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    args = parser.parse_args()

    caminho = Path(args.audio)
    audio_bytes = caminho.read_bytes()
    preprocessado = preprocessar_audio_transcricao(
        audio_bytes,
        caminho.name
    )
    audio_transcricao = preprocessado["audio_bytes"]
    resultados = []

    for provider, modelo in MODELOS:

        inicio = time.perf_counter()

        try:

            texto = transcrever_bytes(
                provider,
                audio_transcricao,
                preprocessado["nome"],
                preprocessado["mime"],
                modelo=modelo
            )
            erro = ""

        except Exception as exc:

            texto = ""
            erro = str(exc)

        segundos = round(time.perf_counter() - inicio, 2)
        custo = estimar_custo_transcricao(
            60,
            provider
        )
        resultados.append({
            "provider": provider,
            "modelo": modelo,
            "texto": texto,
            "tempo": segundos,
            "custo": custo,
            "erro": erro
        })

    print("Audio original:", caminho)
    print("Audio processado:", preprocessado.get("audio_processado_path") or "nao processado")
    print()

    for item in resultados:

        titulo = f"{item['provider']} {item['modelo']}"
        print("=" * len(titulo))
        print(titulo)
        print("=" * len(titulo))
        print("Tempo:", item["tempo"], "s")
        print("Custo estimado:", "US$", f"{item['custo']:.4f}")

        if item["erro"]:

            print("Erro:", item["erro"])

        else:

            print(item["texto"])

        print()

    textos = {
        f"{item['provider']} {item['modelo']}": item["texto"]
        for item in resultados
        if item["texto"]
    }

    print("Diferencas principais")
    print("---------------------")
    print(diferenca_resumida(textos))
    print()
    print("Melhor resultado aparente:", melhor_aparente(resultados))


if __name__ == "__main__":

    main()
