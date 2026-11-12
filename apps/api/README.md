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

As transições inválidas são rejeitadas com HTTP 409. A API regista as datas de início e conclusão. O identificador do funcionário é texto nesta fase; autenticação e gestão de utilizadores serão desenvolvidas numa etapa própria.

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

Os tokens de acesso expiram ao fim do período configurado em `JWT_ACCESS_TOKEN_MINUTES`. Ainda não existem refresh tokens, recuperação de palavra-passe, isolamento por loja nem associação das tarefas a IDs de utilizador. Não expor a chave de bootstrap nem os segredos JWT.


## Dashboard operacional

`GET /api/v1/dashboard/summary` devolve contagens de tarefas por estado e observações que requerem atenção. Os administradores podem filtrar por `store_id`; supervisores ficam limitados à loja da sua conta; funcionários veem apenas as tarefas que lhes foram atribuídas e podem iniciar/concluir essas tarefas, sem alterar a atribuição nem cancelar tarefas. Este endpoint fornece dados agregados para a futura interface, ainda não incluída no repositório.

## Atribuição de tarefas a utilizadores

Ao criar ou atribuir uma tarefa, pode ser enviado `assigned_user_id`. A conta tem de estar ativa e associada à mesma loja da tarefa. O campo textual `assigned_to` é mantido para compatibilidade com tarefas antigas.
