# Fusão conservadora de evidência visual e OCR

## Objetivo

Consolidar, por deteção, a correspondência visual de SKU já persistida e a correspondência textual OCR já calculada para a execução OCR concluída mais recente.

## Endpoints

- `POST /api/v1/shelf-images/{image_id}/evidence-fusion`: calcula e persiste os resultados para a última execução OCR concluída.
- `GET /api/v1/shelf-images/{image_id}/evidence-fusion`: consulta o histórico.

A operação POST é idempotente por execução OCR: se já existirem resultados para essa execução, devolve-os sem os recalcular. É reservada a ADMIN/SUPERVISOR; a leitura respeita o âmbito da loja.

## Estados

| Estado | Significado | Tratamento |
|---|---|---|
| `CONSENSUS` | Visão e OCR propõem o mesmo SKU | Sugestão forte, confirmação humana |
| `VISUAL_ONLY` | Só a visão tem correspondência decisiva | Revisão recomendada |
| `TEXT_ONLY` | Só o OCR tem correspondência decisiva | Revisão obrigatória |
| `CONFLICT` | Visão e OCR propõem SKUs diferentes | Revisão prioritária |
| `AMBIGUOUS` | Pelo menos uma fonte fiável tem candidatos próximos | Revisão obrigatória |
| `UNKNOWN` | Não existe candidato utilizável | Sem atribuição automática |

Os scores visuais e textuais não são somados nem tratados como probabilidades equivalentes.

## Proveniência e segurança

Cada resultado guarda os IDs da execução OCR e da deteção, os estados individuais, os candidatos sugeridos, os scores originais e as versões dos modelos/providers. O registo é append-only por par execução/deteção.

Esta fase não altera `ShelfImageDetection.product_id`, catálogo, snapshots, observações, movimentos nem tarefas de stock. A confirmação/correção continua a passar pelo endpoint de revisão humana existente.

## Limitações

A fusão usa apenas o estado visual atualmente persistido em `ShelfImageDetection` e os resultados OCR da mesma imagem/execução. Não executa inferência, não cria embeddings e não valida a qualidade dos modelos. A ausência de OCR associado a uma deteção é tratada como sinal textual desconhecido.


## Fila de revisão humana

O endpoint `GET /api/v1/shelf-image-review-queue` agrega as deteções com fusão persistida que ainda não têm uma decisão humana. Aceita `status`, `limit` e `offset`; o acesso é reservado a ADMIN/SUPERVISOR e os resultados de utilizadores não administradores ficam limitados à sua loja.

Cada item inclui a caixa normalizada da deteção, confiança do detector, estado de fusão, IDs dos candidatos, scores originais e proveniência OCR/visual. O endpoint não devolve o binário da imagem: a interface pode obtê-lo pelo endpoint autenticado de conteúdo da imagem.

A decisão é registada no endpoint existente `POST /api/v1/shelf-image-detections/{detection_id}/reviews`. O histórico de revisão é append-only. A decisão humana não reescreve o resultado original do modelo nem movimenta stock.
