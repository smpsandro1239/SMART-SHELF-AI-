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
