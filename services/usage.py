from config import (
    MAX_COST_PER_USER_PER_DAY,
    MAX_SUMMARIES_PER_DAY,
    MAX_SYSTEM_COST_PER_DAY,
    USD_BRL_RATE
)


def uso_diario_usuario(cursor, usuario_id, atendimento_id=None):

    params = [usuario_id]
    excluir_atendimento = ""

    if atendimento_id:

        excluir_atendimento = "AND id <> %s"
        params.append(atendimento_id)

    cursor.execute(
        f"""
        SELECT
            COUNT(*),
            COALESCE(SUM(segundos_transcritos), 0),
            COALESCE(SUM(custo_estimado_usd), 0)
        FROM atendimentos
        WHERE usuario_id = %s
        AND inicio_em >= CURRENT_DATE
        AND inicio_em < CURRENT_DATE + INTERVAL '1 day'
        {excluir_atendimento}
        """,
        tuple(params)
    )

    chamadas, segundos, custo = cursor.fetchone()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM transcricoes_chunks tc
        INNER JOIN atendimentos a
        ON a.id = tc.atendimento_id
        WHERE tc.usuario_id = %s
        AND COALESCE(a.inicio_em, tc.criado_em) >= CURRENT_DATE
        AND COALESCE(a.inicio_em, tc.criado_em) < CURRENT_DATE + INTERVAL '1 day'
        """,
        (
            usuario_id,
        )
    )

    chunks = cursor.fetchone()[0]

    return {
        "chamadas": int(chamadas or 0),
        "segundos": int(segundos or 0),
        "chunks": int(chunks or 0),
        "custo": float(custo or 0)
    }


def uso_eventos_diario(cursor, usuario_id=None):

    filtro_usuario = ""
    params = []

    if usuario_id:

        filtro_usuario = "AND usuario_id = %s"
        params.append(usuario_id)

    cursor.execute(
        f"""
        SELECT
            COALESCE(SUM(custo_brl), 0),
            SUM(
                CASE
                    WHEN tipo = 'resumo' THEN 1
                    ELSE 0
                END
            )
        FROM uso_eventos
        WHERE criado_em >= CURRENT_DATE
        AND criado_em < CURRENT_DATE + INTERVAL '1 day'
        {filtro_usuario}
        """,
        tuple(params)
    )

    custo_brl_total, resumos = cursor.fetchone()

    return {
        "custo_brl": float(custo_brl_total or 0),
        "resumos": int(resumos or 0)
    }


def custo_brl(custo_usd):

    return round(
        float(custo_usd or 0) * USD_BRL_RATE,
        4
    )


def registrar_uso_evento(
    cursor,
    usuario_id,
    atendimento_id,
    tipo,
    custo_usd
):

    cursor.execute(
        """
        INSERT INTO uso_eventos (
            usuario_id,
            atendimento_id,
            tipo,
            custo_usd,
            custo_brl
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            usuario_id,
            atendimento_id,
            tipo,
            custo_usd,
            custo_brl(custo_usd)
        )
    )


def avaliar_limites_custo_resumo(
    cursor,
    usuario_id,
    atendimento_id,
    custo_estimado_usd
):

    uso_usuario = uso_eventos_diario(
        cursor,
        usuario_id
    )
    uso_sistema = uso_eventos_diario(cursor)
    custo_projetado = custo_brl(custo_estimado_usd)

    if uso_usuario["resumos"] >= MAX_SUMMARIES_PER_DAY:

        return {
            "evento": "limite_resumos_dia",
            "mensagem": "Limite diario de resumos atingido.",
            "log": {
                "usuario_id": usuario_id,
                "atendimento_id": atendimento_id,
                "resumos": uso_usuario["resumos"],
                "limite": MAX_SUMMARIES_PER_DAY
            },
            "resposta": {
                "resumos_hoje": uso_usuario["resumos"],
                "limite_resumos": MAX_SUMMARIES_PER_DAY
            }
        }

    if (
        uso_usuario["custo_brl"] + custo_projetado
        > MAX_COST_PER_USER_PER_DAY
    ):

        return {
            "evento": "limite_custo_usuario_dia",
            "mensagem": "Limite diario de custo por usuario atingido.",
            "log": {
                "usuario_id": usuario_id,
                "atendimento_id": atendimento_id,
                "custo_brl_atual": uso_usuario["custo_brl"],
                "custo_brl_projetado": custo_projetado,
                "limite": MAX_COST_PER_USER_PER_DAY
            },
            "resposta": {
                "custo_hoje_brl": round(uso_usuario["custo_brl"], 4),
                "custo_projetado_brl": custo_projetado,
                "limite_custo_usuario_brl": MAX_COST_PER_USER_PER_DAY
            }
        }

    if (
        uso_sistema["custo_brl"] + custo_projetado
        > MAX_SYSTEM_COST_PER_DAY
    ):

        return {
            "evento": "limite_custo_sistema_dia",
            "mensagem": "Limite diario de custo total do sistema atingido.",
            "log": {
                "usuario_id": usuario_id,
                "atendimento_id": atendimento_id,
                "custo_brl_atual": uso_sistema["custo_brl"],
                "custo_brl_projetado": custo_projetado,
                "limite": MAX_SYSTEM_COST_PER_DAY
            },
            "resposta": {
                "custo_sistema_hoje_brl": round(uso_sistema["custo_brl"], 4),
                "custo_projetado_brl": custo_projetado,
                "limite_custo_sistema_brl": MAX_SYSTEM_COST_PER_DAY
            }
        }

    return None
