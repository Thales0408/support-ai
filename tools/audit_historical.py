import argparse
import json
import os
import re
from collections import Counter

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
