"""Regressoes: tentativas sem audio nao podem consumir 30 chamadas reais."""

from contextlib import contextmanager
from unittest import TestCase
from unittest.mock import patch

import app
from services.usage import uso_diario_usuario


class FakeCursor:
    def __init__(self, result=(1,)):
        self.result = result
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return self.result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeDatabase:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def cursor(self):
        return self.cursor_obj


class TentativasSemAudioTests(TestCase):
    def test_cota_nao_contabiliza_abandonadas_sem_audio(self):
        class UsageCursor(FakeCursor):
            def fetchone(self):
                if len(self.queries) == 1:
                    return (0, 0, 0)
                return (0,)

        cursor = UsageCursor()
        actual = uso_diario_usuario(cursor, 1, atendimento_id=270)
        self.assertEqual(actual["chamadas"], 0)
        sql, params = cursor.queries[0]
        self.assertIn("COUNT(*) FILTER", sql)
        self.assertIn("a.status = 'gravando'", sql)
        self.assertIn("NOW() - INTERVAL '2 minutes'", sql)
        self.assertIn("NOT EXISTS", sql)
        self.assertIn("a.status <> 'falha_captura'", sql)
        self.assertIn("AND a.id <> %s", sql)
        self.assertEqual(params, (1, 270))

    def _post_cancel(self, result=(1,), atendimento_id=270):
        cursor = FakeCursor(result)

        @contextmanager
        def connection():
            yield FakeDatabase(cursor)

        with patch.object(app, "conectar_banco", connection):
            with patch.object(app, "usuario_logado", return_value=1):
                client = app.app.test_client()
                with client.session_transaction() as session:
                    session["csrf_token"] = "token-de-teste"
                response = client.post(
                    "/atendimentos/cancelar-sem-audio",
                    json={"atendimento_id": atendimento_id},
                    headers={"X-CSRF-Token": "token-de-teste"}
                )
        return response, cursor

    def test_cancelamento_apenas_sem_audio_proprio(self):
        response, cursor = self._post_cancel()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "falha_captura")
        sql, params = cursor.queries[0]
        self.assertIn("WHERE a.id = %s", sql)
        self.assertIn("AND a.usuario_id = %s", sql)
        self.assertIn("AND a.status = 'gravando'", sql)
        self.assertIn("AND NOT EXISTS", sql)
        self.assertEqual(params, (270, 1))

    def test_cancelamento_recusa_registro_com_audio(self):
        response, _ = self._post_cancel(result=None)
        self.assertEqual(response.status_code, 409)

    def test_cancelamento_recusa_identificador_invalido(self):
        response, cursor = self._post_cancel(atendimento_id="nao-id")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(cursor.queries)
