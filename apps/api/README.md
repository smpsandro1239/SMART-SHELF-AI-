SMART SHELF AI — API
====================

## Desenvolvimento local

A partir da raiz do repositório:

    cp .env.example .env
    docker compose up --build

O serviço da API executa as migrações Alembic antes de iniciar o servidor. A API ficará disponível em:
- Health: http://localhost:8000/health
- Readiness (inclui ligação à base de dados): http://localhost:8000/health/ready
- OpenAPI: http://localhost:8000/docs

Para aplicar manualmente as migrações depois de alterações ao schema:

    docker compose exec api alembic upgrade head

Para executar os testes localmente a partir de apps/api:

    pip install -r requirements.txt
    pytest -q

## Primeiro fluxo de teste

Criar uma loja:

    curl -X POST http://localhost:8000/api/v1/stores \
      -H "Content-Type: application/json" \
      -d '{"code":"PILOT-001","name":"Loja Piloto (dados de teste)"}'

Criar uma zona usando o ID da loja devolvido:

    curl -X POST http://localhost:8000/api/v1/zones \
      -H "Content-Type: application/json" \
      -d '{"store_id":1,"name":"Bebidas"}'

Criar uma prateleira usando o ID da zona devolvido:

    curl -X POST http://localhost:8000/api/v1/shelves \
      -H "Content-Type: application/json" \
      -d '{"zone_id":1,"code":"BEB-01"}'

Registar uma observação fictícia:

    curl -X POST http://localhost:8000/api/v1/observations \
      -H "Content-Type: application/json" \
      -d '{"shelf_id":1,"source":"simulation","status":"LOW_STOCK","confidence":0.82,"notes":"Observação fictícia para validar o fluxo"}'

## Nota de estado

Esta é a primeira base de desenvolvimento, ainda não validada por execução neste ambiente. As observações de exemplo são dados fictícios, não deteções de visão computacional. Antes de produção, faltam autenticação, autorização, hardening, observabilidade e validação operacional.


## Catálogo de produtos e prateleiras

Criar um produto:

    curl -X POST http://localhost:8000/api/v1/products \
      -H "Content-Type: application/json" \
      -d '{"sku":"SKU-AGUA-15","name":"Água 1,5 L","brand":"Marca Exemplo","unit":"un"}'

Associar o produto a uma prateleira (substituir os IDs pelos valores reais):

    curl -X POST http://localhost:8000/api/v1/shelf-products \
      -H "Content-Type: application/json" \
      -d '{"shelf_id":1,"product_id":1,"target_quantity":12,"min_display_quantity":4,"position":"nível 2"}'

Consultar o catálogo:

    curl "http://localhost:8000/api/v1/products?active_only=true"

Consultar os produtos associados a uma prateleira:

    curl "http://localhost:8000/api/v1/shelf-products?shelf_id=1"

A quantidade-alvo e o mínimo de exposição descrevem a organização da prateleira. Não representam stock de retaguarda nem stock total da loja.


## Inventário de retaguarda

O inventário é registado como histórico de snapshots provenientes de ERP, WMS, POS, importação ou registo manual. Cada registo preserva a origem e a data/hora de captura; não deve ser tratado como uma contagem visual da prateleira.

Criar um snapshot:

    curl -X POST http://localhost:8000/api/v1/inventory/snapshots \
      -H "Content-Type: application/json" \
      -d '{"store_id":1,"product_id":1,"on_hand_quantity":25,"reserved_quantity":5,"source":"ERP","external_reference":"ERP-0001"}'

A quantidade disponível é calculada como stock existente menos stock reservado. Consultar histórico:

    curl "http://localhost:8000/api/v1/inventory/snapshots?store_id=1&product_id=1"

Consultar o último snapshot:

    curl "http://localhost:8000/api/v1/inventory/latest?store_id=1&product_id=1"

Fontes aceites: ERP, WMS, POS, MANUAL e IMPORT. A referência externa é opcional, mas quando fornecida não pode repetir-se para a mesma loja, produto e origem. A API mantém os snapshots anteriores para auditoria; a integração real com sistemas ERP/WMS ainda não está implementada.


## Recomendações de reposição

Consultar o estado operacional de todos os produtos associados a prateleiras de uma loja:

    curl "http://localhost:8000/api/v1/replenishment/recommendations?store_id=1"

Filtrar por produto e definir a validade máxima da observação (em minutos):

    curl "http://localhost:8000/api/v1/replenishment/recommendations?store_id=1&product_id=1&stale_after_minutes=120"

Estados possíveis:
- `NEEDS_REPLENISHMENT`: observação recente de baixa disponibilidade e stock positivo na retaguarda.
- `BACKROOM_OUT_OF_STOCK`: a prateleira requer atenção, mas não existe stock disponível na retaguarda.
- `INVENTORY_UNKNOWN`: falta um snapshot de inventário.
- `STALE_OBSERVATION`: falta uma observação ou esta ultrapassou o limite de validade.
- `LOW_CONFIDENCE`: a deteção requer confirmação humana.
- `NO_ACTION`: a observação recente não indica baixa disponibilidade.

A API não calcula uma quantidade exata de reposição a partir de rótulos visuais como `LOW_STOCK` ou `EMPTY`. Para isso será necessária uma contagem quantitativa validada ou uma regra operacional adicional.


## Tarefas de reposição

Criar uma tarefa para um produto já associado à prateleira:

    curl -X POST http://localhost:8000/api/v1/tasks \
      -H "Content-Type: application/json" \
      -d '{"store_id":1,"shelf_id":1,"product_id":1,"priority":"HIGH","requested_quantity":8,"notes":"Reposição após verificação"}'

Se for indicado `assigned_to` na criação, a tarefa começa no estado `ASSIGNED`; caso contrário começa em `PENDING`.

Consultar tarefas:

    curl "http://localhost:8000/api/v1/tasks?store_id=1&status=PENDING"
    curl "http://localhost:8000/api/v1/tasks?assigned_to=funcionario-01"

Atualizar o estado:

    curl -X PATCH http://localhost:8000/api/v1/tasks/1/status \
      -H "Content-Type: application/json" \
      -d '{"status":"ASSIGNED","assigned_to":"funcionario-01"}'

Transições suportadas:
- `PENDING -> ASSIGNED` ou `CANCELLED`
- `ASSIGNED -> IN_PROGRESS` ou `CANCELLED`
- `IN_PROGRESS -> COMPLETED` ou `CANCELLED`

As transições inválidas são rejeitadas com HTTP 409. A API regista as datas de início e conclusão. A tarefa pode ser associada a uma conta ativa da mesma loja através de `assigned_user_id`; o campo textual `assigned_to` é mantido por compatibilidade.

A criação valida a loja, a pertença da prateleira à loja e a associação do produto à prateleira. A quantidade pedida é opcional e tem de ser positiva. A tarefa não é criada automaticamente a partir da recomendação nesta primeira versão.


Criar uma tarefa diretamente a partir de uma recomendação confirmada:

    curl -X POST "http://localhost:8000/api/v1/tasks/from-recommendation?stale_after_minutes=120" \
      -H "Content-Type: application/json" \
      -d '{"store_id":1,"shelf_id":1,"product_id":1,"priority":"HIGH","requested_quantity":8}'

Este endpoint só cria a tarefa quando a recomendação atual é `NEEDS_REPLENISHMENT`. Rejeita observações antigas, baixa confiança, inventário desconhecido ou stock indisponível. Também impede a criação de uma segunda tarefa ativa para a mesma combinação loja/prateleira/produto.


## Autenticação inicial

Configurar no ambiente da API `JWT_SECRET_KEY` e `BOOTSTRAP_ADMIN_KEY` com valores aleatórios fortes e distintos. Não utilizar os valores de exemplo em produção.

1. Aplicar migrações: `alembic upgrade head`.
2. Criar o primeiro administrador uma única vez:

    curl -X POST http://localhost:8000/api/v1/auth/bootstrap \
      -H "Content-Type: application/json" \
      -H "X-Bootstrap-Key: $BOOTSTRAP_ADMIN_KEY" \
      -d '{"email":"admin@example.com","full_name":"Administrador","password":"uma-palavra-passe-com-12-ou-mais-caracteres"}'

3. Usar o `access_token` devolvido como `Authorization: Bearer <token>`.
4. Consultar `GET /api/v1/auth/me`.
5. O administrador pode criar contas em `POST /api/v1/auth/users` e consultar `GET /api/v1/auth/users`.

Os tokens de acesso expiram ao fim do período configurado em `JWT_ACCESS_TOKEN_MINUTES`. Ainda não existem refresh tokens nem recuperação de palavra-passe. Não expor a chave de bootstrap nem os segredos JWT.


## Dashboard operacional

`GET /api/v1/dashboard/summary` devolve contagens de tarefas por estado e observações que requerem atenção. Os administradores podem filtrar por `store_id`; supervisores ficam limitados à loja da sua conta; funcionários veem apenas as tarefas que lhes foram atribuídas e podem iniciar/concluir essas tarefas, sem alterar a atribuição nem cancelar tarefas. Este endpoint fornece dados agregados consumidos pela primeira aplicação web em `apps/web`.

## Atribuição de tarefas a utilizadores

Ao criar ou atribuir uma tarefa, pode ser enviado `assigned_user_id`. A conta tem de estar ativa e associada à mesma loja da tarefa. O campo textual `assigned_to` é mantido para compatibilidade com tarefas antigas.


## CORS para o dashboard

Defina `CORS_ALLOWED_ORIGINS` como uma lista de origens separadas por vírgulas, por exemplo `http://localhost:5173`. Em produção, configure apenas o domínio real do frontend; não use curingas.


## Captura de imagens de prateleiras

A API aceita capturas JPEG, PNG e WebP através de `POST /api/v1/shelf-images`:

```bash
curl -X POST http://localhost:8000/api/v1/shelf-images \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F "shelf_id=1" \
  -F "image=@./prateleira.jpg;type=image/jpeg"
```

A resposta contém o ID da captura, tipo MIME, tamanho, SHA-256 e `analysis_status=PENDING`. A imagem pode ser listada em `GET /api/v1/shelf-images` e consultada em `GET /api/v1/shelf-images/{image_id}/content`. O armazenamento é persistido no volume Docker `shelf_images`; configurar `IMAGE_STORAGE_PATH` e `MAX_IMAGE_UPLOAD_BYTES` no ambiente. A validação atual confirma tipo declarado, assinatura inicial e tamanho, mas ainda não descodifica a imagem nem executa um modelo de visão computacional.


## Resultados de visão computacional (estrutura inicial)

Cada captura pode ter zero ou mais registos em `shelf_image_detections`. O endpoint `GET /api/v1/shelf-images/{image_id}/detections` devolve as deteções persistidas, limitadas ao âmbito da loja do utilizador. Cada registo contém classe/etiqueta, confiança entre 0 e 1, caixa delimitadora normalizada (coordenadas entre 0 e 1), produto associado opcional e versão do modelo.

Esta estrutura não executa inferência nem cria deteções automaticamente. A ligação a um modelo real e a um worker de processamento continuam por implementar; não são gerados resultados artificiais.


## Pipeline de inferência e worker

O ciclo de análise está preparado com os estados `PENDING`, `PROCESSING`, `COMPLETED` e `FAILED`. A API guarda também os instantes de início/conclusão e uma mensagem técnica de erro sem incluir caminhos internos dos ficheiros.

O worker é independente do processo HTTP e consome uma captura pendente:

    docker compose exec api python -m app.vision_worker --once

Por segurança, não existe um modelo ativo por omissão. Para ligar um provider, definir `VISION_PROVIDER_FACTORY` com um caminho Python `modulo:factory`. A factory deve devolver um objeto com `analyze(image_path)`, que devolve um objeto com `model_version` e `detections`. Cada deteção deve conter `label`, `confidence`, `x_min`, `y_min`, `x_max`, `y_max` e, opcionalmente, `product_id`. As coordenadas são normalizadas entre 0 e 1. Sem provider configurado, o worker termina sem alterar capturas pendentes; não cria resultados artificiais.

O worker pode ser executado repetidamente por um supervisor externo. A seleção da captura usa bloqueio de linha quando suportado pela base de dados, para reduzir o risco de dois workers processarem a mesma imagem.


### Repetir uma análise falhada

Um administrador ou supervisor da loja pode colocar novamente uma captura no estado `PENDING` através de `POST /api/v1/shelf-images/{image_id}/retry`. Apenas imagens no estado `FAILED` podem ser repetidas; o endpoint limpa os metadados da tentativa anterior e respeita o isolamento por loja. O worker só voltará a processar a imagem se existir um provider real configurado.


## Ferramentas de qualidade do dataset visual

A partir de `apps/api`, depois de preparar os três ficheiros COCO:

```bash
python -m app.dataset_quality \\
  --train /dados/annotations/instances_train.json \\
  --val /dados/annotations/instances_val.json \\
  --test /dados/annotations/instances_test.json \\
  --json-report /dados/reports/dataset-quality.json
```

O relatório inclui distribuição de instâncias por classe, classes sem exemplos, imagens sem anotações e estatísticas de instâncias por imagem. As imagens sem anotações são avisos para revisão, não falhas automáticas. Para ativar critérios quantitativos explícitos, podem ser usados `--min-instances-per-class` e `--max-class-imbalance-ratio`; por omissão, o comando apenas reporta e não impõe limites arbitrários. Consultar `docs/computer-vision/dataset-specification.md` para a interpretação dos resultados.


## Gate de aprovação do dataset

A ferramenta `app.dataset_approval` verifica proveniência, autorização declarada, privacidade, revisões humanas, hash do manifesto e os controlos técnicos COCO/leakage/qualidade. Ver a secção 16 de `docs/computer-vision/dataset-specification.md` e o template `docs/computer-vision/dataset-release-template.json`.

Exemplo a partir de `apps/api`:

```bash
python -m app.dataset_approval \\
  --release-record /dados/private/dataset-release.json \\
  --manifest /dados/metadata/image_manifest.csv \\
  --train /dados/annotations/instances_train.json \\
  --val /dados/annotations/instances_val.json \\
  --test /dados/annotations/instances_test.json \\
  --mode training \\
  --json-report /dados/reports/release-gate.json
```

O gate não autentica revisores nem valida juridicamente autorizações; o resultado é uma verificação técnica e documental das declarações fornecidas.


## Galeria local para revisão visual COCO

Gerar uma página HTML offline com as caixas delimitadoras sobre as imagens originais:

```bash
python -m app.coco_review \
  --annotations /dados/annotations/instances_train.json \
  --image-root /dados/images/train \
  --output /dados/review/train/index.html \
  --include-unannotated
```

Opções:
- `--class-id 0`: filtra por ID de classe; pode repetir a opção para várias classes.
- `--limit 100`: limita a quantidade de imagens, preservando a ordem do COCO.
- `--include-unannotated`: inclui imagens sem anotações correspondentes aos filtros.

Abrir o HTML localmente num navegador. A página referencia as imagens na pasta indicada por `--image-root`; não as copia, modifica nem envia. A ferramenta valida o documento COCO, verifica a existência das imagens e bloqueia caminhos absolutos/traversal. É uma ajuda de revisão humana, não um mecanismo de aprovação semântica.



## Registo de revisão humana por imagem

Criar templates ligados à versão exata de cada ficheiro COCO:

```bash
python -m app.dataset_review --coco /dados/annotations/instances_train.json --split train --create-template /dados/private/review-train.json
python -m app.dataset_review --coco /dados/annotations/instances_val.json --split val --create-template /dados/private/review-val.json
python -m app.dataset_review --coco /dados/annotations/instances_test.json --split test --create-template /dados/private/review-test.json
```

Editar cada entrada e preencher `decision` (`APPROVED`, `NEEDS_CORRECTION` ou `REJECTED`), `reviewer`, `reviewed_at` (ISO 8601) e notas. Validar um split:

```bash
python -m app.dataset_review --coco /dados/annotations/instances_train.json --split train --record /dados/private/review-train.json
```

Para tornar obrigatória a revisão completa dos três splits no gate, acrescentar `--require-visual-review`, `--review-train`, `--review-val` e `--review-test` ao comando `app.dataset_approval`. O gate compara o SHA-256 do COCO e o hash das anotações de cada imagem; qualquer alteração após revisão bloqueia a aprovação até nova revisão. Os registos são privados e não devem ser guardados no Git.



## Comparação entre versões do dataset

A ferramenta `app.dataset_diff` compara duas releases COCO com os respetivos manifestos SHA-256. Identifica imagens adicionadas, removidas, modificadas, renomeadas e movidas entre splits. Também compara as anotações por imagem, usando o nome do ficheiro e o conteúdo semântico da anotação (classe, bbox, área e iscrowd), ignorando alterações isoladas de IDs de anotação.

Exemplo:

```bash
python -m app.dataset_diff \
  --old-manifest /dados/releases/v1/image_manifest.csv \
  --new-manifest /dados/releases/v2/image_manifest.csv \
  --old-train /dados/releases/v1/instances_train.json \
  --new-train /dados/releases/v2/instances_train.json \
  --old-val /dados/releases/v1/instances_val.json \
  --new-val /dados/releases/v2/instances_val.json \
  --old-test /dados/releases/v1/instances_test.json \
  --new-test /dados/releases/v2/instances_test.json \
  --json-report /dados/reports/v1-v2-diff.json
```

O relatório inclui os hashes dos manifestos e dos seis documentos COCO, resumos e diferenças por split. Não inclui imagens nem notas privadas. Uma alteração de bbox é contabilizada como uma anotação alterada quando existe uma remoção e adição correspondente na mesma imagem. Renomes e mudanças de split só são inferidos quando o SHA-256 é único em cada versão. O relatório não inspeciona pixels, não decide se uma anotação está correta e não substitui a revisão humana. Qualquer mudança no COCO deve continuar a passar pelo gate de release e pela revisão aplicável.


## Motor de políticas de reposição (primeira versão)

O módulo `app.replenishment_policy` implementa dois cálculos determinísticos e independentes, inspirados nos conceitos de reposição por limiares e stock projetado documentados por Odoo e ERPNext:

- `suggest_shelf_refill(ShelfRefillInput)`: recebe quantidade observada na prateleira, alvo, limiar mínimo, stock disponível na retaguarda, confiança e idade da observação. Só sugere unidades até ao alvo, limitadas pelo stock de retaguarda. Observações antigas, pouco fiáveis ou sem inventário não geram uma quantidade automática.
- `suggest_purchase_reorder(PurchaseReorderInput)`: calcula stock projetado à data de receção (`on_hand + incoming - reserved - demand_until_receipt`), compara com o ponto de encomenda e sugere quantidade até ao máximo, arredondada ao múltiplo de embalagem e respeitando a quantidade mínima.

Exemplo de utilização:

```python
from app.replenishment_policy import (
    ShelfRefillInput,
    PurchaseReorderInput,
    suggest_shelf_refill,
    suggest_purchase_reorder,
)

shelf_decision = suggest_shelf_refill(ShelfRefillInput(
    shelf_quantity=2,
    target_quantity=12,
    min_display_quantity=3,
    backroom_available_quantity=8,
    observation_confidence=0.91,
    observation_age_minutes=2,
))
# Exemplo sintético: sugere 8 unidades e deixa 2 unidades de diferença.

purchase_decision = suggest_purchase_reorder(PurchaseReorderInput(
    on_hand_quantity=8,
    reserved_quantity=1,
    incoming_quantity=2,
    demand_until_receipt=5,
    reorder_point=6,
    target_max_quantity=24,
    minimum_order_quantity=6,
    pack_multiple=6,
))
# Exemplo sintético: stock projetado 4; propõe 24 unidades (4 packs de 6).
```

A política de refill já está ligada ao endpoint `GET /api/v1/replenishment/recommendations`: quando a observação inclui `observed_quantity`, a API calcula a diferença até ao alvo e limita a sugestão ao stock disponível. `POST /api/v1/tasks/from-recommendation` usa essa quantidade quando o pedido não indica outra. Observações antigas, de baixa confiança, sem quantidade medida ou sem snapshot de inventário não geram uma quantidade exata.

A política de compra/transferência (`suggest_purchase_reorder`) continua isolada e não cria pedidos. A integração com visão automática ainda depende de um provider que identifique SKU e produza uma contagem validada; por agora, `observed_quantity` pode ser fornecida por um processo de observação controlado. Nenhum dos métodos foi validado com dados de loja.


## Exemplares de produto e revisão humana para reconhecimento SKU

Os embeddings de referência são guardados na tabela `product_embedding_exemplars`. A criação regista sempre um exemplar como `PENDING`; não fica disponível para reconhecimento até ser revisto.

Em ambiente autenticado, estes endpoints estão limitados a administradores e supervisores:
- `POST /api/v1/product-embedding-exemplars`: registar exemplar.
- `GET /api/v1/product-embedding-exemplars?product_id=1&review_status=PENDING&model_version=embedding-model-v1`: consultar e filtrar exemplares.
- `PATCH /api/v1/product-embedding-exemplars/{id}/review`: aprovar ou rejeitar.

Exemplo de registo:

```bash
curl -X POST http://localhost:8000/api/v1/product-embedding-exemplars \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": 1,
    "embedding": [0.12, 0.34, 0.56],
    "model_version": "embedding-model-v1",
    "image_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "licence": "store-owned-reference-image"
  }'
```

Rever o exemplar:

```bash
curl -X PATCH http://localhost:8000/api/v1/product-embedding-exemplars/1/review \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"review_status":"APPROVED","review_notes":"SKU e imagem confirmados"}'
```

Se for fornecido `shelf_image_id`, o SHA-256 enviado tem de coincidir com a captura guardada. Os endpoints de leitura não devolvem o vetor. A aprovação regista revisor e data, e não pode ser repetida para o mesmo exemplar. Os vetores estão guardados como JSON relacional; ainda não existe pgvector nem índice de pesquisa vetorial. O serviço interno `app.product_embedding_service.build_approved_product_registry` já consegue carregar apenas exemplares aprovados, revistos e da versão de modelo pedida para o motor experimental; a integração automática com o worker de inferência continua pendente.


## Correspondência SKU no worker (experimental)

O contrato do provider aceita `embedding` e `embedding_model_version` opcionais por deteção. O worker compara o vetor apenas com exemplares `APPROVED`, revistos por um utilizador ainda existente e pertencentes à versão exata do modelo de embeddings. O produto só é associado quando o motor devolve `MATCHED`; `AMBIGUOUS`, `UNKNOWN`, ausência de vetor, dimensão incompatível ou registo de referência vazio deixam `product_id` nulo.

A versão do detector (`model_version`) e a versão do modelo de embeddings (`embedding_model_version`) são distintas. A tabela `shelf_image_detections` guarda estado, similaridade, margem e versão de embeddings para auditoria. Os thresholds não estão calibrados e a integração não deve alimentar contagens de stock sem validação humana.

Aplicar a migração `0012_detection_sku_matching` antes de executar o worker atualizado.


### OCR opcional no worker

O worker pode executar OCR automaticamente depois da deteção visual, quando `OCR_PROVIDER_FACTORY` estiver configurado. O adaptador PaddleOCR é opcional; sem ele, o worker mantém o comportamento visual anterior. As regiões são associadas geometricamente às deteções, e as regiões sem sobreposição suficiente ficam `UNASSIGNED`. A execução e as regiões ficam persistidas para posterior matching de catálogo e fusão. Falhas OCR são registadas como execução `FAILED` e não invalidam a análise visual.


## Worker com OCR opcional

O OCR está desligado por omissão. Configurar `OCR_PROVIDER_FACTORY=app.ocr_paddle:create_provider`, `OCR_PROVIDER_NAME=paddleocr` e `OCR_MODEL_VERSION=PP-OCRv5-pt` no ambiente do worker. Instalar primeiro PaddlePaddle CPU compatível e depois `requirements-ocr.txt`. O worker persiste regiões OCR e associações geométricas. Depois de uma execução OCR concluída, executa automaticamente `app.product_pipeline.process_completed_ocr_run`, que faz matching textual contra o catálogo ativo e cria a fusão com a evidência visual. A operação é idempotente e isolada num savepoint: se falhar, a análise visual e as regiões OCR persistidas são preservadas. Não confirma SKUs nem atualiza inventário.

Os endpoints `POST /api/v1/shelf-images/{image_id}/ocr-matches` e `POST /api/v1/shelf-images/{image_id}/evidence-fusion` continuam disponíveis para execução manual. A fila `GET /api/v1/shelf-image-review-queue` e o resumo `GET /api/v1/shelf-image-review-queue/summary` alimentam a secção de revisão do dashboard para ADMIN/SUPERVISOR. A decisão humana é registada pelo endpoint de reviews da deteção.


A fila tem também o endpoint `GET /api/v1/shelf-image-review-queue/summary`, que devolve contagens pendentes por estado de fusão para alimentar dashboards de revisão. Ambos os endpoints são reservados a ADMIN/SUPERVISOR e limitados à loja do supervisor.


## Previsão de procura e stock de segurança

O módulo `app.demand_forecasting` disponibiliza uma política determinística e explicável para estimar procura diária, consumo durante o prazo de abastecimento, stock de segurança, ponto de encomenda e stock-alvo.

A função recebe uma quantidade de vendas para **cada dia consecutivo**, incluindo dias sem vendas (quantidade zero). Não se devem enviar apenas dias em que existiram transações, porque isso sobrestimaria a procura média.

Exemplo de utilização Python:

    from app.demand_forecasting import DemandForecastInput, forecast_demand

    result = forecast_demand(DemandForecastInput(
        daily_sales=[4, 5, 3, 6, 4, 7, 5, 6, 4, 5, 8, 6, 5, 4],
        lead_time_days=3,
        target_cover_days=7,
        service_factor=1.65,
    ))

    print(result.status)
    print(result.reorder_point)
    print(result.target_stock)

A média diária é ponderada linearmente, dando maior peso aos dias recentes. O stock de segurança é calculado por:

    stock_seguranca = fator_servico * desvio_padrao_diario * raiz(prazo_abastecimento)

O ponto de encomenda corresponde à procura esperada durante o prazo de abastecimento acrescida do stock de segurança. O stock-alvo acrescenta os dias de cobertura configurados.

Estados:
- `FORECAST_READY`: histórico suficiente para calcular uma estimativa.
- `INSUFFICIENT_HISTORY`: histórico insuficiente; não são inventadas quantidades.

Limitações conhecidas: esta primeira versão não modela explicitamente sazonalidade semanal, feriados, campanhas promocionais, ruturas, devoluções ou produtos substitutos. O fator de serviço é um parâmetro operacional, não uma probabilidade calibrada. A previsão ainda não está ligada a dados reais de POS/ERP nem cria encomendas automaticamente.

Executar os testes:

    cd apps/api
    pytest -q tests/test_demand_forecasting.py


## Avaliação explicável do risco de rutura

O módulo `app.stockout_risk` acrescenta uma classificação determinística de risco (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW` ou `UNKNOWN`) a partir do stock disponível, procura média prevista, prazo de abastecimento e stock de segurança. Não apresenta os níveis como probabilidades calibradas, não altera inventário e não cria tarefas ou encomendas automaticamente.

A implementação inclui testes unitários para os diferentes níveis, histórico insuficiente, procura média nula e validação de entradas. Consultar [Avaliação explicável do risco de rutura](../../docs/architecture/stockout-risk-assessment.md). A integração com o endpoint de previsão e com o dashboard será feita numa fase posterior, após validação com dados reais.


### Endpoint integrado de risco de rutura

`GET /api/v1/forecasting/stockout-risk` combina a série diária completa de vendas com o snapshot de inventário mais recente da loja/produto e devolve a previsão e a banda de risco no mesmo resultado.

Exemplo:

```http
GET /api/v1/forecasting/stockout-risk?store_id=1&product_id=42&source=POS&lead_time_days=3&days=28&max_inventory_age_minutes=240
Authorization: Bearer <ACCESS_TOKEN>
```

Parâmetros:
- `store_id`, `product_id`, `source` e `lead_time_days`: obrigatórios.
- `days`: histórico diário consecutivo (7–365; predefinição 28).
- `through_date`: último dia da janela, ISO `YYYY-MM-DD`.
- `target_cover_days`: cobertura adicional usada na previsão (predefinição 7).
- `max_inventory_age_minutes`: idade máxima aceite para o snapshot (1–10080; predefinição 240).

Salvaguardas:
- Se faltar um dia de vendas, responde `409 INCOMPLETE_DAILY_SALES_HISTORY`; dias confirmados sem vendas têm de ser enviados explicitamente com quantidade zero.
- Se não existir snapshot, ou se o snapshot ultrapassar a idade máxima, devolve `risk_level: UNKNOWN` e indica `inventory_status: MISSING` ou `STALE`.
- Só classifica o risco com um snapshot considerado recente.
- Respeita o isolamento de loja já aplicado às restantes rotas.
- Não cria tarefas, encomendas nem movimentos de inventário.

A rota é consultiva e não substitui a validação humana nem a reconciliação com POS/WMS/ERP.

### Proteções na criação de tarefas de reposição

A criação de tarefas através de `POST /api/v1/tasks` e `POST /api/v1/tasks/from-recommendation` verifica se já existe uma tarefa ativa para a mesma combinação de loja, prateleira e produto (`PENDING`, `ASSIGNED` ou `IN_PROGRESS`). Em caso afirmativo, a API responde com HTTP 409 e o identificador/estado da tarefa existente, quando aplicável.

Na criação a partir de uma recomendação:
- A quantidade sugerida é utilizada quando está disponível e não foi indicada outra quantidade.
- Se a recomendação não tiver uma quantidade medida fiável, a criação exige uma quantidade explicitamente confirmada.
- A quantidade solicitada não pode exceder o stock disponível na retaguarda.
- Se o inventário não estiver disponível ou não permitir validar a quantidade, a API não cria a tarefa.

Estas verificações reduzem duplicações e sobre-alocação. A verificação de duplicados ao nível da aplicação não substitui uma restrição única transacional na base de dados; em cenários de concorrência simultânea, deve ser acrescentada uma migração com índice único parcial compatível com o motor de base de dados utilizado.

### Portefólio de risco de rutura por loja

O endpoint `GET /api/v1/forecasting/stockout-risk/portfolio` agrega os produtos ativos associados às prateleiras de uma loja e ordena-os por gravidade do risco.

Exemplo:

```http
GET /api/v1/forecasting/stockout-risk/portfolio?store_id=1&source=POS&lead_time_days=3&days=28&limit=100
Authorization: Bearer <ACCESS_TOKEN>
```

A resposta inclui:
- Identificação do produto (SKU, nome e marca).
- Prateleiras e zonas onde o produto está configurado, incluindo quantidades-alvo e mínimo de exposição.
- Estado e idade do snapshot de inventário.
- Estado da previsão e dias de vendas em falta.
- Nível de risco e explicação, quando os dados permitem a avaliação.
- Número de tarefas de reposição abertas para o produto.

A ordenação é `CRITICAL`, `HIGH`, `MEDIUM`, `UNKNOWN`, `LOW`. Os produtos sem histórico diário completo ou sem inventário recente permanecem em `UNKNOWN`; não são presumidos dias sem vendas nem stock disponível. O parâmetro `limit` aceita valores entre 1 e 200 e limita o número de produtos devolvidos. `total_products` informa quantos produtos ativos estão associados às prateleiras da loja.

Este endpoint é apenas de leitura: não cria tarefas, encomendas, transferências nem movimentos de inventário. A lista é um instrumento de triagem operacional, não uma ordem automática de reposição.

## Ingestão diária de vendas e previsão por loja/produto

A previsão de procura pode agora consumir agregados diários importados de um POS/ERP, sem assumir que as observações visuais da prateleira representam vendas.

### Registar um dia de vendas

`POST /api/v1/sales/daily` (ADMIN ou SUPERVISOR):

```json
{
  "store_id": 1,
  "product_id": 42,
  "sales_date": "2026-11-12",
  "quantity": 18,
  "source": "POS",
  "external_reference": "POS-STORE-01-20261112-42"
}
```

Cada registo representa a quantidade total vendida desse produto nessa loja e nesse dia, para a origem identificada. A referência externa é obrigatória e protege contra reenvios duplicados. As origens aceites são `POS`, `ERP`, `MANUAL` e `IMPORT`.

Um dia sem vendas tem de ser enviado explicitamente com `quantity: 0`. A API não converte dias sem registo em dias sem vendas.

### Consultar a previsão

`GET /api/v1/forecasting/demand?store_id=1&product_id=42&source=POS&lead_time_days=3&days=28`

Parâmetros:
- `store_id`, `product_id` e `source`: identificam a série de vendas a utilizar.
- `lead_time_days`: prazo de reposição em dias.
- `target_cover_days`: cobertura adicional pretendida (predefinição: 7).
- `days`: número de dias consecutivos a analisar (7–365; predefinição: 28).
- `through_date`: último dia do período, no formato ISO `YYYY-MM-DD` (predefinição: data atual do servidor).

A API devolve `409 INCOMPLETE_DAILY_SALES_HISTORY` se faltar qualquer dia do período. Isto evita tratar falhas de sincronização do POS como procura igual a zero. Os registos de fontes diferentes não são somados: a origem tem de ser escolhida explicitamente.

A previsão é consultiva. Não cria encomendas, não altera inventário e não cria tarefas de reposição. A integração real com um fornecedor POS/ERP, incluindo autenticação, sincronização incremental e reconciliação de vendas, continua a ser uma etapa separada.


### Importar um ficheiro CSV

`POST /api/v1/sales/import-csv` (ADMIN ou SUPERVISOR), como `multipart/form-data`:
- `store_id`: identificador da loja.
- `source`: `POS`, `ERP`, `MANUAL` ou `IMPORT` (predefinição: `IMPORT`).
- `file`: ficheiro `.csv` em UTF-8, até 5 MB.

Cabeçalho obrigatório:

```csv
product_id,sales_date,quantity,external_reference
42,2026-11-12,18,POS-STORE-01-20261112-42
42,2026-11-13,0,POS-STORE-01-20261113-42
```

O importador aceita até 5 000 linhas, datas ISO `YYYY-MM-DD`, quantidades não negativas com até três casas decimais e referências externas únicas no ficheiro. Valida todos os produtos antes de gravar. A operação é atómica: se uma referência já existir na base de dados, ou se alguma linha for inválida, não é gravada nenhuma linha. Dias sem vendas devem ser incluídos com quantidade zero.


## Qualidade do reconhecimento SKU com revisão humana

O endpoint `GET /api/v1/sku-evaluation/reviewed` compara a última sugestão visual/OCR de cada deteção com a última decisão humana registada. Pode ser filtrado por `store_id` (ADMIN) e `model_version`.

O relatório mede precisão quando existe proposta, cobertura de produtos conhecidos, abstenções, falsos positivos em deteções rejeitadas e resultados por versão do modelo. Para evitar fuga temporal, considera apenas a evidência de fusão existente no momento da decisão humana; reprocessamentos posteriores não alteram a avaliação histórica.

A avaliação é apenas de leitura. Inclui apenas deteções revistas e não deve ser interpretada como benchmark independente ou amostra estatística aleatória. Não treina modelos, não aprova exemplares e não altera inventário. A rota está disponível a ADMIN/SUPERVISOR, com supervisores limitados à respetiva loja.


## Planeamento operacional de reposição por zona

O endpoint read-only `GET /api/v1/replenishment/plan?store_id=1` organiza as recomendações atuais por zona e apresenta uma prioridade operacional proposta. As prioridades não são probabilidades nem previsões de tempo de execução:

- `HIGH`: existe uma recomendação quantitativa válida de reposição.
- `URGENT_REVIEW`: a prateleira precisa de atenção, mas não existe stock de retaguarda; não autoriza criar uma tarefa de reposição.
- `REVIEW`: inventário desconhecido ou confiança visual insuficiente.
- `RECAPTURE`: observação expirada; é necessária nova captura.
- `NONE`: não é incluído na fila de trabalho.

O plano exclui tarefas já ativas para a mesma combinação prateleira/produto, limita o número de resultados e agrupa os restantes por zona. `task_creation_allowed` só é verdadeiro quando existe uma recomendação quantitativa positiva. O endpoint não cria nem atribui tarefas, não reserva stock e não distribui trabalho por funcionários. Cada item inclui `route_order`, `route_basis` e `physical_route_optimized`. A sequência agrupa por zona e ordena por código de prateleira e posição configurada; o número é repetido para produtos na mesma prateleira. Como ainda não existem coordenadas, corredores ou ligações entre corredores no modelo, `physical_route_optimized` é sempre `false`: trata-se de uma sequência determinística de apoio, não de um percurso físico mínimo. A atribuição automática fica dependente de dados fiáveis sobre disponibilidade, turnos, capacidade e localização dos funcionários.


## Indicadores de carga de trabalho

O endpoint `GET /api/v1/replenishment/workload?store_id=1` está disponível para administradores e supervisores. Apresenta tarefas ativas registadas por funcionário (atribuídas e em curso), tarefas ativas sem funcionário válido e duração média entre início e conclusão para tarefas concluídas com timestamps válidos.

A duração média exclui registos incompletos, negativos e superiores a sete dias. O endpoint também apresenta médias por zona e prioridade, mas só publica uma média segmentada quando existem pelo menos cinco tarefas concluídas válidas nesse grupo; abaixo desse limiar devolve `INSUFFICIENT_SAMPLE` e não expõe uma média. São indicadores descritivos, não SLAs nem estimativas de produtividade individual. O endpoint não assume que um funcionário está de turno ou disponível, não calcula capacidade real e não atribui tarefas automaticamente. Funcionários não podem consultar a carga dos colegas.


## Recomendações de localização de produtos no armazém

Endpoint de consulta (read-only):

    GET /api/v1/warehouse/slotting-recommendations?store_id=1&source=POS&days=28

O motor identifica produtos de rotação elevada com base na média diária de vendas dos últimos dias indicados. Só inclui produtos com um registo diário explícito para todos os dias do período; dias sem vendas devem ser importados com quantidade zero. Produtos com histórico incompleto são excluídos e contabilizados separadamente.

A recomendação `CONSIDER_NEAR_PICKING_AREA` é um sinal para revisão humana. O limiar combina um mínimo configurável (por omissão, uma unidade/dia) com o percentil 75 dos produtos analisáveis. Não é uma decisão automática de mudança de localização.

**Limitação atual:** o modelo ainda não regista localizações/bin locations, coordenadas, distâncias, capacidades, dimensões, peso ou requisitos de conservação. Por isso, a API identifica candidatos a aproximar da zona de preparação, mas não escolhe uma posição concreta nem calcula poupanças de percurso. A mudança física exige validação operacional.


## Localizações físicas e recomendações de slotting

A fase física do Warehouse Slotting introduz três estruturas de dados:

- warehouse_locations: posições físicas por loja, com código, corredor/estante/compartimento, distância à zona de preparação, capacidade volumétrica e capacidade de peso, além da zona de temperatura.
- warehouse_product_profiles: volume e peso unitários, temperatura exigida, fragilidade e necessidade de segregação por produto.
- warehouse_product_placements: quantidade atualmente colocada em cada localização.

Antes de utilizar os novos endpoints, aplicar a migração:

```bash
cd apps/api
alembic upgrade head
```

### Configurar uma localização

```http
POST /api/v1/warehouse/locations
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json
```

```json
{
  "store_id": 1,
  "code": "A01-R02-B03",
  "aisle": "A01",
  "rack": "R02",
  "bin_code": "B03",
  "distance_to_picking_m": 8.5,
  "max_volume_cm3": 120000,
  "max_weight_kg": 250,
  "temperature_zone": "AMBIENT"
}
```

### Definir os requisitos físicos do produto

```http
POST /api/v1/warehouse/product-profiles
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json
```

```json
{
  "product_id": 42,
  "unit_volume_cm3": 850,
  "unit_weight_kg": 0.42,
  "temperature_requirement": "AMBIENT",
  "is_fragile": false,
  "requires_segregation": false
}
```

### Registar uma colocação existente

```http
POST /api/v1/warehouse/placements
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json
```

```json
{
  "location_id": 1,
  "product_id": 42,
  "quantity": 60
}
```

### Pedir recomendações de localização

```http
GET /api/v1/warehouse/physical-slotting?store_id=1&product_id=42&required_quantity=20
Authorization: Bearer <ACCESS_TOKEN>
```

O motor elimina localizações incompatíveis com a temperatura, capacidade volumétrica, capacidade de peso ou segregação exigida. As localizações viáveis são ordenadas primeiro pela distância à zona de preparação e depois pela utilização de capacidade projetada.

A quantidade pedida representa unidades adicionais à ocupação já registada. Para calcular ocupação, todos os produtos existentes numa localização têm de ter perfil dimensional; se faltar um perfil, a posição é excluída em vez de assumir ocupação zero. Localizações sem capacidade ou distância válidas também não são recomendadas.

O resultado é uma proposta, não uma ordem de transferência. automatic_movement_allowed permanece false. A fragilidade é sinalizada para revisão de manuseamento, mas ainda não existe uma certificação de compatibilidade de materiais nem um modelo de risco de empilhamento. Também não existe otimização de percurso por grafo, apenas distância linear registada à zona de preparação.

A criação de localizações e de colocações é reservada a ADMIN/SUPERVISOR e respeita o isolamento por loja. A definição do perfil físico é reservada a ADMIN, porque esse perfil é partilhado no catálogo global; as posições e quantidades permanecem associadas à loja.


## Unidades de medida, venda e embalagens logísticas (UOM)

**A unidade de venda não é determinada pela embalagem logística.** Um produto pode chegar à loja numa palete, ser armazenado em caixas, ser reposto a partir de caixas abertas e continuar a ser vendido ao cliente à unidade.

O catálogo mantém uma unidade base por produto (por exemplo, garrafa, pacote, kg ou litro). As vendas, o stock disponível, as quantidades observadas na prateleira e as quantidades pedidas para reposição devem ser expressas nessa unidade base. Os níveis UNIT, CASE e PALLET representam apenas quantidades logísticas convertíveis para a unidade base.

Exemplo ilustrativo para água:
- Unidade base / venda: 1 garrafa.
- CASE12: 12 garrafas por caixa.
- PALLET720: 720 garrafas por palete (60 caixas).
- Receção: 1 palete = 720 garrafas adicionadas ao stock da loja.
- Reposição: para colocar 20 garrafas na prateleira, podem ser retiradas 1 caixa fechada (12) e 8 garrafas de uma segunda caixa aberta.
- Venda: o cliente compra 1, 2 ou 3 garrafas; não compra necessariamente a caixa nem a palete.

A mesma lógica aplica-se a arroz e açúcar: a palete e a caixa são unidades de movimentação/armazenamento; o pacote individual é a unidade vendida.

Aplicar a migração:

```bash
cd apps/api
alembic upgrade head
```

### Configurar níveis de embalagem

Endpoint administrativo:

```http
POST /api/v1/warehouse/product-packaging
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json
```

Exemplo de configuração para o produto 42 (três pedidos separados):

```json
{
  "product_id": 42,
  "code": "UNIT",
  "name": "Garrafa",
  "package_type": "UNIT",
  "base_units_per_package": 1
}
```

```json
{
  "product_id": 42,
  "code": "CASE12",
  "name": "Caixa de 12",
  "package_type": "CASE",
  "base_units_per_package": 12,
  "gross_weight_kg": 5.4,
  "package_volume_cm3": 14000,
  "is_ordering_unit": true
}
```

```json
{
  "product_id": 42,
  "code": "PALLET720",
  "name": "Palete de 60 caixas",
  "package_type": "PALLET",
  "base_units_per_package": 720,
  "gross_weight_kg": 340,
  "package_volume_cm3": 950000,
  "is_ordering_unit": false
}
```

UNIT tem obrigatoriamente fator 1; CASE e PALLET têm fator superior a 1. Os fatores são explícitos e relativos à unidade base. `is_ordering_unit` identifica um nível logístico usado para encomenda; não altera a unidade de venda. `is_replenishment_unit`, quando utilizado, identifica um nível preferencial de movimentação/reposição, não a unidade vendida ao cliente. A configuração atual destas flags é global por produto e ainda não permite políticas diferentes por loja.

Consultar os níveis ativos:

```http
GET /api/v1/warehouse/product-packaging?product_id=42
Authorization: Bearer <ACCESS_TOKEN>
```

### Calcular embalagens logísticas para uma quantidade de reposição

```http
GET /api/v1/warehouse/replenishment-units?store_id=1&product_id=42&required_base_units=20&packaging_code=CASE12
Authorization: Bearer <ACCESS_TOKEN>
```

A quantidade pedida é sempre expressa em unidades base. Sem abertura de caixas, 20 garrafas necessárias são arredondadas para 2 caixas fechadas, ou seja, 24 garrafas movimentadas e 4 excedentes.

Se a operação permitir abrir uma caixa:

```http
GET /api/v1/warehouse/replenishment-units?store_id=1&product_id=42&required_base_units=20&packaging_code=CASE12&allow_open_package=true
Authorization: Bearer <ACCESS_TOKEN>
```

A proposta passa a ser:
- 1 caixa fechada = 12 garrafas;
- 1 caixa aberta = 8 garrafas retiradas individualmente;
- total = 20 garrafas;
- excedente = 0.

O campo `package_count` conta as embalagens completas que permanecem fechadas; `opened_package_count` conta as embalagens que têm de ser abertas; `loose_base_units` conta as unidades base retiradas da embalagem aberta. Se forem necessárias apenas 8 garrafas, o resultado é 0 caixas fechadas, 1 caixa aberta e 8 unidades soltas.

O cálculo é consultivo: não recebe mercadoria, não transfere stock, não cria tarefas e não altera inventário. A operação física deve ser registada por um fluxo transacional próprio.

**Limitação importante:** esta configuração ainda não modela a cadeia completa de receção, armazenamento, picking e reposição por loja. A mesma palete pode ser a unidade de receção, a caixa a unidade de picking e a garrafa a unidade de venda. Essas funções devem ser configuradas separadamente por produto e, quando necessário, por loja; não devem ser deduzidas automaticamente do tipo de embalagem.


## Simulação de rotação de paletes em períodos de pico

O motor consultivo está em `app/pallet_rotation.py`. A documentação funcional
e os limites encontram-se em
`docs/architecture/pallet-rotation-optimizer.md`. A análise REA de projetos
externos está em `docs/research/existing-applications-pallet-rotation.md`.

Esta fase disponibiliza o motor puro de decisão, o registo persistente de paletes,
a simulação ligada à base de dados e o endpoint de planeamento por janelas horárias.
As operações continuam consultivas e não executam movimentos físicos.
A função recebe quantidades na unidade base, classe de afluência, disponibilidade
de palete de substituição e capacidade de retaguarda, tempos operacionais,
custo laboral e consumo previsto até à próxima janela de baixa afluência.

O resultado é apenas uma recomendação. Não cria tarefas, não reserva paletes,
não altera inventário e não regista movimentos. Os custos atuais comparam
apenas mão de obra; equipamento, espaço, perdas e impacto no serviço ainda
terão de ser medidos num piloto.


## Registo e rastreabilidade de paletes

A migração `0015_pallet_rotation_registry` cria a identidade de paletes físicas,
políticas de rotação por loja/produto e histórico de eventos. Aplicar com:

    docker compose exec api alembic upgrade head

Consultar `docs/architecture/pallet-registry-and-traceability.md` para o modelo
e exemplos completos. Endpoints principais:

- `POST /api/v1/warehouse/pallets` — registar palete física e evento inicial.
- `GET /api/v1/warehouse/pallets?store_id=1` — consultar paletes da loja.
- `POST /api/v1/warehouse/pallet-rotation/policies` — criar política por produto/loja.
- `GET /api/v1/warehouse/pallet-rotation/policies?store_id=1` — consultar políticas.
- `PATCH /api/v1/warehouse/pallet-rotation/policies/{policy_id}` — alterar limiar ou ativação.
- `GET /api/v1/warehouse/pallets/{pallet_id}/events?store_id=1` — consultar auditoria.
- `POST /api/v1/warehouse/pallets/{pallet_id}/events` — registar alteração supervisionada de estado, quantidade ou localização, com controlo otimista de concorrência.

A criação/alteração exige ADMIN ou SUPERVISOR e respeita o âmbito da loja.
O registo usa o nível de embalagem PALLET ativo e guarda quantidade em unidade
base, lote, validade e localização declarada. Não atualiza o inventário agregado,
não executa movimentos e não confirma fisicamente a existência da palete. As alterações posteriores exigem ADMIN/SUPERVISOR, estado e quantidade esperados, motivo e transições permitidas; geram evento auditável na mesma transação, sem atualizar stock agregado.
Os testes de validação dos schemas estão em
`tests/test_pallet_registry_schemas.py`; devem ser executados com `pytest -q`
a partir de `apps/api`.


### Simular a troca de uma palete registada

Endpoint consultivo, reservado a ADMIN/SUPERVISOR:

```http
POST /api/v1/warehouse/pallet-rotation/simulate
```

Exemplo de pedido:

```json
{
  "store_id": 1,
  "pallet_id": 15,
  "traffic_level": "HIGH",
  "backroom_capacity_available": true,
  "conventional_replenishment_minutes": 24,
  "pallet_swap_minutes": 4,
  "transport_minutes": 3,
  "pallet_rebuild_minutes": 5,
  "labour_cost_per_hour": 12,
  "forecast_consumption_until_low_traffic": 180
}
```

A API consulta a palete em exposição, a política ativa do produto e uma
palete substituta READY, completa, não expirada e da mesma referência de
embalagem PALLET. A substituta é ordenada por validade (FEFO) e antiguidade.
O resultado inclui a recomendação e os custos laborais estimados.

`backroom_capacity_available` tem de ser confirmado pelo operador:
a capacidade física da retaguarda ainda não está integrada. A previsão de
consumo e os tempos/custo são inputs fornecidos pelo chamador, não previsões
geradas automaticamente. O endpoint é read-only: não reserva a substituta,
não cria tarefas, não altera estados, eventos, stock ou localizações.


### Recolha de vendas e afluência por hora

A migração `0016_hourly_sales_traffic` cria duas fontes separadas:
`hourly_sales_records` (quantidade vendida por produto/hora) e
`hourly_store_traffic_records` (contagem de clientes por loja/hora).
A hora é a hora local da loja, indicada pelo sistema de origem; não é convertida
automaticamente a partir de UTC.

- `POST /api/v1/sales/hourly` — registar vendas horárias por produto.
- `POST /api/v1/sales/traffic/hourly` — registar contagem horária de clientes.
- `GET /api/v1/warehouse/pallet-rotation/hourly-profile?store_id=1&product_id=42&days=28`
  — obter perfil de 24 horas com médias diárias e cobertura observada.

Os registos são imutáveis e deduplicados por referência externa. Zero é um valor
válido e diferente de ausência de observação. O perfil devolve `null` e indica
as horas em falta quando não há dados; não preenche lacunas com zeros nem gera
uma previsão. O período aceite é de 7 a 90 dias. A API ainda não calcula
janelas ótimas automaticamente; fornece a base empírica para essa fase.


### Recomendar uma janela horária de baixa afluência

`GET /api/v1/warehouse/pallet-rotation/window-plan` cruza o perfil horário
histórico de vendas do produto com a contagem de clientes da loja. Exemplo:

```http
GET /api/v1/warehouse/pallet-rotation/window-plan?store_id=1&product_id=42&pallet_id=15&current_hour=10&residual_base_units=300&duration_hours=1&days=28&minimum_observed_days=7
```

O motor avalia as próximas 24 horas, seleciona a janela com menor afluência
histórica e só a considera se o stock residual cobrir o consumo médio observado
até ao fim da operação. Exige 1 a 4 horas de duração, 7 a 90 dias de histórico e um
mínimo configurável de dias observados por hora. Se a cobertura for insuficiente,
devolve `INSUFFICIENT_DATA`; se o stock não alcançar nenhuma janela elegível,
devolve `REPLENISH_CURRENT`.

A hora atual é fornecida pelo chamador na hora local da loja. O cálculo usa
médias históricas, não uma previsão probabilística nem dados em tempo real.
Não agenda, reserva nem executa movimentos.


### Importação horária em lote

Dois endpoints JSON em lote permitem importar até 500 observações por pedido:

- `POST /api/v1/sales/hourly/batch`
- `POST /api/v1/sales/traffic/hourly/batch`

Cada lote pertence a uma única loja, rejeita chaves externas repetidas e é
transacional: um conflito com registos já existentes rejeita o lote inteiro.
A importação de vendas valida também todos os produtos como ativos. Requer
ADMIN/SUPERVISOR e respeita o âmbito de loja do utilizador.

O planeador exige agora cobertura mínima de vendas e tráfego em todas as 24
horas antes de classificar uma janela como a de menor afluência. Uma lacuna
horária não permite recomendar uma janela como se fosse a melhor.


### Consulta e auditoria dos dados horários

- `GET /api/v1/sales/hourly?store_id=1&product_id=42&start_date=2026-10-01&end_date=2026-10-31&limit=500`
- `GET /api/v1/sales/traffic/hourly?store_id=1&start_date=2026-10-01&end_date=2026-10-31&limit=500`

Os endpoints permitem consultar os registos de origem por loja, período e,
no caso das vendas, produto. O limite é de 1 a 1000 registos por pedido.
Ambos respeitam o âmbito de loja do utilizador e não alteram dados.


### Importação horária por CSV

Endpoints ADMIN/SUPERVISOR, via `multipart/form-data`, até 5 MB e 5000 linhas:

- `POST /api/v1/sales/hourly/import-csv`
- `POST /api/v1/sales/traffic/hourly/import-csv`

Campos: `store_id`, `source` (POS, ERP, MANUAL ou IMPORT) e `file`.

Vendas:
```csv
product_id,business_date,hour_of_day,quantity,external_reference
42,2026-11-12,8,3,POS-42-20261112-08
42,2026-11-12,9,0,POS-42-20261112-09
```

Afluência:
```csv
business_date,hour_of_day,customer_count,external_reference
2026-11-12,8,120,TRAFFIC-20261112-08
2026-11-12,9,0,TRAFFIC-20261112-09
```

Datas ISO, horas 0–23, quantidades e contagens não negativas e referências
externas únicas são obrigatórias. A importação valida tudo antes de gravar e é
atómica. Os zeros são preservados; horas sem registo não são criadas.


O perfil por dia da semana aceita `source` (predefinição `POS`) para evitar
somar contagens potencialmente sobrepostas de fontes diferentes. As médias
de vendas e afluência são calculadas exclusivamente para a origem selecionada.


No plano por zona, os itens são apresentados por prioridade operacional primeiro e, dentro da mesma prioridade, por código de prateleira. O campo `route_order` é calculado separadamente a partir do código/posição da prateleira. A urgência não fica escondida pela sequência heurística; esta continua sem representar um percurso físico otimizado.


Os endpoints `hourly-profile` e `window-plan` aceitam `source`
(predefinição `POS`) e filtram vendas e afluência pela mesma origem. Para
dados importados como `IMPORT`, indicar explicitamente
`source=IMPORT`; não se somam automaticamente fontes potencialmente
sobrepostas.


## Previsão horária de procura — baseline sazonal

Consultar a previsão para um produto e loja:

    curl "http://localhost:8000/api/v1/forecasting/hourly-demand?store_id=1&product_id=1&horizon_days=7&history_days=180&minimum_observed_days=4&source=POS"

O baseline usa as últimas observações disponíveis para o mesmo dia da semana
e hora, com ponderação decrescente para observações mais antigas. Por defeito,
exige quatro dias observados por combinação dia-da-semana/hora. Valores sem
amostra suficiente são devolvidos como `null`, nunca como zero.

A resposta identifica a versão do baseline, a confiança baseada no número de
amostras e métricas de backtesting rolling-origin (MAE e WAPE). É um modelo
estatístico sazonal, não um modelo de machine learning treinado. É read-only
e não cria tarefas nem movimentos de stock.


## Deteção histórica de picos de afluência

    curl "http://localhost:8000/api/v1/forecasting/traffic-peaks?store_id=1&days=56&minimum_observed_days=4&minimum_baseline_hours=6&peak_ratio=1.5&source=POS"

Um pico é uma combinação dia-da-semana/hora cuja média observada excede
o limiar configurado face à média das horas observadas desse mesmo dia.
A classificação exige cobertura mínima para a célula e para a linha de base.
Horas ausentes não são tratadas como zero. É classificação histórica, não
previsão de tráfego.


## Previsão horária da procura

O endpoint `GET /api/v1/forecasting/hourly-demand` calcula um baseline estatístico por dia da semana e hora, usando as observações POS (ou outra origem selecionada) dos últimos 28 a 365 dias. Por omissão, projeta os próximos 7 dias e exige pelo menos 4 dias observados para cada combinação dia-da-semana/hora.

Exemplo:

    curl "http://localhost:8000/api/v1/forecasting/hourly-demand?store_id=1&product_id=1&horizon_days=7&history_days=180&minimum_observed_days=4&source=POS"

A resposta inclui:
- quantidade prevista por data e hora;
- número de dias observados e nível de confiança;
- versão e identificação explícita do baseline;
- backtesting rolling-origin com MAE e WAPE, quando existe histórico suficiente.

Horas sem cobertura suficiente devolvem `predicted_units=null`; não são convertidas em vendas zero. Um zero só é preservado quando existe um registo explícito de zero vendas. O endpoint é apenas de leitura e não altera stock, não cria tarefas e não executa movimentos de paletes.

**Limite importante:** trata-se de um baseline sazonal transparente, não de um modelo de machine learning treinado nem de uma previsão validada em produção. Antes de usar os resultados para decisões operacionais, comparar o backtest com períodos representativos e verificar a qualidade/completude dos dados POS.


## Rotação de paletes e janelas operacionais

A política de troca de paletes está documentada em `docs/operations/pallet-rotation-policy.md`. O limiar predefinido é 50% de quantidade **residual** da palete, configurável por loja/produto. Atingir o limiar não movimenta stock nem cria automaticamente uma tarefa.

Simular a troca de uma palete em exposição:

```bash
curl -X POST http://localhost:8000/api/v1/warehouse/pallet-rotation/simulate \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "store_id": 1,
    "pallet_id": 15,
    "traffic_level": "HIGH",
    "backroom_capacity_available": true,
    "conventional_replenishment_minutes": 24,
    "pallet_swap_minutes": 4,
    "transport_minutes": 3,
    "pallet_rebuild_minutes": 5,
    "labour_cost_per_hour": 12,
    "forecast_consumption_until_low_traffic": 180
  }'
```

O endpoint consulta a palete atual, a política ativa e uma palete substituta completa em estado `READY`. Os tempos, custo horário, nível de afluência, consumo até à próxima janela e confirmação de capacidade da retaguarda são inputs explícitos da simulação.

Consultar o portfolio de paletes da loja:

```bash
curl "http://localhost:8000/api/v1/warehouse/pallet-rotation/portfolio?store_id=1&traffic_level=HIGH&forecast_consumption_until_low_traffic=180&backroom_capacity_available=true"
```

**Limitação importante:** nesta versão, os parâmetros de afluência, consumo e capacidade são fornecidos pelo operador e aplicados às paletes consideradas. O portfolio é read-only e não substitui uma avaliação individual com dados reais por SKU. Consultar os endpoints de perfil horário, janela de baixa afluência e previsão:

- `GET /api/v1/warehouse/pallet-rotation/weekday-hourly-profile?store_id=1&product_id=1`
- `GET /api/v1/warehouse/pallet-rotation/window-plan?store_id=1&product_id=1&pallet_id=15&current_hour=10&residual_base_units=360`
- `GET /api/v1/forecasting/hourly-demand?store_id=1&product_id=1&horizon_days=7`

O baseline horário requer histórico suficiente por dia da semana/hora. Valores em falta permanecem desconhecidos; não são convertidos em zero. Os endpoints são de consulta/simulação e declaram `automatic_stock_movement_allowed=false`.


## Portfolio inteligente de paletes baseado em histórico

O endpoint `GET /api/v1/warehouse/pallet-rotation/portfolio-from-history` constrói um portfolio por palete e SKU usando registos históricos horários de vendas e tráfego. Ao contrário do endpoint `/portfolio`, não exige que o operador forneça uma única previsão de consumo e nível de afluência para todos os produtos.

Exemplo:

```bash
curl "http://localhost:8000/api/v1/warehouse/pallet-rotation/portfolio-from-history?store_id=1&current_hour=10&days=28&duration_hours=1&source=POS&minimum_observed_days=7&backroom_capacity_available=true"
```

Parâmetros principais:
- `current_hour`: hora local da loja, entre 0 e 23; tem de ser fornecida pelo sistema chamador.
- `days`: janela histórica consultada, entre 7 e 90 dias.
- `duration_hours`: duração operacional da janela, entre 1 e 4 horas.
- `minimum_observed_days`: cobertura mínima exigida por hora.
- `source`: origem coerente dos registos (POS, IMPORT, etc.).
- `backroom_capacity_available`: confirmação operacional explícita; não é inferida pelo histórico.

O resultado inclui `recommendations`, `candidate_evidence`, contagem de candidatos excluídos e eventuais erros de perfil por produto. Perfis incompletos ficam em `UNKNOWN`/sem previsão e não entram no ranking operacional. A evidência histórica é específica por SKU; a capacidade da retaguarda continua a ser confirmada pelo operador.

Este endpoint é apenas consultivo: não reserva paletes, não cria tarefas e não movimenta stock. O forecast é um baseline histórico, não uma previsão em tempo real nem uma integração com POS/WMS.
