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

Para cada par produto/prateleira, a API reúne a observação mais recente da prateleira, o snapshot de inventário mais recente da loja/produto, tarefas ativas e vendas diárias dos últimos sete dias.

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
