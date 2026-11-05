# Integração oficial 55PBX — etapa 1

Esta entrega adiciona **recebimento de metadados** da integração oficial Tempo real por URL da 55PBX. Não baixa o áudio, não aciona IA nem altera tickets do ClickDesk. A gravação pelo navegador permanece disponível.

## Referências oficiais

- Manual REST: https://files.55pbx.com/manuais/integration_endpoint.pdf
- Guia de tokens: https://suporte.55pbx.com/support/solutions/articles/151000180038-guia-de-habilitac%C3%A3o-de-tokens-para-integrac%C3%A3o-com-a-api-55pbx

Segundo a documentação, a plataforma envia dois eventos por ligação (início e fim) e pode enviar um terceiro evento na transferência. O formato é JSON, via POST ou PUT. O token de validação vem no header chamado token.

## Ativação após autorização do responsável pela 55PBX

1. Gerar um segredo longo e aleatório em um gerenciador de senhas. Não utilizar a chave de login.
2. Configurar a variável PBX55_WEBHOOK_TOKEN no serviço web do Railway em produção. Não divulgar o segredo no repositório ou em screenshots.
3. Confirmar que o deploy desta versão está saudável.
4. No painel administrativo da 55PBX, acessar Integrações > Tempo real por URL. Cadastrar:
   - URL: https://web-production-b7e8f.up.railway.app/integracoes/55pbx/webhook
   - Método: POST (PUT também é aceito).
   - Chave (token): o mesmo segredo de PBX55_WEBHOOK_TOKEN.
5. Fazer uma chamada de teste com permissão operacional e verificar os registros no PostgreSQL.
6. Não enviar tokens, URLs privadas de áudio ou dados pessoais por prints.

A rota permanece desabilitada (HTTP 503) sem o segredo. Token incorreto retorna 401. JSON inválido retorna 400, tipo de conteúdo incorreto retorna 415, tamanho acima de 64 KiB retorna 413. Erro de banco retorna 503 para permitir tentativas posteriores pelo fornecedor, quando previstas.

## Dados armazenados

A tabela ligacoes_55pbx possui um único registro por central_id e call_id. Armazena telefone normalizado, ramal, fila, status, data da ligação, duração, URL do áudio (somente metadado, sem download), referência de transferência e datas de recebimento. Os campos ticket_numero e ticket_id_interno ficam disponíveis para futura associação ao ClickDesk, mas não são preenchidos nesta etapa.

A tabela eventos_55pbx conserva central_id, call_id, hash SHA-256 do evento e data do recebimento. Isso evita gravar repetidamente a mesma mensagem sem armazenar todo o conteúdo bruto.

As duas tabelas têm RLS ativado e permissões públicas removidas. O backend utiliza PostgreSQL com acesso administrativo controlado; a Data API não pode lê-las diretamente como anon/authenticated.

## Próximas etapas ainda não ativadas

1. Processar áudio oficial somente após proteção contra SSRF, validação de domínios, limites de tamanho e política de retenção.
2. Correlacionar chamadas com o ticket criado pelo ClickDesk com telefone, horário, ramal e analista, sem fazer suposições quando houver ambiguidade.
3. Após autorização formal da API ClickDesk, escrever os campos e a macro mediante revisão humana.
4. Manter encerramento dos tickets manual.

A variável OPENAI_API_KEY é independente do token 55PBX. O webhook pode funcionar sem OpenAI, mas o resumo depende de uma chave OpenAI válida.

## Testes

Executar: SKIP_DB_INIT=1 python -m unittest discover -s tests -p 'test_*.py'

O Railway deve rodar testes automatizados no pre-deploy, mas não chamar reprocessamento histórico que utiliza IA paga.
