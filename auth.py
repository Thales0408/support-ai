from flask import session
from werkzeug.security import check_password_hash


def usuario_logado():

    return session.get("usuario_id")


def usuario_admin():

    return bool(session.get("is_admin"))


def perfil_usuario():

    return session.get(
        "perfil",
        "admin_tecnico" if usuario_admin() else "analista"
    )


def usuario_supervisor():

    return perfil_usuario() in [
        "supervisor",
        "admin_tecnico"
    ]


def usuario_admin_tecnico():

    return perfil_usuario() == "admin_tecnico"


def perfil_valido(perfil):

    return perfil in [
        "analista",
        "supervisor",
        "admin_tecnico"
    ]


def senha_valida(senha_digitada, senha_salva):

    if not senha_salva:

        return False

    try:

        return check_password_hash(senha_salva, senha_digitada)

    except Exception:

        return False


def senha_esta_em_hash(senha_salva):

    return (
        senha_salva.startswith("scrypt:")
        or senha_salva.startswith("pbkdf2:")
    )
