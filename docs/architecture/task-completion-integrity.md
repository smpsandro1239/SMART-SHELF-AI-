# Integridade da conclusão e exceções de tarefas

## Objetivo

Garantir que a conclusão ou o cancelamento de uma tarefa de reposição deixa um registo operacional útil, consistente e auditável. Uma tarefa não pode ser dada como concluída sem quantidade efetivamente reposta; uma conclusão parcial ou cancelamento exige um motivo humano legível.

## Regras aplicadas pela API

O endpoint `PATCH /api/v1/tasks/{task_id}/status` aplica as seguintes regras:

- A transição para `COMPLETED` exige `actual_quantity` positiva e finita.
- Quando existe `requested_quantity`, a quantidade efetiva não pode excedê-la.
- Uma conclusão parcial exige `exception_reason` com pelo menos três caracteres não brancos.
- A transição para `CANCELLED` exige igualmente um motivo com pelo menos três caracteres não brancos.
- Um motivo fornecido é normalizado com `strip()` antes de ser persistido na tarefa e no evento de auditoria.
- Motivos com espaços ou tabulações apenas são rejeitados com HTTP 422 e código `EXCEPTION_REASON_TOO_SHORT`.
- Uma transição inválida ou uma validação falhada não altera o estado da tarefa nem acrescenta um evento.
- A alteração de estado e o respetivo evento de auditoria são confirmados na mesma transação.

## Porque é necessária a normalização

A validação de comprimento do schema Pydantic conta espaços como caracteres. Sem uma validação semântica adicional, um valor como `"   "` poderia satisfazer o comprimento mínimo e tornar-se um motivo aparentemente preenchido, mas sem informação operacional. A validação no handler elimina esse caso e garante que tarefa e evento guardam o mesmo texto normalizado.

## Cobertura de regressão

A suite `apps/api/tests/test_tasks.py` cobre:

- rejeição de conclusão parcial com motivo composto apenas por espaços/tabulações;
- rejeição de cancelamento com motivo composto apenas por espaços;
- preservação do estado e da cronologia após validação rejeitada;
- remoção de espaços periféricos antes da persistência e auditoria;
- conclusão parcial com motivo válido;
- quantidade efetiva obrigatória e limite máximo igual à quantidade pedida;
- rollback conjunto de estado e evento quando a escrita da auditoria falha.

A regressão foi validada na suite completa de API e no smoke PostgreSQL 16 do API CI run `43411545120`; os testes de regressão de motivos são executados na suite API, enquanto o smoke PostgreSQL confirma a cadeia operacional e as invariantes de concorrência.

## Limites conhecidos

- A API regista a quantidade efetivamente reposta, mas a reconciliação contabilística continua a ser uma operação distinta, aprovada por ADMIN/SUPERVISOR.
- A conclusão da tarefa não altera automaticamente o inventário.
- A interface web ainda precisa de apresentar os campos de quantidade real e motivo com validação equivalente antes de enviar a transição.
