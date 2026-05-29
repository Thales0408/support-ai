# Support AI / 55PBX AI

Aplicacao Flask usada para apoiar atendimentos de suporte ERP feitos via 55PBX/Zendesk.

O sistema captura audio da aba do 55PBX e do microfone, envia trechos de audio para o backend, transcreve com OpenAI, gera um resumo em formato pronto para Zendesk e salva o historico no Supabase/PostgreSQL.

## Links

- Repositorio: `https://github.com/Thales0408/support-ai.git`
- App Railway: `https://web-production-b7e8f.up.railway.app/`
- Health check: `https://web-production-b7e8f.up.railway.app/health`

## Stack

- Python 3.11
- Flask
- Waitress
- Supabase/PostgreSQL via Connection Pooler
- OpenAI `gpt-4o-mini-transcribe`
- OpenAI `gpt-4.1-mini`
- HTML, CSS e JavaScript
- MediaRecorder, `getDisplayMedia`, `getUserMedia` e `AudioContext`

## Arquivos principais

- `app.py`: backend Flask, rotas, banco, OpenAI e exportacao.
- `static/popup.js`: captura de audio, chunks, status da gravacao e finalizacao.
- `templates/index.html`: dashboard operacional.
- `templates/login.html`: tela de login.
- `templates/admin.html`: administracao de usuarios.
- `requirements.txt`: dependencias Python.
- `Procfile`: comando usado pelo Railway.
- `runtime.txt`: versao do Python no Railway.
- `.env.example`: modelo de variaveis locais.

## Funcionalidades atuais

- Login com usuarios cadastrados.
- Senhas com hash seguro via `werkzeug.security`.
- Migracao automatica de senha antiga em texto puro no primeiro login.
- Usuario admin inicial.
- Tela admin para criar, editar login, redefinir senha, ativar/desativar e excluir usuarios.
- Analistas veem apenas seus proprios atendimentos.
- Admin pode ver "Meus atendimentos" ou "Todos os analistas".
- Gravacao de audio da aba + microfone.
- Envio de chunks de 30 segundos.
- Transcricao por chunk.
- Finalizacao com resumo pronto para Zendesk.
- Registro de falhas de chunks sem derrubar o atendimento inteiro.
- Dashboard com filtros, busca, status, TMA, grafico, alertas, copiar resumo e detalhes.
- Exportacao para Excel.

## Variaveis de ambiente

Use `.env.example` como base.

Obrigatorias:

```text
OPENAI_API_KEY=
DB_HOST=
DB_PORT=
DB_NAME=
DB_USER=
DB_PASSWORD=
TRANSCRIBE_MODEL=
SUMMARY_MODEL=
SECRET_KEY=
```

O backend prioriza `DB_*` quando `DB_PASSWORD` esta configurada. `DATABASE_URL` pode existir no Railway, mas nao deve ser a fonte principal enquanto o pooler do Supabase estiver configurado via `DB_*`.

## Rodando localmente

```bash
git clone https://github.com/Thales0408/support-ai.git
cd support-ai
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Depois abra:

```text
http://127.0.0.1:8080/health
```

## Primeiro acesso

Por padrao:

```text
usuario: admin
senha: 123456
```

Configure `ADMIN_USUARIO` e `ADMIN_SENHA` nas variaveis de ambiente para mudar o usuario inicial em novos ambientes.

Depois do login como admin:

1. Acesse `Usuarios`.
2. Crie os analistas.
3. Entregue usuario e senha inicial para cada analista.
4. Deixe "Administrador" desmarcado para analistas comuns.

## Documentacao complementar

- `GUIA_MIGRACAO.md`: passo a passo para migrar/continuar em outro computador.
- `GUIA_OPERACAO.md`: como usar o sistema no dia a dia.
- `CONTINUIDADE_CODEX.md`: estado tecnico atual para outra conta Codex continuar.
