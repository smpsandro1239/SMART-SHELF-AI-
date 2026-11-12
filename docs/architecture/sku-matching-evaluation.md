# Avaliação offline do matching de SKU

## Objetivo

O módulo `app.sku_matching_evaluation` mede o comportamento do reconhecimento por embeddings antes de escolher thresholds para o worker. Permite comparar combinações de similaridade mínima e margem mínima, incluindo produtos deliberadamente ausentes da galeria.

O avaliador é offline: não consulta nem altera a base de dados operacional, não aprova exemplares, não modifica o catálogo e não atualiza stock.

## Formato do conjunto de avaliação

Criar um ficheiro JSON fora do Git com a estrutura seguinte:

```json
{
  "model_version": "dinov2-small-v1",
  "exemplars": [
    {
      "product_id": 101,
      "embedding": [0.91, 0.12, 0.08],
      "image_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "reviewed_by": "reviewer@example.test",
      "reviewed_at": "2026-10-20T10:00:00Z",
      "licence": "store-owned-reference-image"
    }
  ],
  "queries": [
    {
      "embedding": [0.90, 0.13, 0.07],
      "expected_product_id": 101
    },
    {
      "embedding": [0.02, 0.03, 0.98],
      "expected_product_id": null
    }
  ]
}
```

- `exemplars`: imagens de referência aprovadas, com SKU, embedding, hash, revisor, data e licença.
- `queries`: recortes de avaliação anotados independentemente. `expected_product_id` é o SKU correto ou `null` quando o produto não existe na galeria.
- Todos os embeddings têm de vir da mesma versão de modelo e ter a mesma dimensão.
- O exemplo é ilustrativo; os vetores não são embeddings reais.

**Separação dos dados:** não usar a mesma fotografia, sequência de vídeo ou sessão de captura na galeria e nas queries. Separar por loja, sessão ou período. Escolher thresholds na validação e reservar um conjunto final intocado para avaliação única.

## Execução

A partir de `apps/api`, com as dependências do projeto instaladas:

```bash
python -m app.sku_matching_evaluation --dataset ../../data/sku-evaluation.json --output ../../artifacts/sku-evaluation-report.json
```

Os diretórios `data/` e `artifacts/` são exemplos locais; não versionar imagens comerciais, embeddings ou dados de loja sem autorização.

## Métricas

- `top1_accuracy_known_before_abstention`: acerto do primeiro candidato nos produtos conhecidos, antes de aplicar a abstenção.
- `precision_when_matched`: proporção de matches aceites que correspondem ao SKU esperado. Inclui falsos matches de produtos desconhecidos no denominador.
- `known_product_coverage`: proporção de queries conhecidas às quais o sistema atribuiu algum SKU.
- `known_product_correct_coverage`: proporção de queries conhecidas corretamente identificadas.
- `unknown_rejection_rate`: proporção de produtos ausentes da galeria que acabaram em `UNKNOWN` ou `AMBIGUOUS`.
- `unknown_false_accept_rate`: proporção de produtos ausentes da galeria que receberam um SKU.
- `ambiguous_rate`: proporção total de queries encaminhadas para revisão por proximidade entre candidatos.

O relatório apresenta uma grelha de thresholds (similaridade e margem). Não escolher o ponto com maior cobertura sem considerar falsos matches: em reposição, um SKU errado pode gerar uma tarefa errada e contaminar indicadores operacionais.

## Limitações e critérios de aceitação

1. O avaliador mede apenas a camada de matching; não avalia deteção, localização, OCR ou contagem.
2. A qualidade depende da completude e independência das anotações.
3. Produtos desconhecidos têm de incluir variantes e categorias plausíveis, não apenas imagens aleatórias.
4. Reportar resultados por SKU, família, loja, iluminação, ângulo, oclusão e versão de embalagem num relatório de piloto mais completo.
5. Não promover thresholds para produção apenas com dados sintéticos ou imagens de treino.
6. Manter revisão humana e stock contabilístico independente da inferência.

O módulo não executa modelos nem prova a precisão do DINOv2. É a ferramenta para medir o comportamento quando existirem embeddings reais e um conjunto de avaliação autorizado.


## Avaliação com decisões humanas da operação

O endpoint `GET /api/v1/sku-evaluation/reviewed` disponibiliza métricas agregadas a partir das decisões humanas já registadas. É um complemento operacional ao benchmark offline por embeddings, não o substitui.

Exemplo:

```http
GET /api/v1/sku-evaluation/reviewed?store_id=1&model_version=dinov2-small-v1
```

A resposta inclui:
- precisão dos SKU efetivamente propostos;
- cobertura de produtos conhecidos e cobertura correta;
- produtos conhecidos que o sistema não identificou (abstenções);
- falsos positivos em deteções rejeitadas pelo operador;
- taxa de rejeição de deteções desconhecidas;
- distribuição por estado da fusão e por decisão humana;
- métricas separadas por versão do modelo visual.

**Regra temporal:** para cada deteção, o relatório usa a última decisão humana e a última fusão disponível até ao instante dessa decisão. Uma reanálise posterior não altera retroativamente a previsão avaliada.

**Âmbito:** só entram deteções revistas. O relatório indica quantas deteções revistas não tinham uma fusão correspondente. As métricas não representam uma amostra aleatória: os casos difíceis tendem a ser revistos com maior frequência. Para comparar versões de modelos, manter também um conjunto de teste independente, separado por loja e sessão de captura.

O endpoint é apenas de leitura e está limitado a ADMIN/SUPERVISOR; supervisores ficam confinados à sua loja.
