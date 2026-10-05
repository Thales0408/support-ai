# Guia de operacao

Este guia descreve a operacao atual do Support AI / 55PBX AI.

## Perfis

### Analista

- Grava atendimentos.
- Ve apenas os proprios atendimentos.
- Copia o texto ClickDesk.
- Abre detalhes e transcricao.
- Exporta o proprio historico.
- Altera a propria senha.

### Supervisor

- Possui as funcoes do analista.
- Pode alternar entre seus atendimentos, todos os analistas ou um analista especifico.
- Nao ve custos tecnicos.

### Admin tecnico

- Possui visao operacional completa.
- Ve custos estimados.
- Cria usuarios e altera nome, perfil, senha e status.
- Contas com atendimentos vinculados nao sao apagadas: sao desativadas para preservar o historico.

## Criar e administrar usuarios

1. Abra `Conta > Usuarios`. A tela abre em nova aba para nao interromper uma gravacao ativa.
2. Informe usuario, senha inicial e perfil.
3. A senha deve respeitar `PASSWORD_MIN_LENGTH` (padrao 12).
4. Para editar um usuario, expanda o cartao correspondente.
5. Prefira `Desativar` quando a pessoa sair da equipe.

Acoes administrativas sensiveis ficam registradas na trilha `auditoria_eventos`.

## Gravar atendimento

1. Abra o painel.
2. Informe o ticket ClickDesk, quando disponivel.
3. Clique em `Iniciar gravacao`.
4. Selecione a aba do 55PBX/ClickDesk e compartilhe o audio da aba.
5. Permita o microfone.
6. Atenda normalmente.
7. Use `Pausar` apenas quando necessario.
8. Clique em `Finalizar atendimento` ao terminar.
9. Aguarde o texto final e revise os campos estruturados antes de colar no ClickDesk.

A aba que iniciou o MediaRecorder precisa continuar aberta. Telas administrativas abrem em nova aba. Se tentar fechar/atualizar a aba de gravacao durante um atendimento, o navegador exibe um aviso.

## Transcricao e fallback

- Chunks usam `CHUNK_SECONDS` (padrao 45 segundos).
- Trechos silenciosos podem ser ignorados para reduzir custo.
- Groq e o provedor principal no ambiente recomendado.
- OpenAI e fallback para erros de provedor e sinais fortes de baixa qualidade.
- No fallback de qualidade, o audio original e enviado ao segundo provedor.
- Se um trecho falhar, o atendimento pode continuar e a falha fica sinalizada.

## Campos ClickDesk

Campos ausentes permanecem vazios. O sistema prefere campo vazio a informacao inventada.

CNPJ reconstruido a partir de fala ambigua pode aparecer como:

`Possivel CNPJ informado: XX.XXX.XXX/XXXX-XX — confirmar com cliente`

O descritivo e gerado separadamente dos campos estruturados.

## Dashboard

Indicadores:

- Total no filtro.
- Finalizados.
- Em andamento.
- Com falha.
- TMA.
- Custo estimado apenas para admin tecnico.
- Volume por dia.
- Pontos de atencao.

Filtros:

- Busca textual.
- Periodo.
- Status.
- Analista/escopo para supervisor e admin.

## Exportacao

A exportacao respeita o escopo/perfil atual. Custos tecnicos so aparecem para admin tecnico.

## Limites e custos

O backend aplica limites configuraveis de:

- atendimentos por dia;
- minutos de audio por dia;
- resumos por dia;
- custo diario por usuario em BRL;
- custo diario total em BRL;
- duracao por atendimento;
- chunks por atendimento;
- tamanho de upload.

Ao atingir um limite durante a chamada, novos chunks podem ser bloqueados, mas a finalizacao continua permitida para preservar o que ja foi capturado.

## Operacao segura

- Nao compartilhe logins.
- Desative acessos imediatamente quando necessario; uma sessao aberta e revalidada contra o status do usuario.
- Nao ative `AUDIO_DIAGNOSTICS_KEEP` fora de investigacoes controladas.
- Revise atendimentos marcados com falha.
- Nao considere um deploy concluido sem healthcheck verde.
- O `/health` deve retornar HTTP 200, banco OK e FFmpeg OK quando o preprocessamento estiver ativo.

## Limitacoes conhecidas

- Nao ha integracao automatica de comentario no ClickDesk.
- A captura depende da aba do navegador permanecer aberta.
- O audio e convertido para mono antes da transcricao; identificacao de speakers ainda e heuristica.
- Nao ha overlap entre chunks.
- O modelo de dados atual e single-tenant; uma unica instancia nao deve atender empresas independentes sem isolamento por organizacao.
- A politica de retencao de transcricoes/LGPD deve ser definida antes de uso comercial externo.
