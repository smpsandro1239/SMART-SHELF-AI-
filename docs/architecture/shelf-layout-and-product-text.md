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

O módulo também disponibiliza `ShelfCell` e `compare_detections_to_cells` para comparar caixas normalizadas com células explícitas fornecidas por uma calibração de câmara ou planograma revisto. Cada célula tem um identificador estável, limites normalizados, SKU esperado opcional e indicadores de visibilidade/oclusão.

Estados devolvidos:

- `OCCUPIED`: existe pelo menos uma deteção associada à célula.
- `OCCUPIED_UNIDENTIFIED`: existe deteção, mas não há SKU identificado.
- `EMPTY`: não existe deteção e a célula foi explicitamente marcada como visível e não ocluída.
- `MISPLACED`: a célula tem SKU esperado e as deteções identificadas apontam para outro SKU.
- `UNKNOWN`: não há calibração explícita de visibilidade, a célula está fora de vista ou está ocluída.

A associação usa a fracção da área da célula coberta pela caixa e um limiar configurável. O resultado preserva os índices das deteções e os IDs observados para permitir rastreabilidade. Uma célula criada sem visibilidade explicitamente confirmada começa em `UNKNOWN`; ausência de deteção nunca é suficiente, por si só, para declarar vazio.

**Limites actuais:** este é um comparador geométrico puro, sem persistência, API de planogramas, segmentação automática de prateleiras ou integração no worker. As células têm de ser fornecidas por uma fonte calibrada/revista. Os estados são evidência visual, não stock contabilístico, e não criam movimentos nem tarefas.
