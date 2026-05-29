# Guia de operacao

Este guia explica como usar o Support AI / 55PBX AI no dia a dia.

## Perfis

### Admin

O admin pode:

- Criar usuarios.
- Editar login de usuario.
- Redefinir senha.
- Ativar ou desativar usuarios.
- Excluir usuarios.
- Ver os proprios atendimentos.
- Alternar o dashboard para ver todos os analistas.

### Analista

O analista pode:

- Fazer login.
- Gravar atendimento.
- Ver apenas os proprios atendimentos.
- Copiar resumo para Zendesk.
- Abrir detalhes e transcricao completa.
- Exportar o proprio historico para Excel.

## Como cadastrar usuarios

1. Entrar como admin.
2. Clicar em `Usuarios`.
3. Preencher `Usuario`.
4. Preencher `Senha inicial`.
5. Marcar `Administrador` apenas se a pessoa tambem deve gerenciar usuarios e ver todos os atendimentos.
6. Clicar em `Criar usuario`.

Depois disso, o analista acessa:

```text
https://web-production-b7e8f.up.railway.app/
```

E entra com o usuario e senha criados pelo admin.

## Como editar usuarios

Na tela `Usuarios`:

- Alterar login: edite o campo na linha do usuario e clique em `Salvar`.
- Redefinir senha: digite a nova senha e clique em `Redefinir`.
- Desativar: bloqueia o login sem apagar historico.
- Ativar: libera novamente o login.
- Excluir: remove o usuario e tambem remove os atendimentos vinculados a ele.

Recomendacao: prefira `Desativar` quando quiser preservar historico.

## Como gravar um atendimento

1. Entrar no sistema.
2. Clicar em `Iniciar Gravacao`.
3. Escolher a aba do 55PBX.
4. Marcar compartilhamento de audio da aba, se o navegador mostrar essa opcao.
5. Permitir o microfone.
6. Fazer o atendimento normalmente.
7. Ao terminar, clicar em `Parar Gravacao`.
8. Aguardar o sistema gerar o resumo final.

Durante a gravacao, o sistema envia chunks de 30 segundos.

Se um chunk falhar, a gravacao continua. O atendimento final fica com aviso de falha para revisao.

## Dashboard

O dashboard mostra:

- Total no filtro.
- Finalizados.
- Em andamento.
- Com falha.
- TMA.
- Grafico de volume por dia.
- Pontos de atencao.
- Lista de atendimentos.

Filtros disponiveis:

- Busca por resumo, transcricao, analista ou data.
- Periodo.
- Status.
- Escopo.

Escopo:

- `Meus atendimentos`: mostra somente atendimentos do usuario logado.
- `Todos os analistas`: aparece apenas para admin.

## Copiar resumo para Zendesk

Na lista de atendimentos:

1. Localize o atendimento.
2. Clique em `Copiar`.
3. Cole no ticket do Zendesk.

Tambem e possivel clicar em `Detalhes` e copiar a partir do modal.

## Ver transcricao completa

1. Clique em `Detalhes`.
2. Leia `Resumo Zendesk`.
3. Leia `Transcricao completa`.

Use isso para revisar atendimentos com falha ou resumo incompleto.

## Exportar Excel

Clique em `Exportar Excel`.

O arquivo inclui:

- Data.
- Resumo.
- Transcricao.
- Total de trechos.
- Trechos com falha.

Analistas exportam o proprio historico. Admin, no estado atual da rota de exportacao, exporta o proprio historico.

## Boas praticas

- Criar um usuario por analista.
- Nao compartilhar login.
- Manter o usuario admin apenas para gestao.
- Desativar usuarios desligados em vez de excluir, se o historico precisar ser preservado.
- Fazer testes com ligacoes reais curtas antes de liberar para todos.
- Revisar atendimentos marcados com falha.

## Limitacoes atuais

- O usuario comum ainda nao troca a propria senha.
- Ainda nao ha integracao automatica com Zendesk.
- Ainda nao ha logs estruturados ou painel de erros.
- Ainda nao ha reprocessamento manual de resumo/chunk.
- Exportacao do admin ainda nao alterna entre "meus" e "todos".
- Custo mensal da OpenAI ainda precisa ser medido em uso real.
