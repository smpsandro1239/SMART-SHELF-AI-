# Política operacional — troca de paletes e meias-paletes

**Estado:** especificação alinhada com o simulador de rotação existente  
**Data:** 12-11-2026

## Objetivo

Para produtos cuja exposição e reposição são feitas por palete, evitar reposições manuais repetidas de pequenas quantidades. Quando a palete em exposição já perdeu pelo menos metade da sua capacidade, o sistema pode propor a retirada da palete parcial e a colocação de uma palete completa preparada na retaguarda.

A regra não se aplica automaticamente a todos os produtos. Cada produto/loja deve estar explicitamente configurado para rotação por palete.

## Regra quantitativa

O limiar é calculado sobre a quantidade residual, não sobre a quantidade vendida:

`residual_ratio = residual_base_units / pallet_capacity_base_units`

Com o limiar predefinido de 0,50:

- 720 unidades na palete, 360 restantes: atingiu exatamente 50% residual; pode entrar na avaliação de troca.
- 720 unidades, 361 restantes: ainda tem mais de 50%; mantém-se a palete atual.
- 720 unidades, 300 restantes: tem menos de 50%; pode entrar na avaliação de troca.

A igualdade faz parte do limiar: `residual_ratio <= threshold_ratio`. O limiar é configurável por produto e loja.

## Condições obrigatórias antes de propor a troca

Atingir o limiar é apenas o início da decisão. O simulador deve ainda confirmar:

1. Produto configurado como elegível para rotação por palete.
2. Nível de afluência conhecido; com dados desconhecidos, não recomendar uma ação física.
3. Existência de uma palete completa em estado READY e disponível para substituição.
4. Capacidade segura na retaguarda para receber a palete parcial.
5. Quantidade residual suficiente para cobrir o consumo previsto até à próxima janela de baixa afluência. Caso contrário, recomendar reposição intermédia da palete atual.
6. Comparação de tempos e custo de mão de obra: reposição convencional versus troca, incluindo transporte e recomposição da palete parcial.

A troca só é recomendada quando todas as condições operacionais são satisfeitas e o custo estimado de mão de obra da troca é inferior ao da reposição convencional.

## Exemplo

Palete original: 720 unidades. Quantidade observada/confirmada restante: 360 unidades. A palete de substituição está preparada e a retaguarda tem espaço.

- O limiar de 50% foi atingido.
- O sistema verifica a procura prevista até à janela operacional adequada.
- Calcula o tempo de retirar a palete parcial, transportar e colocar a palete completa.
- Compara esse custo com o tempo de repor manualmente a palete atual.
- Se a troca for mais económica e segura, apresenta `SWAP_PALLET`; caso contrário, apresenta a razão concreta para manter a palete atual.

## Estados e significado

| Resultado | Interpretação |
|---|---|
| `SWAP_PALLET` | Troca completa recomendada, sujeita a execução autorizada |
| `REPLENISH_CURRENT` | Manter a palete atual e repor/intervir nela |
| `NOT_ECONOMICAL` | A troca não reduz o custo estimado |
| `NOT_ELIGIBLE` | Produto não configurado para rotação |
| `INSUFFICIENT_DATA` | Faltam dados fiáveis para decidir |

## Segurança operacional e rastreabilidade

- Uma recomendação nunca movimenta stock por si só.
- A palete parcial não é descartada: deve regressar a uma localização de retaguarda/preparação, mantendo lote, validade e quantidade residual.
- A palete nova tem de ser identificada e validada antes de ir para a área de venda.
- As alterações de estado/localização devem usar o ciclo de vida da palete, motivo da operação e estado/quantidade esperados para evitar atualizações concorrentes silenciosas.
- A quantidade da palete deve ser expressa na unidade base do produto; a capacidade vem do nível de embalagem configurado.
- Se a observação visual não tiver confiança e frescura suficientes, exigir confirmação humana antes de alterar quantidades ou estados.
- Não inferir unidades em profundidade apenas a partir de uma fotografia frontal.

## Implementação existente e limites

A lógica consultiva está em `apps/api/app/pallet_rotation.py`; a escolha de janela de baixa afluência está em `apps/api/app/pallet_rotation_windows.py`. O modelo suporta limiar configurável por produto/loja e o pedido de simulação recebe tempos, custos, disponibilidade da palete e consumo previsto até à janela de baixa afluência.

Os testes de fronteira validam o limiar exato de 50%, a configuração de outro limiar e o bloqueio quando não existe palete pronta. Esta política não significa que exista uma integração automática com ERP/WMS, robô ou equipamento de loja. A execução física e a atualização contabilística continuam fora do simulador e exigem integração autorizada, registo de eventos e validação operacional.

## Próximos passos técnicos

1. Ligar a previsão horária validada ao cálculo de consumo até à janela escolhida, sem converter horas sem dados em zero.
2. Expor no dashboard a explicação, limiar, quantidade residual, recursos em falta e custo comparado.
3. Acrescentar um fluxo explícito de aprovação e execução, com operador responsável e confirmação das duas paletes.
4. Validar o processo em ambiente de teste com produtos e embalagens reais antes de qualquer piloto em loja.


## API e integração atualmente disponível

Os endpoints de simulação e planeamento existentes são:

- `POST /api/v1/warehouse/pallet-rotation/simulate`: avalia uma palete individual, consulta uma palete substituta completa em estado READY e devolve a decisão sem movimentar stock.
- `GET /api/v1/warehouse/pallet-rotation/portfolio`: ordena várias paletes de uma loja.
- `GET /api/v1/warehouse/pallet-rotation/weekday-hourly-profile`: devolve médias históricas por dia da semana/hora, separando vendas e tráfego.
- `GET /api/v1/warehouse/pallet-rotation/window-plan`: sugere uma janela de baixa afluência a partir do histórico e verifica se a quantidade residual cobre o consumo até essa janela.
- `GET /api/v1/forecasting/hourly-demand`: calcula um baseline sazonal de procura por dia da semana e hora, com backtest rolling-origin.

**Limitação atual a resolver:** o endpoint de portfolio recebe um único nível de afluência, consumo previsto até à janela e confirmação de capacidade da retaguarda como parâmetros fornecidos pelo operador; aplica esses valores a todas as paletes candidatas da loja. Não é ainda uma decisão autónoma, individualizada por SKU e palete. O forecast horário também é um endpoint separado e não alimenta automaticamente o portfolio nem o simulador individual.

### Próxima integração técnica

1. Obter, para cada palete candidata, a política ativa, embalagem, quantidade residual e palete substituta elegível.
2. Construir a procura horária específica da loja/SKU e escolher a janela com o histórico de tráfego da loja.
3. Calcular o consumo esperado desde o instante atual até à janela selecionada, exigindo cobertura histórica suficiente e mantendo valores em falta como desconhecidos.
4. Executar a avaliação económica por palete, usando tempos e custos específicos por operação/loja quando existirem; não reutilizar silenciosamente um custo global como se fosse medido por SKU.
5. Devolver uma decisão individual, proveniência dos dados, confiança/cobertura, razões de exclusão e campos que exigem confirmação humana.
6. Só depois de aprovação explícita criar tarefa de execução; a confirmação da troca deve reconciliar as duas paletes e atualizar o inventário através de integração autorizada.

A integração deve ter testes de contrato para: histórico incompleto, forecast sem cobertura, palete substituta parcial, substituta expirada, stock residual insuficiente até à janela, duas paletes do mesmo SKU, ausência de capacidade na retaguarda e dados alterados entre simulação e aprovação.
