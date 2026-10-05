import unittest

from flask import render_template

import app


class LayoutTests(unittest.TestCase):

    def render_dashboard(self, perfil):
        with app.app.test_request_context("/"):
            return render_template(
                "index.html",
                is_admin=perfil == "admin_tecnico",
                is_supervisor=perfil in ("supervisor", "admin_tecnico"),
                mostrar_custo=perfil == "admin_tecnico",
                chunk_seconds=45,
                perfil=perfil,
            )

    def test_dashboard_controles_e_csrf(self):
        html = self.render_dashboard("analista")
        self.assertIn('class="dashboard-page"', html)
        self.assertIn('id="ticket-clickdesk"', html)
        self.assertIn('id="start"', html)
        self.assertIn('id="status"', html)
        self.assertIn('name="csrf-token"', html)
        self.assertIn('/static/theme.css', html)

    def test_custo_so_para_admin_tecnico(self):
        for perfil in ("analista", "supervisor"):
            html = self.render_dashboard(perfil)
            self.assertNotIn(">Custo estimado</span>", html)
            self.assertNotIn("Usuarios</a>", html)

        html = self.render_dashboard("admin_tecnico")
        self.assertIn("Custo estimado", html)
        self.assertIn("Usuarios</a>", html)

    def test_login_e_admin_usam_tema(self):
        with app.app.test_request_context("/"):
            login = render_template("login.html", erro=None)
            admin = render_template(
                "admin.html", mensagem=None, erro=None,
                usuarios=[], usuario_id=1,
            )
        self.assertIn('class="login-page"', login)
        self.assertIn('class="admin-page"', admin)
        self.assertIn('/static/theme.css', login)
        self.assertIn('/static/theme.css', admin)


if __name__ == "__main__":
    unittest.main()
