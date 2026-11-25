# Ledger de eventos dos movimentos de inventário

## Contexto

`inventory_movements` é o registo imutável da transferência aprovada de stock WMS para uma prateleira. O histórico da tarefa e o ledger de reconciliação têm âmbitos diferentes e não substituem a proveniência própria do movimento.

## Decisão

A migration `0087_inventory_movement_event_ledger` introduz `inventory_movement_events`, um ledger append-only ligado ao movimento e à sua `operation_id`. Cada evento congela loja, actor, motivo, tipo, timestamp e evidência estruturada. A base de dados verifica que movimento, operação, loja, actor e motivo coincidem antes de aceitar o evento e impede UPDATE/DELETE em PostgreSQL e SQLite.

A primeira fase grava `MOVEMENT_RECORDED` na mesma transacção que cria o snapshot resultante, o movimento e o evento da tarefa. Se a inserção do evento falhar, toda a reconciliação é revertida. A leitura é disponibilizada em `GET /api/v1/inventory/movements/{movement_id}/events`, limitada a ADMIN e SUPERVISOR com isolamento por loja e ocultação de IDs estrangeiros.

## Tipos previstos

- `MOVEMENT_RECORDED`: criação do movimento interno aprovado.
- `WMS_CONFIRMATION_RECORDED`: confirmação externa correlacionada com a operação.
- `COMPENSATION_RECORDED`: referência a movimento compensatório, sem editar o movimento original.
- `DISCREPANCY_RECORDED`: evidência de divergência que exige reconciliação.

Só `MOVEMENT_RECORDED` é produzido nesta fase. Os restantes tipos são reservados ao desenvolvimento posterior; não representam ainda integração WMS nem compensações implementadas.

## Limites e evolução

O endpoint actual é read-only. A confirmação WMS requer adapter homologado, identidade idempotente da confirmação e evidência externa validada. As compensações exigem regras de quantidade/unidade e autorização específicas. Não se infere que o snapshot `MANUAL` resultante seja confirmação do WMS. A migration preserva os movimentos históricos; não inventa eventos anteriores nem proveniência ausente.
