# Fluxo operacional de visão, OCR e revisão humana

## Objetivo

Este documento descreve a sequência operacional desde a fotografia até à decisão humana. A arquitetura separa deteção, leitura de texto, matching de catálogo, fusão de evidência e decisão de revisão.

## Configuração opcional do worker

O OCR está desligado por omissão. Para o ativar, instalar as dependências CPU compatíveis e configurar no ambiente do worker:

```dotenv
VISION_PROVIDER_FACTORY=app.vision_onnx:create_provider
OCR_PROVIDER_FACTORY=app.ocr_paddle:create_provider
OCR_PROVIDER_NAME=paddleocr
OCR_MODEL_VERSION=PP-OCRv5-pt
```

Os modelos ONNX de deteção e embeddings têm de existir nos caminhos configurados. O runtime PaddlePaddle e os pesos PaddleOCR devem ser instalados separadamente, de acordo com a plataforma. A configuração de exemplo encontra-se em `apps/api/.env.vision.example`.

Executar o worker a partir de `apps/api`:

```bash
python -m app.vision_worker --once
```

Sem `OCR_PROVIDER_FACTORY`, o worker executa apenas a visão. Se a inicialização ou inferência OCR falhar, a análise visual é preservada e a execução OCR fica marcada como `FAILED`.

## Sequência funcional

1. Carregar a fotografia para `POST /api/v1/shelf-images`.
2. O worker cria deteções visuais e, se configurado, persiste regiões OCR.
3. Cada região OCR é associada geometricamente a, no máximo, uma deteção. Regiões sem sobreposição suficiente ficam `UNASSIGNED`.
4. Calcular matching textual com `POST /api/v1/shelf-images/{image_id}/ocr-matches`.
5. Calcular fusão com `POST /api/v1/shelf-images/{image_id}/evidence-fusion`.
6. Consultar a fila com `GET /api/v1/shelf-image-review-queue`; filtrar por `status`, `limit` e `offset`.
7. Consultar a fotografia e as deteções e submeter a decisão humana em `POST /api/v1/shelf-image-detections/{detection_id}/reviews`.

## Prioridade e decisão

A fila ordena `CONFLICT`, `AMBIGUOUS`, `TEXT_ONLY`, `UNKNOWN` e `VISUAL_ONLY`. `CONSENSUS` também pode ser consultado, mas não é uma aprovação automática.

Uma revisão é um registo append-only. Se for criada nova evidência depois da última revisão, a deteção volta a aparecer na fila. A confirmação/correção valida um SKU ativo associado à prateleira; rejeitar não seleciona SKU.

## Limites de segurança e validade

- O worker nunca atualiza stock nem cria movimentos de inventário.
- OCR e visão não são probabilidades intercambiáveis; os scores são apresentados separadamente.
- A caixa OCR representa texto, não o produto.
- A associação geométrica não garante que o texto pertence semanticamente ao produto; reflexos, etiquetas de preço e cartazes podem exigir revisão.
- A decisão humana não reescreve a saída original do modelo.
- A execução com provider simulado valida integração, não a precisão em imagens reais.
- Antes de um piloto, medir precisão/recall OCR, taxa de associação correta, precisão de SKU quando sugerido, cobertura, taxa de abstenção e tempo médio de revisão num conjunto de imagens autorizado e representativo.
