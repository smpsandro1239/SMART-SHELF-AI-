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


### Migrações e rastreabilidade da orquestração
- `0078_inventory_external_product_mapping`: mappings explícitos de produto externo, únicos por loja/fonte/ID externo e por loja/fonte/SKU.
- `0079_inventory_sync_run_identity`: permite fixar o `external_run_id` apenas durante a transição terminal do ledger, mantendo a regra de uma única conclusão.
- `run_inventory_source_sync`: serviço de worker com integração ACTIVE, fornecedor exacto, mapping exacto, paginação limitada, timeout/retries, transacção por página e replay idempotente.

A contagem `processed_records` inclui snapshots novos e replays idênticos já persistidos. Se houver falha após páginas confirmadas, o ledger termina em PARTIAL; os snapshots dessas páginas permanecem como evidência. A API de gestão dos mappings, worker durável, secret manager e adapter real continuam pendentes.


## Administração de mappings externos
Endpoints autenticados:
- `GET /api/v1/stores/{store_id}/inventory/external-mappings` — filtra por fonte/estado e limita resultados.
- `POST /api/v1/stores/{store_id}/inventory/external-mappings` — cria mapping com motivo obrigatório.
- `PATCH /api/v1/stores/{store_id}/inventory/external-mappings/{mapping_id}` — altera produto de destino ou estado activo, sempre com motivo.
- `GET /api/v1/stores/{store_id}/inventory/external-mappings/{mapping_id}/events` — consulta histórico de auditoria.

ADMIN pode gerir todas as lojas; SUPERVISOR apenas a loja associada à sua conta. EMPLOYEE não tem acesso. A criação exige integração activa para ERP/WMS e produto interno activo. O mapping não pode ser eliminado; a desactivação preserva o histórico. A identidade (loja, fonte, ID externo e SKU externo) é imutável ao nível da base de dados. Migrações 0080 e 0081 criam auditoria append-only e triggers de protecção.

O endpoint não cria snapshots, movimentos, reconciliações ou aprovações. A gestão do mapping é uma operação administrativa separada da sincronização.


## Integridade adicional dos mapeamentos

A regra de unicidade cobre agora também o produto interno: numa mesma loja e fonte (ERP ou WMS), um produto interno só pode ter um mapeamento externo activo/histórico. Isto evita que duas identidades externas concorrentes alimentem o mesmo produto e tornem ambígua a proveniência dos snapshots.

- A migração histórica `0078_inventory_external_product_mapping` inclui a regra para instalações novas.
- A migração aditiva `0082_inventory_external_mapping_product_unique` aplica a mesma protecção em bases de dados onde a migração 0078 já tinha sido executada.
- Antes de criar o índice, a migração 0082 verifica duplicados existentes e falha explicitamente para revisão manual; não elimina nem reescreve mapeamentos.
- A constraint é também declarada no modelo SQLAlchemy para manter alinhados ORM, SQLite e PostgreSQL.

A instalação de testes inclui `pytest-asyncio`, necessário para executar os testes assíncronos do contrato do adapter e dos retries do orquestrador.


## Fila durável e worker independente (primeira versão)

A migração `0083_inventory_sync_jobs` cria `inventory_sync_jobs` e `inventory_sync_job_events`. A API coloca pedidos na fila; o processo independente `app.inventory_sync_worker` consulta a fila sem manter pedidos HTTP abertos.

- `POST /api/v1/stores/{store_id}/inventory/sync-jobs` cria um job idempotente por loja/fonte/chave.
- `GET /api/v1/stores/{store_id}/inventory/sync-jobs` consulta estado e tentativas.
- `GET /api/v1/stores/{store_id}/inventory/sync-jobs/{job_id}/events` consulta auditoria append-only.
- PostgreSQL usa `SELECT ... FOR UPDATE SKIP LOCKED` para claims concorrentes.
- Cada claim cria lease token aleatório e incrementa fencing token monotónico.
- Leases expirados podem ser recuperados; retries têm backoff exponencial limitado.
- Quando um lease expira, a recuperação fecha atomicamente a tentativa anterior que ainda esteja em `STARTED`: regista `PARTIAL`, `WORKER_LEASE_EXPIRED` e um evento `COMPLETED` append-only antes de atribuir o novo fencing token.
- Como os snapshots não estão ligados a uma tentativa transitória, a recuperação mantém as contagens como desconhecidas (`NULL`) e classifica conservadoramente a execução como parcial; não inventa contagens nem elimina evidência já persistida.
- O orquestrador valida e renova o lease na mesma transação que confirma cada página de snapshots. Um worker com fencing token antigo não pode confirmar páginas.
- Cada retry cria uma tentativa separada no ledger `inventory_source_syncs`; os snapshots já persistidos são reutilizados por idempotência.
- O worker é um serviço Docker Compose separado, sem dependência de uma ligação HTTP persistente.

Configuração:
- `INVENTORY_ERP_ADAPTER_FACTORY=package.module:factory`
- `INVENTORY_WMS_ADAPTER_FACTORY=package.module:factory`
- As factories são código confiável do deployment, nunca input HTTP. Segredos têm de ser injectados pelo mecanismo seguro do ambiente de execução. Esta versão ainda não integra Vault/Secrets Manager nem contém adapters reais.
- Sem factory real configurada, o worker falha de forma fechada e aplica retries limitados.

A fila não altera stock ERP/WMS, movimentos contabilísticos ou decisões humanas.


## Validação de concorrência e recuperação do worker

O script `apps/api/scripts/postgres_inventory_sync_job_smoke.py` está integrado no workflow API CI, que provisiona PostgreSQL 16. Exercita dois claims concorrentes, takeover com fencing, rejeição do worker antigo e SIGKILL de um processo após confirmar uma tentativa STARTED. A recuperação fecha o ledger como PARTIAL, com evento COMPLETED e contagens NULL.

O smoke foi expandido para demonstrar também a interrupção após commit de uma página real e o replay idempotente dos snapshots. A primeira execução do API CI dessa versão detectou uma falha no próprio teste: `DetachedInstanceError` ao aceder a atributos ORM expirados depois do fecho da sessão. A correcção captura os tokens de lease/fencing enquanto a instância está associada à sessão; não altera a lógica de produção. A garantia só deve ser considerada validada depois de o novo API CI executar com sucesso o smoke e a suite completa.


## Interrupção depois de uma página confirmada

O smoke `apps/api/scripts/postgres_inventory_sync_job_smoke.py` executa o orquestrador real com um adapter determinístico. O processo é terminado com SIGKILL apenas depois de a primeira página ter sido confirmada e antes de a segunda resposta ser devolvida. Após takeover, a sincronização abandonada fica PARTIAL; a repetição da primeira página tem de reutilizar o snapshot existente (mesmo ID e conteúdo), e a página seguinte pode acrescentar uma nova referência.

O teste corre no API CI contra PostgreSQL 16. A integração no workflow não equivale a aprovação: consultar o resultado do run correspondente ao SHA antes de declarar a garantia validada.


O smoke testa também o fencing no limite de escrita: depois do takeover pelo worker B, tenta executar o orquestrador com o lease/fencing token antigo do worker A. A tentativa tem de falhar no lease guard antes de criar um novo ledger ou persistir snapshots; o teste confirma ambos os contadores a zero para a loja isolada.


## Validação CI — worker durável e recuperação idempotente (2026-11-25)

Commit validado: `ffe76015e82d9d1ae608dc61a1bb5c9a9d8c710e`.

Os quatro workflows terminaram com sucesso no mesmo commit:

- [API CI](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45522939384) — migrações PostgreSQL 16, smoke de claims concorrentes/fencing, tentativa de escrita com credenciais obsoletas, SIGKILL após confirmação de uma página, recuperação PARTIAL e replay idempotente; suite da API aprovada.
- [Quality Gates](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45522939251) — verificações de qualidade, compilação Python, testes API e build Web aprovados.
- [Security Scans](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45522939233) — OWASP ZAP passive baseline e importação OpenAPI/análise em modo seguro concluídos com sucesso; Gitleaks e auditorias de dependências Web/Python aprovados.
- [Docker Compose](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45522939260) — smoke de arranque e serviços aprovado.

A correcção do teste de fencing captura os valores escalares do lease enquanto a instância ORM ainda está associada à sessão. Não alterou o mecanismo de produção de leases, fencing ou persistência. Estes resultados validam os cenários automatizados indicados; não constituem homologação de conectores ERP/WMS reais nem certificação de segurança independente.


## Isolamento multi-loja na reconciliação

O teste test_inventory_reconciliation_isolates_shared_product_snapshots_and_ledger_across_stores reutiliza um produto global em duas lojas e cria snapshots ERP/WMS independentes em cada uma. A API tem de seleccionar os snapshots usando simultaneamente store_id e product_id; a consulta e o ledger filtrados para uma loja não podem revelar evidência da outra. A revisão por ID estrangeiro é ocultada com HTTP 404 e não pode alterar o estado do registo. O teste está publicado no commit 07b141b91d2d76a6ff6e1cefe0e721cf42978e8b; aguarda validação CI nesse SHA.

**Decisão operacional aprovada e contrato implementado (2026-11-25):** WMS é a fonte de referência do stock físico da retaguarda; ERP permanece uma fonte administrativa independente para reconciliação. POS alimenta vendas/procura. MANUAL regista operações/contagens auditáveis. IMPORT não recebe autoridade implícita.

### Autoridade WMS por loja e localização

A autoridade física é configurada por loja através de `InventoryFreshnessPolicy` com `source=WMS` e `backroom_location_code`. A localização é um identificador exacto fornecido pelo WMS; não existe inferência por nome, SKU ou proximidade. A alteração da localização exige motivo e cria um evento append-only em `inventory_freshness_policy_events`, com actor, localização anterior/nova e timestamp.

Cada `InventorySnapshot` pode guardar `location_code` e `availability_status`:
- `AVAILABLE`: pode alimentar a quantidade disponível, calculada como físico menos reservado.
- `UNAVAILABLE`: não pode alimentar reposição.
- `UNKNOWN`: não pode alimentar reposição.
- Um snapshot sem localização não pode ser tratado como stock de retaguarda.
- A localização só é elegível quando coincide exactamente com a localização WMS configurada para a loja.

O sistema selecciona o snapshot WMS mais recente para a localização configurada, independentemente do estado de disponibilidade. Isto é intencional: um registo recente `UNAVAILABLE` ou `UNKNOWN` impede que um snapshot antigo `AVAILABLE` seja reutilizado. Não existe fallback para ERP, POS, MANUAL, IMPORT, outra localização ou outro snapshot antigo.

Se não existir `backroom_location_code` configurado, o stock de retaguarda é desconhecido. A recomendação de reposição não recebe quantidade e a reconciliação de um movimento concluído é recusada com `BACKROOM_LOCATION_NOT_CONFIGURED`. O ERP continua visível como evidência independente, mas não é somado nem substitui o WMS.

### Contratos e persistência

- A API de snapshots aceita `location_code` e `availability_status`; registos legados são migrados como `UNKNOWN` e sem localização, portanto não se tornam elegíveis por migração.
- O contrato `NormalizedInventoryRecord` mantém Decimal e timestamps com fuso horário. Um lote WMS exige localização física explícita e estado de disponibilidade explícito; um lote ERP não ganha autoridade física por conter esses campos.
- O orquestrador persiste localização/estado e compara ambos durante replay idempotente. Reutilizar uma referência com localização ou disponibilidade diferente é conflito de conteúdo.
- A reconciliação de movimentos só pode consumir snapshots WMS da localização configurada. As reservas e movimentos anteriores sobre o mesmo snapshot são subtraídos; o movimento preserva actor, motivo, tarefa, snapshot de origem e snapshot resultante.
- A migration `0084_wms_backroom_location_authority` acrescenta metadados e política por loja; `0085_inventory_backroom_policy_audit` acrescenta o histórico append-only de alterações à autoridade.

### Limites ainda existentes

Não há adapter real de fornecedor nem integração WMS homologada. A configuração da localização é explícita, mas a sua exactidão depende do contrato e dos dados fornecidos pelo WMS. A normalização de unidades logísticas (unidade/caixa/palete), reservas multi-localização e regras de transferência entre localizações continuam a exigir contratos próprios. Não converter nem somar unidades incompatíveis. A validação CI da implementação desta fase tem de ser confirmada no SHA final antes de a considerar concluída.


## Autoridade física WMS por loja/localização (2026-11-25)

O contrato operacional define WMS como autoridade da retaguarda apenas para uma localização física exacta configurada em `InventoryFreshnessPolicy.backroom_location_code` na loja correspondente. O snapshot mais recente dessa localização prevalece mesmo quando está UNAVAILABLE ou UNKNOWN; nesses estados não se reutiliza evidência anterior nem se recorre a ERP, outra localização ou MANUAL. AVAILABLE expõe `on_hand_quantity - reserved_quantity`; reservas e quantidades indisponíveis nunca entram na proposta de reposição.

ERP continua a ser fonte administrativa independente. A quantidade ERP é calculada para comparação mesmo quando `availability_status=UNKNOWN`, porque esse campo só determina disponibilidade física WMS. POS fornece evidência de vendas/procura. MANUAL mantém origem, actor, motivo e auditoria; não ganha autoridade de retaguarda por omissão. IMPORT requer classificação explícita antes de qualquer uso operacional.

Novos snapshots WMS têm de incluir `location_code` não vazio e `availability_status` AVAILABLE ou UNAVAILABLE. A API e o ORM validam o contrato; triggers de INSERT PostgreSQL e SQLite reforçam-no na base de dados. A validação é aplicada a novas linhas para preservar snapshots históricos: os registos anteriores sem localização ficam com UNKNOWN e não são elegíveis para reposição. A migration 0084 mantém os guards append-only de snapshots SQLite; a migration 0085 cria o ledger append-only das alterações de localização autorizada, com actor, localização anterior/nova, motivo e timestamp.

A regressão `test_inventory_backroom_authority_migration.py` cobre a preservação de snapshots legados, rejeição de novas linhas WMS sem proveniência, estados inválidos e imutabilidade dos snapshots/eventos. A suite completa passou com 1679 testes e 1 ignorado no SHA `c8efb82b64d4aed9fcc81fdb4a0571695fdd23cf`; os quatro workflows GitHub (API CI, Quality Gates, Security Scans e Docker Compose) terminaram com sucesso.

**Limite:** não existe adapter WMS real homologado. O código não confirma que o código de localização configurado corresponde fisicamente à retaguarda no fornecedor. Não apresentar a CI como homologação de integração externa. Normalização unidade/caixa/palete e reservas multi-localização continuam por especificar.


## Auditoria de proveniência dos movimentos de reposição (2026-11-25)

### Estado observado no código

A entidade `InventoryMovement` persiste tarefa, loja, produto, tipo, quantidade, snapshot de origem, snapshot resultante, actor, motivo e timestamp. O tipo está actualmente limitado a `BACKROOM_TO_SHELF`; a unicidade por tarefa e por snapshot resultante evita duplicações directas. O endpoint de reconciliação exige ADMIN/SUPERVISOR, tarefa concluída, quantidade efectivamente reposta positiva, snapshot WMS AVAILABLE na localização configurada e evidência dentro da política de frescura. As reservas e movimentos anteriores associados ao mesmo snapshot de origem são deduzidos antes de aceitar a quantidade.

### Lacunas que permanecem abertas

1. **Destino indirecto:** o movimento não congela directamente um identificador/código de localização de destino. O destino é inferido através da tarefa associada e da prateleira nela indicada. Para uma trilha probatória duradoura, o movimento deve guardar a identidade da prateleira/localização de destino no momento da aprovação, sem depender de uma relação operacional que possa ser alterada posteriormente.
2. **Origem indirecta:** o código de localização de origem reside no snapshot WMS referenciado. Deve ser exposto explicitamente no contrato de leitura/auditoria, mantendo o snapshot como evidência imutável e validando a coincidência com a política WMS da loja.
3. **Semântica do snapshot resultante:** a reconciliação cria um snapshot `MANUAL` com referência `TASK-RECONCILIATION-...`. Este registo representa a projecção interna do movimento aprovado; não é confirmação de escrita no WMS nem deve ser interpretado como novo saldo autoritativo da retaguarda. A sincronização WMS posterior tem de ser reconciliada sem somar novamente o movimento.
4. **Imutabilidade já implementada:** a migration `0053_inventory_movement_append_only` instala protecção de base de dados contra `UPDATE` e `DELETE` em `inventory_movements` (PostgreSQL e SQLite), com testes de migration. A migration `0052_inventory_movement_lineage_guard` valida a relação entre tarefa, loja, produto, snapshots e conservação da quantidade. Não se deve recriar estes mecanismos; a evolução deve preservá-los.
5. **Ledgers existentes, mas distintos:** `inventory_reconciliation_events` (migration `0076`) guarda eventos append-only de revisão de divergências, e `replenishment_task_events` regista o ciclo da tarefa. Nenhum destes é um ledger de eventos do movimento que represente confirmação WMS, compensação e divergência externa. Esta distinção deve ficar explícita na nova arquitectura.
6. **Concorrência:** o endpoint bloqueia a linha do produto e o snapshot de origem com `with_for_update()` e trata conflitos de integridade. O bloqueio do produto serializa conservadoramente reconciliações do mesmo SKU (inclusive entre lojas); ainda não foi localizada uma prova PostgreSQL específica com duas operações de reconciliação simultâneas a disputar o mesmo saldo. A prova deve confirmar que apenas uma operação consome a quantidade disponível e que a outra observa o saldo actualizado ou falha de forma controlada.

### Contrato de segurança a implementar

- Congelar no movimento a origem física e o destino físico, além dos IDs de evidência.
- Manter Decimal na quantidade e declarar a unidade base do produto; não aceitar conversões implícitas.
- Tratar o snapshot MANUAL resultante como registo interno de movimento, nunca como confirmação do WMS.
- Preservar as protecções append-only já existentes (`0052`/`0053`) e introduzir correcções por compensação, sem UPDATE/DELETE de movimentos aprovados.
- Criar um ledger próprio de eventos do movimento, distinto do ledger de revisão `inventory_reconciliation_events` e do histórico de tarefas.
- Garantir atomicidade entre movimento, snapshot de projecção e evento de tarefa, na mesma transacção.
- Adicionar smoke PostgreSQL com sessões concorrentes, reservas, rollback após falha e repetição idempotente.
- Só considerar o saldo externo reconciliado quando chegar evidência WMS posterior com referência/correlação inequívoca; divergências devem ir para revisão independente.

**Estado desta auditoria:** revisão adicional das migrations `0052`, `0053`, `0076`, do modelo e do smoke PostgreSQL existente. A imutabilidade do movimento e a validação de lineage já estão implementadas; o ledger de eventos do movimento, a proveniência congelada e a confirmação WMS continuam pendentes. Não foram alterados modelos, migrations, endpoints ou testes nesta passagem.


## 2026-11-25 — Identidade e proveniência física congelada dos movimentos

A migration 0086_inventory_movement_identity_provenance acrescenta operation_id UUID único, source_location_code e destination_shelf_id a inventory_movements. O endpoint de reconciliação preenche a localização de origem a partir do snapshot WMS aprovado e a prateleira de destino a partir da tarefa concluída. O contrato de leitura expõe estes campos.

A migração atribui UUID distinto a cada movimento histórico e copia a localização apenas do snapshot WMS imutável. O destino histórico permanece NULL: a relação actual da tarefa com a prateleira não prova, por si só, que essa era a prateleira no instante da aprovação. Novos movimentos congelam o destination_shelf_id no momento da criação. Os novos movimentos são protegidos por trigger INSERT PostgreSQL/SQLite que exige UUID, localização de origem não vazia e prateleira pertencente à mesma loja. Para executar o backfill, a migration suspende temporariamente apenas os triggers 0053 conhecidos dentro da própria transacção e recria-os exactamente antes de terminar; o teste dedicado verifica que UPDATE e DELETE continuam bloqueados após a migração.

Limite desta fatia: o destino congelado é o identificador da prateleira; ainda não existe um código físico de localização de loja separado da identidade da prateleira. A migration não introduz ainda ledger de eventos do movimento, compensações ou confirmação WMS idempotente. A validação final depende dos workflows GitHub Actions no SHA desta alteração.


## Precisão e semântica das reservas

Os snapshots físicos persistem `on_hand_quantity` e `reserved_quantity` em `NUMERIC(12,3)`. O endpoint de criação rejeita precisão superior a três casas decimais e converte os números HTTP para Decimal antes da persistência, evitando arredondamento silencioso. O contrato de adapters já normaliza ambas as quantidades como Decimal e rejeita `reserved_quantity > on_hand_quantity`.

A reserva é um agregado reportado pela fonte WMS para a localização configurada. O SMART SHELF AI calcula `available_quantity = on_hand_quantity - reserved_quantity`; não cria, liberta ou altera reservas externas. A criação/atribuição de uma tarefa de reposição não reserva stock e o plano de embalagens mantém `stock_reserved=false`.

Não existe ainda detalhe de reserva por identificador externo, documento, estado ou linha de encomenda. Sem esse contrato do fornecedor, não é seguro inventar um ledger interno nem reconciliar reservas individuais. A reconciliação actual é ao nível do snapshot, loja, SKU e localização WMS autorizada.


## Unidade base e embalagens logísticas internas

O catálogo define Product.unit como unidade base do SKU. ProductPackagingLevel.base_units_per_package expressa cada nível UNIT/CASE/PALLET nessa unidade base, com factor decimal persistido em NUMERIC(14,3). O planeamento converte quantidades com Decimal, expõe campos exactos textuais e não cria reservas nem movimentos de stock. A API rejeita factores com mais de três casas decimais para impedir que a persistência arredonde silenciosamente o factor.

**Fronteira ainda não implementada:** o adapter WMS ainda não normaliza os códigos de unidade do fornecedor para Product.unit, nem homologa factores de conversão externos. Não assumir que EA, CS, BOX, PAL, kg, litros ou outras unidades são equivalentes sem catálogo/mapeamento aprovado por fornecedor e SKU. A configuração actual de embalagens internas não constitui prova de correspondência com a unidade externa.


## Contagens MANUAL — identidade e auditoria (migration 0091)

As contagens `source=MANUAL` exigem utilizador autenticado e activo com papel ADMIN ou SUPERVISOR autorizado para a loja, além de motivo explícito. O snapshot e o evento `inventory_manual_count_events` são inseridos na mesma transacção; uma falha de auditoria reverte também o snapshot. O evento é append-only, liga snapshot/loja/produto através de FK composta e preserva actor, motivo e timestamp. Os triggers PostgreSQL e SQLite validam a proveniência; o trigger SQLite exige igualmente actor activo e papel ADMIN ou SUPERVISOR da mesma loja. Esta operação regista uma contagem manual auditável, não constitui confirmação WMS nem altera o stock externo.

A migration 0091 e a regressão de actor inactivo foram corrigidas no commit `94fe027` e `ecc751c`. A validação efectiva da migration em SQLite/PostgreSQL 16 e os workflows CI do HEAD continuam pendentes; não considerar a migration integralmente homologada até essa evidência existir.


## Validação de proveniência da contagem MANUAL — revisão 0091

A migration 0091 possui agora cobertura específica da migration SQLite, não apenas testes sobre tabelas criadas por ORM: a suite aplica directamente `upgrade()` e `downgrade()`, valida a aceitação de SUPERVISOR activo da mesma loja e ADMIN global, e rejeita actor de outra loja, actor inactivo, EMPLOYEE e snapshots com origem diferente de MANUAL. O mesmo teste verifica UPDATE/DELETE bloqueados e preservação dos snapshots no downgrade.

O API CI inclui também `postgres_inventory_manual_count_audit_smoke.py`, que exercita PostgreSQL 16 após `alembic upgrade head`, através do endpoint autenticado e de INSERTs directos para provar os triggers da base de dados. O smoke específico passou no SHA `7a20c95`. A suite do HEAD posterior ainda tem de confirmar o teste SQLite, os restantes smokes, e os workflows globais antes de a revisão ser considerada homologada.


### Homologação da migration 0091 (25/11/2026)

A revisão 0091 foi validada no SHA `c4f839bcfd076c2b5575eccfd314fae96983b3ed`. O API CI executou `alembic upgrade head` em PostgreSQL 16 e o smoke dedicado confirmou os triggers de proveniência e append-only. A suite executou o teste de migration SQLite (upgrade/downgrade e rejeições de provenance) e terminou com **1707 passed, 1 skipped**. Quality Gates, Security Scans e Docker Compose terminaram com sucesso.

Runs: API CI `45650155916`; Quality Gates `45650155829`; Security Scans `45650155800`; Docker Compose `45650155946`.

A migration 0091 está homologada para os cenários cobertos. A próxima revisão centra-se na semântica de snapshots WMS consecutivos e reservas agregadas, sem criar um ledger de reservas individuais sem identificadores/documentos disponibilizados pelo fornecedor.


## Proveniência de snapshots por execução de sincronização — migration 0092

Os snapshots criados pelo worker ERP/WMS passam a transportar `source_sync_id`, referência à execução persistida em `inventory_source_syncs`. O vínculo é validado no INSERT: a execução tem de existir, pertencer à mesma loja, usar a mesma origem e permanecer em `STARTED`. PostgreSQL aplica FK RESTRICT e trigger com lock da linha da execução; SQLite aplica trigger equivalente. A imutabilidade do snapshot torna o vínculo permanente.

Snapshots históricos, contagens MANUAL e snapshots criados fora do worker permanecem com `source_sync_id=NULL`; não foi fabricada proveniência retroactiva. No replay após falha, uma linha de página já commitada mantém a execução PARTIAL que realmente a inseriu; páginas novas pertencem à execução de recuperação SUCCESS. A API de leitura inclui o identificador para permitir navegar da evidência de stock até ao histórico de sincronização.

A validação no branch `f63543c` terminou com API CI **1715 passed, 1 skipped**, PostgreSQL 16 smoke, Quality Gates, Security Scans e Docker Compose com sucesso. O commit de merge `76fb62d` ainda tinha os workflows main queued quando esta nota foi preparada.

### Limitação em avaliação — skew temporal ERP/WMS

A comparação actual pode classificar `DIVERGENCE` quando ambos os snapshots estão dentro das respectivas janelas de freshness, mesmo que tenham instantes de captura significativamente diferentes. A diferença de captura deve ser explicitada e sujeita a uma política de skew configurável antes de classificar a divergência. Não foi introduzido um limite arbitrário.


### Confirmação dos workflows na main — 25/11/2026

Após o merge da migration 0092, os workflows da branch `main` terminaram com sucesso: API CI `45654043683` (**1715 passed, 1 skipped**), Quality Gates `45654278572`, Security Scans `45654278738` e Docker Compose `45654043988`. O check Vercel continua com `build-rate-limit`, uma limitação de quota externa, separada da validação GitHub.

A próxima análise é o skew temporal ERP/WMS. O sistema expõe os timestamps de cada origem, mas ainda não existe uma política operacional de tolerância entre capturas; nenhum limite deve ser inventado pelo código.


## Política de skew temporal ERP/WMS — migration 0093

A diferença absoluta entre os timestamps de captura ERP e WMS é exposta em `erp_wms_capture_skew_seconds`. A tolerância é configurada na política ERP da loja, através de `comparison_skew_tolerance_minutes`; o campo é opcional, aceita 0–10080 minutos e exige motivo auditável. A política WMS não pode definir esta tolerância. NULL significa explicitamente que a tolerância operacional ainda não foi configurada.

Quando ambas as fontes estão CURRENT e a tolerância está NULL, timestamps diferentes produzem `TEMPORAL_SKEW_UNCONFIGURED`; o delta quantitativo fica NULL. Com tolerância configurada, um skew superior ao limite produz `TEMPORAL_SKEW`, também sem delta. Apenas capturas dentro da tolerância permitem comparar quantidades e produzir IN_SYNC/DIVERGENCE. Um valor zero exige timestamps coincidentes.

Cada alteração é registada na mesma transacção da política, com actor, valor anterior/novo, motivo e timestamp no ledger append-only existente. A migration 0093 preserva políticas e eventos históricos com tolerância NULL; não introduz limite operacional por defeito. A configuração efectiva deve ser aprovada pelo responsável da operação e validada com a cadência real dos adapters.


## Snapshots WMS fora de ordem e mudança da localização autorizada

A reconciliação selecciona o snapshot WMS mais recente pela combinação `store_id + product_id + source=WMS + backroom_location_code`, ordenando por `captured_at DESC, id DESC`. Uma alteração da localização autorizada não reutiliza snapshots da localização anterior. Se ainda não existir evidência na nova localização, o stock de retaguarda permanece desconhecido; não há fallback para a localização antiga.

Snapshots recebidos tardiamente com `captured_at` anterior são preservados como histórico imutável, mas não substituem evidência mais recente da mesma localização. O desempate de timestamps iguais é determinístico pelo ID do snapshot. A disponibilidade operacional continua a ser `on_hand_quantity - reserved_quantity`; a reserva é um agregado reportado pelo WMS, não uma lista de reservas individuais.

A regressão `test_wms_backroom_location_change_and_late_snapshot_never_restore_old_stock` cobre a mudança auditada de localização, ausência de fallback, chegada tardia e cálculo de disponibilidade. API CI PostgreSQL 16 terminou com **1718 passed, 1 skipped** no SHA `fb1470185126dfe295a15b1f69f635aed05b3da3`; os quatro workflows GitHub passaram.


## Reservas agregadas e movimentos internos

O campo WMS `reserved_quantity` é tratado como agregado por SKU/localização, não como lista de reservas identificáveis. A disponibilidade do snapshot é `on_hand_quantity - reserved_quantity`. Ao reconciliar um movimento, o serviço deduz adicionalmente a soma dos movimentos já registados sobre o mesmo `source_snapshot_id`; não altera o snapshot WMS original. O snapshot interno resultante preserva o agregado reservado e reduz o on-hand pela quantidade movimentada, sendo uma projecção interna e não uma confirmação WMS.

A regressão `test_reserved_wms_quantity_is_subtracted_once_across_multiple_movements` valida dois movimentos sucessivos de 6 unidades sobre um snapshot com on-hand 20 e reserva agregada 5: disponibilidades resultantes 9 e 3, mantendo a reserva 5 e o snapshot WMS original imutável. API CI PostgreSQL 16: **1719 passed, 1 skipped** no SHA `043c15f4980b45c4d50d2cd47fb921c5504eccac`.

A confirmação externa WMS permanece separada. Não se deve inferir que um snapshot posterior confirma um movimento apenas porque a quantidade mudou; é necessária correlação inequívoca fornecida pelo adapter/ERP/WMS e uma decisão de contrato explícita.


## Proveniência física do destino dos movimentos — migration 0094

Cada movimento conserva `destination_shelf_id` e `destination_shelf_code`. O ID identifica a entidade; o código é um snapshot imutável do identificador físico legível no instante da operação. O serviço bloqueia a prateleira de destino, confirma a associação à loja da tarefa e grava o código no movimento e no evento `MOVEMENT_RECORDED`.

A migration 0094 preenche o código histórico através da relação tarefa → prateleira → zona/loja e falha de forma segura se encontrar movimentos sem destino consistente. Triggers PostgreSQL/SQLite validam novos movimentos contra a prateleira e a loja da tarefa, impedindo destino forjado ou ausente. Renomear uma prateleira posteriormente não altera a evidência histórica já registada.

A validação no SHA `3f4c9740ce70e932c5cb35745e96edd1163bf864` incluiu migration PostgreSQL 16, teste SQLite de backfill/guardas, smoke PostgreSQL de linhagem e concorrência e suite API: **1720 passed, 1 skipped**.


## Identidade completa do destino e retenção — migration 0095

O movimento congela a identidade física do destino com `destination_shelf_id`, `destination_shelf_code`, `destination_zone_id` e `destination_zone_name`. O flag `destination_location_backfilled` distingue os dados capturados na operação (`false`) dos valores históricos preenchidos pela hierarquia actualmente disponível durante a migration (`true`). Esta distinção é necessária porque renomeações anteriores à migration não podem ser reconstruídas sem um ledger histórico.

As guardas PostgreSQL/SQLite validam a correspondência tarefa → prateleira → zona → loja, incluindo código e nome, e rejeitam novos movimentos com o flag de backfill activo. O smoke PostgreSQL confirmou que renomear a prateleira/zona não altera os campos históricos do movimento e que a eliminação física da prateleira/zona é bloqueada pela cadeia de retenção que passa pela tarefa e pelo movimento.

Se a operação exigir esconder ou descontinuar zonas/prateleiras, deve ser implementado arquivamento/soft-delete; não se deve remover FKs, apagar movimentos ou reescrever a evidência. API CI PostgreSQL 16: **1722 passed, 1 skipped** no SHA `48fdf8310d1b17179ba6520d7a559b3bcc822c7f`.
