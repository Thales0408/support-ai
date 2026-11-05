import unittest
from contextlib import contextmanager
from unittest.mock import patch

from services.integracao_55pbx import (
    normalizar_evento,
    registrar_evento,
    token_autorizado,
)


EVENTO = {
    "central_id": "1000",
    "branch_mask": 5000,
    "call_id": "1479477009.5199",
    "call_date": "2026-11-05 09:00:00",
    "call_number": "988536541",
    "call_area_code": "11",
    "call_country_code": "55",
    "call_queue": "Suporte",
}


class CursorSimulado:
    def __init__(self):
        self.hashes = set()
        self.comandos = []
        self.ultimo_insert = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.comandos.append((sql, params))
        if "INSERT INTO eventos_55pbx" in sql:
            chave = tuple(params)
            self.ultimo_insert = chave not in self.hashes
            self.hashes.add(chave)

    def fetchone(self):
        return (1,) if self.ultimo_insert else None


class ConexaoSimulada:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class Integracao55PBXTest(unittest.TestCase):
    def test_token_deve_ser_configurado_e_valido(self):
        self.assertFalse(token_autorizado("", "segredo"))
        self.assertFalse(token_autorizado("segredo", ""))
        self.assertFalse(token_autorizado("outro", "segredo"))
        self.assertTrue(token_autorizado("segredo", "segredo"))

    def test_normaliza_chamada_e_telefone(self):
        e = normalizar_evento(EVENTO)
        self.assertEqual(e["central_id"], "1000")
        self.assertEqual(e["call_id"], "1479477009.5199")
        self.assertEqual(e["telefone"], "5511988536541")
        self.assertEqual(e["ramal"], "5000")
        self.assertIsNone(e["url_audio"])

    def test_payload_precisa_ser_um_objeto_e_ter_ids(self):
        for dado in ([], {}, {"call_id": "x"}, {"central_id": "1000"}):
            with self.subTest(dado=dado), self.assertRaises(ValueError):
                normalizar_evento(dado)

    def test_url_audio_deve_ser_https_sem_credentials(self):
        for url in (
            "http://example.test/a.wav",
            "https://u:p@example.test/a.wav",
            "file:///etc/passwd",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalizar_evento({**EVENTO, "call_url_audio": url})

    def test_eventos_inicio_fim_duplicados_sao_idempotentes(self):
        cursor = CursorSimulado()
        inicial = normalizar_evento(EVENTO)
        final = normalizar_evento({
            **EVENTO,
            "call_duration": 175,
            "call_time": 150,
            "call_url_audio": "https://sip1.55pbx.com/audio.wav",
        })
        self.assertTrue(registrar_evento(cursor, inicial))
        self.assertFalse(registrar_evento(cursor, inicial))
        self.assertTrue(registrar_evento(cursor, final))
        self.assertFalse(registrar_evento(cursor, final))
        self.assertEqual(
            len([c for c, _ in cursor.comandos if "INSERT INTO ligacoes_55pbx" in c]),
            2
        )
        self.assertNotEqual(inicial["hash_evento"], final["hash_evento"])

    def test_webhook_inativo_sem_token(self):
        import app

        with patch.object(app, "PBX55_WEBHOOK_TOKEN", None):
            resposta = app.app.test_client().post(
                "/integracoes/55pbx/webhook", json=EVENTO
            )
        self.assertEqual(resposta.status_code, 503)

    def test_webhook_rejeita_token_invalido_antes_do_banco(self):
        import app

        with patch.object(app, "PBX55_WEBHOOK_TOKEN", "token-secreto"):
            with patch.object(app, "conectar_banco") as banco:
                resposta = app.app.test_client().post(
                    "/integracoes/55pbx/webhook",
                    json=EVENTO,
                    headers={"token": "token-incorreto"},
                )
        self.assertEqual(resposta.status_code, 401)
        banco.assert_not_called()

    def test_webhook_aceita_post_e_put_sem_cookie_csrf(self):
        import app

        for metodo in ("post", "put"):
            cursor = CursorSimulado()

            @contextmanager
            def conexao():
                yield ConexaoSimulada(cursor)

            with self.subTest(metodo=metodo):
                with patch.object(app, "PBX55_WEBHOOK_TOKEN", "token-secreto"):
                    with patch.object(app, "conectar_banco", conexao):
                        resposta = getattr(app.app.test_client(), metodo)(
                            "/integracoes/55pbx/webhook",
                            json=EVENTO,
                            headers={"token": "token-secreto"},
                        )
                self.assertEqual(resposta.status_code, 200)
                self.assertFalse(resposta.get_json()["duplicado"])

    def test_webhook_rejeita_json_grande(self):
        import app

        with patch.object(app, "PBX55_WEBHOOK_TOKEN", "token-secreto"):
            resposta = app.app.test_client().post(
                "/integracoes/55pbx/webhook",
                data=b'{"extra":"' + b"x" * 65536 + b'"}',
                content_type="application/json",
                headers={"token": "token-secreto"},
            )
        self.assertEqual(resposta.status_code, 413)


if __name__ == "__main__":
    unittest.main()
