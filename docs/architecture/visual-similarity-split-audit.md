# Auditoria de semelhança visual entre splits

## Objetivo

Detetar fotografias iguais ou quase iguais colocadas em conjuntos diferentes, mesmo quando a compressão, o formato ou uma pequena alteração de enquadramento mudam o SHA-256.

## Método

- Normalizar orientação EXIF.
- Converter para escala de cinzentos e reduzir para 9 × 8 píxeis.
- Calcular dHash de 64 bits por comparação horizontal.
- Comparar com distância de Hamming através de uma BK-tree.
- Registar pares dentro do mesmo split como informação e bloquear pares entre splits até revisão.

## Execução

```bash
cd apps/api
python -m app.image_similarity_audit \
  --train /data/images/train \
  --val /data/images/val \
  --test /data/images/test \
  --max-distance 6 \
  --json-report /data/reports/visual-similarity.json
```

## Interpretação

A distância 0 indica o mesmo hash perceptual; valores pequenos indicam imagens estruturalmente semelhantes. O valor 6 é apenas um ponto de partida, não um limiar universal. Fotografias diferentes da mesma prateleira podem legitimamente ser semelhantes, pelo que os pares encontrados devem ser revistos e o limiar calibrado num conjunto representativo antes do gate de produção.

Este método não deteta de forma fiável duplicados semânticos com grandes mudanças de perspetiva, iluminação ou composição. Não substitui SHA-256, agrupamento por sessão, revisão humana, direitos de utilização nem controlos de privacidade.


## Relatórios de qualidade consumíveis por máquina

Ambos os auditores escrevem agora `status` (`passed` ou `failed`) e a lista `errors` no JSON. A criação de uma release exige `status: passed` e `errors: []` nos dois relatórios; relatórios antigos sem estes campos devem ser regenerados.

## Registo imutável de release

`app.dataset_release` valida as entradas do manifest, exige os três splits, calcula uma fingerprint SHA-256 determinística e grava um JSON em `<registry>/releases/<fingerprint>.json`. O registo inclui contagens, hashes de proveniência e o equilíbrio de classes devolvido pela auditoria COCO. A operação é idempotente. Nesta fase o registo é local e não tem assinatura criptográfica, controlo de acesso, retenção remota ou promoção automática de modelos.

```bash
cd apps/api
python -m app.dataset_release \
  --manifest /data/metadata/image_manifest.csv \
  --split-audit /data/reports/split-audit.json \
  --visual-audit /data/reports/visual-similarity.json \
  --registry /data/dataset-registry
```


A release também regista instâncias por classe e por split. Classes sem exemplos num dos conjuntos são apresentadas como avisos; é possível transformar esse requisito num gate bloqueante com `--min-class-instances N`. O número mínimo de imagens por split é configurável com `--min-images-per-split N` (por omissão, 1).