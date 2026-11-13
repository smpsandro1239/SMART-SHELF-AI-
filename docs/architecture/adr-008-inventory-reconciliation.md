# ADR-008 — Reconciliação auditável da reposição com inventário

**Estado:** implementação inicial publicada; endurecimento e validação operacional pendentes  
**Data:** 13-11-2026

## Contexto

A conclusão de uma tarefa já guarda `actual_quantity` e, quando necessário, um motivo de exceção. Os snapshots de inventário são históricos e representam uma observação recebida de uma fonte como ERP/WMS/manual. Alterar um snapshot antigo para refletir uma reposição destruiria a proveniência e dificultaria explicar divergências.

Também não é seguro assumir que a quantidade efetivamente reposta deve ser abatida de qualquer snapshot: pode ter chegado entretanto um snapshot mais recente que já inclui o movimento, ou o stock disponível pode ter sido consumido/reservado por outra operação.

## Decisão

1. Concluir uma tarefa regista a execução física declarada; **não altera automaticamente inventário**.
2. A reconciliação é uma ação separada, explícita e autorizada para ADMIN/SUPERVISOR, com aprovação humana.
3. A reconciliação cria um movimento imutável `BACKROOM_TO_SHELF`, associado de forma única à tarefa concluída.
4. O movimento referencia o snapshot de origem e o snapshot de inventário resultante.
5. O snapshot original nunca é atualizado nem apagado. A reconciliação cria um novo snapshot, com origem `MANUAL` e referência externa idempotente baseada no identificador da tarefa.
6. Só é possível reconciliar se:
   - a tarefa estiver `COMPLETED` e tiver `actual_quantity` positiva;
   - não existir movimento de reconciliação para a mesma tarefa;
   - o snapshot de origem pertencer à mesma loja e produto;
   - o snapshot não for posterior à conclusão da tarefa;
   - o snapshot cumprir a política de frescura;
   - o stock disponível, descontando movimentos posteriores já registados, cobrir a quantidade real.
7. Se existir snapshot posterior à conclusão, snapshot desatualizado ou stock insuficiente, a API bloqueia a operação e exige reconciliação com a fonte externa. Nunca tenta adivinhar se o movimento já foi contabilizado.
8. O evento `INVENTORY_RECONCILED` entra na cronologia da tarefa com ator, quantidade, snapshot anterior e novo snapshot.
9. A operação é transacional: movimento, snapshot resultante e evento de auditoria são confirmados ou revertidos em conjunto.

## Modelo de dados proposto

Tabela append-only `inventory_movements`:
- `task_id` único e obrigatório;
- `store_id`, `product_id`;
- `movement_type` limitado a `BACKROOM_TO_SHELF`;
- `quantity` estritamente positiva;
- `source_snapshot_id` e `result_snapshot_id`;
- `actor_user_id`, `reason`, `created_at`.

A tabela não substitui os snapshots. É o registo de transferência que explica a diferença entre o snapshot de origem e o snapshot resultante.

## Limites e trabalho posterior

- A reconciliação do stock de retaguarda não cria, por si só, uma contagem exata do stock de exposição. A quantidade na prateleira continua a exigir observação/contagem própria.
- `WarehouseProductPlacement` representa localizações de armazém e não deve ser tratado automaticamente como saldo total de retaguarda.
- Integrações ERP/WMS devem consumir o movimento com chave idempotente e devolver confirmação externa; não se deve escrever diretamente no ERP sem contrato e autorização.
- A política de frescura deve ser configurável por loja/fonte e validada com o processo real de inventário.

## Critérios de aceitação

- Não é possível reconciliar tarefas não concluídas, sem quantidade real ou já reconciliadas.
- Não é possível reconciliar com snapshot posterior, desatualizado ou stock disponível insuficiente.
- Duas aprovações concorrentes para a mesma tarefa só produzem um movimento.
- Snapshot anterior permanece inalterado; novo snapshot reflete a quantidade abatida.
- A cronologia da tarefa mostra a reconciliação e permite identificar quem a aprovou.
- Falhas em qualquer escrita deixam movimento, snapshot e auditoria sem alterações parciais.



## Implementação inicial publicada

A primeira implementação está na branch `main` (commit `d602c9427eea47f70a0a5fba3b3d12f0cd689db9`), com testes API aprovados no commit de correção `d3db736d83945028198c54941f4081148474877a`.

- Endpoint: `POST /api/v1/tasks/{task_id}/reconcile-inventory`.
- Apenas utilizadores autenticados com papel `ADMIN` ou `SUPERVISOR`; o supervisor fica limitado à sua loja.
- Exige tarefa `COMPLETED`, quantidade efetiva positiva e motivo da aprovação.
- Rejeita snapshots posteriores à conclusão, ausência de snapshot, evidência com mais de 240 minutos e stock disponível insuficiente.
- Bloqueia a criação concorrente de snapshots/reconciliações através de bloqueio da linha do produto em PostgreSQL.
- Cria um movimento `BACKROOM_TO_SHELF` único por tarefa e um novo snapshot `MANUAL` com referência `TASK-RECONCILIATION-{task_id}`.
- Mantém o snapshot de origem intacto e regista `INVENTORY_RECONCILED` na cronologia da tarefa.
- Movimento, snapshot resultante e evento são gravados na mesma transação.
- A migração `0021_inventory_reconciliation` instala restrições de unicidade e triggers append-only para impedir `UPDATE` e `DELETE` em `inventory_movements`.

## Validação ainda necessária

- Testar duas aprovações simultâneas da mesma tarefa em PostgreSQL 16: exatamente uma resposta 201, uma 409 e um movimento/snapshot/evento.
- Testar falhas entre a criação do snapshot, movimento e evento, confirmando rollback integral.
- Exercitar os triggers append-only com tentativas reais de `UPDATE` e `DELETE` no CI PostgreSQL.
- Tornar a janela de frescura configurável por loja/fonte; os 240 minutos atuais são um limite inicial conservador, não uma política final.
- Validar a reconciliação com operadores e fontes reais antes de a usar como saldo operacional ou integração ERP/WMS.

