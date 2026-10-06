import argparse
import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("SKIP_DB_INIT", "1")

from app import (  # noqa: E402
    analisar_com_ia,
    extrair_entidades_transcricao,
    extrair_secao_texto,
    limpar_texto,
    limpar_transcricao_para_resumo,
    limpar_vazamento_prompt_transcricao,
    normalizar_entidades_faladas,
    texto_zendesk_formatado,
)
from services.database import conectar_banco  # noqa: E402


ROTULOS = {
    "empresa": ["Nome da empresa", "Empresa"],
    "empresa_loja": ["Empresa/Loja", "Loja"],
    "cnpj": ["CNPJ"],
    "cliente_nome": ["Nome do Cliente", "Cliente"],
    "telefone": ["Telefone de contato", "Telefone"],
    "email": ["E-mail Solicitante", "Email", "E-mail"],
    "descritivo": [
        "Descritivo da ocorrência do atendimento",
        "Descritivo da ocorrencia do atendimento",
        "Descritivo do atendimento",
        "Resumo do atendimento",
    ],
}


def campos(conteudo):
    texto = texto_zendesk_formatado(conteudo)
    return {
        chave: extrair_secao_texto(texto, rotulos)
        for chave, rotulos in ROTULOS.items()
    }


def cortar(texto, limite=1800):
    texto = str(texto or "")
    if len(texto) <= limite:
        return texto
    return texto[:limite] + "..."


def executar(ids):
    ids = sorted(set(int(valor) for valor in ids))

    if not ids:
        raise SystemExit("Informe pelo menos um ID.")

    if len(ids) > 10:
        raise SystemExit("Dry-run limitado a no maximo 10 atendimentos por execucao.")

    with conectar_banco() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    a.id,
                    a.conteudo,
                    a.transcricao_completa,
                    COALESCE(u.usuario, '')
                FROM atendimentos a
                LEFT JOIN usuarios u
                ON u.id = a.usuario_id
                WHERE a.id = ANY(%s)
                ORDER BY a.id
                """,
                (ids,)
            )
            rows = cursor.fetchall()

    encontrados = {int(row[0]) for row in rows}
    faltantes = [valor for valor in ids if valor not in encontrados]

    if faltantes:
        print(
            "DRY_REPROCESS_MISSING="
            + json.dumps(faltantes)
        )

    for atendimento_id, conteudo_antigo, transcricao_bruta, analista in rows:
        transcricao_original = limpar_vazamento_prompt_transcricao(
            limpar_texto(transcricao_bruta or "")
        )

        entidades = extrair_entidades_transcricao(
            transcricao_original,
            analista
        )

        transcricao = normalizar_entidades_faladas(
            limpar_transcricao_para_resumo(
                transcricao_original
            )
        )

        if not transcricao:
            print(
                "DRY_REPROCESS="
                + json.dumps(
                    {
                        "id": atendimento_id,
                        "erro": "transcricao_vazia",
                    },
                    ensure_ascii=False,
                )
            )
            continue

        analise = analisar_com_ia(
            transcricao,
            analista,
            entidades_extraidas=entidades
        )

        novo_conteudo = analise.get("resumo_zendesk", "")
        antigos = campos(conteudo_antigo)
        novos = campos(novo_conteudo)

        print(
            "DRY_REPROCESS="
            + json.dumps(
                {
                    "id": atendimento_id,
                    "analista": analista,
                    "entidades_deterministicas": entidades,
                    "campos_antigos": {
                        chave: antigos.get(chave, "")
                        for chave in [
                            "empresa",
                            "empresa_loja",
                            "cnpj",
                            "cliente_nome",
                            "telefone",
                            "email",
                        ]
                    },
                    "campos_novos": {
                        chave: novos.get(chave, "")
                        for chave in [
                            "empresa",
                            "empresa_loja",
                            "cnpj",
                            "cliente_nome",
                            "telefone",
                            "email",
                        ]
                    },
                    "descritivo_antigo": cortar(
                        antigos.get("descritivo", "")
                    ),
                    "descritivo_novo": cortar(
                        novos.get("descritivo", "")
                    ),
                    "categoria_nova": analise.get("categoria", ""),
                    "problema_principal_novo": analise.get(
                        "problema_principal",
                        ""
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Reprocessa atendimentos em memoria para QA. "
            "Nao atualiza o banco."
        )
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        type=int,
        required=True,
    )
    args = parser.parse_args()
    executar(args.ids)
