# ADR-008: correspondência conservadora de SKU por embeddings

- **Estado:** Aceite como contrato técnico inicial; integração persistente pendente.
- **Data:** 2026-11-12

## Contexto

O contrato de visão existente persiste deteções genéricas, mas não oferece um
mecanismo isolado para comparar exemplares de produtos do catálogo. Associar
diretamente uma classe genérica a um SKU cria risco de falsos positivos.

## Decisão

Introduzir `ProductEmbeddingRegistry` como componente independente. Recebe
embeddings e exemplares revistos, compara por similaridade do cosseno e abstém
quando o score ou a margem não são suficientes. Cada exemplar exige
proveniência mínima: SKU, versão do modelo, hash da imagem, revisor, data e
licença.

## Consequências

- Não é escolhida nem instalada uma arquitetura de embeddings nesta decisão.
- Não são descarregados pesos nem utilizados datasets de terceiros.
- Os thresholds são configuráveis e carecem de calibração com dados autorizados.
- O registo inicial é em memória; persistência, revisão humana e integração com
  observações ficam para uma fase posterior.
- Um resultado `UNKNOWN` ou `AMBIGUOUS` nunca atualiza automaticamente o stock.
