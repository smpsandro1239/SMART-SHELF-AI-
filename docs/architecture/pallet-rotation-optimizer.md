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


## Planeamento de janela de baixa afluência

O módulo `app/pallet_rotation_windows.py` escolhe uma janela contínua de 1 a
4 horas nas próximas 24 horas. Compara a afluência média histórica e verifica
se a quantidade residual cobre o consumo médio por hora até ao fim da operação.
Cada hora considerada tem de atingir o mínimo configurado de dias observados.
Ausência de dados nunca é convertida em zero.

Endpoint:
`GET /api/v1/warehouse/pallet-rotation/window-plan`

A hora atual é a hora local da loja e é fornecida explicitamente pelo chamador.
O algoritmo é determinístico e heurístico: não prevê vendas futuras, não usa
tráfego em tempo real e não agenda tarefas. O resultado é consultivo e não
executa qualquer movimento.


## Dados horários e desempenho de consulta

As tabelas `hourly_sales_records` e `hourly_store_traffic_records` têm
índices compostos orientados às consultas por loja, produto (quando aplicável),
data e hora. A recolha separa vendas por SKU da contagem global de clientes da
loja, evitando replicar o tráfego por produto.

Os registos horários usam a data e hora local de negócio fornecidas pelo POS.
O projeto ainda não guarda um identificador de fuso horário por loja; a
integração deve normalizar os dados de origem e respeitar alterações de hora
legal antes de importar. Os valores zero devem ser enviados explicitamente;
ausência de registo permanece desconhecida.


## Importação em lote e critérios de qualidade

Os endpoints `/api/v1/sales/hourly/batch` e
`/api/v1/sales/traffic/hourly/batch` recebem até 500 observações por pedido.
Um lote pertence a uma só loja e não pode repetir a chave externa. A persistência
é atómica; qualquer colisão na base de dados rejeita o lote completo.

O planeador exige cobertura mínima de vendas e tráfego em todas as 24 horas
antes de classificar uma janela como a de menor afluência. Esta restrição é
deliberadamente conservadora: sem cobertura global, o sistema não conhece
alternativas potencialmente mais calmas. Valores negativos, não finitos ou
ausência de observações não são convertidos em zeros.


## Consulta dos registos de origem

Os endpoints GET `/api/v1/sales/hourly` e
`/api/v1/sales/traffic/hourly` permitem auditar as observações importadas,
filtrando por loja e intervalo de datas; as vendas permitem ainda filtrar SKU.
As respostas são limitadas a 1000 linhas por pedido e ordenadas por data/hora
descendente. A consulta é read-only e respeita o âmbito de loja.


## Importação CSV horária

Foram adicionados importadores CSV para vendas por SKU e contagem de clientes.
Ambos limitam os ficheiros a 5 MB e 5000 linhas, validam UTF-8, cabeçalhos,
datas ISO, horas 0–23, valores não negativos e referências externas únicas.
A persistência só começa após validação completa e é atómica. Os zeros são
preservados como observações explícitas; não são fabricadas linhas para horas
ausentes.


O perfil por dia da semana seleciona uma única origem (`source`, por
predefinição `POS`) para não somar contagens possivelmente sobrepostas entre
POS, ERP e sensores. A comparação de fontes deve ser feita em pedidos
separados.


A lista é ordenada por prioridade operacional e depois por código/posição de prateleira. O atributo `route_order` é calculado independentemente pela ordem estável das prateleiras. Prioridade de execução não é uma rota física otimizada.


O perfil de 24 horas e o planeador de janela também filtram por uma única
origem (`source`, predefinição `POS`). O mesmo valor é aplicado a vendas e
afluência para impedir que contagens duplicadas entre origens sejam somadas.
Registos importados com origem `IMPORT` requerem `source=IMPORT`.


## Baseline de previsão horária

O endpoint `GET /api/v1/forecasting/hourly-demand` produz um baseline sazonal
por dia da semana e hora. Agrega registos por data/hora, utiliza as últimas
observações do mesmo dia da semana e aplica pesos decrescentes à antiguidade.
O número mínimo de observações é configurável; sem cobertura suficiente,
`predicted_units` permanece `null`.

A resposta inclui uma versão explícita do método e backtesting rolling-origin
com MAE e WAPE quando há pontos suficientes. Este componente é uma referência
estatística transparente, não uma alegação de IA treinada nem uma previsão
validada em produção. Não altera inventário, não cria tarefas e não executa
movimentos físicos.


## Deteção de picos históricos de afluência

O módulo `app/traffic_peak_detection.py` compara cada combinação de dia da
semana/hora com a média das horas observadas desse mesmo dia. Uma célula só é
classificada quando cumpre a cobertura mínima e existe número suficiente de
horas para formar a linha de base. Zeros explícitos são preservados e horas
ausentes não são imputadas. O resultado é histórico, não previsão de tráfego,
e não desencadeia qualquer movimento ou tarefa.
