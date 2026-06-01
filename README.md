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
- Groq `whisper-large-v3-turbo` para transcricao de baixo custo
- OpenAI `gpt-4.1-mini`
- HTML, CSS e JavaScript
- MediaRecorder, `getDisplayMedia`, `getUserMedia` e `AudioContext`

## Arquivos principais

- `app.py`: backend Flask e rotas principais.
- `services/ai.py`: clientes e chamadas de IA/transcricao.
- `services/database.py`: conexao e inicializacao do banco.
- `services/usage.py`: limites diarios, custo e eventos de uso.
- `auth.py`: helpers de autenticacao e perfis.
- `config.py`: leitura e validacao de variaveis de ambiente.
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
- Perfis de acesso: analista, supervisor e admin tecnico.
- Tela admin tecnico para criar, editar login/perfil, redefinir senha, ativar/desativar e excluir usuarios.
- Analistas veem apenas seus proprios atendimentos.
- Supervisor e admin tecnico podem ver "Meus atendimentos" ou "Todos os analistas".
- Gravacao de audio da aba + microfone.
- Envio de chunks de 30 segundos.
- Transcricao por chunk.
- Finalizacao com resumo pronto para Zendesk.
- Registro de falhas de chunks sem derrubar o atendimento inteiro.
- Dashboard com filtros, busca, status, TMA, grafico, alertas, copiar resumo e detalhes.
- Exportacao para Excel.
- Pausa de gravacao e deteccao automatica de silencio para reduzir custo.
- Campo de ticket Zendesk por atendimento.
- Resumo Zendesk curto, tags internas para busca, classificacao operacional, reprocessamento de resumo e troca de senha pelo usuario.
- Estimativa de custo por atendimento e no dashboard.

## Variaveis de ambiente

Use `.env.example` como base.

Obrigatorias:

```text
OPENAI_API_KEY=
GROQ_API_KEY=
GROQ_BASE_URL=
DB_HOST=
DB_PORT=
DB_NAME=
DB_USER=
DB_PASSWORD=
TRANSCRIBE_PROVIDER=
TRANSCRIBE_MODEL=
SUMMARY_MODEL=
TRANSCRIBE_USD_HORA=
SUMMARY_USD_POR_ATENDIMENTO=
SECRET_KEY=
ADMIN_USUARIO=
ADMIN_SENHA=
MAX_CALLS_PER_DAY=
MAX_AUDIO_MINUTES_PER_DAY=
MAX_SUMMARIES_PER_DAY=
MAX_COST_PER_USER_PER_DAY=
MAX_SYSTEM_COST_PER_DAY=
MAX_CALL_DURATION_MINUTES=
MAX_CHUNKS_PER_CALL=
LOGIN_MAX_ATTEMPTS=
LOGIN_BLOCK_MINUTES=
```

Para reduzir custo mensal, use:

```text
TRANSCRIBE_PROVIDER=groq
TRANSCRIBE_MODEL=whisper-large-v3-turbo
GROQ_BASE_URL=https://api.groq.com/openai/v1
```

O `OPENAI_API_KEY` continua sendo usado para gerar o resumo final. A transcricao usa `GROQ_API_KEY` quando `TRANSCRIBE_PROVIDER=groq`.

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

## Configuracao inicial de acesso

O sistema nao cria credenciais padrao. Configure um admin tecnico antes de subir:

```text
ADMIN_USUARIO=seu_admin_tecnico
ADMIN_SENHA=troque_por_uma_senha_forte_com_12_caracteres
SECRET_KEY=uma_chave_aleatoria_com_mais_de_32_caracteres
```

Sem essas variaveis, ou usando senha fraca, o app recusa iniciar.

Depois do login como admin:

1. Acesse `Usuarios`.
2. Crie os analistas.
3. Entregue usuario e senha inicial para cada analista.
4. Deixe "Administrador" desmarcado para analistas comuns.

## Documentacao complementar

- `GUIA_MIGRACAO.md`: passo a passo para migrar/continuar em outro computador.
- `GUIA_OPERACAO.md`: como usar o sistema no dia a dia.
- `CONTINUIDADE_CODEX.md`: estado tecnico atual para outra conta Codex continuar.
