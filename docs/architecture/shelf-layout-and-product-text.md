# Localização geométrica de filas e frentes visíveis

O módulo `app.shelf_layout` agrupa deteções com caixas normalizadas em filas
horizontais. Usa a sobreposição vertical entre caixas e ordena posições da
esquerda para a direita.

## Saída e interpretação

- `ShelfRow.row_index`: índice da fila estimada, de cima para baixo.
- `ShelfPosition.detection_index`: índice da deteção original.
- `ShelfPosition.product_id`: SKU associado pela camada de matching, ou
  `null` quando desconhecido.
- `ShelfRow.visible_facings`: número de objetos detetados na frente da fila.

**Limitação importante:** `visible_facings` é uma contagem de deteções frontais,
não uma estimativa de unidades em profundidade nem do stock disponível. Uma
caixa pode corresponder a um produto parcialmente oculto ou a uma deteção
duplicada. A qualidade depende da deteção e da perspetiva da câmara.

O limiar de sobreposição vertical é heurístico (por omissão, 0,35) e deve ser
calibrado com imagens anotadas da loja. Não representa uma distância física
entre prateleiras, nem deteta automaticamente as tábuas/limites físicos.

## OCR auxiliar

O módulo `app.product_text` define o contrato `OCRText`, normalização de
texto e ranking de candidatos do catálogo. Não instala nem escolhe um motor
OCR. A normalização preserva palavras de variante e números (por exemplo,
“Zero”, “Original”, “1.5 L”). Os resultados são `SUGGESTED`, `AMBIGUOUS` ou
`UNKNOWN`; mesmo `SUGGESTED` é apenas uma pista para combinar com embeddings,
localização e revisão humana.

A pontuação textual não é uma probabilidade. O OCR pode confundir caracteres,
perder palavras pequenas, unidades e separadores decimais. Não se deve aprovar
um SKU nem alterar quantidades contabilísticas com base apenas no texto.

## Próxima integração

A etapa seguinte é acrescentar um provider OCR real, preservar as caixas
normalizadas dos textos reconhecidos e combinar evidências visuais/textuais
numa camada de decisão calibrada com imagens reais. O worker atual não chama
estes módulos automaticamente.


## Fusão de evidências

A combinação de resultados visuais e OCR está especificada em [Fusão de evidências para identificação de SKU](product-evidence-fusion.md). A camada devolve sugestões conservadoras e não altera os registos persistidos.


## Provider OCR opcional

O adaptador PaddleOCR experimental e os passos de instalação isolada estão documentados em [Provider OCR PaddleOCR](paddleocr-provider.md). Ainda não existe integração no worker nem inferência real validada.
