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
