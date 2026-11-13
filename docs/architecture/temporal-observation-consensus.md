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
