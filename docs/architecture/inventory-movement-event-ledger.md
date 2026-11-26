# Ledger de eventos dos movimentos de inventário

## Contexto

`inventory_movements` é o registo imutável da transferência aprovada de stock WMS para uma prateleira. O histórico da tarefa e o ledger de reconciliação têm âmbitos diferentes e não substituem a proveniência própria do movimento.

## Decisão

A migration `0087_inventory_movement_event_ledger` introduz `inventory_movement_events`, um ledger append-only ligado ao movimento e à sua `operation_id`. Cada evento congela loja, actor, motivo, tipo, timestamp e evidência estruturada. A base de dados exige sempre a identidade exacta do movimento, operação e loja. Para MOVEMENT_RECORDED, também exige actor e motivo iguais aos do movimento aprovado; eventos externos posteriores podem ter actor e motivo próprios. UPDATE/DELETE são bloqueados em PostgreSQL e SQLite.

A primeira fase grava `MOVEMENT_RECORDED` na mesma transacção que cria o snapshot resultante, o movimento e o evento da tarefa. Se a inserção do evento falhar, toda a reconciliação é revertida. A leitura é disponibilizada em `GET /api/v1/inventory/movements/{movement_id}/events`, limitada a ADMIN e SUPERVISOR com isolamento por loja e ocultação de IDs estrangeiros.

## Tipos previstos

- `MOVEMENT_RECORDED`: criação do movimento interno aprovado.
- `WMS_CONFIRMATION_RECORDED`: confirmação externa correlacionada com a operação.
- `COMPENSATION_RECORDED`: referência a movimento compensatório, sem editar o movimento original.
- `DISCREPANCY_RECORDED`: evidência de divergência que exige reconciliação.

Só `MOVEMENT_RECORDED` é produzido nesta fase. Os restantes tipos são reservados ao desenvolvimento posterior; não representam ainda integração WMS nem compensações implementadas.

## Limites e evolução

O endpoint actual é read-only. A confirmação WMS requer adapter homologado, identidade idempotente da confirmação e evidência externa validada. As compensações exigem regras de quantidade/unidade e autorização específicas. Não se infere que o snapshot `MANUAL` resultante seja confirmação do WMS. A migration preserva os movimentos históricos; não inventa eventos anteriores nem proveniência ausente.


## Concorrência da reconciliação de movimentos

A reconciliação serializa operações do mesmo produto através do lock da linha de produto e bloqueia o snapshot WMS seleccionado. A quantidade utilizável é calculada como on-hand menos reservas e movimentos já registados a partir do mesmo snapshot. O movimento, o snapshot MANUAL resultante, o evento `MOVEMENT_RECORDED` e o evento da tarefa são confirmados numa única transacção.

O smoke `apps/api/scripts/postgres_inventory_movement_concurrency_smoke.py` cria duas tarefas concluídas para o mesmo SKU/loja e disputa simultaneamente a mesma evidência WMS em PostgreSQL 16. O cenário reserva uma unidade e disponibiliza seis: duas reposições de quatro unidades não podem ambas ser aprovadas. O resultado esperado é exactamente um movimento de quatro unidades, saldo resultante de três unidades on-hand com uma reservada, um evento de movimento e rejeição da segunda operação por stock insuficiente. O smoke repete ainda o pedido vencedor e exige conflito idempotente com referência ao movimento já existente.

A existência do script e do passo CI não equivale a validação; só um workflow verde no SHA exacto confirma o cenário. O smoke inclui ainda uma falha injectada com SQLSTATE de violação de integridade durante a inserção do evento; exige rollback de movimento, snapshot resultante e evento da tarefa. O smoke não homologa adapters WMS nem define conversões entre unidade, caixa e palete.


## Disponibilidade obrigatória da origem WMS

A migration `0088_inventory_movement_available_source_guard` reforça o trigger de proveniência da migration 0086. Para movimentos novos, a relação tarefa → prateleira → loja e snapshot → loja/produto/WMS/localização tem também de provar `availability_status=AVAILABLE`. `UNAVAILABLE`, `UNKNOWN` e NULL falham fechados ao nível da base de dados, mesmo em INSERT directo fora da API.

A regra não reinterpreta snapshots históricos nem altera o ledger existente. A política de frescura continua a ser avaliada pelo serviço porque depende da configuração `InventoryFreshnessPolicy` da loja.


## Unidade base e precisão decimal (migration 0089)

A unidade base já existe no catálogo como `Product.unit` e é usada pelos níveis logísticos através de `base_units_per_package`. A migration `0089_inventory_movement_base_unit_snapshot` acrescenta `InventoryMovement.unit_code`: novos movimentos têm de guardar exactamente a unidade do produto no momento da inserção. O trigger PostgreSQL/SQLite rejeita unidade ausente, vazia ou diferente da unidade base do SKU.

A coluna é nullable apenas para preservar movimentos históricos sem inferir a unidade retroactivamente. A quantidade é Decimal sobre `NUMERIC(12,3)`; a API mantém `quantity` numérico para compatibilidade e acrescenta `quantity_exact` textual para transporte sem perda. A API de conclusão da tarefa rejeita escalas superiores a três casas decimais antes de persistir `actual_quantity`; a reconciliação mantém uma segunda validação defensiva para dados legados. Não existe conversão implícita entre unidades ou embalagens.


## Quantidades exactas no planeamento logístico

O cálculo de embalagens já opera internamente com Decimal. A API mantém os campos numéricos legados e acrescenta representações textuais exactas para quantidade necessária, factor por embalagem, quantidade solta, quantidade planeada e excesso. O parâmetro de entrada é interpretado como Decimal desde a query string. A regra é apenas de planeamento: `automatic_stock_movement_allowed=false` permanece obrigatório; o cálculo nunca cria movimentos.


## Quantidades fraccionárias de exposição (migration 0090)

O contrato de exposição também tem de respeitar a unidade base do SKU. `ShelfProduct.target_quantity` e `min_display_quantity` são agora `Decimal/Numeric(12,3)`, não inteiros. A migration 0090 converte os valores inteiros históricos sem alteração de valor. O downgrade só é permitido quando todos os valores forem integrais; caso contrário falha explicitamente para impedir truncagem. O limite de três casas decimais é consistente com os movimentos de inventário.
