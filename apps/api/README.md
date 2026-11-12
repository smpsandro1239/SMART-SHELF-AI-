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

A política de refill já está ligada ao endpoint `GET /api/v1/replenishment/recommendations`: quando a observação inclui `observed_quantity`, a API calcula a diferença até ao alvo e limita a sugestão ao stock disponível. `POST /api/v1/tasks/from-recommendation` usa essa quantidade quando o pedido não indica outra. Observações antigas, de baixa confiança, sem quantidade medida ou sem snapshot de inventário não geram uma quantidade exata.\n\nA política de compra/transferência (`suggest_purchase_reorder`) continua isolada e não cria pedidos. A integração com visão automática ainda depende de um provider que identifique SKU e produza uma contagem validada; por agora, `observed_quantity` pode ser fornecida por um processo de observação controlado. Nenhum dos métodos foi validado com dados de loja.
