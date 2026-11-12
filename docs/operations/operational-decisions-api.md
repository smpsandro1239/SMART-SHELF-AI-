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

Quando existem vendas registadas, a previsão baseline de 24 horas é a média aritmética das quantidades diárias registadas na janela de sete dias. É uma baseline deliberadamente simples: não ajusta sazonalidade, promoções, tráfego, feriados ou dias em falta. A resposta identifica explicitamente o método e a janela.

## Segurança operacional

- Não cria tarefas nem altera inventário.
- Não faz movimentos automáticos.
- Não interpreta ausência de vendas ou de inventário como stock zero.
- Uma observação de prateleira pode abranger vários produtos; por isso é um sinal de contexto da prateleira e não uma contagem individual de SKU.
- A quantidade sugerida só é calculada com inventário e previsão recentes e válidos.
- O endpoint inclui contagens por estado e os dados de evidência usados em cada decisão.

## Próxima integração

A interface web pode consumir este endpoint para apresentar exceções e recomendações explicáveis. A criação de tarefa deve continuar a passar pelo fluxo existente de aprovação/validação e pelas verificações de duplicação e stock.
