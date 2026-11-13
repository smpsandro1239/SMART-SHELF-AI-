# API de decisões operacionais

## Endpoint

`GET /api/v1/operational-decisions`

Parâmetros opcionais:
- `store_id`: loja a consultar (administradores podem omitir para consultar todas).
- `shelf_id`: limitar a uma prateleira.
- `product_id`: limitar a um produto.
- `limit`: máximo de pares produto/prateleira devolvidos (1–500).

A consulta é apenas de leitura. Colaboradores não podem consultar o motor global; supervisores ficam limitados à sua loja. Administradores podem consultar uma loja específica ou todas.

## Evidência usada

Para cada par produto/prateleira, a API reúne a observação mais recente da prateleira, o snapshot mais recente de stock de retaguarda, tarefas ativas e vendas diárias dos últimos sete dias. O snapshot de retaguarda é apresentado separadamente e não é usado como quantidade física na prateleira.

Quando existem vendas registadas, a previsão baseline de 24 horas é a média aritmética das quantidades por dia com registos na janela de sete dias. Dias sem registos não são tratados como dias de venda zero. É uma baseline deliberadamente simples: não ajusta sazonalidade, promoções, tráfego ou feriados. A resposta identifica explicitamente o método e a janela.

## Segurança operacional

- Não cria tarefas nem altera inventário.
- Não faz movimentos automáticos.
- Não interpreta ausência de vendas ou de inventário como stock zero.
- Uma observação de prateleira pode abranger vários produtos; por isso é um sinal de contexto da prateleira e não uma contagem individual de SKU.
- A quantidade sugerida só é calculada com inventário e previsão recentes e válidos.
- O endpoint inclui contagens por estado e os dados de evidência usados em cada decisão.

## Próxima integração

A interface web pode consumir este endpoint para apresentar exceções e recomendações explicáveis. A criação de tarefa deve continuar a passar pelo fluxo existente de aprovação/validação e pelas verificações de duplicação e stock.


## Cobertura estimada do inventário

Quando existe previsão válida, o motor calcula as horas de cobertura estimada:
`inventário disponível / procura média por hora`. Uma recomendação por risco de procura é emitida quando a cobertura fica abaixo ou igual ao limiar configurado (12 horas por omissão). Este indicador é uma estimativa, não uma garantia de disponibilidade física.


## Ordenação e prioridade operacional

A resposta é ordenada para colocar primeiro recomendações que exigem ação, depois trabalho já em execução, evidência insuficiente e itens em monitorização. Dentro das recomendações, prioridade alta precede prioridade normal; quando existe cobertura estimada, a menor cobertura aparece primeiro.

A prioridade alta exige uma observação de estado EMPTY recente e com confiança suficiente, ou uma previsão válida de cobertura com inventário disponível igual a zero. Um estado EMPTY antigo ou de baixa confiança não pode, por si só, elevar a prioridade.

A resposta inclui `priority_counts`, permitindo ao dashboard distinguir quantidade de ações recomendadas e quantidade de ações de prioridade alta.


## Resumo de prioridades por zona

A resposta inclui `zone_summaries`, agregando as decisões por loja e zona sem misturar zonas com o mesmo nome em lojas diferentes. Cada resumo apresenta referências avaliadas, recomendações, prioridades altas, tarefas já em execução, situações sem evidência e itens em monitorização.

A ordenação das zonas favorece primeiro as que têm mais prioridades altas e recomendações; a menor cobertura estimada desempata quando existe informação suficiente. Cada zona inclui até três referências recomendadas para consulta rápida. Este resumo não altera tarefas, inventário nem atribuições de colaboradores.


## Separação entre exposição e retaguarda

Os registos `InventorySnapshot` representam stock de retaguarda (em mão, reservado e disponível). Não representam uma contagem da exposição. Por isso, o endpoint de decisões operacionais não os injeta no motor como inventário da prateleira nem calcula cobertura de exposição a partir deles.

O campo `backroom_inventory` apresenta as quantidades e a data da captura, mantendo explícita a origem. A observação visual EMPTY/LOW_STOCK pode justificar avaliação operacional, mas não permite deduzir uma quantidade exata a repor. Para uma proposta quantitativa, usar o fluxo de recomendações de reposição, que combina quantidade observada na prateleira, quantidade-alvo e stock disponível na retaguarda.
