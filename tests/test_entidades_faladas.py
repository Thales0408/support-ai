import unittest

import app


class EntidadesFaladasTest(unittest.TestCase):

    def test_cnpj_falado_mil_contra_por_extenso(self):

        self.assertEqual(
            app.extrair_possivel_cnpj(
                "zero oito seis três três oito oito nove mil contra cinquenta e seis"
            ),
            "Possível CNPJ informado: 08.633.889/0001-56 — confirmar com cliente"
        )

    def test_cnpj_falado_mil_contra_numerico(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("08 633 889 mil contra 56"),
            "Possível CNPJ informado: 08.633.889/0001-56 — confirmar com cliente"
        )

    def test_cnpj_falado_dois_mil_contra(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("08 633 889 dois mil contra 56"),
            "Possível CNPJ informado: 08.633.889/0002-56 — confirmar com cliente"
        )

    def test_cnpj_falado_cinco_mil_contra(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("08 633 889 cinco mil contra 56"),
            "Possível CNPJ informado: 08.633.889/0005-56 — confirmar com cliente"
        )

    def test_cnpj_falado_mil_de_re(self):

        self.assertEqual(
            app.extrair_possivel_cnpj(
                "CNPJ oito seis três três oito oito nove mil de ré cinquenta e seis"
            ),
            "Possível CNPJ informado: 08.633.889/0001-56 — confirmar com cliente"
        )

    def test_cnpj_formatado_por_barra_traco(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("CNPJ 08 633 889 barra 0001 traço 56"),
            "08.633.889/0001-56"
        )

    def test_email_gmail_falado(self):

        self.assertEqual(
            app.normalizar_email_falado(
                "suporte equipamentos arroba gmail ponto com"
            ),
            "suporteequipamentos@gmail.com"
        )

    def test_email_outlook_falado(self):

        self.assertEqual(
            app.normalizar_email_falado(
                "financeiro ponto loja arroba outlook ponto com"
            ),
            "financeiro.loja@outlook.com"
        )

    def test_email_empresa_com_br_falado(self):

        self.assertEqual(
            app.normalizar_email_falado(
                "contato underline fiscal arroba empresa ponto com ponto br"
            ),
            "contato_fiscal@empresa.com.br"
        )

    def test_email_hotmail_falado(self):

        self.assertEqual(
            app.normalizar_email_falado(
                "suporte traço loja arroba hotmail ponto com"
            ),
            "suporte-loja@hotmail.com"
        )

    def test_normalizar_entidades_faladas_enriquece_transcricao(self):

        texto = app.normalizar_entidades_faladas(
            "Cliente informou CNPJ 08 633 889 mil contra 56 "
            "e suporte equipamentos arroba gmail ponto com"
        )

        self.assertIn(
            "CNPJ identificado: Possível CNPJ informado: 08.633.889/0001-56 — confirmar com cliente",
            texto
        )
        self.assertIn(
            "E-mail identificado: suporteequipamentos@gmail.com",
            texto
        )


if __name__ == "__main__":

    unittest.main()
