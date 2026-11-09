"""Inventario de retencao; NUNCA apaga dados sem duas autorizacoes.

Uso seguro (dry run):
    python -m scripts.lgpd_retention --days 365

Execucao SOMENTE apos aprovacao de prazo pelo controlador e backup verificado:
    LGPD_RETENTION_APPLY_ENABLED=1 python -m scripts.lgpd_retention \
        --days 365 --apply --confirm EXCLUIR_TRANSCRICOES

Preserva macros, tickets, metadados e transcricoes de atendimentos nao
finalizados. Nao limpa audio pendente no Chrome ou dados de fornecedores.
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

from services.database import conectar_banco


def retention_inventory(cursor, cutoff):
    cursor.execute("""
        SELECT COUNT(*), COUNT(*) FILTER (
            WHERE COALESCE(transcricao_completa, '') <> ''
        )
        FROM atendimentos
        WHERE status='finalizado' AND fim_em IS NOT NULL AND fim_em < %s
    """, (cutoff,))
    atendimentos, completos = cursor.fetchone()
    cursor.execute("""
        SELECT COUNT(*) FROM transcricoes_chunks tc
        INNER JOIN atendimentos a ON a.id=tc.atendimento_id
        WHERE a.status='finalizado' AND a.fim_em IS NOT NULL AND a.fim_em < %s
        AND (
            COALESCE(tc.texto,'') <> '' OR
            COALESCE(tc.transcricao_bruta,'') <> '' OR
            COALESCE(tc.transcricao_normalizada,'') <> '' OR
            COALESCE(tc.transcricao_limpa_para_resumo,'') <> ''
        )
    """, (cutoff,))
    trechos = cursor.fetchone()[0]
    return dict(atendimentos_elegiveis=atendimentos,
                transcricoes_completas=completos, trechos_com_texto=trechos)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Retencao LGPD: simulacao por padrao")
    parser.add_argument("--days", type=int, required=True,
                        help="Prazo definido e aprovado pelo controlador")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if not 30 <= args.days <= 3650:
        parser.error("Prazo deve estar entre 30 e 3650 dias.")
    if args.apply and not (
        os.getenv("LGPD_RETENTION_APPLY_ENABLED") == "1"
        and args.confirm == "EXCLUIR_TRANSCRICOES"
    ):
        parser.error("Exclusao desativada. Flag e confirmacao exata obrigatorias.")

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    with conectar_banco() as conn:
        with conn.cursor() as cursor:
            inventory = retention_inventory(cursor, cutoff)
            print(json.dumps({
                "modo": "APLICAR" if args.apply else "SIMULACAO",
                "prazo_dias": args.days, **inventory
            }, ensure_ascii=False))
            if not args.apply:
                return 0

            # Lock por transacao para impedir expurgos simultaneos.
            cursor.execute("SELECT pg_try_advisory_xact_lock(550055, 2026)")
            if not cursor.fetchone()[0]:
                raise RuntimeError("Ja existe expurgo em execucao.")
            cursor.execute("""
                UPDATE transcricoes_chunks tc
                SET texto=NULL, transcricao_bruta=NULL,
                    transcricao_normalizada=NULL,
                    transcricao_limpa_para_resumo=NULL
                FROM atendimentos a
                WHERE tc.atendimento_id=a.id
                  AND a.status='finalizado'
                  AND a.fim_em IS NOT NULL AND a.fim_em < %s
            """, (cutoff,))
            trechos_atualizados = cursor.rowcount
            cursor.execute("""
                UPDATE atendimentos a
                SET transcricao_completa=NULL
                WHERE a.status='finalizado' AND a.fim_em IS NOT NULL
                  AND a.fim_em < %s
            """, (cutoff,))
            atendimentos_atualizados = cursor.rowcount
            detalhes = json.dumps({
                "prazo_dias": args.days,
                "trechos_atualizados": trechos_atualizados,
                "atendimentos_atualizados": atendimentos_atualizados
            })
            cursor.execute("""
                INSERT INTO auditoria_eventos (acao, detalhes)
                VALUES ('lgpd_retencao_transcricao', %s::jsonb)
            """, (detalhes,))
            print(json.dumps({
                "resultado": "APLICADO",
                "trechos_atualizados": trechos_atualizados,
                "atendimentos_atualizados": atendimentos_atualizados
            }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
