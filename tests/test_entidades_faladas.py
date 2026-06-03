import unittest
from unittest.mock import patch

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

    def test_cnpj_1000_avalia_variante_0001_baixa_confianca(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("CNPJ 43-405-954-1000-97"),
            self.POSSIVEL + "43.405.954/0001-97" + self.CONFIRMAR
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

    def test_cnpj_deformado_curto_fica_como_possivel_bruto(self):

        self.assertEqual(
            app.extrair_possivel_cnpj(
                "Cliente informou o CNPJ da empresa 1,005-911730 para cadastro"
            ),
            self.POSSIVEL + "1,005-911730" + self.CONFIRMAR
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

    def test_extrair_analista_nao_preenche_cliente_por_saudacao(self):

        entidades = app.extrair_entidades_transcricao(
            "Meu nome e Thales, falo do suporte. Qual o CNPJ da empresa?"
        )

        self.assertEqual(entidades["analista_nome"], "Thales")
        self.assertEqual(entidades["cliente_nome"], "")

    def test_analisar_com_ia_remove_cliente_igual_analista(self):

        class Mensagem:
            content = (
                '{"nome_empresa":"","empresa_loja":"","cnpj":"",'
                '"nome_cliente":"Thales","telefone":"","email":"",'
                '"analista_responsavel":"Thales",'
                '"descritivo":"Solicitado acesso remoto.",'
                '"sentimento_cliente":"neutro","urgencia":"media",'
                '"categoria":"acesso","problema_principal":"Acesso remoto",'
                '"tags":["acesso"]}'
            )

        class Choice:
            message = Mensagem()

        class Resposta:
            choices = [Choice()]

        class Completions:
            def create(self, **kwargs):
                return Resposta()

        class Chat:
            completions = Completions()

        class Cliente:
            chat = Chat()

        with patch("app.cliente_resumo", return_value=Cliente()):
            analise = app.analisar_com_ia(
                "Meu nome e Thales. Cliente pediu acesso remoto.",
                "Thales",
                entidades_extraidas={
                    "analista_nome": "Thales",
                    "cliente_nome": "",
                    "empresa": "",
                    "cnpj": "",
                    "email": "",
                    "telefone": ""
                }
            )

        self.assertIn("Analista responsável: Thales", analise["resumo_zendesk"])
        self.assertIn("Nome do Cliente: \n", analise["resumo_zendesk"])

    def test_limpar_transcricao_para_resumo_remove_ruidos_sem_remover_numeros(self):

        texto = app.limpar_transcricao_para_resumo(
            "nis, nis, nis. alo alo alo. CNPJ 1,005-911730. fiscal fiscal fiscal"
        )

        self.assertIn("1,005-911730", texto)
        self.assertNotIn("nis, nis", texto.lower())
        self.assertIn("fiscal", texto.lower())


if __name__ == "__main__":

    unittest.main()
