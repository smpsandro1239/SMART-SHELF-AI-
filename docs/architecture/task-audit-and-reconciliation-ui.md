# Cronologia auditável e reconciliação de tarefas na interface

## Objetivo

Disponibilizar aos perfis ADMIN e SUPERVISOR a consulta da cronologia operacional e a reconciliação explícita de tarefas de reposição concluídas, reutilizando os contratos já existentes na API. A interface não altera inventário como consequência automática da conclusão da tarefa.

## Cronologia

Na lista de tarefas, ADMIN e SUPERVISOR podem abrir **Ver cronologia**. A interface consulta:

`GET /api/v1/tasks/{task_id}/events`

Os eventos são apresentados por ordem cronológica, com tipo de evento, data/hora local do browser, estado de origem/destino, identificador do ator, quantidade efetiva e motivo de auditoria.

A consulta é carregada a pedido e fica em memória durante a sessão da página. O endpoint mantém a autorização e o isolamento por loja aplicados pela API. EMPLOYEE não recebe o controlo de consulta da cronologia.

## Reconciliação de inventário

A reconciliação é apresentada apenas para tarefas `COMPLETED` com `actual_quantity` positiva e para ADMIN/SUPERVISOR. O operador tem de introduzir um motivo com pelo menos três caracteres úteis.

A interface envia `POST /api/v1/tasks/{task_id}/reconcile-inventory` com `{ "reason": "..." }`.

A API continua a ser a autoridade para confirmar o perfil e o âmbito da loja, verificar a conclusão e quantidade efetiva, impedir duplicações, validar frescura/origem do snapshot, detetar stock insuficiente e criar movimento, snapshot resultante e evento `INVENTORY_RECONCILED` atomicamente.

Após sucesso, a interface apresenta o identificador do movimento, quantidade e snapshot resultante e atualiza a cronologia. Erros estruturados como `INVENTORY_SNAPSHOT_STALE`, `INSUFFICIENT_BACKROOM_STOCK` e `INVENTORY_ALREADY_RECONCILED` são apresentados através da mensagem/código devolvido pela API.

## Limites e decisões

- A interface não permite que EMPLOYEE reconcilie inventário.
- Não existe alteração de stock ao concluir uma tarefa; a reconciliação é um passo separado e aprovado.
- A interface não estima stock nem contorna snapshots ausentes/desatualizados.
- Não foi criado um endpoint de leitura de movimentos: a existência da reconciliação é refletida pelo evento `INVENTORY_RECONCILED`, enquanto a resposta da operação apresenta os detalhes do movimento recém-criado.
- A cronologia é carregada sob pedido para evitar uma chamada por cada tarefa listada.
- As tarefas canceladas permanecem visíveis na lista, permitindo consultar o motivo e a respetiva cronologia.

## Validação

A compilação TypeScript e o build Vite passaram no Web CI run `43412797984`. A validação dos Quality Gates integrados ainda deve ser acompanhada no workflow correspondente. Os contratos de autorização, frescura, concorrência, imutabilidade e rollback da reconciliação backend já foram validados no API CI run `43401542425`; a interface não substitui esses controlos.
