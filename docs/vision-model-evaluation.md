# Protocolo de avaliação de Computer Vision

## Estado

Foi implementado um avaliador COCO v1 e um runner que executa o provider ONNX assinado apenas sobre um *test split* de um release aprovado para inferência. O código e os testes ainda necessitam de CI verde. Não existe neste momento um dataset real autorizado nem resultados de precisão que possam ser publicados.

## Preparação do dataset

- Formato COCO com `images`, `annotations` e `categories`.
- Cada imagem deve incluir `id`, `file_name`, `width`, `height` e SHA-256 em minúsculas.
- Cada anotação deve incluir `image_id`, `category_id`, `bbox` absoluta COCO `[x, y, width, height]` e `iscrowd=0`.
- As categorias têm IDs e nomes consistentes em train/val/test; os nomes têm de corresponder exactamente aos labels do modelo.
- Separar por loja, sessão de captura ou sequência antes de criar os splits. O auditor existente reconhece `capture_group_id`, `capture_group_key`, `capture_session_id` e `sequence_id`, além de nomes de ficheiro e hashes, e bloqueia grupos que atravessem splits.
- O dataset precisa de proveniência, direitos de utilização, revisão de privacidade, revisão visual, aprovação técnica e aprovação para inferência. Usar o release gate existente; não executar directamente o runner sobre dados não aprovados.

## Execução

O runner deve ser chamado como consumidor síncrono de `app.dataset_execution`, com `--mode inference`, para que a aprovação e os bloqueios de retenção permaneçam activos durante toda a execução.

Exemplo conceptual (substituir os caminhos pelos artefactos do release aprovado):

```bash
VISION_PROVIDER_MODE=real \
VISION_CONFIDENCE_THRESHOLD=0.0 \
python -m app.dataset_execution \
  --manifest /datasets/manifest.csv \
  --split-audit /datasets/split-audit.json \
  --visual-audit /datasets/visual-audit.json \
  --provenance-manifest /datasets/provenance.json \
  --release-record /datasets/release-record.json \
  --train /datasets/instances_train.json \
  --val /datasets/instances_val.json \
  --test /datasets/instances_test.json \
  --registry /datasets/registry \
  --mode inference \
  -- python scripts/evaluate_vision_model.py \
    --annotations /datasets/instances_test.json \
    --images-root /datasets/images \
    --output /reports/vision-evaluation.json \
    --operating-threshold 0.25
```

O runner exige as variáveis de contexto do release aprovado, a aprovação explícita para inferência, manifesto ONNX Ed25519 válido, keyring confiável e SHA-256 coerentes. O provider deve usar `VISION_CONFIDENCE_THRESHOLD=0.0` para que o cálculo AP receba todas as detecções; `--operating-threshold` é independente e mede o ponto operacional escolhido.

## Métricas e interpretação

- AP por classe com interpolação de precisão em 101 níveis de recall.
- `mAP50` e `mAP50_95`, média macro por classes com pelo menos uma instância ground-truth.
- Precision, recall e F1 no ponto operacional definido por confidence threshold e IoU 0.50.
- Contagens TP/FP/FN, número de imagens/anotações/predições e resultados por classe.
- Identidade do release, fingerprint do dataset, versão do modelo, SHA-256 e versão de pré-processamento no relatório.

A versão 1 rejeita anotações COCO `iscrowd` em vez de as tratar incorrectamente como objectos comuns. Classes sem ground-truth são reportadas com AP `null` e excluídas da média macro. Resultados não representam stock físico, disponibilidade, poupança ou impacto comercial.

## Requisitos antes de publicar resultados

1. Dataset com autorização e licença verificadas; imagens anonimizadas e EXIF/GPS removidos.
2. Anotações com protocolo versionado, dupla revisão amostral e resolução de desacordos.
3. Splits separados por loja/sessão e auditorias de hash, grupo e semelhança visual aprovadas.
4. Baseline comparável, thresholds definidos em validation e test set intocado até avaliação final.
5. Relatório completo por classe, loja/cenário, iluminação, oclusão e resolução; latência p50/p95 medida separadamente.
6. Repetição independente e revisão humana dos falsos positivos/falsos negativos críticos.

Sem pesos autorizados, dataset aprovado e execução verificável, não publicar métricas nem activar o provider real em operação.
