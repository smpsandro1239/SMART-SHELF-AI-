# Avaliação retrospetiva de previsões

O módulo `app.forecast_evaluation` calcula métricas sobre pares de procura observada e prevista, sem consultar nem alterar inventário.

## Contrato dos dados

Cada observação deve representar a mesma combinação de loja, SKU e período:

- `actual`: quantidade efetivamente observada/vendida no período;
- `predicted`: quantidade prevista para exatamente o mesmo período;
- `store_id` e `product_id`: dimensões opcionais para segmentação;
- `period`: identificador opcional do período, útil para rastreabilidade no sistema que prepara os dados.

Os registos sem observação real devem ser omitidos. Nunca preencher lacunas com zero: zero significa procura observada igual a zero, não ausência de dados.

## Métricas

| Métrica | Interpretação |
|---|---|
| MAE | Erro absoluto médio, nas unidades do produto |
| RMSE | Penaliza mais os erros de maior dimensão |
| WAPE | Erro absoluto total dividido pela procura real total |
| Bias | Previsão menos realidade; positivo sobrestima, negativo subestima |
| MAPE | Erro percentual absoluto médio; exclui períodos com realidade zero |

WAPE e MAPE devolvem `None` quando o denominador não permite uma interpretação válida. A contagem de períodos com realidade zero é sempre reportada. As métricas segmentadas por loja e SKU só incluem registos que tenham a respetiva chave.

## Utilização

A partir de `apps/api`:

```python
from app.forecast_evaluation import evaluate_forecasts

result = evaluate_forecasts(
    [
        {
            "store_id": 1,
            "product_id": 42,
            "period": "2026-11-01T10:00",
            "actual": 12,
            "predicted": 10,
        },
        {
            "store_id": 1,
            "product_id": 42,
            "period": "2026-11-01T11:00",
            "actual": 0,
            "predicted": 2,
        },
    ],
    minimum_observations=2,
)
```

O estado `INSUFFICIENT_HISTORY` indica que a amostra não atingiu o mínimo pedido; as métricas disponíveis continuam a ser devolvidas para diagnóstico, mas não devem ser usadas como gate de aceitação.

## Limitações e próximos passos

- O módulo não consulta diretamente tabelas de vendas nem cria previsões.
- O chamador é responsável por alinhar SKU, loja, unidade de medida, granularidade e horizonte temporal.
- A avaliação não corrige censura de procura causada por ruturas, promoções, feriados ou alterações de sortido.
- Não existe ainda baseline comparativa, segmentação temporal automática, intervalos de confiança ou persistência de resultados.
- Antes de usar métricas como critério de ativação, definir amostras mínimas, períodos de teste fora da amostra e limites por categoria/SKU.

Este módulo é uma ferramenta de avaliação offline. Não autoriza encomendas, movimentos de stock nem ativação automática de políticas.
