# Histórico de sincronizações ERP/WMS

## Estado e âmbito

O backend disponibiliza um ledger operacional para registar tentativas de sincronização ERP e WMS. Este mecanismo regista o ciclo de vida reportado por um connector ou operador; **não implementa, por si só, conectividade real com ERP/WMS, agendamento, retries ou transferência de dados**.

A integração real continua dependente de especificação do fornecedor, credenciais, endpoint, modelo de autenticação, limites de tráfego e ambiente de homologação.

## Ciclo de vida

1. POST /api/v1/inventory/source-syncs cria uma tentativa STARTED, identificando loja, fonte (ERP ou WMS), fornecedor e referência externa opcional.
2. O processo responsável executa a operação externa fora desta API.
3. POST /api/v1/inventory/source-syncs/{sync_id}/complete fecha a tentativa com SUCCESS, PARTIAL ou FAILED, contagens e, quando aplicável, código/descrição do erro.

Uma tentativa só pode transitar uma vez de STARTED para um estado terminal. A identidade da tentativa e os timestamps de início não podem ser alterados. Os eventos STARTED e COMPLETED são append-only; a base de dados bloqueia alterações e eliminações do histórico.

processed_records não pode exceder received_records. Uma falha exige error_code e error_message. Um sucesso não aceita metadados de erro.

## Consulta e alertas

- GET /api/v1/inventory/source-syncs?store_id={id} consulta o histórico, com filtros opcionais source e status, e limite máximo de 200.
- GET /api/v1/inventory/source-syncs/health?store_id={id} apresenta a última tentativa e a última execução bem-sucedida por fonte.

O limite de atualidade é lido de inventory_freshness_policies por loja/fonte, com 240 minutos por defeito. Sem uma execução bem-sucedida, a fonte recebe SOURCE_NEVER_SYNCHRONIZED. Quando a última execução bem-sucedida ultrapassa o limite, recebe SOURCE_SYNC_STALE. Uma última tentativa falhada é apresentada separadamente.

Os alertas são calculados na consulta; nesta fase não enviam notificações nem executam jobs de sincronização. Uma tentativa PARTIAL não é considerada uma sincronização integralmente bem-sucedida para efeitos de frescura.

## Segurança e limites contabilísticos

Todas as rotas exigem ADMIN ou SUPERVISOR e aplicam o âmbito multi-loja. A conclusão de uma tentativa só é permitida uma vez e é auditada com o utilizador responsável.

O ledger não altera snapshots ERP/WMS, quantidades disponíveis, movimentos de inventário nem saldos contabilísticos. O registo de sucesso significa apenas que o processo externo reportou sucesso e as contagens declaradas; não certifica a exatidão dos dados recebidos.

## Contrato de código já disponível

O pacote `apps/api/app/inventory_connectors` define agora:
- `InventorySourceAdapter`: protocolo assíncrono read-only com identidade de fonte/fornecedor e operação paginada `fetch_inventory(store_external_code, cursor)`.
- `NormalizedInventoryRecord`: registo normalizado com ID externo do produto, SKU, quantidades físicas/reservadas em Decimal, timestamp com fuso horário e referência externa.
- `InventorySyncBatch`: lote ERP/WMS com referência de execução e cursor da página seguinte.
- `load_inventory_adapter("package.module:factory", expected_source)`: loader para uma factory confiável definida pela configuração de deployment. Falha explicitamente quando não existe configuração ou a implementação não cumpre o contrato.

A validação do DTO rejeita quantidades negativas/não finitas, precisão incompatível com Numeric(12, 3), reserva superior ao stock físico, timestamps sem fuso horário, identificadores vazios e SKU/referências repetidos no mesmo lote. A factory é código de deployment confiável: nunca deve ser controlada por input HTTP ou por um utilizador da aplicação.

**Limite actual:** o contrato e o loader estão implementados e testados, mas ainda não estão ligados a um worker, endpoint de ingestão, scheduler ou credenciais de fornecedor. Não existe adapter concreto nem chamada de rede. O contrato não escreve snapshots; o futuro orquestrador terá de mapear os SKUs para produtos internos, registar a tentativa no ledger e persistir os snapshots através de uma transação idempotente.

## Contrato para adapters futuros

Um adapter real deverá:
- validar a integração ativa e o âmbito da loja antes de comunicar;
- obter credenciais de um gestor de segredos, nunca do frontend ou dos logs;
- usar timeouts, retries limitados com backoff e idempotência por external_run_id;
- validar o schema, a origem, a loja e a ordenação temporal dos snapshots;
- registar contagens reais e erros sanitizados, sem credenciais, tokens ou dados pessoais;
- persistir snapshots através dos fluxos de ingestão já existentes, sem criar movimentos contabilísticos implicitamente;
- separar a ingestão técnica da reconciliação e da aprovação humana.

A implementação de adapters fica bloqueada até existir documentação e ambiente de homologação do fornecedor.

## Orquestrador de ingestão (primeira implementação)

O módulo `apps/api/app/inventory_connectors/orchestrator.py` disponibiliza `run_inventory_source_sync` para execução por um worker confiável (não é uma rota HTTP pública). O worker tem de resolver previamente a factory do adapter e as credenciais através da configuração segura do deployment.

A execução:
- exige integração ACTIVE para a loja, fonte e fornecedor exactos;
- usa o código da loja como identificador externo até existir um campo de código externo dedicado;
- exige um mapeamento activo e exacto por loja, fonte, ID externo e SKU;
- valida a identidade do lote em todas as páginas;
- aplica timeout e até três tentativas com backoff por página;
- limita cada execução a 1000 páginas e rejeita cursores repetidos;
- persiste cada página numa transacção e usa a chave única existente (loja, produto, fonte, referência externa) para idempotência;
- aceita replays idênticos sem duplicar snapshots e rejeita referências repetidas com conteúdo diferente;
- conclui o ledger com SUCCESS, PARTIAL ou FAILED e contagens;
- sanitiza mensagens de erro para não registar detalhes do fornecedor potencialmente sensíveis.

Foi adicionada a tabela `inventory_external_product_mappings`, com unicidade por loja/fonte/ID externo e por loja/fonte/SKU. O mapeamento é explícito: não existe correspondência automática por semelhança de SKU.

**Limites desta fase:** ainda não existe API de administração dos mapeamentos, worker/scheduler executável, secret manager integrado ou adapter de fornecedor real. A função é a camada de serviço que um worker futuro poderá invocar. As páginas já confirmadas permanecem como evidência se uma página posterior falhar; o ledger termina em PARTIAL. Nenhum passo altera stock de origem, cria movimentos, inicia reconciliação ou aprova divergências.
