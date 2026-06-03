import unittest

import app


class EntidadesFaladasTest(unittest.TestCase):

    POSSIVEL = "Possível CNPJ informado: "
    CONFIRMAR = " — confirmar com cliente"

    def test_cnpj_falado_mil_contra_por_extenso(self):

        self.assertEqual(
            app.extrair_possivel_cnpj(
                "zero oito seis tres tres oito oito nove mil contra cinquenta e seis"
            ),
            self.POSSIVEL + "08.633.889/0001-56" + self.CONFIRMAR
        )

    def test_cnpj_falado_mil_contra_numerico(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("08 633 889 mil contra 56"),
            self.POSSIVEL + "08.633.889/0001-56" + self.CONFIRMAR
        )

    def test_cnpj_falado_dois_mil_contra(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("08 633 889 dois mil contra 56"),
            self.POSSIVEL + "08.633.889/0002-56" + self.CONFIRMAR
        )

    def test_cnpj_falado_cinco_mil_contra(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("08 633 889 cinco mil contra 56"),
            self.POSSIVEL + "08.633.889/0005-56" + self.CONFIRMAR
        )

    def test_cnpj_falado_mil_de_re(self):

        self.assertEqual(
            app.extrair_possivel_cnpj(
                "CNPJ oito seis tres tres oito oito nove mil de re cinquenta e seis"
            ),
            self.POSSIVEL + "08.633.889/0001-56" + self.CONFIRMAR
        )

    def test_cnpj_formatado_por_barra_traco(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("CNPJ 08 633 889 barra 0001 traco 56"),
            "08.633.889/0001-56"
        )

    def test_cnpj_numericamente_1000_vira_0001_em_contexto(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("CNPJ 09-114-915-1000-00"),
            self.POSSIVEL + "09.114.915/0001-00" + self.CONFIRMAR
        )

    def test_cnpj_numericamente_blocos_1000_a_9000(self):

        for numero in range(1, 10):

            with self.subTest(numero=numero):

                self.assertEqual(
                    app.extrair_possivel_cnpj(
                        f"CNPJ 09-114-915-{numero}000-00"
                    ),
                    self.POSSIVEL + f"09.114.915/000{numero}-00" + self.CONFIRMAR
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
                "suporte traco loja arroba hotmail ponto com"
            ),
            "suporte-loja@hotmail.com"
        )

    def test_normalizar_entidades_faladas_nao_injeta_rotulos(self):

        texto = app.normalizar_entidades_faladas(
            "Cliente informou CNPJ 08 633 889 mil contra 56 "
            "e suporte equipamentos arroba gmail ponto com"
        )

        self.assertNotIn("CNPJ identificado", texto)
        self.assertNotIn("Possível CNPJ informado", texto)
        self.assertNotIn("E-mail identificado", texto)

    def test_extrair_entidades_transcricao_separadamente(self):

        entidades = app.extrair_entidades_transcricao(
            "Cliente informou CNPJ 08 633 889 mil contra 56 "
            "e suporte equipamentos arroba gmail ponto com"
        )

        self.assertEqual(
            entidades["cnpj"],
            self.POSSIVEL + "08.633.889/0001-56" + self.CONFIRMAR
        )
        self.assertEqual(
            entidades["email"],
            "suporteequipamentos@gmail.com"
        )


if __name__ == "__main__":

    unittest.main()
