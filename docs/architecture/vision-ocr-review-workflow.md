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
4. Depois de persistir uma execução OCR concluída, o worker chama automaticamente o serviço `app.product_pipeline.process_completed_ocr_run`: cria correspondências textuais contra produtos ativos e funde-as com os resultados visuais.
5. O matching e a fusão são executados num savepoint isolado. Uma falha nesta fase é registada, mas não invalida as deteções visuais nem as regiões OCR já persistidas.
6. O serviço é idempotente: preserva correspondências e fusões existentes e cria apenas os registos em falta. Os endpoints `POST /api/v1/shelf-images/{image_id}/ocr-matches` e `POST /api/v1/shelf-images/{image_id}/evidence-fusion` continuam disponíveis para execução manual.
7. Consultar os totais por estado em `GET /api/v1/shelf-image-review-queue/summary` e a fila em `GET /api/v1/shelf-image-review-queue`; filtrar por `status`, `limit` e `offset`.
8. Consultar a fotografia e as deteções e submeter a decisão humana em `POST /api/v1/shelf-image-detections/{detection_id}/reviews`.

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


## Interface de operação

O dashboard React apresenta a fila de revisão a administradores e supervisores, com contagens por estado, prioridade, identificação da fotografia e motivo da decisão. A ação **Abrir fotografia e rever** leva à captura correspondente, onde o operador pode consultar as caixas de deteção, os produtos atribuídos à prateleira e o histórico de decisões humanas.

A fila do dashboard carrega até 50 itens prioritários. O endpoint suporta paginação por `limit` e `offset`; a navegação de todas as páginas pode ser adicionada quando o volume operacional o justificar.

## Recuperação de tarefas de inferência interrompidas

O worker reencaminha tarefas `PROCESSING` abandonadas para `PENDING` quando `analysis_started_at` é anterior ao limite configurado em `VISION_PROCESSING_TIMEOUT_SECONDS` (24 horas por omissão; intervalo permitido de 60 segundos a 7 dias). Apenas imagens com retenção `ACTIVE` são elegíveis. O mecanismo limpa os timestamps de execução e conserva uma indicação de recuperação em `analysis_error`. Imagens recentes e imagens `RESTRICTED` não são recuperadas. A recuperação é executada antes de cada procura de novo trabalho.

## Exclusão de resultados de leases expirados

Cada tentativa de processamento fica identificada pelo valor de `analysis_started_at` gravado quando a imagem é reclamada. Após a inferência, o worker bloqueia e atualiza a leitura da linha (`populate_existing`) e verifica que o estado continua `PROCESSING` e que o timestamp ainda pertence à sua tentativa. Se o timeout tiver reencaminhado a tarefa e outro worker a tiver reclamado, a tentativa anterior termina sem persistir deteções ou evidência OCR. A mesma verificação é repetida antes de marcar a imagem como `COMPLETED`. O teste `test_worker_discards_result_when_processing_lease_changes_during_inference` cobre a substituição do lease durante a inferência. A validação CI ainda está pendente.
