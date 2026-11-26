# Contrato de acknowledgements de tarefas por dispositivos Edge

Estado: **contrato de produto proposto; implementação operacional não autorizada por este documento**
Data: 2026-11-26

## 1. Objectivo e fronteira

Definir como um dispositivo Edge pode comunicar que recebeu ou observou uma tarefa sem transformar uma mensagem técnica numa decisão humana nem alterar inventário.

O envelope `TASK_ACKNOWLEDGED` já aceita `task_id`, `task_version` e uma acção (`ACCEPTED`, `STARTED`, `COMPLETED`). A existência do evento no inbox prova apenas que o dispositivo autenticado enviou a mensagem. Não prova que um funcionário executou a tarefa, que a quantidade foi reposta ou que o inventário físico mudou.

## 2. Semântica obrigatória das acções

| Acção | Significado permitido | Efeito operacional |
|---|---|---|
| `ACCEPTED` | O dispositivo recebeu e aceitou tecnicamente a mensagem de tarefa | Registar acknowledgement imutável; não atribuir utilizador nem mudar o estado da tarefa |
| `STARTED` | O dispositivo declara que iniciou a actividade | Registar declaração do dispositivo; não substituir o início confirmado por utilizador |
| `COMPLETED` | O dispositivo declara que terminou a actividade | Registar declaração pendente de validação; não concluir a tarefa nem reconciliar inventário |

Nenhuma destas acções cria movimentos, reservas, snapshots, observações de stock ou confirmações WMS.

## 3. Identidade e autorização necessárias

Antes de processar um acknowledgement, o sistema tem de provar cumulativamente:

1. O dispositivo e a credencial continuam activos e autenticados.
2. A loja do dispositivo coincide com a loja da tarefa.
3. Existe uma associação explícita e vigente entre o dispositivo e a tarefa (ou uma atribuição de dispositivo equivalente, versionada e auditável).
4. O dispositivo está autorizado para o tipo de tarefa e para a acção declarada.
5. `task_version` corresponde à versão operacional esperada; uma mensagem atrasada para uma versão anterior não pode alterar a versão actual.
6. O evento não foi já processado com conteúdo diferente.

A pertença à mesma loja, por si só, não autoriza qualquer dispositivo a aceitar ou concluir qualquer tarefa. Não inferir associação a partir de `shelf_id`, proximidade, tipo de dispositivo ou nome declarado no payload.

## 4. Persistência e idempotência

A implementação futura deve preservar o evento original no inbox e acrescentar um registo de acknowledgement append-only, com pelo menos:

- `store_id`, `task_id`, `task_version`, `device_id`;
- `inbox_id`, `event_id`, `sequence_number` e fingerprint;
- acção declarada;
- timestamp declarado pelo dispositivo e timestamp de recepção;
- resultado de validação e razão de rejeição, sem guardar segredos;
- identidade da associação dispositivo-tarefa que autorizou a mensagem.

A chave de deduplicação deve impedir duas aplicações do mesmo evento. Uma repetição exacta é idempotente; reutilização do mesmo event ID com conteúdo diferente é conflito. A persistência do acknowledgement e a transição do processamento para `PROCESSED` têm de ser atómicas.

## 5. Concorrência e fencing

O worker só pode confirmar processamento com o lease e fencing token actuais. A transacção de aplicação deve bloquear/revalidar a associação dispositivo-tarefa e a versão da tarefa antes de inserir o acknowledgement. Se a atribuição ou versão mudar durante a execução, o evento deve terminar como rejeitado/obsoleto, sem alterar a tarefa.

Não manter locks durante chamadas externas ou I/O. Não aceitar resultados de um worker cujo lease tenha expirado.

## 6. Revisão humana e inventário

- `ACCEPTED` e `STARTED` são telemetria operacional do dispositivo.
- `COMPLETED` cria apenas evidência pendente de revisão.
- A conclusão oficial continua a exigir o fluxo autenticado de confirmação humana existente.
- A quantidade efectivamente reposta é recolhida e validada separadamente.
- O movimento de inventário continua sujeito à reconciliação WMS, à localização autorizada, à frescura, às reservas e à auditoria existentes.
- Uma captura ou observação visual posterior pode apoiar a revisão, mas não confirma automaticamente a reposição.

## 7. Estados de processamento

O acknowledgement deve distinguir pelo menos:

- `ACCEPTED`: evento autorizado e registado;
- `STALE_TASK_VERSION`: versão da tarefa já não corresponde;
- `UNASSIGNED_DEVICE`: não existe associação vigente;
- `DEVICE_NOT_ALLOWED`: dispositivo sem permissão para a acção;
- `REVIEW_REQUIRED`: declaração COMPLETED registada, aguardando validação humana;
- `DUPLICATE`: replay exacto já registado.

Rejeições de autorização não devem revelar a existência de tarefas de outras lojas.

## 8. Critérios de aceitação

- Associação dispositivo-tarefa explícita, versionada, auditável e revogável.
- Testes de loja diferente, dispositivo não associado, associação expirada/revogada e task_version obsoleta.
- Testes de replay exacto e event ID reutilizado com payload diferente.
- Teste de concorrência PostgreSQL entre alteração da associação, mudança de versão e processamento do evento.
- Prova de que `COMPLETED` não altera estado da tarefa, stock, snapshots ou movimentos.
- Prova de atomicidade entre acknowledgement e estado de processamento.
- Testes de perda/expiração de lease e fencing.
- CI completa e documentação operacional antes de activar o handler.

## 9. Estado actual

A API de ingestão e o worker Edge já existem. O worker mantém apenas `DEVICE_HEARTBEAT` como handler built-in; eventos sem handler vão para dead-letter. Esta é a política correcta até estarem implementadas a associação dispositivo-tarefa e as garantias acima.

Este documento não autoriza a activação do handler `TASK_ACKNOWLEDGED`, não declara integração com robôs homologada e não altera o estado de tarefas ou inventário.


## 10. Descoberta de implementação no código actual (2026-11-26)

A inspecção do HEAD `6159c326909fa0d6d6fd830067d6e4e243391e87` confirmou:

- `ReplenishmentTask.assigned_user_id` identifica um utilizador/funcionário. Não representa uma associação a um dispositivo Edge.
- `ReplenishmentTaskEvent` é o ledger actual do ciclo de vida da tarefa; os tipos permitidos são CREATED, APPROVED, STATUS_CHANGED e INVENTORY_RECONCILED. Não deve ser reutilizado para registar silenciosamente eventos de dispositivo.
- `replenishment_assignment.py` calcula um plano equilibrado de atribuição de tarefas a funcionários; é um planeador determinístico, não um registo persistente de atribuições de dispositivos.
- `EdgeDevice`, credenciais, inbox e processamento persistente já existem nas migrations 0071–0073. Não criar um segundo registo de dispositivos nem duplicar a inbox.
- O modelo actual `ReplenishmentTask` não expõe um campo explícito `task_version`. `updated_at` não deve ser tratado como substituto sem definir e provar a semântica concorrente.

### Consequências para a implementação

A migration `0102_edge_task_assignments` já introduz a entidade persistente com `store_id`, `device_id`, `task_id`, `task_version`, validade (`valid_from`/`valid_until`), actor de criação/revogação e timestamps. As FKs compostas ligam dispositivo e tarefa à mesma loja. Um índice parcial permite apenas uma associação não revogada por par dispositivo/tarefa. A associação só pode ser fechada uma vez; os eventos CREATED/REVOKED são append-only e únicos por tipo.

A mesma migration introduz `ReplenishmentTask.task_version`. Triggers PostgreSQL e SQLite incrementam a revisão em cada UPDATE da tarefa; a escrita directa do contador é bloqueada. Assim, qualquer mutação concorrente da tarefa invalida a versão capturada pela associação. O acknowledgement é evidência append-only e não deve actualizar a tarefa; as transições humanas continuam a alterar a revisão e tornam acknowledgements antigos obsoletos.

A implementação do serviço/API ainda deve bloquear Store → Task → Device → Assignment por esta ordem, validar a loja e persistir associação + evento na mesma transacção. O handler de acknowledgement terá de integrar o registo append-only e a conclusão do processamento do inbox numa única transacção com fencing. O worker actual separa a chamada do handler da confirmação de processamento; essa fronteira transaccional tem de ser resolvida antes de activar o handler.

A unicidade e as regras de validade são garantidas no PostgreSQL, não apenas por validação Python. SQLite mantém cobertura unitária, mas não é prova de concorrência.

**Estado:** schema e modelos implementados no commit `6ae449d883c845072127f188861be44e57dd2193`. A migration completa passou no passo `alembic upgrade head` do API CI run `45876761643`; a suite concluiu com **1747 passed, 1 skipped**. Quality Gates `45876761651`, Security Scans `45876761497` e Docker Compose `45876761707` também passaram no mesmo SHA de código. Serviço/API, handler e smoke concorrente dedicado permanecem pendentes. O worker mantém comportamento fail-closed.
