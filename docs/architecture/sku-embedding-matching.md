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

Os valores por omissão (`PRODUCT_MATCHING_MIN_SIMILARITY=0.90` e
`PRODUCT_MATCHING_MIN_MARGIN=0.05`) são configuráveis no ambiente do worker.
O primeiro define a semelhança mínima do melhor candidato; o segundo define a
diferença mínima entre os dois melhores SKUs. Valores mais exigentes reduzem
matches automáticos e aumentam a abstenção. São apenas valores conservadores para testes de
contrato. Não são métricas de precisão nem thresholds certificados. Devem ser
calibrados com imagens reais autorizadas, separadas por loja, produto, sessão
de captura e condições de iluminação. As variáveis são lidas pelo worker no
arranque; alterar o `.env` exige reiniciar o worker. A avaliação deve incluir falsos matches,
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

## Revisão humana das deteções

O worker já usa `app.product_embedding_service.build_approved_product_registry` para carregar apenas exemplares `APPROVED`, com identidade de revisor ainda disponível e versão exata do modelo. O registo é reutilizado durante o processamento de cada imagem.

Endpoints:
- `POST /api/v1/shelf-image-detections/{detection_id}/reviews`
- `GET /api/v1/shelf-image-detections/{detection_id}/reviews`

Decisões suportadas:
- `CONFIRMED`: confirma o SKU proposto; `selected_product_id` é opcional e, por omissão, usa o SKU da deteção.
- `CORRECTED`: exige `selected_product_id` para selecionar outro SKU.
- `REJECTED`: rejeita a associação e não aceita `selected_product_id`.

Nas confirmações e correções, o produto tem de estar ativo e atribuído à prateleira da imagem. Os endpoints são restritos a administradores e supervisores, com validação do âmbito da loja.

Cada decisão cria um registo em `detection_sku_reviews`, incluindo SKU original, SKU selecionado, revisor, data e notas. As decisões anteriores não são alteradas e a deteção original do modelo não é sobrescrita. A chave estrangeira do SKU selecionado impede a eliminação de produtos ainda referenciados no histórico.

Esta revisão manual ainda não alimenta `Observation.observed_quantity`, não conta unidades automaticamente e não substitui uma avaliação de visão com imagens reais anotadas.
## Avaliação offline

Antes de selecionar thresholds para o worker, usar o avaliador offline e a grelha de calibração documentados em [Avaliação offline do matching de SKU](sku-matching-evaluation.md). A avaliação deve incluir produtos ausentes da galeria e manter o conjunto final separado.


## Filas, frentes visíveis e OCR auxiliar

A localização geométrica das deteções e o contrato de OCR auxiliar estão documentados em [Filas, frentes visíveis e OCR](shelf-layout-and-product-text.md). Estes módulos ainda não estão ligados ao worker de produção.


## Concorrência com retenção da imagem de origem

Ao construir o registo de matching, o worker identifica os exemplares aprovados
que apontam para imagens capturadas na plataforma e bloqueia, numa única
operação ordenada por ID, a imagem alvo e todas as imagens de origem relevantes
com `SELECT ... FOR UPDATE`. O serviço de registo volta a validar
`retention_status = ACTIVE` depois de adquirir os bloqueios. O bloqueio mantém-se até ao commit/rollback da
transação do worker. Como a operação de restrição também bloqueia a linha da
imagem, a restrição e o uso do exemplar ficam serializados: se a restrição
ganhar primeiro, o exemplar não entra no registo; se o matching adquirir o
bloqueio primeiro, a restrição aguarda a conclusão dessa transação.

Exemplares sem `shelf_image_id` continuam permitidos para referências externas
com licença declarada. A retenção de uma captura não pode ser inferida para
essas referências desligadas; a sua elegibilidade depende da licença e da
governação da fonte. A validação sequencial de regressão usa SQLite, que não
implementa bloqueios de linha equivalentes aos do PostgreSQL. A garantia de
serialização concorrente deve ser confirmada em PostgreSQL antes de produção.


## Prova de concorrência em PostgreSQL

O script `apps/api/scripts/postgres_embedding_retention_smoke.py` executa duas
transações em sessões independentes: o worker adquire os bloqueios da imagem
alvo e das referências aprovadas; em paralelo, a operação de retenção tenta
bloquear a imagem de referência. O teste consulta `pg_stat_activity` e
`pg_blocking_pids` para confirmar que a segunda transação está efetivamente à
espera da primeira, liberta o matching e confirma que a restrição termina depois
do commit. Por fim, constrói um novo registo e confirma que o exemplar restrito
já não produz correspondência. O script corre no API CI após as migrações
PostgreSQL 16.


## Validação CI

O smoke concorrente PostgreSQL foi executado com sucesso no API CI `43589628653`; a suite terminou com 753 testes aprovados e 1 ignorado. O Quality Gates `43589628597` também passou, incluindo compilação Python e build web.
