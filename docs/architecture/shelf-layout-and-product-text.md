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


## Células calibradas e deteção de posições vazias

O módulo também disponibiliza `ShelfCell`, `ShelfCellObservation` e `compare_detections_to_cells` para comparar caixas normalizadas com células explícitas fornecidas por uma calibração de câmara ou planograma revisto. Cada célula tem um identificador estável, limites normalizados, SKU esperado opcional, número de facings esperado e indicadores de visibilidade/oclusão. `expected_facings` é opcional, tem de ser positivo e exige SKU esperado. Por segurança, `is_visible` começa em `false`: a calibração tem de confirmar explicitamente que a região está observável.

Estados devolvidos:

- `OCCUPIED`: existe deteção identificada e, quando configurado, o número de facings observados coincide com o esperado.
- `UNDER_FACED`: foram observados menos facings do SKU esperado do que o planograma prevê.
- `OVER_FACED`: foram observados mais facings do SKU esperado do que o planograma prevê.
- `OCCUPIED_UNIDENTIFIED`: existe deteção, mas não há SKU identificado.
- `EMPTY`: existe deteção positiva com label `empty_facing`, confiança igual/superior ao limiar configurado e intersecção geométrica suficiente; a célula também tem de estar explicitamente visível e não ocluída.
- `MISPLACED`: a célula tem SKU esperado e pelo menos uma deteção identificada aponta para outro SKU.
- `CONFLICT`: a mesma célula recebe evidência de produto e de espaço vazio; o comparador não escolhe silenciosamente uma das hipóteses.
- `UNKNOWN`: não há deteções, a evidência de vazio tem confiança insuficiente, falta visibilidade calibrada ou a célula está ocluída.

A associação usa a fracção da área da célula coberta pela caixa e limiares configuráveis. O limiar de confiança para `empty_facing` é 0,80 por omissão e deve ser calibrado com dados reais. O resultado preserva os índices das deteções, IDs observados, facings esperados/observados e sobreposição para permitir rastreabilidade. `observed_facings` conta apenas objetos de produto detectados na frente; não estima unidades em profundidade, retaguarda ou stock contabilístico. **A ausência de deteção nunca declara uma célula vazia**: sem evidência positiva de `empty_facing`, o estado é `UNKNOWN`. Uma célula criada sem visibilidade explicitamente confirmada também começa em `UNKNOWN`.

**Limites actuais:** este é um comparador geométrico puro, sem persistência, API de planogramas, segmentação automática de prateleiras ou integração no worker. As células têm de ser fornecidas por uma fonte calibrada/revista. Os estados são evidência visual, não stock contabilístico, e não criam movimentos nem tarefas.
