import unittest
from unittest.mock import patch

from services import database


class FakeConnection:

    def __init__(self):

        self.closed = 0
        self.commits = 0
        self.rollbacks = 0

    def commit(self):

        self.commits += 1

    def rollback(self):

        self.rollbacks += 1


class FakePool:

    def __init__(self, conn):

        self.conn = conn
        self.returned = []

    def getconn(self):

        return self.conn

    def putconn(self, conn, close=False):

        self.returned.append((conn, close))


class DatabasePoolTest(unittest.TestCase):

    def test_contexto_commita_e_devolve_conexao(self):

        conn = FakeConnection()
        pool = FakePool(conn)

        with patch(
            "services.database.obter_pool",
            return_value=pool
        ):

            with database.conectar_banco() as atual:

                self.assertIs(atual, conn)

        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.rollbacks, 0)
        self.assertEqual(len(pool.returned), 1)
        self.assertFalse(pool.returned[0][1])

    def test_contexto_faz_rollback_em_erro(self):

        conn = FakeConnection()
        pool = FakePool(conn)

        with patch(
            "services.database.obter_pool",
            return_value=pool
        ):

            with self.assertRaises(ValueError):

                with database.conectar_banco():

                    raise ValueError("falha")

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(len(pool.returned), 1)


if __name__ == "__main__":

    unittest.main()
