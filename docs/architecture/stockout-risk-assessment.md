# Avaliação explicável do risco de rutura

## Objetivo

Converter uma previsão de procura válida e uma quantidade de stock disponível numa banda operacional de risco. O módulo é independente da API, do POS/ERP e da visão computacional.

Não calcula uma probabilidade estatística de rutura. Os níveis são regras determinísticas, transparentes e configuráveis. Não cria tarefas, encomendas nem movimentos de stock.

## Entradas

- available_quantity: stock disponível (stock físico menos reservas), proveniente de uma fonte de inventário identificada.
- average_daily_demand: procura diária média estimada pelo módulo demand_forecasting.
- lead_time_days: prazo de abastecimento.
- safety_stock: stock de segurança calculado pela previsão.
- forecast_status: tem de ser FORECAST_READY para classificar risco.
- warning_cover_days: margem adicional para aviso antecipado (por omissão, dois dias).

## Regras

| Nível | Regra |
|---|---|
| CRITICAL | Stock disponível igual a zero ou stock projetado negativo à data de receção |
| HIGH | Stock projetado à receção abaixo do stock de segurança |
| MEDIUM | Cobertura de stock até ao prazo de abastecimento mais a margem de aviso |
| LOW | Cobertura superior ao prazo e margem, preservando o stock de segurança |
| UNKNOWN | Histórico/previsão insuficiente ou procura média nula |

Stock projetado à receção = stock disponível - procura média diária × prazo de abastecimento.

Dias de cobertura = stock disponível / procura média diária.

## Utilização

    from app.stockout_risk import StockoutRiskInput, assess_stockout_risk

    risk = assess_stockout_risk(StockoutRiskInput(
        available_quantity=20,
        average_daily_demand=5,
        lead_time_days=3,
        safety_stock=8,
    ))
    print(risk.risk_level)

## Salvaguardas

- Não converter histórico incompleto em procura zero.
- Não confundir stock visual estimado com inventário contabilístico.
- Não classificar procura média zero como risco baixo.
- Manter origem, timestamp e idade do inventário no serviço chamador.
- Validar os limiares com dados históricos reais antes de usar para priorização automática.
- Exigir revisão operacional antes de qualquer encomenda ou movimento.

## Limitações

A regra atual não modela sazonalidade, promoções, procura censurada por ruturas, devoluções, substituição entre produtos, atrasos variáveis de fornecedor ou incerteza probabilística do prazo. A classificação é uma camada de apoio à decisão e não uma previsão calibrada de probabilidade.
