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
- Os exemplares têm persistência relacional em `product_embedding_exemplars`; o vetor é guardado como JSON e não existe ainda um índice vetorial dedicado.
- A criação começa sempre em `PENDING`; só supervisores/administradores podem registar e rever exemplares em ambiente autenticado.
- A revisão regista o utilizador e o instante da decisão; a mesma entrada só pode ser revista uma vez.
- Quando a captura de origem é indicada, o hash SHA-256 tem de coincidir com o ficheiro registado.
- A API não devolve os vetores nos endpoints de leitura.

## Calibração antes de produção

Os valores por omissão (`minimum_similarity=0.90` e
`minimum_margin=0.05`) são apenas valores conservadores para testes de
contrato. Não são métricas de precisão nem thresholds certificados. Devem ser
calibrados com imagens reais autorizadas, separadas por loja, produto, sessão
de captura e condições de iluminação. A avaliação deve incluir falsos matches,
taxa de abstention, top-1 accuracy e cobertura por SKU.

## API de persistência e revisão

- `POST /api/v1/product-embedding-exemplars`: regista um vetor em estado `PENDING`.
- `GET /api/v1/product-embedding-exemplars`: filtra por produto, estado e versão do modelo.
- `PATCH /api/v1/product-embedding-exemplars/{id}/review`: aprova ou rejeita um exemplar pendente.

O corpo de criação exige `product_id`, `embedding`, `model_version`, `image_sha256` e `licence`; `shelf_image_id` é opcional. Exemplo ilustrativo:

```json
{
  "product_id": 12,
  "shelf_image_id": 31,
  "embedding": [0.12, 0.34, 0.56],
  "model_version": "embedding-model-v1",
  "image_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "licence": "store-owned-reference-image"
}
```

A resposta não inclui o vetor. A aprovação é feita separadamente com `review_status` igual a `APPROVED` ou `REJECTED` e notas opcionais. Em ambiente autenticado, apenas `ADMIN` e `SUPERVISOR` podem aceder a estes endpoints; os supervisores ficam limitados aos exemplares associados à sua loja ou criados por si quando não existe captura associada.

## Próxima integração

A fase seguinte deverá carregar apenas exemplares aprovados para o motor de correspondência, garantir que a versão/dimensão do embedding coincide e ligar o resultado à revisão de deteções. Não se deve preencher automaticamente `Observation.observed_quantity` até existir uma contagem validada por SKU e uma política explícita de agregação.
