import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("SKIP_DB_INIT", "1")

from app import (  # noqa: E402
    extrair_entidades_transcricao,
    extrair_secao_texto,
    limpar_texto,
    limpar_transcricao_para_resumo,
    limpar_vazamento_prompt_transcricao,
    normalizar_para_comparacao,
    texto_zendesk_formatado,
)
from services.ai import pontuacao_ruido_transcricao  # noqa: E402
from services.database import conectar_banco  # noqa: E402


ROTULOS = {
    "empresa": ["Nome da empresa", "Empresa"],
    "empresa_loja": ["Empresa/Loja", "Loja"],
    "cnpj": ["CNPJ"],
    "cliente_nome": ["Nome do Cliente", "Cliente"],
    "telefone": ["Telefone de contato", "Telefone"],
    "email": ["E-mail Solicitante", "Email", "E-mail"],
    "analista_nome": [
        "Analista responsável",
        "Analista responsavel",
        "Analista",
    ],
    "descritivo": [
        "Descritivo da ocorrência do atendimento",
        "Descritivo da ocorrencia do atendimento",
        "Descritivo do atendimento",
        "Resumo do atendimento",
    ],
}

MARCADORES_DESCRITIVO_SUSPEITO = [
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


def normalizar(valor):
    return normalizar_para_comparacao(str(valor or ""))


def extrair_campos_salvos(conteudo):
    texto = texto_zendesk_formatado(conteudo)

    return {
        chave: extrair_secao_texto(texto, rotulos)
        for chave, rotulos in ROTULOS.items()
    }


def diferenca_campo(antigo, novo):
    antigo_n = normalizar(antigo)
    novo_n = normalizar(novo)

    if not antigo_n and not novo_n:
        return ""

    if not antigo_n and novo_n:
        return "preenchivel"

    if antigo_n and not novo_n:
        return "antigo_sem_evidencia_atual"

    if antigo_n != novo_n:
        return "divergente"

    return ""


def flags_descritivo(texto):
    comparacao = normalizar(texto)
    return [
        marcador
        for marcador in MARCADORES_DESCRITIVO_SUSPEITO
        if normalizar(marcador) in comparacao
    ]


def contexto_curto(texto, valor, margem=110):
    texto = str(texto or "")
    valor = str(valor or "").strip()

    if not texto or not valor:
        return ""

    match = re.search(
        re.escape(valor),
        texto,
        flags=re.IGNORECASE
    )

    if not match:
        return ""

    inicio = max(0, match.start() - margem)
    fim = min(len(texto), match.end() + margem)

    trecho = texto[inicio:fim]
    trecho = re.sub(r"\s+", " ", trecho).strip()

    return trecho


def auditar(limit=None, case_limit=80):
    sql = """
        SELECT
            a.id,
            a.conteudo,
            a.transcricao_completa,
            a.status,
            a.data,
            a.usuario_id,
            COALESCE(u.usuario, ''),
            COALESCE(a.categoria, ''),
            COALESCE(a.problema_principal, ''),
            COALESCE(a.tags, '')
        FROM atendimentos a
        LEFT JOIN usuarios u
        ON u.id = a.usuario_id
        WHERE COALESCE(TRIM(a.transcricao_completa), '') <> ''
        ORDER BY a.id
    """

    with conectar_banco() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()

    if limit:
        rows = rows[:limit]

    totais = Counter()
    casos = []

    for row in rows:
        (
            atendimento_id,
            conteudo,
            transcricao_bruta,
            status,
            data,
            usuario_id,
            usuario,
            categoria,
            problema_principal,
            tags,
        ) = row

        transcricao_original = limpar_vazamento_prompt_transcricao(
            limpar_texto(transcricao_bruta or "")
        )

        transcricao_limpa = limpar_transcricao_para_resumo(
            transcricao_original
        )

        atuais = extrair_campos_salvos(conteudo)
        novos = extrair_entidades_transcricao(
            transcricao_original,
            usuario,
        )

        comparacoes = {}
        evidencia_antiga = {}

        transcricao_normalizada = normalizar(
            transcricao_original
        )
        inicio_normalizado = normalizar(
            transcricao_original[:320]
        )

        for campo in [
            "empresa",
            "cnpj",
            "cliente_nome",
            "telefone",
            "email",
        ]:
            tipo = diferenca_campo(
                atuais.get(campo, ""),
                novos.get(campo, ""),
            )
            if tipo:
                comparacoes[campo] = tipo
                totais[f"{campo}:{tipo}"] += 1

            valor_antigo = atuais.get(campo, "")
            valor_antigo_normalizado = normalizar(
                valor_antigo
            )

            presente = bool(
                valor_antigo_normalizado
                and valor_antigo_normalizado
                in transcricao_normalizada
            )
            presente_inicio = bool(
                valor_antigo_normalizado
                and valor_antigo_normalizado
                in inicio_normalizado
            )

            evidencia_antiga[campo] = {
                "presente_transcricao": presente,
                "presente_inicio": presente_inicio,
            }

            if valor_antigo:
                totais[
                    f"{campo}:antigo_presente_transcricao"
                    if presente
                    else f"{campo}:antigo_ausente_transcricao"
                ] += 1

        score_ruido = pontuacao_ruido_transcricao(
            transcricao_original
        )

        if score_ruido:
            totais["transcricao:ruido"] += 1

        if transcricao_original != transcricao_limpa:
            totais["transcricao:limpeza_alterou"] += 1

        suspeitas = flags_descritivo(
            atuais.get("descritivo", "")
        )
        if suspeitas:
            totais["descritivo:frase_suspeita"] += 1

        if not atuais.get("cliente_nome") and novos.get("cliente_nome"):
            totais["oportunidade:nome_cliente"] += 1

        if not atuais.get("empresa") and novos.get("empresa"):
            totais["oportunidade:empresa"] += 1

        if not atuais.get("cnpj") and novos.get("cnpj"):
            totais["oportunidade:cnpj"] += 1

        contexto_cliente_antigo = ""
        if (
            atuais.get("cliente_nome")
            and not novos.get("cliente_nome")
            and evidencia_antiga.get(
                "cliente_nome",
                {}
            ).get("presente_transcricao")
        ):
            contexto_cliente_antigo = contexto_curto(
                transcricao_original,
                atuais.get("cliente_nome", "")
            )

        contexto_empresa_antiga = ""
        if (
            atuais.get("empresa")
            and not novos.get("empresa")
            and evidencia_antiga.get(
                "empresa",
                {}
            ).get("presente_transcricao")
        ):
            contexto_empresa_antiga = contexto_curto(
                transcricao_original,
                atuais.get("empresa", "")
            )

        if comparacoes or score_ruido or suspeitas:
            casos.append({
                "id": atendimento_id,
                "status": status,
                "data": str(data or ""),
                "usuario_id": usuario_id,
                "analista": usuario,
                "categoria": categoria,
                "problema_principal": problema_principal,
                "tags": tags,
                "comparacoes": comparacoes,
                "evidencia_antiga": evidencia_antiga,
                "contexto_cliente_antigo": contexto_cliente_antigo,
                "contexto_empresa_antiga": contexto_empresa_antiga,
                "campos_salvos": {
                    campo: atuais.get(campo, "")
                    for campo in [
                        "empresa",
                        "cnpj",
                        "cliente_nome",
                        "telefone",
                        "email",
                    ]
                },
                "campos_atuais": {
                    campo: novos.get(campo, "")
                    for campo in [
                        "empresa",
                        "cnpj",
                        "cliente_nome",
                        "telefone",
                        "email",
                    ]
                },
                "score_ruido": score_ruido,
                "frases_suspeitas": suspeitas,
            })

    resumo = {
        "atendimentos_com_transcricao": len(rows),
        "casos_com_sinal_de_revisao": len(casos),
        "contagens": dict(sorted(totais.items())),
    }

    print(
        "AUDIT_SUMMARY="
        + json.dumps(
            resumo,
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    for caso in casos[:case_limit]:
        print(
            "AUDIT_CASE="
            + json.dumps(
                caso,
                ensure_ascii=False,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Auditoria histórica somente leitura dos atendimentos. "
            "Não altera registros nem chama IA."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--case-limit",
        type=int,
        default=80,
    )
    args = parser.parse_args()

    auditar(
        limit=args.limit,
        case_limit=args.case_limit,
    )
