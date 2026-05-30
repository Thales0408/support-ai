# Guia de migracao e continuidade em outro PC

Este guia serve para continuar o projeto Support AI / 55PBX AI em outro computador.

## 1. O que precisa ter instalado

- Git
- Python 3.11
- Acesso ao GitHub do repositorio
- Acesso ao Railway
- Acesso ao Supabase
- Chave da OpenAI

Opcional, mas recomendado:

- VS Code
- Extensao Python do VS Code

## 2. Clonar o projeto

```bash
git clone https://github.com/Thales0408/support-ai.git
cd support-ai
```

Se o repositorio abrir direto na pasta backend, continue dai. Se houver uma pasta extra, entre nela ate encontrar `app.py`, `requirements.txt` e `Procfile`.

## 3. Criar ambiente Python

No Windows:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Se `python` apontar para outra versao, tente:

```bash
py -3.11 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Criar `.env` local

Copie o modelo:

```bash
copy .env.example .env
```

Edite o `.env` e preencha:

```text
OPENAI_API_KEY=<chave real da OpenAI>
GROQ_API_KEY=<chave real da Groq>
GROQ_BASE_URL=https://api.groq.com/openai/v1
DB_HOST=aws-1-sa-east-1.pooler.supabase.com
DB_PORT=6543
DB_NAME=postgres
DB_USER=postgres.epegojdxngrcwvzecupl
DB_PASSWORD=<senha atual do Supabase>
TRANSCRIBE_PROVIDER=groq
TRANSCRIBE_MODEL=whisper-large-v3-turbo
SUMMARY_MODEL=gpt-4.1-mini
TRANSCRIBE_USD_HORA=0.04
SUMMARY_USD_POR_ATENDIMENTO=0.003
ADMIN_USUARIO=admin
ADMIN_SENHA=123456
SECRET_KEY=<chave grande e aleatoria>
```

Para manter o custo baixo em volume, a transcricao deve usar Groq (`TRANSCRIBE_PROVIDER=groq`). A OpenAI continua sendo usada para o resumo final.

Nao commitar `.env`. Ele esta ignorado pelo Git.

## 5. Rodar localmente

```bash
python app.py
```

Abra:

```text
http://127.0.0.1:8080/health
```

Resultado esperado:

```json
{
  "status": "ok",
  "database": "ok"
}
```

Depois abra:

```text
http://127.0.0.1:8080/
```

## 6. Validar fluxo minimo

1. Fazer login como admin.
2. Abrir `Usuarios`.
3. Criar um usuario de teste.
4. Sair e entrar com o usuario de teste.
5. Clicar em `Iniciar Gravacao`.
6. Escolher a aba do 55PBX.
7. Permitir microfone.
8. Gravar 40 a 60 segundos.
9. Parar a gravacao.
10. Confirmar que o resumo aparece no dashboard.

## 7. Deploy no Railway

O Railway usa:

```text
Procfile
runtime.txt
requirements.txt
```

Comando atual:

```text
web: python app.py
```

Runtime atual:

```text
python-3.11
```

Para publicar:

```bash
git status
git add <arquivos>
git commit -m "Mensagem objetiva"
git push origin main
```

O Railway deve redeployar automaticamente quando recebe push na `main`.

## 8. Variaveis no Railway

Conferir no Railway:

```text
OPENAI_API_KEY
GROQ_API_KEY
GROQ_BASE_URL
DB_HOST
DB_PORT
DB_NAME
DB_USER
DB_PASSWORD
TRANSCRIBE_PROVIDER
TRANSCRIBE_MODEL
SUMMARY_MODEL
TRANSCRIBE_USD_HORA
SUMMARY_USD_POR_ATENDIMENTO
SECRET_KEY
ADMIN_USUARIO
ADMIN_SENHA
```

O `DB_HOST` deve usar o pooler:

```text
aws-1-sa-east-1.pooler.supabase.com
```

Porta:

```text
6543
```

Evite voltar para o host direto `db.<projeto>.supabase.co:5432`, pois houve problema de IPv6 no Railway.

## 9. Banco de dados

O backend cria e ajusta as tabelas automaticamente ao iniciar.

Tabelas:

- `usuarios`
- `atendimentos`
- `transcricoes_chunks`

As senhas antigas em texto puro sao migradas automaticamente para hash no primeiro login bem-sucedido.

## 10. Checklist apos migrar

- `python -m py_compile app.py` passa sem erro.
- `/health` retorna database ok.
- Login admin funciona.
- Tela `Usuarios` abre.
- Criacao de analista funciona.
- Analista comum ve apenas os proprios atendimentos.
- Admin consegue alternar dashboard para todos os analistas.
- Gravacao real de 40 a 60 segundos gera resumo.
- Exportar Excel baixa arquivo.

## 11. Problemas comuns

### `Network is unreachable`

Provavel uso do host direto do Supabase em IPv6. Usar pooler:

```text
aws-1-sa-east-1.pooler.supabase.com:6543
```

### `Unexpected token '<'`

O frontend tentou ler HTML como JSON. Geralmente significa erro 500 no backend ou sessao expirada. Verificar logs do Railway e `/health`.

### Login funciona, mas gravacao nao inicia

Testar:

```text
POST /atendimentos/iniciar
```

Tambem confirmar se o navegador tem permissao de microfone e compartilhamento de aba com audio.

### Sem audio da aba

No Chrome/Edge, ao escolher a aba, marcar a opcao de compartilhar audio da aba.

## 12. Como continuar com Codex em outra conta

Use o prompt no final de `CONTINUIDADE_CODEX.md`.
