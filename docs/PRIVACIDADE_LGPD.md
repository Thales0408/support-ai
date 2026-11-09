# LGPD: implantação progressiva e sem exclusão automática

**Estado:** controles técnicos propostos em branch de revisão. Não é certificação de conformidade LGPD.

## Inventário resumido de tratamentos

| Fluxo | Dados | Destino | Observação |
|---|---|---|---|
| Ligação | Voz e metadados | Chrome / 55PBX | A sessão de captura pode permanecer autorizada; não gravar fora de chamadas |
| Backup pendente | Arquivos de áudio | IndexedDB do perfil Chrome | Áudio pendente pode continuar armazenado localmente; não apagar sem confirmação de entrega |
| Transcrição | Áudio | Groq (OpenAI em fallback, quando configurado) | O áudio chega ao prestador antes da máscara local de transcrição |
| Macro | Texto da transcrição | OpenAI API | Segredos reconhecidos podem ser mascarados **somente se** `LGPD_MASK_SECRETS=true` |
| Histórico | Transcrições, trechos, macro | Supabase | Há RLS e concessões revogadas para `anon/authenticated`; validar também as permissões dos usuários na aplicação |
| Ticket | Macro | ClickDesk | Envio deve permanecer manual após revisão |

## Controles deste PR

1. **Exportação Excel**: não interpretar conteúdo do cliente como fórmulas, sem alterar relatórios comuns.
2. **Máscara conservadora de segredos**: senhas, tokens, CPF mencionado e códigos de verificação com padrões confiáveis. Não mascara CNPJ, telefone, e-mail ou nome usados na macro. **Não é anonimização completa.**
3. **Retenção controlada**: `python -m scripts.lgpd_retention --days 365` faz apenas inventário em ambiente autenticado. O período é EXEMPLO, não uma política aprovada.
4. **Exclusão somente após três condições**: decisão do controlador sobre prazo, `LGPD_RETENTION_APPLY_ENABLED=1`, e `--apply --confirm EXCLUIR_TRANSCRICOES`. O expurgo só atinge texto de transcrições de atendimentos finalizados, nunca macros/tickets, gravações pendentes ou conteúdo de fornecedores. Registra contagens no log `auditoria_eventos`.
5. **Sem mudanças** na extensão 0.6.6, automação, chamadas, vínculo de ticket, tarifas, API keys ou limites financeiros.

## Implantação segura

1. Revisar com encarregado/jurídico a base legal e a informação ao titular; confirmar aviso de gravação no 55PBX.
2. Confirmar o papel da empresa e contratos/DPA de 55PBX, ClickDesk, Groq, OpenAI, Railway e Supabase, incluindo transferência internacional e subprocessadores.
3. Reexecutar testes, verificar no ambiente de homologação pelo menos cinco chamadas autorizadas, inclusive duas consecutivas e tentativas de inserir resumos no ticket errado.
4. Testar `LGPD_MASK_SECRETS=true` em homologação com frases positivas e negativas. **Não ativar no Railway sem validar precisão**, pois a máscara modifica texto de transcrição e pode prejudicar a documentação.
5. Executar o inventário de retenção em modo simulação. Definir prazos distintos para áudio bruto, áudio pendente, transcrição, macro, logs, backups e conteúdo em subprocessadores; considerar retenção legal e demandas do titular.
6. Fazer backup, validar restore, retenções legais e responsáveis; só então autorizar o expurgo em janela controlada. Não executar automaticamente em produção neste PR.
7. Implementar mecanismo administrativo de solicitações do titular (acesso, correção, eliminação quando cabível) e política de resposta a incidentes antes de liberar operação em larga escala.

## Lacunas que este PR **não** resolve

- Dados em áudio já enviados à Groq ou eventual fallback OpenAI; requer configuração contratual.
- Criptografia própria de blobs IndexedDB no Chrome; cada perfil/estação precisa de controles corporativos de dispositivo.
- Expiração automática e eliminação comprovada em fornecedores externos e backups.
- Retificação/eliminação de históricos já publicados no ClickDesk.
- Associação errada entre chamada e ticket; permanece a prioridade funcional de prevenção de incidentes.
- Controle completo de quem pode exportar, baixar e copiar transcrições; exige análise por perfil.
- Aprovação da base legal, avisos, RIPD e contratos; são decisões da empresa.

## Comandos (após deploy/revisão)

```bash
# Somente simulação, não apaga nenhum dado
python -m scripts.lgpd_retention --days 365

# NÃO executar sem autorização formal e backup restaurável
# LGPD_RETENTION_APPLY_ENABLED=1 python -m scripts.lgpd_retention --days 365 \
#   --apply --confirm EXCLUIR_TRANSCRICOES
```

## Critério de sucesso

Nenhum ticket recebe dados de outra ligação; nenhuma nota é enviada sem revisão; uma falha de rede não perde áudio sem alerta; retenção/eliminação tem prazo aprovado, trilha de auditoria e procedimento de resposta a incidentes. Só considerar ambiente apto à produção após validação real e revisão legal.
