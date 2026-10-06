import unittest
from pathlib import Path

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
        self.assertIn('id="capture-shell"', html)
        self.assertIn('id="recording-timer"', html)
        self.assertIn('id="capture-state-label"', html)
        self.assertIn('class="account-menu"', html)
        self.assertIn('name="csrf-token"', html)
        self.assertIn('/static/theme.css', html)
        self.assertIn('/static/theme.js', html)
        self.assertIn('/static/favicon.svg', html)
        self.assertNotIn('class="analyst-table"', html)
        self.assertIn('class="main-table"', html)
        self.assertIn('data-theme-toggle', html)

        html_supervisor = self.render_dashboard("supervisor")
        self.assertIn('class="analyst-table"', html_supervisor)

    def test_custo_so_para_admin_tecnico(self):
        for perfil in ("analista", "supervisor"):
            html = self.render_dashboard(perfil)
            self.assertNotIn(">Custo estimado</span>", html)
            self.assertNotIn("Usuários", html)

        html = self.render_dashboard("admin_tecnico")
        self.assertIn("Custo estimado", html)
        self.assertIn("Usuários", html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener"', html)

    def test_gravacao_desacopla_captura_da_finalizacao(self):
        script = Path("static/popup.js").read_text(encoding="utf-8")

        self.assertIn("const finalizacoesPendentes = new Map()", script)
        self.assertIn("atendimentoIdDoUpload", script)
        self.assertIn("concluirFinalizacaoEmSegundoPlano", script)
        self.assertIn("resetarEstadoCaptura()", script)
        self.assertIn(
            "você já pode iniciar outra gravação",
            script
        )

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
        self.assertIn('data-theme-toggle', login)
        self.assertIn('data-theme-toggle', admin)
        self.assertIn('/static/theme.js', login)
        self.assertIn('/static/theme.js', admin)
        self.assertIn('/static/favicon.svg', login)
        self.assertIn('/static/favicon.svg', admin)
        self.assertIn("Support AI", login)
        self.assertIn("Equipe e acessos", admin)
        self.assertIn('class="user-list"', admin)
        self.assertIn("Gerencie usuários sem poluir", admin)
        self.assertNotIn("<style>", login)
        self.assertNotIn("<style>", admin)


if __name__ == "__main__":
    unittest.main()
