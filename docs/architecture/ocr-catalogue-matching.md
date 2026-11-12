# Matching OCR com o catálogo de produtos

## Objetivo

Converter texto OCR associado a uma deteção numa lista explicável de candidatos
do catálogo, sem atribuir automaticamente um SKU à deteção.

## Sinais usados

O motor `rank_product_catalogue_candidates` considera:

- semelhança entre o texto observado e nome/designação do produto;
- tokens da marca;
- correspondência exata ou parcial do SKU quando este aparece no texto;
- conflitos entre variantes relevantes (por exemplo, Zero vs Original);
- conflitos entre números de embalagem (por exemplo, 500 ml vs 1,5 l).

As razões são devolvidas por candidato. As pontuações servem para ordenar
candidatos; não são probabilidades calibradas e não devem ser apresentadas como
percentagem de certeza.

## Estados

- `SUGGESTED`: candidato acima do limiar e suficientemente separado do segundo.
- `AMBIGUOUS`: existem candidatos próximos; não é selecionado um produto.
- `UNKNOWN`: nenhum candidato ultrapassa o limiar.

Os valores iniciais são `minimum_score=0.68` e `minimum_margin=0.10`.
Devem ser calibrados com imagens e catálogo reais antes de qualquer utilização
operacional. Evidência OCR com confiança inferior a 0.65 não é usada para
sugerir SKU no endpoint.

## API

- `POST /api/v1/shelf-images/{image_id}/ocr-matches`: calcula uma vez os
  candidatos para a execução OCR concluída mais recente e guarda o resultado.
- `GET /api/v1/shelf-images/{image_id}/ocr-matches`: consulta o histórico.

O cálculo agrupa as regiões OCR pelo `detection_id`. Usa apenas produtos
ativos. O resultado guardado inclui texto observado, confiança mínima das
regiões, estado, pontuação, margem e até cinco candidatos com razões.

A criação é idempotente para a mesma execução OCR: se já existirem resultados
para essa execução, a API devolve-os sem recalcular. Uma nova execução OCR
permite gerar um novo conjunto de resultados.

## Segurança e limites

- A criação exige ADMIN ou SUPERVISOR; leitura respeita o âmbito da loja.
- Apenas regiões já associadas a uma deteção entram no matching.
- Não há aprovação automática nem alteração de `ShelfImageDetection.product_id`.
- Não são criadas tarefas nem movimentos de stock.
- O catálogo atual não contém atributos estruturados de volume/variante em
  todos os produtos; por isso, a extração de características de embalagem é
  heurística e depende do texto.
- A API não executa PaddleOCR: consome evidência já persistida.
- As pontuações necessitam de calibração offline com ground truth antes de
  definir thresholds de produção.

## Migração

```bash
cd apps/api
alembic upgrade head
```

A migração `0015_shelf_image_ocr_matches` depende da migração
`0014_shelf_image_ocr_evidence`.
