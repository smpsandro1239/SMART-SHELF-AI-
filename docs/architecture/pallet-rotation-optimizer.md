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
- **WAIT_FOR_LOW_TRAFFIC**: o stock residual não cobre a procura prevista até
  à próxima janela de baixa afluência.
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
