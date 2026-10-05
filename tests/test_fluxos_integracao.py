import io
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from openpyxl import load_workbook

import app
from services import ai


class FakeCursor:

    def __init__(self, state):

        self.state = state
        self.result = None

    def __enter__(self):

        return self

    def __exit__(self, exc_type, exc, tb):

        return False

    def execute(self, sql, params=None):

        params = params or ()
        sql_lower = " ".join(str(sql).lower().split())
        self.state["queries"].append((sql_lower, params))

        if (
            "select usuario, ativo, perfil, is_admin"
            in sql_lower
            and "from usuarios" in sql_lower
            and "where id = %s" in sql_lower
        ):

            usuario_id = int(params[0])
            user = next(
                (
                    item
                    for item in self.state["users_by_name"].values()
                    if item["id"] == usuario_id
                ),
                None
            )
            self.result = [
                (
                    user["usuario"],
                    user["ativo"],
                    user["perfil"],
                    user["is_admin"]
                )
            ] if user else []
            return

        if "from usuarios" in sql_lower and "where usuario = %s" in sql_lower:

            usuario = params[0]
            user = self.state["users_by_name"].get(usuario)
            self.result = [
                (
                    user["id"],
                    user["senha"],
                    user["is_admin"],
                    user["ativo"],
                    user["perfil"]
                )
            ] if user else []
            return

        if (
            "select count(*) from atendimentos"
            in sql_lower
            and "where usuario_id = %s" in sql_lower
        ):

            usuario_id = int(params[0])
            quantidade = len([
                atendimento
                for atendimento in self.state["atendimentos"].values()
                if atendimento["usuario_id"] == usuario_id
            ])
            self.result = [(quantidade,)]
            return

        if (
            "update usuarios set ativo = false"
            in sql_lower
            and "where id = %s" in sql_lower
        ):

            usuario_id = int(params[0])
            for user in self.state["users_by_name"].values():
                if user["id"] == usuario_id:
                    user["ativo"] = False
            self.result = []
            return

        if (
            "delete from usuarios"
            in sql_lower
            and "where id = %s" in sql_lower
        ):

            usuario_id = int(params[0])
            remover = next(
                (
                    nome
                    for nome, user
                    in self.state["users_by_name"].items()
                    if user["id"] == usuario_id
                ),
                None
            )
            if remover:
                del self.state["users_by_name"][remover]
            self.result = []
            return

        if "insert into atendimentos" in sql_lower and "returning id" in sql_lower:

            atendimento_id = self.state["next_atendimento_id"]
            self.state["next_atendimento_id"] += 1
            self.state["atendimentos"][atendimento_id] = {
                "id": atendimento_id,
                "usuario_id": params[0],
                "arquivo": params[1],
                "conteudo": params[2],
                "data": params[3],
                "status": params[4],
                "ticket_zendesk": params[5],
                "transcricao_completa": "",
                "duracao_segundos": 0,
                "chunks_total": 0,
                "chunks_falhos": 0,
                "chunks_ignorados": 0,
                "segundos_transcritos": 0,
                "custo_estimado_usd": 0,
                "resumo_editado": False,
                "sentimento_cliente": "neutro",
                "urgencia": "media",
                "categoria": "outro",
                "problema_principal": "",
                "tags": ""
            }
            self.result = [(atendimento_id,)]
            return

        if "select 1 from atendimentos" in sql_lower:

            atendimento_id = int(params[0])
            usuario_id = int(params[1])
            atendimento = self.state["atendimentos"].get(atendimento_id)
            self.result = [(1,)] if atendimento and atendimento["usuario_id"] == usuario_id else []
            return

        if (
            "select status, texto, provider_usado, modelo_usado, fallback_usado,"
            in sql_lower
            and "motivo_fallback, audio_processado" in sql_lower
            and "from transcricoes_chunks" in sql_lower
        ):

            key = (int(params[0]), int(params[2]))
            chunk = self.state["chunks"].get(key)
            self.result = [
                (
                    chunk["status"],
                    chunk.get("texto", ""),
                    chunk.get("provider_usado", ""),
                    chunk.get("modelo_usado", ""),
                    bool(chunk.get("fallback_usado")),
                    chunk.get("motivo_fallback", ""),
                    bool(chunk.get("audio_processado"))
                )
            ] if chunk else []
            return

        if (
            "select coalesce(sum(duracao_segundos), 0) from transcricoes_chunks"
            in sql_lower
            and "ordem <> %s" in sql_lower
        ):

            atendimento_id = int(params[0])
            usuario_id = int(params[1])
            ordem = int(params[2])
            segundos = sum(
                int(chunk.get("duracao_segundos") or 0)
                for chunk in self.state["chunks"].values()
                if chunk["atendimento_id"] == atendimento_id
                and chunk["usuario_id"] == usuario_id
                and chunk["status"] == "transcrito"
                and chunk["ordem"] != ordem
            )
            self.result = [(segundos,)]
            return

        if (
            "select coalesce(sum(tc.duracao_segundos), 0)"
            in sql_lower
            and "from transcricoes_chunks tc" in sql_lower
        ):

            usuario_id = int(params[0])
            atendimento_id = int(params[1])
            ordem = int(params[2])
            segundos = sum(
                int(chunk.get("duracao_segundos") or 0)
                for chunk in self.state["chunks"].values()
                if chunk["usuario_id"] == usuario_id
                and chunk["status"] == "transcrito"
                and not (
                    chunk["atendimento_id"] == atendimento_id
                    and chunk["ordem"] == ordem
                )
            )
            self.result = [(segundos,)]
            return

        if "select status, provider_usado, fallback_usado from transcricoes_chunks" in sql_lower:

            key = (int(params[0]), int(params[2]))
            chunk = self.state["chunks"].get(key)
            self.result = [
                (
                    chunk["status"],
                    chunk.get("provider_usado"),
                    chunk.get("fallback_usado")
                )
            ] if chunk else []
            return

        if "insert into transcricoes_chunks" in sql_lower and "'erro'" in sql_lower:

            key = (int(params[0]), int(params[2]))
            self.state["chunks"][key] = {
                "atendimento_id": int(params[0]),
                "usuario_id": int(params[1]),
                "ordem": int(params[2]),
                "texto": params[3],
                "status": "erro",
                "provider_tentado": params[5],
                "provider_usado": "",
                "fallback_usado": False,
                "duracao_segundos": 0,
                "transcricao_bruta": "",
                "transcricao_normalizada": "",
                "transcricao_limpa_para_resumo": ""
            }
            self.result = []
            return

        if "insert into transcricoes_chunks" in sql_lower:

            key = (int(params[0]), int(params[2]))
            self.state["chunks"][key] = {
                "atendimento_id": int(params[0]),
                "usuario_id": int(params[1]),
                "ordem": int(params[2]),
                "texto": params[3],
                "status": "transcrito",
                "provider_tentado": params[4],
                "provider_usado": params[5],
                "fallback_usado": bool(params[6]),
                "motivo_fallback": params[7],
                "duracao_segundos": int(params[8]),
                "transcricao_bruta": params[9],
                "transcricao_normalizada": params[10],
                "transcricao_limpa_para_resumo": params[11],
                "modelo_usado": params[12],
                "tamanho_audio_original": params[13],
                "tamanho_audio_processado": params[14],
                "audio_processado": bool(params[15])
            }
            self.result = []
            return

        if "update atendimentos set status = 'transcrevendo'" in sql_lower:

            atendimento = self.state["atendimentos"].get(int(params[0]))
            if atendimento:
                atendimento["status"] = "transcrevendo"
            self.result = []
            return

        if "update atendimentos set status = 'finalizando'" in sql_lower:

            atendimento = self.state["atendimentos"].get(int(params[0]))
            if atendimento:
                atendimento["status"] = "finalizando"
            self.result = []
            return

        if "select status, conteudo, chunks_total" in sql_lower and "for update" in sql_lower:

            atendimento = self.state["atendimentos"].get(int(params[0]))
            usuario_id = int(params[1])
            if not atendimento or atendimento["usuario_id"] != usuario_id:
                self.result = []
                return
            self.result = [(
                atendimento["status"],
                atendimento["conteudo"],
                atendimento["chunks_total"],
                atendimento["chunks_falhos"],
                atendimento["chunks_ignorados"],
                atendimento["segundos_transcritos"],
                atendimento["custo_estimado_usd"]
            )]
            return

        if "coalesce(transcricao_limpa_para_resumo, texto)" in sql_lower:

            atendimento_id = int(params[0])
            usuario_id = int(params[1])
            chunks = [
                chunk
                for chunk in self.state["chunks"].values()
                if chunk["atendimento_id"] == atendimento_id
                and chunk["usuario_id"] == usuario_id
            ]
            self.result = [
                (
                    chunk.get("transcricao_limpa_para_resumo") or chunk["texto"],
                    chunk["status"],
                    chunk.get("transcricao_bruta") or chunk["texto"]
                )
                for chunk in sorted(chunks, key=lambda item: item["ordem"])
            ]
            return

        if "select count(*), sum(" in sql_lower and "from transcricoes_chunks" in sql_lower:

            atendimento_id = int(params[0])
            usuario_id = int(params[1])
            chunks = [
                chunk
                for chunk in self.state["chunks"].values()
                if chunk["atendimento_id"] == atendimento_id
                and chunk["usuario_id"] == usuario_id
            ]
            self.result = [(
                len(chunks),
                len([chunk for chunk in chunks if chunk["status"] == "erro"])
            )]
            return

        if (
            "select coalesce(provider_tentado" in sql_lower
            and "coalesce(motivo_fallback" in sql_lower
        ):

            atendimento_id = int(params[3])
            usuario_id = int(params[4])
            chunks = [
                chunk
                for chunk in self.state["chunks"].values()
                if chunk["atendimento_id"] == atendimento_id
                and chunk["usuario_id"] == usuario_id
                and chunk["status"] == "transcrito"
            ]
            self.result = [
                (
                    chunk.get("provider_tentado") or "groq",
                    chunk.get("provider_usado") or "groq",
                    bool(chunk.get("fallback_usado")),
                    chunk.get("motivo_fallback") or "",
                    chunk["duracao_segundos"]
                )
                for chunk in sorted(chunks, key=lambda item: item["ordem"])
            ]
            return

        if "update atendimentos set conteudo = %s" in sql_lower and "status = 'finalizado'" in sql_lower:

            atendimento = self.state["atendimentos"].get(int(params[13]))
            if atendimento:
                atendimento.update({
                    "conteudo": params[0],
                    "transcricao_completa": params[1],
                    "status": "finalizado",
                    "duracao_segundos": params[2],
                    "chunks_total": params[3],
                    "chunks_falhos": params[4],
                    "chunks_ignorados": params[5],
                    "segundos_transcritos": params[6],
                    "custo_estimado_usd": params[7],
                    "sentimento_cliente": params[8],
                    "urgencia": params[9],
                    "categoria": params[10],
                    "problema_principal": params[11],
                    "tags": params[12]
                })
            self.result = []
            return

        if "insert into uso_eventos" in sql_lower:

            self.state["uso_eventos"].append(params)
            self.result = []
            return

        if "from atendimentos a left join usuarios u" in sql_lower and "limit 300" in sql_lower:

            rows = []
            for atendimento in sorted(
                self.state["atendimentos"].values(),
                key=lambda item: item["id"],
                reverse=True
            ):
                rows.append(self._linha_resultado(atendimento))
            self.result = rows
            return

        if "select id, usuario from usuarios" in sql_lower:

            self.result = [
                (user["id"], user["usuario"])
                for user in self.state["users_by_name"].values()
                if user["ativo"]
            ]
            return

        if "where a.id = %s and a.usuario_id = %s" in sql_lower:

            atendimento = self.state["atendimentos"].get(int(params[0]))
            if not atendimento or atendimento["usuario_id"] != int(params[1]):
                self.result = []
                return
            self.result = [self._linha_detalhe(atendimento)]
            return

        if "where a.id = %s" in sql_lower and "from atendimentos a" in sql_lower:

            atendimento = self.state["atendimentos"].get(int(params[0]))
            self.result = [self._linha_detalhe(atendimento)] if atendimento else []
            return

        if "from atendimentos a" in sql_lower and "order by a.id desc" in sql_lower:

            self.result = [
                self._linha_exportacao(atendimento)
                for atendimento in sorted(
                    self.state["atendimentos"].values(),
                    key=lambda item: item["id"],
                    reverse=True
                )
            ]
            return

        self.result = []

    def _usuario_nome(self, usuario_id):

        for user in self.state["users_by_name"].values():
            if user["id"] == usuario_id:
                return user["usuario"]
        return ""

    def _linha_resultado(self, atendimento):

        return (
            atendimento["id"],
            atendimento["arquivo"],
            atendimento["conteudo"],
            atendimento["data"],
            atendimento["status"],
            atendimento["chunks_total"],
            atendimento["chunks_falhos"],
            atendimento["duracao_segundos"],
            atendimento["transcricao_completa"],
            atendimento["ticket_zendesk"],
            atendimento["chunks_ignorados"],
            atendimento["segundos_transcritos"],
            atendimento["custo_estimado_usd"],
            atendimento["resumo_editado"],
            atendimento["sentimento_cliente"],
            atendimento["urgencia"],
            atendimento["categoria"],
            atendimento["problema_principal"],
            atendimento["tags"],
            self._usuario_nome(atendimento["usuario_id"]),
            atendimento["usuario_id"]
        )

    def _linha_detalhe(self, atendimento):

        return (
            atendimento["id"],
            atendimento["conteudo"],
            atendimento["transcricao_completa"],
            atendimento["data"],
            atendimento["status"],
            atendimento["duracao_segundos"],
            atendimento["chunks_total"],
            atendimento["chunks_falhos"],
            atendimento["ticket_zendesk"],
            atendimento["chunks_ignorados"],
            atendimento["segundos_transcritos"],
            atendimento["custo_estimado_usd"],
            atendimento["resumo_editado"],
            atendimento["sentimento_cliente"],
            atendimento["urgencia"],
            atendimento["categoria"],
            atendimento["problema_principal"],
            atendimento["tags"],
            self._usuario_nome(atendimento["usuario_id"])
        )

    def _linha_exportacao(self, atendimento):

        return (
            atendimento["data"],
            self._usuario_nome(atendimento["usuario_id"]),
            atendimento["ticket_zendesk"],
            atendimento["conteudo"],
            atendimento["transcricao_completa"],
            atendimento["chunks_total"],
            atendimento["chunks_falhos"],
            atendimento["chunks_ignorados"],
            atendimento["segundos_transcritos"],
            atendimento["custo_estimado_usd"],
            atendimento["sentimento_cliente"],
            atendimento["urgencia"],
            atendimento["categoria"],
            atendimento["problema_principal"],
            atendimento["tags"]
        )

    def fetchone(self):

        if not self.result:
            return None
        return self.result[0]

    def fetchall(self):

        return list(self.result or [])


class FakeConn:

    def __init__(self, state):

        self.state = state

    def __enter__(self):

        return self

    def __exit__(self, exc_type, exc, tb):

        return False

    def cursor(self):

        return FakeCursor(self.state)


class FluxosIntegracaoTest(unittest.TestCase):

    def setUp(self):

        app.app.config.update(
            TESTING=True,
            SESSION_COOKIE_SECURE=False
        )
        self.state = {
            "next_atendimento_id": 10,
            "users_by_name": {
                "analista": {
                    "id": 1,
                    "usuario": "analista",
                    "senha": "senha",
                    "is_admin": False,
                    "ativo": True,
                    "perfil": "analista"
                },
                "supervisor": {
                    "id": 2,
                    "usuario": "supervisor",
                    "senha": "senha",
                    "is_admin": False,
                    "ativo": True,
                    "perfil": "supervisor"
                },
                "admin": {
                    "id": 3,
                    "usuario": "admin",
                    "senha": "senha",
                    "is_admin": True,
                    "ativo": True,
                    "perfil": "admin_tecnico"
                }
            },
            "atendimentos": {
                99: {
                    "id": 99,
                    "usuario_id": 2,
                    "arquivo": "streaming",
                    "conteudo": app.resumo_zendesk_exato(
                        nome_empresa="Empresa X",
                        analista="supervisor",
                        descritivo="Atendimento finalizado."
                    ),
                    "data": "03/06/2026 09:00",
                    "status": "finalizado",
                    "ticket_zendesk": "ZD-99",
                    "transcricao_completa": "Cliente solicitou suporte.",
                    "duracao_segundos": 60,
                    "chunks_total": 1,
                    "chunks_falhos": 0,
                    "chunks_ignorados": 0,
                    "segundos_transcritos": 60,
                    "custo_estimado_usd": 0.05,
                    "resumo_editado": False,
                    "sentimento_cliente": "neutro",
                    "urgencia": "media",
                    "categoria": "fiscal",
                    "problema_principal": "NFS-e",
                    "tags": "fiscal,nfse"
                }
            },
            "chunks": {},
            "uso_eventos": [],
            "queries": []
        }

        self.patchers = [
            patch("app.conectar_banco", self.fake_connect),
            patch("app.login_bloqueado", return_value=False),
            patch("app.registrar_login_falho", return_value=None),
            patch("app.limpar_tentativas_login", return_value=None),
            patch("app.log_evento", return_value=None),
            patch("app.uso_diario_usuario", return_value={
                "chamadas": 0,
                "segundos": 0,
                "chunks": 0,
                "custo": 0
            }),
            patch("app.validar_limites_custo_resumo", return_value=None),
            patch("app.validar_limite_custo_fallback_transcricao", return_value=None)
        ]
        for patcher in self.patchers:
            patcher.start()

        self.client = app.app.test_client()

    def tearDown(self):

        for patcher in reversed(self.patchers):
            patcher.stop()

    @contextmanager
    def fake_connect(self):

        yield FakeConn(self.state)

    def set_session(self, usuario_id=1, perfil="analista", nome="analista"):

        with self.client.session_transaction() as sess:
            sess["usuario_id"] = usuario_id
            sess["perfil"] = perfil
            sess["is_admin"] = perfil == "admin_tecnico"
            sess["usuario_nome"] = nome
            sess["csrf_token"] = "csrf-teste"

    def post_json(self, url, payload=None, token_header="X-CSRFToken"):

        return self.client.post(
            url,
            json=payload or {},
            headers={token_header: "csrf-teste"}
        )

    def test_health_mostra_banco_e_ffmpeg(self):

        with patch(
            "app.shutil.which",
            return_value="/usr/bin/ffmpeg"
        ):

            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        dados = response.get_json()
        self.assertEqual(dados["status"], "ok")
        self.assertEqual(dados["database"], "ok")

        if app.AUDIO_PREPROCESS_ENABLED:

            self.assertEqual(dados["ffmpeg"], "ok")

        else:

            self.assertEqual(dados["ffmpeg"], "desativado")

    def test_login_logout_dashboard(self):

        with self.client.session_transaction() as sess:
            sess["csrf_token"] = "csrf-teste"

        response = self.client.post(
            "/login",
            data={
                "usuario": "analista",
                "senha": "senha",
                "csrf_token": "csrf-teste"
            },
            follow_redirects=False
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

        dashboard = self.client.get("/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"55PBX AI", dashboard.data)

        with self.client.session_transaction() as sess:
            token_logout = sess["csrf_token"]

        logout = self.client.post(
            "/logout",
            data={
                "csrf_token": token_logout
            },
            follow_redirects=False
        )
        self.assertEqual(logout.status_code, 302)
        self.assertIn("/login", logout.headers["Location"])

    def test_usuario_desativado_perde_sessao_imediatamente(self):

        self.set_session()
        self.state["users_by_name"]["analista"]["ativo"] = False

        response = self.client.get(
            "/resultados"
        )

        self.assertEqual(
            response.status_code,
            401
        )
        self.assertIn(
            "desativado",
            response.get_json()["erro"].lower()
        )

    def test_perfil_alterado_atualiza_sessao(self):

        self.set_session(
            usuario_id=1,
            perfil="analista",
            nome="analista"
        )
        self.state["users_by_name"]["analista"]["perfil"] = "supervisor"

        response = self.client.get(
            "/resultados"
        )

        self.assertEqual(
            response.status_code,
            200
        )
        self.assertTrue(
            response.get_json()["is_supervisor"]
        )

    def test_csrf_exigido_e_aceita_header_sem_hifen(self):

        self.set_session()

        sem_token = self.client.post("/atendimentos/iniciar", json={})
        self.assertEqual(sem_token.status_code, 403)

        com_token = self.post_json("/atendimentos/iniciar")
        self.assertEqual(com_token.status_code, 200)
        self.assertEqual(com_token.get_json()["status"], "gravando")

    def test_fluxo_gravacao_chunk_finalizacao_clickdesk(self):

        self.set_session(nome="analista")

        inicio = self.post_json(
            "/atendimentos/iniciar",
            {"ticket_clickdesk": "1052065"}
        )
        self.assertEqual(inicio.status_code, 200)
        atendimento_id = inicio.get_json()["atendimento_id"]
        self.assertEqual(
            self.state["atendimentos"][atendimento_id]["ticket_zendesk"],
            "1052065"
        )

        with patch("app.transcrever_chunk", return_value={
            "texto": (
                "Cliente informou CNPJ 08 633 889 mil contra 56 "
                "e suporte equipamentos arroba gmail ponto com"
            ),
            "provider_tentado": "groq",
            "provider_usado": "groq",
            "fallback_usado": False
        }):
            chunk = self.client.post(
                "/atendimentos/chunk",
                data={
                    "atendimento_id": str(atendimento_id),
                    "ordem": "0",
                    "duracao_segundos": "30",
                    "audio": (
                        io.BytesIO(b"a" * 2048),
                        "chunk.webm"
                    )
                },
                headers={"X-CSRFToken": "csrf-teste"},
                content_type="multipart/form-data"
            )

        self.assertEqual(chunk.status_code, 200)
        self.assertEqual(chunk.get_json()["status"], "chunk_transcrito")
        self.assertNotIn("E-mail identificado", chunk.get_json()["texto"])
        self.assertNotIn("CNPJ identificado", chunk.get_json()["texto"])

        with patch("app.analisar_com_ia", return_value={
            "resumo_zendesk": app.resumo_zendesk_exato(
                nome_empresa="Empresa Teste",
                cnpj="Possivel CNPJ informado: 08.633.889/0001-56 - confirmar com cliente",
                email="suporteequipamentos@gmail.com",
                analista="analista",
                descritivo="Cliente solicitou analise de cadastro fiscal."
            ),
            "sentimento_cliente": "neutro",
            "urgencia": "media",
            "categoria": "fiscal",
            "problema_principal": "Cadastro fiscal",
            "tags": "fiscal,cadastro"
        }) as mock_ia:
            finalizar = self.post_json(
                "/atendimentos/finalizar",
                {
                    "atendimento_id": atendimento_id,
                    "duracao_segundos": 30,
                    "chunks_total": 1,
                    "chunks_falhos": 0,
                    "chunks_ignorados": 0,
                    "segundos_transcritos": 30
                }
            )

        self.assertEqual(finalizar.status_code, 200)
        resposta = finalizar.get_json()
        self.assertEqual(resposta["status"], "finalizado")
        self.assertIn("Nome da empresa:", resposta["resultado"])
        self.assertIn("E-mail Solicitante: suporteequipamentos@gmail.com", resposta["resultado"])
        self.assertEqual(mock_ia.call_count, 1)
        self.assertNotIn(
            "Possível CNPJ informado",
            mock_ia.call_args.args[0]
        )
        self.assertIn(
            "08 633 889 0001 56",
            mock_ia.call_args.args[0]
        )
        self.assertEqual(
            mock_ia.call_args.kwargs["entidades_extraidas"]["cnpj"],
            "Possível CNPJ informado: 08.633.889/0001-56 — confirmar com cliente"
        )
        self.assertEqual(
            mock_ia.call_args.kwargs["entidades_extraidas"]["email"],
            "suporteequipamentos@gmail.com"
        )
        tipos_uso = [
            evento[2]
            for evento in self.state["uso_eventos"]
        ]
        self.assertIn("transcricao", tipos_uso)
        self.assertIn("resumo", tipos_uso)

        with patch("app.analisar_com_ia") as mock_ia_repetida:
            repetida = self.post_json(
                "/atendimentos/finalizar",
                {"atendimento_id": atendimento_id}
            )

        self.assertEqual(repetida.status_code, 200)
        self.assertTrue(repetida.get_json()["reutilizado"])
        self.assertEqual(mock_ia_repetida.call_count, 0)

    def test_chunk_repetido_reutiliza_sem_retranscrever(self):

        self.set_session()
        inicio = self.post_json("/atendimentos/iniciar")
        atendimento_id = inicio.get_json()["atendimento_id"]

        resultado_transcricao = {
            "texto": "Cliente pediu ajuda.",
            "provider_tentado": "groq",
            "provider_usado": "groq",
            "fallback_usado": False,
            "motivo_fallback": "",
            "modelo_usado": "whisper-large-v3-turbo",
            "audio_processado": False,
            "tamanho_audio_original": 2048,
            "tamanho_audio_processado": 2048,
            "tempo_transcricao_segundos": 0.1,
            "erro_preprocessamento": "",
            "audio_original_path": "",
            "audio_processado_path": ""
        }

        with patch(
            "app.transcrever_chunk",
            return_value=resultado_transcricao
        ) as mock_transcrever:

            primeiro = self.client.post(
                "/atendimentos/chunk",
                data={
                    "atendimento_id": str(atendimento_id),
                    "ordem": "0",
                    "duracao_segundos": "30",
                    "audio": (
                        io.BytesIO(b"a" * 2048),
                        "chunk.webm"
                    )
                },
                headers={"X-CSRFToken": "csrf-teste"},
                content_type="multipart/form-data"
            )

            segundo = self.client.post(
                "/atendimentos/chunk",
                data={
                    "atendimento_id": str(atendimento_id),
                    "ordem": "0",
                    "duracao_segundos": "30",
                    "audio": (
                        io.BytesIO(b"b" * 2048),
                        "chunk.webm"
                    )
                },
                headers={"X-CSRFToken": "csrf-teste"},
                content_type="multipart/form-data"
            )

        self.assertEqual(primeiro.status_code, 200)
        self.assertEqual(segundo.status_code, 200)
        self.assertTrue(segundo.get_json()["reutilizado"])
        self.assertEqual(mock_transcrever.call_count, 1)

    def test_chunk_grande_e_rejeitado(self):

        self.set_session()
        inicio = self.post_json("/atendimentos/iniciar")
        atendimento_id = inicio.get_json()["atendimento_id"]

        with patch(
            "app.tamanho_arquivo_upload",
            return_value=(app.MAX_CHUNK_UPLOAD_MB * 1024 * 1024) + 1
        ):

            response = self.client.post(
                "/atendimentos/chunk",
                data={
                    "atendimento_id": str(atendimento_id),
                    "ordem": "0",
                    "duracao_segundos": "30",
                    "audio": (
                        io.BytesIO(b"a" * 2048),
                        "chunk.webm"
                    )
                },
                headers={"X-CSRFToken": "csrf-teste"},
                content_type="multipart/form-data"
            )

        self.assertEqual(response.status_code, 413)
        self.assertIn("excede", response.get_json()["erro"].lower())

    def test_health_degradado_retorna_503(self):

        with patch(
            "app.shutil.which",
            return_value=None
        ):

            response = self.client.get("/health")

        if app.AUDIO_PREPROCESS_ENABLED:

            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.get_json()["status"],
                "degradado"
            )

    def test_headers_de_seguranca_presentes(self):

        response = self.client.get("/health")

        self.assertEqual(
            response.headers.get("X-Content-Type-Options"),
            "nosniff"
        )
        self.assertEqual(
            response.headers.get("X-Frame-Options"),
            "DENY"
        )
        self.assertIn(
            "frame-ancestors 'none'",
            response.headers.get("Content-Security-Policy", "")
        )
        self.assertTrue(
            response.headers.get("X-Request-ID")
        )
        self.assertIn(
            "no-store",
            response.headers.get("Cache-Control", "")
        )

    def test_chunk_bloqueia_novo_audio_apos_limite_da_chamada(self):

        self.set_session()
        inicio = self.post_json("/atendimentos/iniciar")
        atendimento_id = inicio.get_json()["atendimento_id"]
        self.state["chunks"][(atendimento_id, 0)] = {
            "atendimento_id": atendimento_id,
            "usuario_id": 1,
            "ordem": 0,
            "texto": "trecho anterior",
            "status": "transcrito",
            "provider_usado": "groq",
            "fallback_usado": False,
            "duracao_segundos": app.MAX_CALL_DURATION_MINUTES * 60
        }

        response = self.client.post(
            "/atendimentos/chunk",
            data={
                "atendimento_id": str(atendimento_id),
                "ordem": "1",
                "duracao_segundos": "1",
                "audio": (
                    io.BytesIO(b"a" * 2048),
                    "chunk.webm"
                )
            },
            headers={"X-CSRFToken": "csrf-teste"},
            content_type="multipart/form-data"
        )

        self.assertEqual(response.status_code, 403)
        dados = response.get_json()
        self.assertTrue(dados["limite"])
        self.assertTrue(dados["deve_parar_gravacao"])
        self.assertEqual(
            dados["tipo"],
            "limite_duracao_atendimento"
        )

    def test_finalizacao_contabiliza_fallback_de_qualidade(self):

        self.set_session()
        inicio = self.post_json("/atendimentos/iniciar")
        atendimento_id = inicio.get_json()["atendimento_id"]
        self.state["chunks"][(atendimento_id, 0)] = {
            "atendimento_id": atendimento_id,
            "usuario_id": 1,
            "ordem": 0,
            "texto": "Cliente informou problema fiscal.",
            "status": "transcrito",
            "provider_tentado": "groq",
            "provider_usado": "openai",
            "fallback_usado": True,
            "motivo_fallback": "baixa_qualidade",
            "duracao_segundos": 45,
            "transcricao_bruta": "Cliente informou problema fiscal.",
            "transcricao_normalizada": "Cliente informou problema fiscal.",
            "transcricao_limpa_para_resumo": "Cliente informou problema fiscal."
        }

        with patch("app.analisar_com_ia", return_value={
            "resumo_zendesk": app.resumo_zendesk_exato(
                analista="analista",
                descritivo="Cliente informou problema fiscal."
            ),
            "sentimento_cliente": "neutro",
            "urgencia": "media",
            "categoria": "fiscal",
            "problema_principal": "Problema fiscal",
            "tags": "fiscal"
        }):

            response = self.post_json(
                "/atendimentos/finalizar",
                {
                    "atendimento_id": atendimento_id,
                    "duracao_segundos": 45,
                    "chunks_total": 1,
                    "segundos_transcritos": 45
                }
            )

        self.assertEqual(response.status_code, 200)
        esperado = (
            app.estimar_custo_transcricao(45, "openai")
            + app.estimar_custo_transcricao(45, "groq")
            + app.estimar_custo_atendimento(0, True)
        )
        self.assertAlmostEqual(
            float(self.state["atendimentos"][atendimento_id]["custo_estimado_usd"]),
            round(esperado, 4),
            places=4
        )

    def test_excluir_usuario_com_historico_apenas_desativa(self):

        self.set_session(
            usuario_id=3,
            perfil="admin_tecnico",
            nome="admin"
        )

        with patch("app.registrar_auditoria") as mock_auditoria:

            response = self.client.post(
                "/admin/usuarios/2/excluir",
                data={
                    "csrf_token": "csrf-teste"
                },
                follow_redirects=False
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            self.state["users_by_name"]["supervisor"]["ativo"]
        )
        self.assertIn(99, self.state["atendimentos"])
        mock_auditoria.assert_called_once()

    def test_permissoes_custos_dashboard_detalhe_exportacao(self):

        self.set_session(usuario_id=1, perfil="analista", nome="analista")
        detalhe_analista = self.client.get("/atendimentos/99")
        self.assertEqual(detalhe_analista.status_code, 404)

        self.set_session(usuario_id=2, perfil="supervisor", nome="supervisor")
        resultados_supervisor = self.client.get("/resultados")
        self.assertEqual(resultados_supervisor.status_code, 200)
        dados_supervisor = resultados_supervisor.get_json()
        self.assertTrue(dados_supervisor["is_supervisor"])
        self.assertFalse(dados_supervisor["mostrar_custo"])
        self.assertNotIn("usd_brl_rate", dados_supervisor)
        self.assertNotIn("custo_estimado_usd", dados_supervisor["resultados"][0])

        detalhe_supervisor = self.client.get("/atendimentos/99")
        self.assertEqual(detalhe_supervisor.status_code, 200)
        self.assertNotIn("custo_estimado_usd", detalhe_supervisor.get_json())

        export_supervisor = self.client.get("/exportar")
        self.assertEqual(export_supervisor.status_code, 200)
        workbook_supervisor = load_workbook(
            io.BytesIO(export_supervisor.data)
        )
        cabecalho_supervisor = [
            cell.value
            for cell in workbook_supervisor.active[1]
        ]
        self.assertNotIn("Custo estimado USD", cabecalho_supervisor)
        self.assertNotIn("Custo estimado BRL", cabecalho_supervisor)
        workbook_supervisor.close()

        self.set_session(usuario_id=3, perfil="admin_tecnico", nome="admin")
        resultados_admin = self.client.get("/resultados")
        self.assertEqual(resultados_admin.status_code, 200)
        dados_admin = resultados_admin.get_json()
        self.assertTrue(dados_admin["mostrar_custo"])
        self.assertIn("usd_brl_rate", dados_admin)
        self.assertIn("custo_estimado_usd", dados_admin["resultados"][0])

        detalhe_admin = self.client.get("/atendimentos/99")
        self.assertEqual(detalhe_admin.status_code, 200)
        self.assertIn("custo_estimado_usd", detalhe_admin.get_json())

        export_admin = self.client.get("/exportar")
        self.assertEqual(export_admin.status_code, 200)
        workbook_admin = load_workbook(
            io.BytesIO(export_admin.data)
        )
        cabecalho_admin = [
            cell.value
            for cell in workbook_admin.active[1]
        ]
        self.assertIn("Custo estimado USD", cabecalho_admin)
        self.assertIn("Custo estimado BRL", cabecalho_admin)
        workbook_admin.close()

    def test_finalizacao_aceita_duracao_acima_do_limite(self):

        self.set_session()
        self.state["atendimentos"][10] = {
            "id": 10,
            "usuario_id": 1,
            "arquivo": "streaming",
            "conteudo": "Transcricao em andamento...",
            "data": "03/06/2026 09:00",
            "status": "transcrevendo",
            "ticket_zendesk": "",
            "transcricao_completa": "",
            "duracao_segundos": 0,
            "chunks_total": 0,
            "chunks_falhos": 0,
            "chunks_ignorados": 0,
            "segundos_transcritos": 0,
            "custo_estimado_usd": 0,
            "resumo_editado": False,
            "sentimento_cliente": "neutro",
            "urgencia": "media",
            "categoria": "outro",
            "problema_principal": "",
            "tags": ""
        }

        response = self.post_json(
            "/atendimentos/finalizar",
            {
                "atendimento_id": 10,
                "duracao_segundos": app.MAX_CALL_DURATION_MINUTES * 60 + 1
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.state["atendimentos"][10]["status"], "finalizado")
        self.assertEqual(
            self.state["atendimentos"][10]["duracao_segundos"],
            app.MAX_CALL_DURATION_MINUTES * 60 + 1
        )

    def test_recuperar_finalizacao_sem_duracao_reutiliza_chunks(self):

        self.set_session()
        inicio = self.post_json("/atendimentos/iniciar")
        atendimento_id = inicio.get_json()["atendimento_id"]
        self.state["atendimentos"][atendimento_id]["status"] = "transcrevendo"
        self.state["chunks"][(atendimento_id, 0)] = {
            "atendimento_id": atendimento_id,
            "usuario_id": 1,
            "ordem": 0,
            "texto": "Cliente pediu ajuda com o sistema.",
            "status": "transcrito",
            "provider_usado": "groq",
            "duracao_segundos": 45
        }

        self.set_session(usuario_id=2, perfil="supervisor", nome="supervisor")
        negado = self.post_json(
            "/atendimentos/finalizar", {"atendimento_id": atendimento_id}
        )
        self.assertEqual(negado.status_code, 404)

        self.set_session()
        with patch("app.analisar_com_ia", return_value={
            "resumo_zendesk": app.resumo_zendesk_exato(
                analista="analista", descritivo="Cliente pediu ajuda com o sistema."
            ),
            "sentimento_cliente": "neutro",
            "urgencia": "baixa",
            "categoria": "outro",
            "problema_principal": "Ajuda com o sistema",
            "tags": ""
        }) as mock_ia:
            resposta = self.post_json(
                "/atendimentos/finalizar", {"atendimento_id": atendimento_id}
            )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.state["atendimentos"][atendimento_id]["status"], "finalizado")
        self.assertEqual(self.state["atendimentos"][atendimento_id]["duracao_segundos"], 45)
        self.assertEqual(mock_ia.call_count, 1)


class FallbackTranscricaoTest(unittest.TestCase):

    def test_fallback_por_baixa_qualidade(self):

        chamadas = []

        def fake_transcrever_bytes(provider, audio_bytes, nome, mime, modelo=None):

            chamadas.append((provider, audio_bytes, nome))

            if provider == "groq":

                return (
                    "TRISHUL DRISHUIZSORVAGENCIA "
                    "Transcreva somente as palavras audiveis"
                )

            return "Cliente informou que a nota fiscal esta cancelada."

        arquivo = io.BytesIO(b"audio")
        arquivo.filename = "chunk.webm"
        arquivo.mimetype = "audio/webm"

        with patch("services.ai.TRANSCRIBE_PROVIDER", "groq"), \
                patch("services.ai.TRANSCRIBE_FALLBACK_PROVIDER", "openai"), \
                patch("services.ai.transcrever_bytes", fake_transcrever_bytes), \
                patch("services.ai.preprocessar_audio_transcricao", return_value={
                    "audio_bytes": b"processado",
                    "nome": "chunk.webm",
                    "mime": "audio/webm",
                    "audio_processado": False,
                    "audio_original_path": "",
                    "audio_processado_path": "",
                    "tamanho_audio_original": 5,
                    "tamanho_audio_processado": 5,
                    "tempo_preprocessamento_segundos": 0,
                    "erro_preprocessamento": ""
                }):

            resultado = ai.transcrever_chunk(arquivo)

        self.assertEqual(chamadas[0][0], "groq")
        self.assertEqual(chamadas[1][0], "openai")
        self.assertEqual(chamadas[0][1], b"processado")
        self.assertEqual(chamadas[1][1], b"audio")
        self.assertEqual(chamadas[1][2], "chunk.webm")
        self.assertEqual(resultado["provider_usado"], "openai")
        self.assertTrue(resultado["fallback_usado"])
        self.assertEqual(resultado["motivo_fallback"], "baixa_qualidade")
        self.assertIn("nota fiscal", resultado["texto"].lower())


    def test_fallback_groq_para_openai(self):

        chamadas = []

        def fake_transcrever_bytes(provider, audio_bytes, nome, mime, modelo=None):

            chamadas.append(provider)
            if provider == "groq":
                raise RuntimeError("rate limit reached")
            return "texto via openai"

        arquivo = io.BytesIO(b"audio")
        arquivo.filename = "chunk.webm"
        arquivo.mimetype = "audio/webm"

        with patch("services.ai.TRANSCRIBE_PROVIDER", "groq"), \
                patch("services.ai.TRANSCRIBE_FALLBACK_PROVIDER", "openai"), \
                patch("services.ai.transcrever_bytes", fake_transcrever_bytes):
            resultado = ai.transcrever_chunk(arquivo)

        self.assertEqual(chamadas, ["groq", "openai"])
        self.assertEqual(resultado["provider_tentado"], "groq")
        self.assertEqual(resultado["provider_usado"], "openai")
        self.assertTrue(resultado["fallback_usado"])
        self.assertEqual(resultado["texto"], "texto via openai")


if __name__ == "__main__":

    unittest.main()
