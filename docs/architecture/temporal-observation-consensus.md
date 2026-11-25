# Consenso temporal de observações

O módulo `app.observation_consensus` fornece uma função determinística para avaliar evidência repetida de uma única combinação loja/prateleira/SKU. O chamador tem de filtrar previamente os registos para esse âmbito; o módulo não consulta a base de dados nem agrega entidades diferentes.

## Contrato

`evaluate_observation_consensus(observations, now=...)` recebe observações com `status`, `observed_at`, `confidence` e, opcionalmente, `source`.

- Considera apenas `LOW_STOCK`, `EMPTY`, `MISPLACED` e `DAMAGED`.
- Exclui observações fora da janela, no futuro ou abaixo da confiança mínima.
- Exige confirmações temporalmente espaçadas para reduzir a inflação provocada por frames consecutivos.
- Devolve `CONFLICT` quando existem estados concorrentes com suporte suficiente; não escolhe arbitrariamente.
- Expõe primeira/última ocorrência, número de confirmações, confiança média e fontes.
- Não cria alertas persistidos, tarefas, movimentos nem altera stock.

## Exemplo

```python
from datetime import datetime, timezone
from app.observation_consensus import evaluate_observation_consensus

result = evaluate_observation_consensus(
    observations,
    now=datetime.now(timezone.utc),
    window_minutes=15,
    minimum_confirmations=3,
    minimum_interval_seconds=10,
    minimum_confidence=0.65,
)
```

Os valores por omissão são parâmetros iniciais conservadores, não thresholds calibrados. Antes da integração no motor/API, é necessário validar a janela, intervalo e confiança com imagens reais autorizadas, associar a evidência à identidade do SKU e implementar persistência/idempotência do alerta. O módulo não está ainda ligado ao worker nem às decisões operacionais.


## Integração HTTP — âmbito de prateleira e SKU

O endpoint autenticado `GET /api/v1/shelves/{shelf_id}/observation-consensus` expõe a avaliação de observações repetidas para uma prateleira e respeita o isolamento por loja. Aceita `window_minutes`, `minimum_confirmations`, `minimum_interval_seconds` e `minimum_confidence`. Observações sem confiança são tratadas como evidência não elegível.

**Atribuição explícita:** `Observation.product_id` é opcional para preservar registos legados. Quando fornecido, a API exige que o produto esteja ativo e associado explicitamente à prateleira através de `ShelfProduct`; caso contrário responde HTTP 422. A migração `0026_observation_product_attribution` acrescenta a FK anulável com `ON DELETE SET NULL`. O endpoint aceita `product_id` e avalia apenas esse SKU (`scope: SHELF_SKU`, `sku_attribution_available: true`). Sem `product_id`, avalia exclusivamente observações legadas sem SKU, evitando misturar produtos diferentes. O isolamento por loja continua a ser aplicado antes da avaliação. A persistência/idempotência de alertas, resolução humana, integração do worker e calibração com imagens reais continuam pendentes. O endpoint não cria tarefas nem movimenta inventário.


A consulta limita o custo de leitura às 500 observações mais recentes por prateleira. A seleção é feita em ordem descendente e os registos são reordenados cronologicamente antes da avaliação; desta forma, o limite não pode ocultar evidência recente atrás de um histórico antigo. A regressão correspondente semeia mais de 500 observações antigas e confirma que as três confirmações recentes continuam a ser avaliadas.


## Persistência idempotente e resolução humana de alertas

A migração `0027_observation_alerts` acrescenta `observation_alerts` e `observation_alert_events`. Apenas evidência com consenso `CONFIRMED` e SKU explícito pode originar um alerta. O endpoint `POST /api/v1/shelves/{shelf_id}/observation-alerts/evaluate?product_id=...` cria ou atualiza o alerta ativo da combinação loja/prateleira/SKU/condição. Um índice único parcial em PostgreSQL e SQLite impede duplicados ativos; o bloqueio da linha da loja serializa a avaliação concorrente em PostgreSQL. A mesma avaliação repetida atualiza a evidência existente, em vez de criar novo alerta.

Os alertas podem ser consultados por `GET /api/v1/observation-alerts`, reconhecidos por `PATCH /api/v1/observation-alerts/{id}` com estado `ACKNOWLEDGED`, ou resolvidos/dispensados com motivo obrigatório. Apenas ADMIN/SUPERVISOR podem executar estas operações e o âmbito da loja é aplicado. O histórico é consultável em `GET /api/v1/observation-alerts/{id}/events`; a tabela de eventos é append-only em PostgreSQL e SQLite.

A persistência não cria tarefas, não altera inventário e não movimenta stock. A avaliação continua a ser explícita via endpoint; a integração automática no worker permanece pendente. A migração e os testes de concorrência em PostgreSQL 16 devem passar antes de qualquer piloto.
