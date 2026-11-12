# API de portefólio de rotação de paletes

## Endpoint

`GET /api/v1/warehouse/pallet-rotation/portfolio`

Parâmetros:
- `store_id` — loja consultada; utilizadores não ADMIN ficam limitados à sua loja.
- `traffic_level` — `HIGH`, `LOW` ou `UNKNOWN`, fornecido pelo operador.
- `forecast_consumption_until_low_traffic` — consumo estimado em unidades base até à próxima janela calma, fornecido pelo operador.
- `backroom_capacity_available` — confirmação explícita do operador; por omissão é `false`.
- `conventional_minutes`, `swap_minutes`, `transport_minutes`, `rebuild_minutes` — estimativas operacionais em minutos.
- `limit` — máximo de recomendações, entre 1 e 500.

## Dados obtidos pela API

A API seleciona paletes `ON_DISPLAY` ou `PARTIAL` em `SALES_FLOOR`, políticas ativas da loja e níveis de embalagem `PALLET`. Procura substitutas `READY`, completas, na mesma loja, produto e nível de embalagem, localizadas em `WAREHOUSE` ou `PREPARATION`, sem validade expirada. A ordenação de substitutas é feita pelo planeador individual de simulação; o portefólio limita-se a confirmar a existência de uma substituta elegível.

## Limites deliberados

- A afluência, consumo previsto, tempos e capacidade de retaguarda são inputs explícitos do operador. Ainda não são obtidos automaticamente de sensores, POS ou ERP.
- A confirmação booleana de capacidade não substitui a validação geométrica de volume, peso, temperatura, fragilidade e segregação da localização.
- O endpoint não reserva paletes, não cria tarefas, não altera estados, não movimenta inventário e não executa trocas.
- Resposta inclui `simulation_only=true` e `automatic_stock_movement_allowed=false`.
- O endpoint é consultivo e não deve ser interpretado como autorização operacional para executar movimentos físicos.

## Exemplo

```http
GET /api/v1/warehouse/pallet-rotation/portfolio?store_id=1&traffic_level=HIGH&forecast_consumption_until_low_traffic=120&backroom_capacity_available=true&conventional_minutes=24&swap_minutes=4&transport_minutes=3&rebuild_minutes=5&limit=100
```
