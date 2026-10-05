# Support AI / 55PBX AI

Aplicacao Flask usada para apoiar atendimentos de suporte ERP feitos via 55PBX/ClickDesk.

O sistema captura audio da aba do 55PBX e do microfone, envia trechos de audio para o backend, transcreve primeiro com Groq, usa OpenAI como fallback de transcricao quando necessario, gera o resumo com OpenAI e salva o historico no Supabase/PostgreSQL.

## Links

- Repositorio: `https://github.com/Thales0408/support-ai.git`
- Dominio Railway anterior: `https://web-production-b7e8f.up.railway.app/` (confirmar apos republicar).
- Health check: `/health` no dominio ativo.

## Stack

- Python 3.11
- Flask
- Waitress
- Supabase/PostgreSQL via Connection Pooler
- Groq `whisper-large-v3` como transcricao principal focada em precisao
- OpenAI `gpt-4o-transcribe` como fallback de maior precisao
- OpenAI `gpt-4.1-mini` para resumo final
- HTML, CSS e JavaScript
- MediaRecorder, `getDisplayMedia`, `getUserMedia` e `AudioContext`

## Arquivos principais

- `app.py`: backend Flask e rotas principais.
- `services/ai.py`: clientes e chamadas de IA/transcricao.
- `services/database.py`: pool de conexoes, schema e inicializacao do banco.
- `tools/migrate.py`: migracao idempotente usada antes do deploy.
- `Dockerfile`: imagem de producao com FFmpeg instalado.
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
- Envio de chunks configuraveis, com padrao de 45 segundos.
- Transcricao por chunk.
- Finalizacao com texto pronto para colar no ticket ClickDesk.
- Registro de falhas de chunks sem derrubar o atendimento inteiro.
- Dashboard com filtros, busca, status, TMA, grafico, alertas, copiar resumo e detalhes.
- Exportacao para Excel.
- Pausa de gravacao e deteccao automatica de silencio para reduzir custo.
- Campo de ticket ClickDesk por atendimento.
- Resumo ClickDesk curto, tags internas para busca, classificacao operacional, reprocessamento de resumo e troca de senha pelo usuario.
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
TRANSCRIBE_FALLBACK_PROVIDER=
TRANSCRIBE_MODEL=
OPENAI_TRANSCRIBE_MODEL=
SUMMARY_MODEL=
TRANSCRIBE_USD_HORA_GROQ=
TRANSCRIBE_USD_HORA_GROQ_LARGE_V3=
TRANSCRIBE_USD_MINUTO_OPENAI_MINI=
TRANSCRIBE_USD_MINUTO_OPENAI=
TRANSCRIBE_USD_HORA=
SUMMARY_USD_POR_ATENDIMENTO=
AUDIO_PREPROCESS_ENABLED=
AUDIO_DIAGNOSTICS_KEEP=
AUDIO_DIAGNOSTICS_DIR=
FFMPEG_PATH=
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
CHUNK_SECONDS=
LOGIN_MAX_ATTEMPTS=
LOGIN_BLOCK_MINUTES=
```

Para reduzir custo mensal, use:

```text
TRANSCRIBE_PROVIDER=groq
TRANSCRIBE_FALLBACK_PROVIDER=openai
TRANSCRIBE_MODEL=whisper-large-v3
OPENAI_TRANSCRIBE_MODEL=gpt-4o-transcribe
GROQ_BASE_URL=https://api.groq.com/openai/v1
TRANSCRIBE_USD_HORA_GROQ=0.04
TRANSCRIBE_USD_HORA_GROQ_LARGE_V3=0.111
TRANSCRIBE_USD_MINUTO_OPENAI_MINI=0.003
TRANSCRIBE_USD_MINUTO_OPENAI=0.006
AUDIO_PREPROCESS_ENABLED=true
AUDIO_DIAGNOSTICS_KEEP=false
CHUNK_SECONDS=45
```

O `OPENAI_API_KEY` tem dois usos: gerar o resumo final e servir como fallback de transcricao quando `TRANSCRIBE_FALLBACK_PROVIDER=openai`. A transcricao principal e a Groq quando `TRANSCRIBE_PROVIDER=groq`; se a Groq retornar limite, indisponibilidade, timeout ou erro 5xx, o backend tenta OpenAI Whisper como fallback. O fallback tambem pode ser acionado quando a transcricao Groq apresenta sinais fortes de baixa qualidade; nesse caso, o OpenAI recebe o audio original para criar uma segunda tentativa independente. Os limites diarios de custo continuam sendo verificados antes do fallback.

Para evitar requisicoes pagas sem fala, o navegador mede atividade nos canais da aba e do microfone e nao envia trechos silenciosos. Se a medicao falhar ou o AudioContext estiver suspenso, o trecho e enviado normalmente para nao perder uma fala. Ajuste o limiar apenas apos comparar com gravacoes reais, especialmente vozes baixas. O dashboard atualiza os dados a cada 30 segundos enquanto a aba esta visivel e imediatamente quando ela volta ao primeiro plano.

Os arquivos de diagnostico de audio sao removidos por padrao apos o preprocessamento. Use `AUDIO_DIAGNOSTICS_KEEP=true` apenas durante investigacoes controladas, pois esses arquivos podem conter gravacoes de clientes.

Para comparar modelos em um audio real:

```text
python tools/compare_transcription.py caminho/audio.webm --duracao-segundos 45
```

A ferramenta compara o audio original e, quando disponivel, a versao preprocessada nos modelos Groq `whisper-large-v3-turbo`, Groq `whisper-large-v3` e OpenAI `whisper-1`, exibindo tempo, custo estimado, similaridade e uma heuristica de qualidade.

O backend prioriza `DB_*` quando `DB_PASSWORD` esta configurada e reutiliza conexoes por meio de pool local. Ajuste `DB_POOL_MIN` e `DB_POOL_MAX` conforme o limite do banco. `DATABASE_URL` continua suportada como alternativa.

## ClickDesk e Railway

O ClickDesk cria o ticket quando a ligacao toca. Informe o numero do ticket ao iniciar a gravacao, ou salve-o depois nos detalhes do atendimento. Ao finalizar, copie o texto pronto e use "Abrir ticket" nos detalhes para colar no ClickDesk. O sistema ainda nao envia comentarios ao ClickDesk automaticamente; isso depende de uma API autorizada pela empresa.

Os dados existentes continuam nas colunas `ticket_zendesk` do banco e nas chaves `ticket_zendesk`/`resumo_zendesk` da API por compatibilidade. A interface envia `ticket_clickdesk`, aceito pelo backend junto com o nome antigo. Nao renomeie a coluna sem migracao de banco.

No Railway, use o `Dockerfile` do repositorio para garantir FFmpeg, configure `/health` como healthcheck e execute `python tools/migrate.py` seguido da suite de testes no pre-deploy antes de promover uma versao. Confirme no servico Railway que `/health` retorna `status: ok`, `database: ok` e, quando o preprocessamento estiver ativo, `ffmpeg: ok`. Uma implantacao so deve ser considerada concluida depois de testar login, inicio, chunk e finalizacao pelo dominio HTTPS ativo.

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


## Hardening de producao

- Sessoes expiram apos periodo configuravel por `SESSION_HOURS`.
- Senhas novas respeitam `PASSWORD_MIN_LENGTH`.
- POSTs usam CSRF e logout e uma operacao POST.
- Headers de seguranca, no-store para paginas privadas e HSTS em HTTPS.
- Uploads possuem limite global e limite especifico por chunk.
- Dashboard usa filtros, metricas e paginacao no PostgreSQL; transcricao completa so e carregada no detalhe.
- Exportacao Excel protege contra formula injection.
- Chunks possuem retry de rede com backoff e idempotencia por atendimento/ordem.
- Acoes administrativas sensiveis geram registros em `auditoria_eventos`.
- Finalizacoes abandonadas podem ser retomadas apos expirar o lease.
- Audios temporarios sao removidos por padrao.

### Deploy seguro

```text
python tools/migrate.py
python -m unittest discover -s tests -p test_*.py
python app.py
```

Nao aumente replicas antes de validar concorrencia, pool de banco e processamento assincrono de IA.
