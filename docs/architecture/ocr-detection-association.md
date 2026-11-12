# Associação de regiões OCR a deteções de produto

## Objetivo

Uma imagem de prateleira pode conter vários produtos lado a lado. O texto
reconhecido deve ser atribuído à deteção correta, e não comparado globalmente
com o catálogo, porque isso pode associar a marca de um produto ao SKU do
produto vizinho.

## Algoritmo

`app.product_ocr_association.associate_ocr_regions`:

1. Recebe caixas de produto e regiões OCR, todas normalizadas entre 0 e 1.
2. Calcula a fração da área de cada região OCR coberta por cada caixa de produto.
3. Atribui a região à caixa com maior cobertura, desde que ultrapasse
   `minimum_region_coverage` (predefinição: 0.5).
4. Se houver empate, prefere a caixa de produto mais pequena, útil em deteções
   aninhadas.
5. Cada região OCR é atribuída no máximo a uma deteção; regiões sem cobertura
   suficiente ficam sem associação.

As linhas de texto de cada deteção são ordenadas de cima para baixo e da
esquerda para a direita. O texto combinado conserva a menor confiança OCR das
linhas, em vez de esconder uma linha fraca através de uma média.

## Correção do contrato PaddleOCR

A integração usa `rec_polys` em paralelo com `rec_texts` e `rec_scores`.
Não usa `dt_polys` para este alinhamento: este último pode conter caixas
detetadas que não sobreviveram ao filtro de reconhecimento. Esta distinção
está descrita na documentação PaddleOCR 3.x.

## Limites

- É uma associação geométrica, não uma identificação de SKU.
- Produtos sobrepostos, caixas de deteção muito grandes e texto fora da frente
  da embalagem podem gerar associações erradas ou nenhuma associação.
- Não existe ainda persistência das regiões OCR no modelo de dados.
- O worker não chama OCR nesta fase.
- A associação deve ser avaliada com imagens anotadas antes de ligar o pipeline.
