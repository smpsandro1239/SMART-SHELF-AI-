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


## Integração HTTP inicial (âmbito de prateleira)

O endpoint autenticado `GET /api/v1/shelves/{shelf_id}/observation-consensus` expõe a avaliação de observações repetidas para uma prateleira e respeita o isolamento por loja. Aceita `window_minutes`, `minimum_confirmations`, `minimum_interval_seconds` e `minimum_confidence`. Observações sem confiança são tratadas como evidência não elegível.

**Limite semântico:** o modelo `Observation` referencia apenas `shelf_id`, não um SKU. A API declara `scope: SHELF` e `sku_attribution_available: false`; não replica incorretamente uma observação por todos os produtos da prateleira. A persistência/idempotência de alertas, resolução humana, associação explícita a SKU, integração do worker e calibração com imagens reais continuam pendentes. O endpoint não cria tarefas nem movimenta inventário.
