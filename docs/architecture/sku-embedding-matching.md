# Reconhecimento de SKU por embeddings

## Objetivo

A camada `app.product_matching` compara um embedding fornecido por um
`VisionProvider` com exemplares de produtos previamente revistos. Não carrega
modelos, não descarrega pesos e não assume que uma deteção genérica corresponde
a um SKU do catálogo.

## Fluxo

1. Um provider de visão produz uma deteção e um embedding com uma versão de
   modelo identificada.
2. O registo contém exemplares associados a um `product_id`, com hash da
   imagem de referência, revisor, data de revisão e licença declarada.
3. A comparação usa similaridade do cosseno e conserva apenas a melhor
   pontuação de cada SKU.
4. O resultado é `MATCHED`, `AMBIGUOUS` ou `UNKNOWN`.
5. Apenas `MATCHED`, depois de validação operacional, poderá ser considerado
   para associação ao catálogo. Os outros estados exigem revisão humana.

## Guardrails

- Embeddings vazios, nulos, infinitos, com dimensão errada ou vetor zero são
  rejeitados.
- Os exemplares têm de usar a mesma versão do modelo.
- O mesmo SKU não pode ocupar várias posições no ranking por ter várias fotos.
- Um score abaixo do limiar produz `UNKNOWN`.
- Uma margem pequena entre os dois melhores SKUs produz `AMBIGUOUS`.
- A ausência de deteções nunca significa, por si só, prateleira vazia.
- O registo é atualmente em memória: não é ainda uma tabela persistente nem um
  serviço de indexação vetorial.

## Calibração antes de produção

Os valores por omissão (`minimum_similarity=0.90` e
`minimum_margin=0.05`) são apenas valores conservadores para testes de
contrato. Não são métricas de precisão nem thresholds certificados. Devem ser
calibrados com imagens reais autorizadas, separadas por loja, produto, sessão
de captura e condições de iluminação. A avaliação deve incluir falsos matches,
taxa de abstention, top-1 accuracy e cobertura por SKU.

## Próxima integração

A próxima fase deverá persistir os exemplares e a sua proveniência, expor uma
ação de revisão humana e ligar o resultado aceite ao fluxo de deteções. Não se
deve preencher automaticamente `Observation.observed_quantity` até existir
uma contagem validada por SKU e uma política explícita de agregação.
