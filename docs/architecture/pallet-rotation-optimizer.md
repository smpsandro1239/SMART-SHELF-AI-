# Pallet Rotation & Peak Replenishment Optimizer

## Objetivo

Avaliar se uma palete parcialmente consumida deve ser trocada por uma palete
completa preparada durante um período de elevada afluência. A palete parcial
pode regressar à retaguarda para recomposição posterior, desde que sejam
preservadas a rastreabilidade, a segurança e a capacidade de armazenamento.

A primeira implementação é um motor determinístico de simulação. Não executa
operações de inventário.

## Decisões possíveis

- **SWAP_PALLET**: limiar atingido, afluência elevada, palete de substituição
  disponível, capacidade segura na retaguarda, cobertura de procura até à
  próxima janela de baixa afluência e custo laboral inferior.
- **REPLENISH_CURRENT**: manter a palete atual; o limiar não foi atingido,
  a afluência é baixa ou falta um recurso operacional.
- **REPLENISH_CURRENT** com motivo INTERIM_REPLENISHMENT_REQUIRED: o stock
  residual não cobre a procura até à próxima janela; é necessária reposição
  intermédia para evitar rutura.
- **INSUFFICIENT_DATA**: faltam dados críticos de tráfego, procura, duração ou custo.
- **NOT_ECONOMICAL**: a troca não reduz o custo laboral estimado.
- **NOT_ELIGIBLE**: produto não configurado para exposição/troca por palete.

O limiar de 50% é apenas um valor inicial configurável, não uma regra universal.

## Modelo de custo

Todas as quantidades usam a unidade base do produto. Os tempos são fornecidos
em minutos e o custo de mão de obra em moeda por hora:

- custo convencional = minutos de reposição convencional × custo/hora ÷ 60;
- custo de troca = (tempo de troca + transporte + recomposição) × custo/hora ÷ 60.

A primeira versão só compara mão de obra. Ainda não contabiliza equipamento,
ocupação do espaço, danos, perdas, interrupção da circulação ou risco de serviço.
Um resultado favorável é um candidato a piloto, não prova de ROI total positivo.

## Dados necessários

O chamador tem de fornecer quantidade residual, capacidade da palete, limiar,
classe de afluência, disponibilidade da palete completa, capacidade segura na
retaguarda, tempos medidos, custo laboral e consumo previsto até à próxima
janela de baixa afluência. Dados em falta produzem INSUFFICIENT_DATA; o motor
não inventa tráfego nem procura.

## Requisitos antes de executar movimentos reais

Uma futura operação deve identificar cada palete e preservar SKU, loja,
lote, validade, quantidade residual, localização e estado. FIFO/FEFO e
compatibilidade de lotes têm de ser respeitados ao recompor paletes parciais.
Devem ainda ser validados estabilidade, peso/altura, equipamento, segurança
de clientes e trabalhadores, temperatura e localização de retaguarda.

## Limites da implementação atual

O motor recebe inputs explícitos e devolve uma recomendação. Não cria tarefas,
não reserva paletes, não altera stock, não regista movimentos, não estima
afluência a partir de vendas diárias e não afirma otimizar percursos físicos.
A integração futura deverá acrescentar identidade individual de paletes,
políticas por loja/produto, histórico de eventos e dados horários validados.
Movimentos físicos terão de ser uma operação separada, auditada e autorizada.

## Plano de validação

Começar com produtos seguros e efetivamente expostos em palete, como água,
bebidas e papel. Comparar reposição convencional e troca em janelas de tráfego
equivalentes. Medir duração das tarefas, deslocação, recomposição, ocupação da
retaguarda, disponibilidade, ruturas e incidentes. Expandir apenas quando o
custo total e o nível de serviço melhorarem.


## Integração consultiva com paletes registadas

`POST /api/v1/warehouse/pallet-rotation/simulate` liga o motor às
paletes físicas e à política ativa por loja/produto. A simulação só aceita
paletes `ON_DISPLAY` ou `PARTIAL` localizadas em
`SALES_FLOOR`.

A palete substituta tem de ser do mesmo produto e nível PALLET, estar em
`READY` numa localização `WAREHOUSE` ou
`PREPARATION`, ter quantidade igual à capacidade integral e não
estar expirada. Quando existem várias, a seleção dá prioridade à validade
mais próxima (FEFO), depois à data de registo. A substituição pode ter outro
lote: as duas paletes permanecem unidades rastreáveis separadas; não se permite
misturar lotes.

O pedido fornece afluência, previsão de consumo até à próxima janela baixa,
tempos e custo laboral. Não são inferidos a partir de vendas diárias. A
capacidade da retaguarda é também uma confirmação explícita do operador,
porque ainda não existe modelo físico integrado para a validar.

A resposta identifica a palete de exposição, a substituta candidata, a
política e a decisão do motor. A operação é estritamente read-only: não reserva
a palete candidata, não cria tarefa, não muda estado nem regista movimento.
Apenas uma futura operação de execução, com confirmação por scan e controlo
transacional, poderá fazê-lo.
