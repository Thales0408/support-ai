import unittest
from unittest.mock import patch

import app


class EntidadesFaladasTest(unittest.TestCase):

    POSSIVEL = "Possível CNPJ informado: "
    CONFIRMAR = " — confirmar com cliente"

    def test_cnpj_falado_mil_contra_por_extenso(self):

        self.assertEqual(
            app.extrair_possivel_cnpj(
                "CNPJ zero oito seis tres tres oito oito nove mil contra cinquenta e seis"
            ),
            self.POSSIVEL + "08.633.889/0001-56" + self.CONFIRMAR
        )

    def test_cnpj_falado_mil_contra_numerico(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("CNPJ 08 633 889 mil contra 56"),
            self.POSSIVEL + "08.633.889/0001-56" + self.CONFIRMAR
        )

    def test_cnpj_falado_dois_mil_contra(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("CNPJ 08 633 889 dois mil contra 37"),
            self.POSSIVEL + "08.633.889/0002-37" + self.CONFIRMAR
        )

    def test_cnpj_falado_cinco_mil_contra(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("CNPJ 08 633 889 cinco mil contra 80"),
            self.POSSIVEL + "08.633.889/0005-80" + self.CONFIRMAR
        )

    def test_cnpj_falado_filial_com_dv_invalido_e_rejeitado(self):

        self.assertEqual(
            app.extrair_possivel_cnpj("CNPJ 08 633 889 dois mil contra 56"),
            ""
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

        dvs = {
            1: "00",
            2: "83",
            3: "64",
            4: "45",
            5: "26",
            6: "07",
            7: "98",
            8: "79",
            9: "50"
        }

        for numero, dv in dvs.items():

            with self.subTest(numero=numero):

                self.assertEqual(
                    app.extrair_possivel_cnpj(
                        f"CNPJ 09-114-915-{numero}000-{dv}"
                    ),
                    self.POSSIVEL + f"09.114.915/000{numero}-{dv}" + self.CONFIRMAR
                )

    def test_cnpj_possivel_invalido_tambem_e_rejeitado(self):

        self.assertEqual(
            app.normalizar_cnpj(
                "Possível CNPJ informado: 3, 486, 1000 — confirmar com cliente",
                permitir_possivel=True
            ),
            ""
        )

    def test_cnpj_deformado_curto_nao_vai_para_documentacao(self):

        self.assertEqual(
            app.extrair_possivel_cnpj(
                "Cliente informou o CNPJ da empresa 1,005-911730 para cadastro"
            ),
            ""
        )

    def test_cnpj_grotesco_curto_nao_vai_para_documentacao(self):

        self.assertEqual(
            app.extrair_possivel_cnpj(
                "CNPJ 3, 486, 1000 contra 76"
            ),
            ""
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

    def test_analista_logado_e_fonte_primaria(self):

        entidades = app.extrair_entidades_transcricao(
            "Meu nome e Thales, falo do suporte. Qual o CNPJ da empresa?",
            analista_nome="Thales"
        )

        self.assertEqual(entidades["analista_nome"], "Thales")
        self.assertEqual(entidades["cliente_nome"], "")

    def test_cliente_meu_nome_com_contexto_de_solicitante(self):

        casos = [
            (
                "Bom dia, meu nome e Nicolas. Eu queria tirar uma duvida.",
                "Nicolas"
            ),
            (
                "Oi, meu nome e Ana Paula. Preciso de ajuda com uma nota.",
                "Ana Paula"
            ),
            (
                "Ola, aqui e Ivanete. Estou com um problema no financeiro.",
                "Ivanete"
            ),
        ]

        for texto, esperado in casos:

            with self.subTest(texto=texto):

                entidades = app.extrair_entidades_transcricao(
                    texto,
                    analista_nome="admin"
                )

                self.assertEqual(
                    entidades["cliente_nome"],
                    esperado
                )

    def test_apresentacao_inicial_de_suporte_continua_ambigua(self):

        entidades = app.extrair_entidades_transcricao(
            (
                "Bom dia, meu nome e Thales. "
                "Como posso te ajudar?"
            ),
            analista_nome="admin"
        )

        self.assertEqual(
            entidades["cliente_nome"],
            ""
        )

    def test_cliente_meu_nome_com_contexto_de_solicitante(self):

        casos = [
            (
                "Bom dia, meu nome e Nicolas. Eu queria tirar uma duvida.",
                "Nicolas"
            ),
            (
                "Oi, meu nome e Ana Paula. Preciso de ajuda com uma nota.",
                "Ana Paula"
            ),
            (
                "Ola, aqui e Ivanete. Estou com um problema no financeiro.",
                "Ivanete"
            ),
        ]

        for texto, esperado in casos:

            with self.subTest(texto=texto):

                entidades = app.extrair_entidades_transcricao(
                    texto,
                    analista_nome="admin"
                )

                self.assertEqual(
                    entidades["cliente_nome"],
                    esperado
                )

    def test_apresentacao_inicial_de_suporte_continua_ambigua(self):

        entidades = app.extrair_entidades_transcricao(
            (
                "Bom dia, meu nome e Thales. "
                "Como posso te ajudar?"
            ),
            analista_nome="admin"
        )

        self.assertEqual(
            entidades["cliente_nome"],
            ""
        )

    def test_cliente_thiago_com_voce_acentuado(self):

        entidades = app.extrair_entidades_transcricao(
            (
                "Bom dia, aqui você fala com o Thiago. "
                "Eu faço parte da empresa que presta assessoria contábil "
                "e eu queria tirar uma dúvida."
            ),
            analista_nome="teste"
        )

        self.assertEqual(
            entidades["cliente_nome"],
            "Thiago"
        )

    def test_extrair_secao_vazia_nao_engole_proximo_rotulo(self):

        texto = (
            "Nome da empresa: Sonho de Indústria\n\n"
            "Empresa/Loja:\n\n"
            "CNPJ:\n\n"
            "Nome do Cliente: Thiago\n\n"
            "Telefone de contato:\n\n"
            "E-mail Solicitante:\n\n"
            "Analista responsável: teste"
        )

        self.assertEqual(
            app.extrair_secao_texto(
                texto,
                ["CNPJ"]
            ),
            ""
        )
        self.assertEqual(
            app.extrair_secao_texto(
                texto,
                ["Nome do Cliente"]
            ),
            "Thiago"
        )
        self.assertEqual(
            app.extrair_secao_texto(
                texto,
                ["Telefone de contato"]
            ),
            ""
        )

    def test_cliente_thiago_em_apresentacao_de_solicitante(self):

        entidades = app.extrair_entidades_transcricao(
            (
                "Bom dia, aqui voce fala com o Thiago. "
                "Eu faco parte da empresa que presta assessoria contabil "
                "e queria tirar uma duvida."
            ),
            analista_nome="teste"
        )

        self.assertEqual(
            entidades["cliente_nome"],
            "Thiago"
        )

    def test_aqui_voce_fala_com_sem_contexto_de_solicitante_e_ambiguo(self):

        entidades = app.extrair_entidades_transcricao(
            (
                "Bom dia, aqui voce fala com o Thiago. "
                "Como posso te ajudar?"
            ),
            analista_nome="teste"
        )

        self.assertEqual(
            entidades["cliente_nome"],
            ""
        )

    def test_limpeza_remove_ctranscreva_e_tristario(self):

        texto = app.limpar_transcricao_para_resumo(
            (
                "Cliente explicou o problema. "
                "TRISTARIO Ctranscreva somente as palavras audiveis. "
                "Depois informou que a nota existe."
            )
        )

        self.assertNotIn("TRISTARIO", texto.upper())
        self.assertNotIn("CTRANSCREVA", texto.upper())
        self.assertIn(
            "Cliente explicou o problema",
            texto
        )
        self.assertIn(
            "Depois informou que a nota existe",
            texto
        )

    def test_cliente_luiz_e_empresa_la_gourmet_na_apresentacao(self):

        entidades = app.extrair_entidades_transcricao(
            (
                "Boa tarde, meu nome e Luiz Torelli, tudo bem? "
                "Estou falando de Sao Paulo, da La Gourmet. "
                "Eu estou fazendo a conciliacao de um banco."
            ),
            analista_nome="admin"
        )

        self.assertEqual(entidades["cliente_nome"], "Luiz Torelli")
        self.assertEqual(
            app.normalizar_para_comparacao(entidades["empresa"]),
            "la gourmet"
        )

    def test_meu_nome_sem_contexto_de_empresa_continua_ambiguo(self):

        entidades = app.extrair_entidades_transcricao(
            "Boa tarde, meu nome e Thales. Como posso te ajudar?",
            analista_nome="admin"
        )

        self.assertEqual(entidades["cliente_nome"], "")

    def test_cliente_barbara_apos_oi_boa_tarde(self):

        entidades = app.extrair_entidades_transcricao(
            (
                "Suporte tecnico, boa tarde, com quem eu falo? "
                "Oi, boa tarde, aqui e Barbara, Medecientific, tudo bem?"
            ),
            analista_nome="admin"
        )

        self.assertEqual(entidades["cliente_nome"], "Barbara")

    def test_cnpj_32694456_000_contra_95(self):

        self.assertEqual(
            app.extrair_possivel_cnpj(
                "Me fala o seu CNPJ, por gentileza. "
                "E o 32694 456.000 contra 95."
            ),
            self.POSSIVEL + "32.694.456/0001-95" + self.CONFIRMAR
        )

    def test_cliente_joao_pedro_apos_pergunta_com_quem_falo(self):

        entidades = app.extrair_entidades_transcricao(
            (
                "Boa tarde, com quem eu falo? Boa tarde, meu nome e Joao Pedro, "
                "por gentileza do que eu to falando. Tudo bem, Joao Pedro."
            ),
            analista_nome="admin"
        )

        self.assertEqual(entidades["cliente_nome"], "Joao Pedro")

    def test_pergunta_generica_de_nome_nao_define_cliente(self):

        entidades = app.extrair_entidades_transcricao(
            "Qual e seu nome? Meu nome e Thales. Como posso te ajudar?",
            analista_nome="admin"
        )

        self.assertEqual(entidades["cliente_nome"], "")

    def test_nome_alucinado_trisk_e_rejeitado(self):

        self.assertEqual(
            app.nome_participante_confiavel(
                "Entao TRISK",
                "admin"
            ),
            ""
        )

    def test_rotulo_cliente_nao_vira_nome(self):

        entidades = app.extrair_entidades_transcricao(
            "Cliente: preciso de ajuda com a nota fiscal.",
            analista_nome="admin"
        )

        self.assertEqual(entidades["cliente_nome"], "")

    def test_cnpj_possivel_sem_acento_preserva_baixa_confianca(self):

        self.assertEqual(
            app.normalizar_cnpj(
                "Possivel CNPJ informado: 43.405.954/0001-97 - confirmar com cliente",
                permitir_possivel=True
            ),
            self.POSSIVEL + "43.405.954/0001-97" + self.CONFIRMAR
        )

    def test_empresa_remove_confirmacao_apos_interrogacao(self):

        casos = [
            (
                "Qual que e o nome da empresa? Mundo das Tintas? Isso.",
                "mundo das tintas"
            ),
            (
                "Qual que e o nome da empresa? Cia das Placas? Isso mesmo.",
                "cia das placas"
            ),
            (
                "Qual que e o nome da empresa? DEN Informatica? Essa mesma.",
                "den informatica"
            ),
        ]

        for texto, esperado in casos:

            with self.subTest(texto=texto):

                entidades = app.extrair_entidades_transcricao(
                    texto,
                    analista_nome="admin"
                )

                self.assertEqual(
                    app.normalizar_para_comparacao(
                        entidades["empresa"]
                    ),
                    esperado
                )

    def test_empresa_rejeita_resposta_conversacional(self):

        for texto in [
            "Qual que e o nome da empresa? diversos.",
            "Qual que e o nome da empresa? esse valor que ta ai pra voce.",
            "Qual que e o nome da empresa? a gente nao vai poder.",
            "A empresa e do Simples Nacional.",
        ]:

            with self.subTest(texto=texto):

                entidades = app.extrair_entidades_transcricao(
                    texto,
                    analista_nome="admin"
                )

                self.assertEqual(
                    entidades["empresa"],
                    ""
                )

    def test_empresa_remove_ruido_apos_nome(self):

        entidades = app.extrair_entidades_transcricao(
            (
                "Qual que e o nome da empresa? "
                "MIMEG Comercio e Servicos TRISTAO PROSO PORTO."
            ),
            analista_nome="admin"
        )

        self.assertEqual(
            app.normalizar_para_comparacao(
                entidades["empresa"]
            ),
            "mimeg comercio e servicos"
        )

    def test_empresa_chama_gigante_e_importes(self):

        entidades = app.extrair_entidades_transcricao(
            "A empresa chama gigante e importes? E isso ai.",
            analista_nome="admin"
        )

        self.assertEqual(
            app.normalizar_para_comparacao(entidades["empresa"]),
            "gigante e importes"
        )

    def test_frase_generica_com_empresa_nao_vira_nome(self):

        entidades = app.extrair_entidades_transcricao(
            "A empresa nao consegue importar os produtos.",
            analista_nome="admin"
        )

        self.assertEqual(entidades["empresa"], "")

    def test_empresa_cpa_digital_por_pergunta_explicita(self):

        entidades = app.extrair_entidades_transcricao(
            "Qual que e o nome da empresa? E CPA digital.",
            analista_nome="admin"
        )

        self.assertEqual(
            app.normalizar_para_comparacao(entidades["empresa"]),
            "cpa digital"
        )

    def test_limpeza_remove_transcreva_em_portugues_curto(self):

        texto = app.limpar_vazamento_prompt_transcricao(
            "Transcreva em português. Cliente pediu ajuda."
        )

        self.assertEqual(texto, "Cliente pediu ajuda")

    def test_limpeza_remove_contexto_hallucinado(self):

        texto = app.limpar_vazamento_prompt_transcricao(
            "Contexto, cumprimento de suporte tecnico para o seu. "
            "Cliente pediu ajuda."
        )

        self.assertEqual(texto, "Cliente pediu ajuda")

    def test_limpeza_remove_vazamento_transcreva_somente_palavras(self):

        texto = app.limpar_vazamento_prompt_transcricao(
            "Transcreva somente as palavras audiveis. Cliente pediu suporte."
        )

        self.assertEqual(texto, "Cliente pediu suporte")

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

    def test_ia_nao_inventa_campos_estruturados_sem_evidencia(self):

        class Mensagem:
            content = (
                '{"nome_empresa":"Empresa Inventada","empresa_loja":"Loja X",'
                '"cnpj":"43.405.954/0001-97","nome_cliente":"Maria",'
                '"telefone":"11999999999","email":"inventado@example.com",'
                '"analista_responsavel":"admin",'
                '"descritivo":"Cliente solicitou orientacao sobre tributacao.",'
                '"sentimento_cliente":"neutro","urgencia":"media",'
                '"categoria":"fiscal","problema_principal":"Tributacao",'
                '"tags":["fiscal"]}'
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
                "Cliente solicitou orientacao sobre tributacao.",
                "admin",
                entidades_extraidas={
                    "analista_nome": "admin",
                    "cliente_nome": "",
                    "empresa": "",
                    "cnpj": "",
                    "email": "",
                    "telefone": ""
                }
            )

        resumo = analise["resumo_zendesk"]
        self.assertIn("Nome da empresa: \n", resumo)
        self.assertIn("Empresa/Loja: \n", resumo)
        self.assertIn("CNPJ: \n", resumo)
        self.assertIn("Nome do Cliente: \n", resumo)
        self.assertIn("Telefone de contato: \n", resumo)
        self.assertIn("E-mail Solicitante: \n", resumo)
        self.assertIn(
            "Cliente solicitou orientacao sobre tributacao.",
            resumo
        )

    def test_limpar_transcricao_para_resumo_remove_ruidos_sem_remover_numeros(self):

        texto = app.limpar_transcricao_para_resumo(
            "nis, nis, nis. alo alo alo. CNPJ 1,005-911730. fiscal fiscal fiscal"
        )

        self.assertIn("1,005-911730", texto)
        self.assertNotIn("nis, nis", texto.lower())
        self.assertIn("fiscal", texto.lower())


if __name__ == "__main__":

    unittest.main()
