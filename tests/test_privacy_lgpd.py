import unittest

from services.privacy import mask_high_risk_secrets, safe_excel_value


class PrivacyTests(unittest.TestCase):
    def test_mask_credential_only_if_high_confidence(self):
        self.assertEqual(
            mask_high_risk_secrets("senha: abc12345"),
            "senha: [DADO PROTEGIDO]"
        )
        self.assertEqual(
            mask_high_risk_secrets("A senha está inválida"),
            "A senha está inválida"
        )

    def test_mask_otp_cpf_but_keep_cnpj(self):
        self.assertIn(
            "[DADO PROTEGIDO]",
            mask_high_risk_secrets("código de verificação é 123456")
        )
        text = "CPF 123.456.789-09 e CNPJ 36.751.298/0001-19"
        out = mask_high_risk_secrets(text)
        self.assertIn("CPF [DADO PROTEGIDO]", out)
        self.assertIn("36.751.298/0001-19", out)

    def test_contact_fields_preserved(self):
        text = "Joao, fone +5531999887766, email contato@empresa.com"
        self.assertEqual(mask_high_risk_secrets(text), text)

    def test_excel_formula_injection(self):
        for value in ("=HYPERLINK(\"https://example.com\")",
                      " +SUM(1,2)", "@SUM(1,2)", "-1+2"):
            self.assertTrue(safe_excel_value(value).startswith("'"))

    def test_excel_normal_and_xml_unsafe(self):
        self.assertEqual(safe_excel_value("Empresa LTDA"), "Empresa LTDA")
        self.assertEqual(safe_excel_value(12.35), 12.35)
        self.assertEqual(safe_excel_value("a\x00b"), "ab")
        self.assertLessEqual(
            len(safe_excel_value("=" + "a" * 40000)), 32767
        )


if __name__ == "__main__":
    unittest.main()
