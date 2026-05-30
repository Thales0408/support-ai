# Continuidade do Projeto - Support AI / 55PBX AI

Atualizado em: 2026-05-29

## Resumo

O Support AI / 55PBX AI e uma aplicacao Flask hospedada no Railway, com banco Supabase/PostgreSQL, usada para apoiar atendimentos de suporte ERP feitos via 55PBX/Zendesk.

O objetivo e capturar o audio da ligacao, transcrever automaticamente e gerar um resumo/documentacao pronta para colar no ticket do Zendesk.

## Repositorio

```text
https://github.com/Thales0408/support-ai.git
```

Branch principal:

```text
main
```

Commits recentes importantes:

```text
3c14b0d Permite editar e excluir usuarios
6c451f0 Melhora dashboard de atendimentos
649c6af Adiciona usuarios e melhora fluxo de gravacao
5a8495c Corrige inicio de gravacao no Railway
3219509 Define pooler Supabase como padrao
```

## Deploy atual

Railway:

```text
https://web-production-b7e8f.up.railway.app/
```

Health check:

```text
https://web-production-b7e8f.up.railway.app/health
```

Status validado em 2026-05-29:

```json
{
  "database": "ok",
  "db_config": {
    "host": "aws-1-sa-east-1.pooler.supabase.com",
    "modo": "variaveis_db",
    "password_configurada": true,
    "port": "6543",
    "user": "postgres.epegojdxngrcwvzecupl"
  },
  "status": "ok",
  "transcribe_provider": "groq",
  "transcribe_model": "whisper-large-v3-turbo"
}
```

## Stack atual

Frontend:

- HTML
- CSS
- JavaScript
- Chart.js
- MediaRecorder
- getDisplayMedia
- getUserMedia
- AudioContext

Backend:

- Python 3.11
- Flask
- Waitress
- psycopg2
- Werkzeug security
- openpyxl

Banco:

- Supabase PostgreSQL
- Connection Pooler/Supavisor

IA:

- Groq `whisper-large-v3-turbo` para transcricao de baixo custo.
- OpenAI `gpt-4.1-mini` para resumo final.

## Arquivos principais

```text
app.py
requirements.txt
runtime.txt
Procfile
.env.example
README.md
GUIA_MIGRACAO.md
GUIA_OPERACAO.md
CONTINUIDADE_CODEX.md
templates/index.html
templates/login.html
templates/admin.html
static/popup.js
```

## Variaveis de ambiente

Obrigatorias:

```text
OPENAI_API_KEY=<chave real da OpenAI>
GROQ_API_KEY=<chave real da Groq>
GROQ_BASE_URL=https://api.groq.com/openai/v1
DB_HOST=aws-1-sa-east-1.pooler.supabase.com
DB_PORT=6543
DB_NAME=postgres
DB_USER=postgres.epegojdxngrcwvzecupl
DB_PASSWORD=<senha atual do banco Supabase>
TRANSCRIBE_PROVIDER=groq
TRANSCRIBE_MODEL=whisper-large-v3-turbo
SUMMARY_MODEL=gpt-4.1-mini
SECRET_KEY=<chave secreta forte>
```

Opcionais:

```text
ADMIN_USUARIO=admin
ADMIN_SENHA=123456
```

O `DATABASE_URL` pode existir, mas o backend prioriza as variaveis `DB_*` quando `DB_PASSWORD` esta configurada.

## Banco de dados

O backend cria e ajusta automaticamente as tabelas se elas nao existirem.

Tabelas usadas:

```text
usuarios
atendimentos
transcricoes_chunks
```

Tabela `usuarios`:

```text
id
usuario
senha
criado_em
is_admin
ativo
```

Tabela `atendimentos`:

```text
id
usuario_id
arquivo
conteudo
data
status
transcricao_completa
inicio_em
fim_em
duracao_segundos
chunks_total
chunks_falhos
```

Tabela `transcricoes_chunks`:

```text
id
atendimento_id
usuario_id
ordem
texto
criado_em
status
erro
```

Observacoes:

- `usuarios.senha` agora usa hash seguro.
- Senhas antigas em texto puro sao migradas para hash no primeiro login valido.
- O usuario `ADMIN_USUARIO` e marcado como admin automaticamente.
- Excluir usuario remove atendimentos vinculados por `ON DELETE CASCADE`.

## Arquitetura atual

Fluxo:

```text
Browser
-> Permissao para capturar aba do 55PBX
-> Permissao de microfone
-> Backend cria atendimento
-> MediaRecorder envia chunks de 30 segundos
-> Flask/Railway recebe cada chunk
-> Groq whisper-large-v3-turbo transcreve cada trecho
-> Supabase salva chunks
-> Fim da ligacao
-> Frontend aguarda uploads pendentes
-> Backend junta transcricao completa
-> OpenAI gpt-4.1-mini gera resumo Zendesk
-> Supabase salva atendimento finalizado
-> Dashboard carrega historico
```

Se um chunk falhar:

```text
Frontend registra falha
Backend salva chunk com status erro
Atendimento continua
Resumo final inclui aviso interno
Dashboard mostra atendimento com falha
```

## Endpoints

```text
GET /health
GET /
GET|POST /login
GET /logout
GET|POST /admin
POST /admin/usuarios/<id>/status
POST /admin/usuarios/<id>/senha
POST /admin/usuarios/<id>/nome
POST /admin/usuarios/<id>/excluir
POST /atendimentos/iniciar
POST /atendimentos/chunk
POST /atendimentos/finalizar
GET /atendimentos/<id>
POST /transcrever
GET /resultados
GET /exportar
```

`/transcrever` foi mantido apenas para compatibilidade com o fluxo antigo de arquivo unico.

## Regras de acesso

Admin:

- Cria usuarios.
- Edita login.
- Redefine senha.
- Ativa/desativa usuarios.
- Exclui usuarios.
- Ve proprios atendimentos.
- Pode alternar o dashboard para todos os analistas.

Analista comum:

- Ve apenas os proprios atendimentos.
- Grava atendimento.
- Copia resumo.
- Abre detalhes/transcricao.
- Exporta o proprio historico.

## Dashboard atual

O dashboard possui:

- Total no filtro.
- Finalizados.
- Em andamento.
- Com falha.
- TMA.
- Busca.
- Filtro por periodo.
- Filtro por status.
- Filtro por escopo.
- Grafico de volume por dia.
- Painel de pontos de atencao.
- Tabela de atendimentos.
- Botao copiar resumo.
- Modal de detalhes com resumo e transcricao completa.

## Como rodar em outro computador

Ver `GUIA_MIGRACAO.md`.

Resumo:

```bash
git clone https://github.com/Thales0408/support-ai.git
cd support-ai
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Depois abrir:

```text
http://127.0.0.1:8080/health
```

## O que ja foi corrigido

- Removida dependencia do localhost como unica forma de uso.
- Corrigido deploy no Railway com `python-3.11`.
- Corrigido caminho do JavaScript para `/static/popup.js`.
- Adicionado `psycopg2-binary`.
- Trocado fluxo local de SQLite para Supabase/PostgreSQL.
- Configurado Supabase Connection Pooler para evitar problema de IPv6.
- Removido Faster Whisper do fluxo principal.
- Implementada transcricao por chunks de 30 segundos.
- Implementado resumo final somente no encerramento da ligacao.
- Adicionado `/health` com diagnostico seguro de banco.
- Corrigido erro `Unexpected token '<'` causado por 500 no inicio da gravacao.
- Adicionados usuarios reais por analista.
- Adicionadas senhas com hash.
- Adicionada tela admin.
- Adicionado dashboard operacional.
- Adicionado detalhe/transcricao por atendimento.
- Adicionado copiar resumo para Zendesk.
- Adicionado tratamento de falha individual de chunk.
- Adicionado editar/excluir usuarios.
- Criada documentacao de migracao e operacao.

## Pontos importantes

O projeto ainda nao deve ser considerado producao final para 10 analistas sem mais testes.

O desenho atual ja e bem melhor para uso real, mas ainda precisa evoluir:

- permitir que o proprio usuario troque senha;
- exigir troca de senha no primeiro login;
- exportacao admin respeitar escopo "todos";
- criar campo ticket Zendesk;
- permitir editar resumo antes de copiar/salvar;
- reprocessar resumo;
- reprocessar chunks com erro;
- logs estruturados;
- monitoramento;
- teste de ligacoes longas;
- teste com multiplos analistas simultaneos;
- medicao de custo OpenAI;
- integracao automatica com Zendesk.

## Proximas tarefas recomendadas

1. Validar uma gravacao real de 40 a 60 segundos.
2. Criar usuarios reais dos analistas.
3. Testar login de analista comum e confirmar isolamento de historico.
4. Testar dashboard admin com "Todos os analistas".
5. Fazer teste com 2 a 3 analistas simultaneos.
6. Medir tempo de resumo em ligacoes de 5, 10 e 15 minutos.
7. Criar troca de senha pelo proprio usuario.
8. Criar campo `ticket_zendesk`.
9. Permitir edicao/revisao do resumo.
10. Planejar integracao Zendesk via API.

## Contexto tecnico importante

Erro antigo no Railway:

```text
Network is unreachable
```

Motivo:

```text
db.epegojdxngrcwvzecupl.supabase.co:5432
```

usa conexao direta com IPv6. Railway nao conectou corretamente por IPv6.

Solucao aplicada:

```text
aws-1-sa-east-1.pooler.supabase.com:6543
```

via Supabase Transaction Pooler.

## Prompt para outra conta Codex

Use este prompt:

```text
Voce vai dar continuidade ao projeto Support AI / 55PBX AI.

Repositorio: https://github.com/Thales0408/support-ai.git
Branch: main
App Railway: https://web-production-b7e8f.up.railway.app/
Health: https://web-production-b7e8f.up.railway.app/health

Leia primeiro:
- README.md
- GUIA_MIGRACAO.md
- GUIA_OPERACAO.md
- CONTINUIDADE_CODEX.md

Estado atual:
- Backend Flask em Python 3.11.
- Deploy Railway.
- Banco Supabase/PostgreSQL via pooler.
- Transcricao por chunks de 30 segundos usando Groq whisper-large-v3-turbo.
- Resumo final usando gpt-4.1-mini.
- Usuarios com senha hash.
- Tela admin para criar, editar, desativar, excluir e redefinir senha de usuarios.
- Analistas veem apenas seus proprios atendimentos.
- Admin pode ver todos os analistas no dashboard.
- Dashboard com filtros, busca, TMA, status, grafico, alertas, copiar resumo e detalhes.
- Controle de custo com Groq, pausa, deteccao automatica de silencio e estimativa por atendimento.
- Campo ticket Zendesk, resumo editavel, reprocessamento de resumo e troca de senha pelo usuario.
- Tabelas criadas/ajustadas automaticamente: usuarios, atendimentos, transcricoes_chunks.
- Health check validado com database ok.

Objetivo:
Continuar evoluindo para uso por cerca de 10 analistas simultaneos, cada um com usuario proprio, historico separado, transcricao mais rapida, resumo final pronto para Zendesk e operacao segura.

Primeiro passo:
Clonar o repo, configurar .env a partir de .env.example, rodar python -m py_compile app.py, abrir /health e validar uma gravacao real de 40-60 segundos.

Nao reverter commits existentes. Preserve a arquitetura em chunks.
```
