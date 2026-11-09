import importlib.util
import io
import os
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


class FakeCursor:
    def __init__(self):
        self.queries = []
        self.answers = [(3, 2), (5,)]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, sql, params=None):
        self.queries.append(sql.strip())

    def fetchone(self):
        return self.answers.pop(0)


class FakeConnection:
    def __init__(self, cursor):
        self.value = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def cursor(self):
        return self.value


class RetentionGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "scripts" / "lgpd_retention.py"
        spec = importlib.util.spec_from_file_location("lgpd_retention_under_test", path)
        cls.module = importlib.util.module_from_spec(spec)
        stub = types.SimpleNamespace(conectar_banco=lambda: None)
        with patch.dict(sys.modules, {"services.database": stub}):
            spec.loader.exec_module(cls.module)

    def test_dry_run_only_reads(self):
        cursor = FakeCursor()
        with patch.object(self.module, "conectar_banco",
                          return_value=FakeConnection(cursor)):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(self.module.main(["--days", "365"]), 0)
        self.assertEqual(len(cursor.queries), 2)
        self.assertTrue(all(sql.upper().startswith("SELECT") for sql in cursor.queries))

    def test_apply_blocked_without_two_unlocks(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(self.module, "conectar_banco",
                              side_effect=AssertionError("Never connect")):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        self.module.main([
                            "--days", "365", "--apply",
                            "--confirm", "EXCLUIR_TRANSCRICOES"
                        ])


if __name__ == "__main__":
    unittest.main()
