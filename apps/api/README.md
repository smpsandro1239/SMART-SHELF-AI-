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
