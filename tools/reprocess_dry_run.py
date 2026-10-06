import argparse
import json
import os
import sys
from collections import Counter
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


def valor_normalizado(valor):
    return " ".join(
        str(valor or "").strip().lower().split()
    )


def comparar_campos(antigos, novos):
    diferencas = {}

    for chave in [
        "empresa",
        "empresa_loja",
        "cnpj",
        "cliente_nome",
        "telefone",
        "email",
    ]:
        antigo = antigos.get(chave, "")
        novo = novos.get(chave, "")

        if valor_normalizado(antigo) == valor_normalizado(novo):
            continue

        if not antigo and novo:
            tipo = "preenchido"
        elif antigo and not novo:
            tipo = "removido"
        else:
            tipo = "alterado"

        diferencas[chave] = {
            "tipo": tipo,
            "antes": antigo,
            "depois": novo,
        }

    return diferencas


MARCADORES_SUSPEITOS = [
    "acompanhamento continuo",
    "acompanhamento contínuo",
    "orientado acompanhamento",
    "cliente esta ciente",
    "cliente está ciente",
    "definir proximos passos",
    "definir próximos passos",
    "deve ser compartilhada",
    "deve ser compartilhado",
]


def frases_suspeitas(texto):
    base = valor_normalizado(texto)
    return [
        marcador
        for marcador in MARCADORES_SUSPEITOS
        if valor_normalizado(marcador) in base
    ]


def executar(ids=None, todos=False, compacto=False, case_limit=120):
    ids = sorted(set(int(valor) for valor in (ids or [])))

    if not ids and not todos:
        raise SystemExit("Informe pelo menos um ID ou use --all.")

    if ids and len(ids) > 10:
        raise SystemExit("Dry-run por IDs limitado a no maximo 10 atendimentos.")

    with conectar_banco() as conn:
        with conn.cursor() as cursor:
            if todos:
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
                    WHERE COALESCE(TRIM(a.transcricao_completa), '') <> ''
                    ORDER BY a.id
                    """
                )
            else:
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
    faltantes = [
        valor for valor in ids
        if valor not in encontrados
    ]

    if faltantes:
        print(
            "DRY_REPROCESS_MISSING="
            + json.dumps(faltantes)
        )

    print(
        "DRY_REPROCESS_SUMMARY="
        + json.dumps(
            {
                "selecionados": len(rows),
                "modo": "all" if todos else "ids",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    contagens = Counter()
    casos = []

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

        campos_antigos = {
            chave: antigos.get(chave, "")
            for chave in [
                "empresa",
                "empresa_loja",
                "cnpj",
                "cliente_nome",
                "telefone",
                "email",
            ]
        }
        campos_novos = {
            chave: novos.get(chave, "")
            for chave in [
                "empresa",
                "empresa_loja",
                "cnpj",
                "cliente_nome",
                "telefone",
                "email",
            ]
        }

        diferencas = comparar_campos(
            campos_antigos,
            campos_novos
        )
        suspeitas_antigas = frases_suspeitas(
            antigos.get("descritivo", "")
        )
        suspeitas_novas = frases_suspeitas(
            novos.get("descritivo", "")
        )

        for chave, detalhe in diferencas.items():
            contagens[
                f"{chave}:{detalhe['tipo']}"
            ] += 1

        if suspeitas_antigas:
            contagens["descritivo:suspeito_antigo"] += 1

        if suspeitas_novas:
            contagens["descritivo:suspeito_novo"] += 1

        if diferencas or suspeitas_antigas or suspeitas_novas:
            casos.append({
                "id": atendimento_id,
                "analista": analista,
                "diferencas": diferencas,
                "suspeitas_antigas": suspeitas_antigas,
                "suspeitas_novas": suspeitas_novas,
                "problema_principal_novo": analise.get(
                    "problema_principal",
                    ""
                ),
                "descritivo_antigo": cortar(
                    antigos.get("descritivo", ""),
                    650 if compacto else 1800
                ),
                "descritivo_novo": cortar(
                    novos.get("descritivo", ""),
                    650 if compacto else 1800
                ),
            })

        if not compacto:
            print(
                "DRY_REPROCESS="
                + json.dumps(
                    {
                        "id": atendimento_id,
                        "analista": analista,
                        "entidades_deterministicas": entidades,
                        "campos_antigos": campos_antigos,
                        "campos_novos": campos_novos,
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

    print(
        "DRY_REPROCESS_FINAL="
        + json.dumps(
            {
                "processados": len(rows),
                "casos_com_mudanca": len(casos),
                "contagens": dict(sorted(contagens.items())),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    if compacto:
        for caso in casos[:case_limit]:
            print(
                "DRY_REPROCESS_CASE="
                + json.dumps(
                    caso,
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
    grupo = parser.add_mutually_exclusive_group(
        required=True
    )
    grupo.add_argument(
        "--ids",
        nargs="+",
        type=int,
    )
    grupo.add_argument(
        "--all",
        action="store_true",
        help=(
            "Reprocessa em memoria todos os atendimentos "
            "com transcricao salva. Nao altera o banco."
        ),
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Imprime apenas resumo e casos com mudancas.",
    )
    parser.add_argument(
        "--case-limit",
        type=int,
        default=120,
    )
    args = parser.parse_args()
    executar(
        ids=args.ids,
        todos=args.all,
        compacto=args.compact,
        case_limit=args.case_limit,
    )
