# SaaS Readiness

Estado arquitetural do Support AI / 55PBX AI apos a auditoria macro.

## Liberacao interna / piloto corporativo

Pode ser liberado quando:

- [ ] suite de testes do Railway passa;
- [ ] /health retorna HTTP 200;
- [ ] banco e FFmpeg aparecem como OK;
- [ ] login, inicio, chunk, pausa e finalizacao foram testados no dominio HTTPS;
- [ ] uma ligacao real valida nome/CNPJ/empresa;
- [ ] custo e fallback aparecem coerentes no dashboard.

## Controles implementados

- CSRF em POST.
- Sessao segura, expiracao e revogacao imediata para usuario desativado.
- Perfis analista/supervisor/admin tecnico.
- Escopo de dados por usuario/perfil.
- Senhas com hash e minimo configuravel.
- Bloqueio de tentativas de login.
- Limites de uso/custo.
- Limites de upload.
- Idempotencia sequencial de chunks.
- Fallback de transcricao por indisponibilidade e baixa qualidade.
- Healthcheck de banco/FFmpeg.
- Headers de seguranca.
- Audio temporario removido por padrao.
- Trilha persistente de auditoria administrativa.
- Preservacao de historico ao desativar/excluir contas com atendimentos.
- Timezone explicito.
- Testes antes do deploy no Railway.
- Tracing de infraestrutura habilitado.

## Bloqueadores para SaaS multiempresa

### 1. Isolamento por organizacao

O modelo atual e single-tenant. Antes de compartilhar a mesma instancia entre empresas independentes, criar:

- tabela `organizacoes`;
- `organizacao_id` em usuarios, atendimentos, chunks, uso e auditoria;
- filtros obrigatorios por tenant em todas as queries;
- admins e supervisores limitados a propria organizacao;
- testes de isolamento horizontal/IDOR entre tenants.

Alternativa para a primeira fase comercial: uma implantacao e um banco dedicados por cliente.

### 2. Migracoes versionadas

A inicializacao atual mantem migracoes de compatibilidade no startup e usa advisory lock para evitar corrida. Para multiplas replicas/evolucao comercial, migrar para Alembic com migrations versionadas e rollback documentado.

### 3. Privacidade e LGPD

Definir formalmente:

- base legal/consentimento para gravacao;
- politica de retencao de transcricoes;
- prazo de exclusao;
- exportacao/exclusao por cliente;
- acesso interno a dados;
- DPA/termos e politica de privacidade;
- tratamento de incidentes.

### 4. Backup e disaster recovery

Validar no provedor PostgreSQL:

- backup automatico;
- retencao;
- restore para ambiente separado;
- RPO/RTO definidos;
- teste periodico de restauracao.

### 5. Captura e diarizacao

A captura separa fontes no navegador, mas o preprocessamento converte para mono. Para elevar a confianca de nomes/speakers:

- testar canais separados ou diarizacao;
- comparar modelos em corpus real;
- adicionar dataset de regressao anonimizado;
- considerar overlap curto de chunks com deduplicacao.

## Melhorias de escala

- dividir `app.py` em blueprints/services;
- usar migrations Alembic;
- considerar pool de conexoes no processo;
- mover tarefas longas de IA para fila/worker quando o volume crescer;
- proteger `main` com checks obrigatorios;
- fixar/self-host dependencias front-end externas;
- criar painel para auditoria e observabilidade;
- configurar alertas de deploy/erro para um canal operacional.

## Criterio de pronto comercial

Nao chamar de SaaS multiempresa pronto enquanto os itens de isolamento por organizacao, privacidade/LGPD e backup/restore nao estiverem concluídos e testados.
