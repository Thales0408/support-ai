"""Protecoes conservadoras de dados pessoais em chamadas de suporte.

Nao e anonimização completa. Protege apenas credenciais identificadas com
alta confianca e nao altera CNPJ, e-mail, telefone ou nome do atendimento.
"""
import re

_CREDENTIAL = re.compile(
    r"(?P<label>\b(?:senha|password|token(?:\s+de\s+acesso)?|"
    r"api[_ -]?key|chave\s+(?:de\s+)?api)\b)"
    r"(?P<sep>\s*(?::|=|é|eh|foi|igual\s+a)\s*)"
    r"(?P<value>[^\s,;]{4,96})", flags=re.IGNORECASE,
)
_VERIFICATION = re.compile(
    r"(?P<label>\b(?:c[oó]digo\s+(?:de\s+)?(?:verifica[cç][aã]o|"
    r"autentica[cç][aã]o|acesso|2fa)|c[oó]digo\s+sms)\b)"
    r"(?P<sep>\s*(?:(?::|=|é|eh|foi|igual\s+a)\s*)?)"
    r"(?P<value>\d{4,8})\b", flags=re.IGNORECASE,
)
_CPF = re.compile(
    r"(?P<label>\bCPF\b)(?P<sep>\s*(?:(?::|=|é|eh|n[uú]mero)\s*)?)"
    r"(?P<value>\d{3}\.?\d{3}\.?\d{3}[-.]?\d{2})\b",
    flags=re.IGNORECASE,
)
_CARD = re.compile(
    r"(?P<label>\b(?:n[uú]mero\s+do\s+cart[aã]o|cart[aã]o)\b)"
    r"(?P<sep>\s*(?:(?::|=|é|eh|n[uú]mero)\s*)?)"
    r"(?P<value>(?:\d[ -]?){12,18}\d)\b", flags=re.IGNORECASE,
)
_BEARER = re.compile(r"\b(Bearer)\s+([A-Za-z0-9._~+/-]{12,})\b", re.IGNORECASE)
_INVALID_EXCEL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_EXCEL_FORMULA = re.compile(r"^[\s\x00-\x1f]*[=+@-]")


def _mask_if_secret(match):
    value = match.group("value")
    # Nao alterar falas como "a senha e invalida".
    if not (any(c.isdigit() for c in value) or
            (len(value) >= 16 and bool(re.search(r"[A-Z]", value)))):
        return match.group(0)
    return f"{match.group('label')}{match.group('sep')}[DADO PROTEGIDO]"


def mask_high_risk_secrets(text):
    """Mascara segredos obvios. Audio original ja foi recebido pela Groq."""
    if not isinstance(text, str) or not text:
        return text
    value = _BEARER.sub(r"\1 [DADO PROTEGIDO]", text)
    value = _CREDENTIAL.sub(_mask_if_secret, value)
    for rule in (_VERIFICATION, _CPF, _CARD):
        value = rule.sub(
            lambda m: f"{m.group('label')}{m.group('sep')}[DADO PROTEGIDO]",
            value,
        )
    return value


def safe_excel_value(value):
    """Texto de cliente deve ser celula literal, nunca formula XLSX."""
    if not isinstance(value, str):
        return value
    clean = _INVALID_EXCEL_XML.sub("", value)[:32767]
    # Telefones (+55...) e numeros negativos literais nao sao formulas.
    stripped = clean.strip()
    if re.fullmatch(r"\+\d[\d\s()\-]*", stripped) or re.fullmatch(
        r"-\d+(?:[.,]\d+)?", stripped
    ):
        return clean
    if _EXCEL_FORMULA.match(clean):
        return "'" + clean[:32766]
    return clean
