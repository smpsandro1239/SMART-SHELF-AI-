# Persistência de evidência OCR

## Modelo de dados

A migração `0014_shelf_image_ocr_evidence` acrescenta duas tabelas:

- `shelf_image_ocr_runs`: uma execução OCR por imagem, com provider, versão
  do modelo, estado e autor quando existe.
- `shelf_image_ocr_evidence`: uma linha por região reconhecida, com texto
  original, texto normalizado, confiança, caixa normalizada e associação
  opcional a uma deteção.

Uma região sem deteção associada é guardada como `UNASSIGNED`; não é descartada.
Uma região com `detection_id` válido fica `ASSIGNED`. O endpoint valida que
todas as deteções pertencem à mesma imagem. As execuções e regiões são
append-only ao nível desta API: uma nova inferência cria um novo run, em vez
de sobrescrever resultados anteriores.

## API

### Criar uma execução

`POST /api/v1/shelf-images/{image_id}/ocr-runs`

Requer papel ADMIN ou SUPERVISOR. Exemplo:

```json
{
  "provider": "paddleocr",
  "model_version": "PP-OCRv5-pt",
  "regions": [
    {
      "detection_id": 42,
      "text": "Leite Meio-Gordo 1 L",
      "confidence": 0.93,
      "x_min": 0.2,
      "y_min": 0.2,
      "x_max": 0.6,
      "y_max": 0.3
    },
    {
      "detection_id": null,
      "text": "PROMOÇÃO",
      "confidence": 0.72,
      "x_min": 0.01,
      "y_min": 0.01,
      "x_max": 0.1,
      "y_max": 0.05
    }
  ]
}
```

O corpo aceita até 1000 regiões. As coordenadas e confiança são validadas
entre 0 e 1. O texto normalizado remove acentos e pontuação, mantendo dígitos.

### Consultar evidência

- `GET /api/v1/shelf-images/{image_id}/ocr-evidence`
- `GET /api/v1/shelf-images/{image_id}/ocr-runs`

Os resultados respeitam o âmbito da loja do utilizador. Colaboradores podem
consultar evidência OCR, mas apenas ADMIN/SUPERVISOR podem registar novas
execuções OCR.

## Limites nesta fase

- O endpoint recebe resultados já produzidos; não executa PaddleOCR.
- O worker ainda não está ligado a esta API.
- A associação `detection_id` é validada contra a imagem, mas a geometria tem
  de ser calculada previamente pelo módulo
  `product_ocr_association.associate_ocr_regions`.
- Não é persistida uma decisão de matching OCR/SKU nesta migração.
- Nenhuma evidência OCR atualiza `ShelfImageDetection.product_id), stock,
  observações ou tarefas de reposição.
- Uma execução vazia pode ser guardada para documentar uma inferência sem
  regiões legíveis; erros de inferência ainda não têm endpoint de registo.

## Aplicar migração

```bash
cd apps/api
alembic upgrade head
```

Antes de produção, fazer backup e aplicar primeiro num ambiente de staging.
