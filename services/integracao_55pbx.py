"""Recebimento de metadados da API oficial de eventos 55PBX.

O webhook apenas registra eventos: nao baixa audio, nao aciona IA
e nao escreve no ClickDesk nesta primeira etapa.
"""

import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit


MAX_EVENT_BYTES = 64 * 1024


def token_autorizado(token_recebido, token_configurado):
    """Valida o header 'token' descrito no manual oficial."""
    if not token_configurado or not token_recebido:
        return False
    if len(token_recebido) > 512:
        return False
    return hmac.compare_digest(
        token_recebido.encode("utf-8"),
        token_configurado.encode("utf-8")
    )


def _texto(valor, limite=128):
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    if len(texto) > limite:
        raise ValueError("Campo da chamada excede o tamanho permitido")
    return texto


def _segundos(valor):
    if valor is None or valor == "":
        return None
    try:
        numero = int(valor)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Duracao de chamada invalida") from None
    if not 0 <= numero <= 86400:
        raise ValueError("Duracao de chamada fora do limite")
    return numero


def normalizar_telefone(payload):
    numero = re.sub(r"\D", "", str(payload.get("call_number") or ""))
    area = re.sub(r"\D", "", str(payload.get("call_area_code") or ""))
    pais = re.sub(r"\D", "", str(payload.get("call_country_code") or "55"))
    if not numero:
        return None
    if len(numero) in (8, 9) and len(area) == 2:
        numero = area + numero
    if len(numero) in (10, 11) and pais:
        numero = pais + numero
    if not 8 <= len(numero) <= 20:
        raise ValueError("Numero de telefone invalido")
    return numero


def _url_audio(valor):
    texto = _texto(valor, 2048)
    if not texto:
        return None
    partes = urlsplit(texto)
    if partes.scheme != "https" or not partes.hostname or partes.username or partes.password:
        raise ValueError("URL de audio invalida")
    # A URL e armazenada, nunca buscada nesta etapa. A proxima etapa
    # exigira lista de hosts permitidos e protecao SSRF antes do download.
    return texto


def normalizar_evento(payload):
    if not isinstance(payload, dict):
        raise ValueError("Evento precisa ser um objeto JSON")

    central_id = _texto(payload.get("central_id"), 128)
    call_id = _texto(payload.get("call_id"), 128)
    if not central_id or not call_id:
        raise ValueError("central_id e call_id sao obrigatorios")

    # Evita chaves arbitrarias em logs e problemas de controle no banco.
    if not re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", central_id):
        raise ValueError("central_id invalido")
    if not re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", call_id):
        raise ValueError("call_id invalido")

    url_audio = _url_audio(payload.get("call_url_audio"))
    base = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False
    ).encode("utf-8")

    return {
        "central_id": central_id,
        "call_id": call_id,
        "hash_evento": hashlib.sha256(base).hexdigest(),
        "ramal": _texto(payload.get("branch_mask"), 40),
        "telefone": normalizar_telefone(payload),
        "fila": _texto(payload.get("call_queue"), 160),
        "status_ligacao": _texto(payload.get("call_status"), 80),
        "tipo_ligacao": _texto(payload.get("call_type"), 40),
        "data_ligacao": _texto(payload.get("call_date"), 120),
        "duracao_segundos": _segundos(payload.get("call_duration")),
        "tempo_falado_segundos": _segundos(payload.get("call_time")),
        "url_audio": url_audio,
        "transferencia_id": _texto(payload.get("call_transfer_id"), 128),
    }


def registrar_evento(cursor, evento):
    """Insere um evento uma vez e acumula dados da chamada sem apagar os anteriores.

    Mesma mensagem repetida: nao modifica a chamada. Primeiro e segundo push
    da mesma chamada: consolidados pela chave (central_id, call_id).
    """
    cursor.execute(
        """
        INSERT INTO eventos_55pbx (central_id, call_id, hash_evento)
        VALUES (%s, %s, %s)
        ON CONFLICT (central_id, call_id, hash_evento) DO NOTHING
        RETURNING id
        """,
        (
            evento["central_id"],
            evento["call_id"],
            evento["hash_evento"],
        )
    )
    if cursor.fetchone() is None:
        return False

    cursor.execute(
        """
        INSERT INTO ligacoes_55pbx (
            central_id, call_id, ramal, telefone, fila, status_ligacao,
            tipo_ligacao, data_ligacao, duracao_segundos,
            tempo_falado_segundos, url_audio, transferencia_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (central_id, call_id) DO UPDATE SET
            ramal = COALESCE(EXCLUDED.ramal, ligacoes_55pbx.ramal),
            telefone = COALESCE(EXCLUDED.telefone, ligacoes_55pbx.telefone),
            fila = COALESCE(EXCLUDED.fila, ligacoes_55pbx.fila),
            status_ligacao = COALESCE(EXCLUDED.status_ligacao, ligacoes_55pbx.status_ligacao),
            tipo_ligacao = COALESCE(EXCLUDED.tipo_ligacao, ligacoes_55pbx.tipo_ligacao),
            data_ligacao = COALESCE(EXCLUDED.data_ligacao, ligacoes_55pbx.data_ligacao),
            duracao_segundos = GREATEST(
                COALESCE(EXCLUDED.duracao_segundos, 0),
                COALESCE(ligacoes_55pbx.duracao_segundos, 0)
            ),
            tempo_falado_segundos = GREATEST(
                COALESCE(EXCLUDED.tempo_falado_segundos, 0),
                COALESCE(ligacoes_55pbx.tempo_falado_segundos, 0)
            ),
            url_audio = COALESCE(EXCLUDED.url_audio, ligacoes_55pbx.url_audio),
            transferencia_id = COALESCE(
                EXCLUDED.transferencia_id, ligacoes_55pbx.transferencia_id
            ),
            atualizado_em = NOW()
        """,
        (
            evento["central_id"],
            evento["call_id"],
            evento["ramal"],
            evento["telefone"],
            evento["fila"],
            evento["status_ligacao"],
            evento["tipo_ligacao"],
            evento["data_ligacao"],
            evento["duracao_segundos"],
            evento["tempo_falado_segundos"],
            evento["url_audio"],
            evento["transferencia_id"],
        )
    )
    return True
