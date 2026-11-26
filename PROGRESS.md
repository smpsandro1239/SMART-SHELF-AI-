## 2026-11-26 — Correcção do smoke PostgreSQL de propriedade da prateleira

- SHA inicial desta correcção: `e502850fba7106944827b79cf1671c029b7b2d29`.
- A API CI [45819714432](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45819714432) falhou no passo `Verify PostgreSQL capture-session tenant authorization`, antes de executar a suite pytest e o smoke dos sync jobs.
- O log identificou a causa exacta: `_assert_zone_transfer_waits_for_shelf_write_lock()` esperava que o UPDATE de `zones.store_id` tivesse sucesso depois de libertar o lock. A trigger `prevent_shelf_record_upstream_store_change()` rejeitou-o correctamente porque a transacção tinha acabado de persistir uma `CaptureSession`, que constitui evidência operacional retida.
- Corrigido `apps/api/scripts/postgres_capture_session_authorization_smoke.py`: mantém a prova de espera PostgreSQL (`wait_event_type='Lock'` e PID bloqueador), exige depois `IntegrityError` com a razão esperada, e confirma que a sessão e a zona permanecem na loja A e que o supervisor da loja A conserva acesso.
- Commit da correcção: `5f7867bb67c2d2334d8afe85da7c8838ba87db5b`.
- Não foi alterada nenhuma migration nem a regra de integridade. Não foram executados testes localmente nesta sessão; a validação depende da nova API CI/PostgreSQL 16 e dos restantes workflows no HEAD actualizado.

## Continuação da auditoria P0

## P0 — Serialização da propriedade da prateleira nas escritas (2026-11-26)

- [x] Introduzir `_lock_store_scoped_shelf()`: obter a linhagem inicial, bloquear primeiro `Zone` com `SELECT FOR UPDATE`, validar novamente o tenant e bloquear depois `Shelf`; uma alteração de `zones.store_id` tem de aguardar pela transacção da escrita.
- [x] Aplicar o helper à criação de observações, criação de sessões de captura e upload de imagens.
- [x] Derivar `CaptureSession.store_id` e o directório de armazenamento da zona bloqueada, nunca de uma relação ORM carregada antes do lock.
- [x] Manter a ordem de locks `Zone → Shelf → CaptureSession` no upload e validar que a sessão pertence à mesma prateleira e loja.
- [x] Abranger escrita do ficheiro, `flush`, `refresh` e `commit` no mesmo bloco de limpeza; qualquer falha antes do commit faz rollback e remove um ficheiro parcial.
- [x] Acrescentar regressão HTTP para observação, sessão e upload cross-store, sessão de outra loja, sessão da mesma loja mas de outra prateleira e controlo positivo same-store.
- [x] Reforçar o smoke PostgreSQL já executado pelo API CI: criação HTTP de sessões same-store/cross-store e prova de que um UPDATE concorrente de `zones.store_id` fica em `wait_event_type='Lock'`, bloqueado pelo PID da transacção que mantém a escrita da prateleira.
- [ ] Executar e confirmar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA final.
- [ ] Rever o resultado dos workflows e corrigir eventuais regressões antes de considerar P0.1 fechado.

Limite: o inventário actual de rotas não encontrou endpoint HTTP de transferência/actualização de zonas. O smoke usa um UPDATE SQL concorrente para representar a alteração da loja proprietária e comprovar a serialização ao nível PostgreSQL; não afirma a existência de uma operação de transferência na API. Os testes adicionados e o smoke ainda carecem de execução CI no SHA final. As migrations 0099/0100 não foram alteradas.


## 2026-11-26 — Revalidação de tenant no consenso de observações

- SHA inicial da ronda: `702462a57d108041c62e92624aed79b609666a52`.
- Alterado `apps/api/app/main.py`: a validação da associação SKU/prateleira e a query de observações aplicam agora o âmbito `Zone.store_id` através da linhagem Shelf → Zone, na própria instrução que lê os registos.
- A resposta do SUPERVISOR mantém o `store_id` do tenant autenticado, sem voltar a expor o valor da relação após o preflight.
- Alterado `apps/api/tests/test_observations.py`: regressão determinística que transfere a zona depois do preflight e confirma que a query de evidência não devolve observações do novo tenant.
- Commits de código/teste: `61a69adfd2cb9325410daf4ea0c1f4e9d17dce9d` e `a61811c6f8a78358a7882d437a7358599503cba9`.
- A documentação foi reconciliada com a evidência CI anterior: API CI `45812501875` confirmou os smokes de artefactos externos e IDs directos de deteções/exemplares; Quality Gates `45812501507`, Security Scans `45812501427` e Docker Compose `45812501364` passaram no commit de código anterior.
- **Validação da alteração de consenso pendente:** os novos commits ainda precisam de API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose. Não afirmar que o novo teste passou até os workflows terminarem.
- Próxima prioridade: continuar a auditoria de IDs directos e históricos ERP/WMS, incluindo a query de eventos de jobs de sincronização, sem assumir vulnerabilidade antes de provar a linhagem e o caminho concorrente.

## 2026-11-26 — Hardening BOLA/IDOR no histórico de eventos de alertas

- A auditoria encontrou que `GET /api/v1/observation-alerts/{alert_id}/events` fazia uma leitura scoped do alerta-pai e, numa segunda query, carregava os eventos apenas por `alert_id`. Como `ObservationAlertEvent` não tem `store_id`, a query final não repetia a condição de tenant e existia uma janela de TOCTOU entre as duas leituras.
- A consulta de eventos passou a fazer JOIN com `ObservationAlert` e, para SUPERVISOR, aplica `ObservationAlert.store_id == actor.store_id` directamente na query que devolve os eventos.
- Quando não existem eventos, uma query scoped de existência distingue um alerta próprio sem histórico de um alerta estrangeiro/inexistente. O primeiro devolve `[]`; os dois últimos devolvem HTTP 404 indistinguível. ADMIN mantém acesso global e EMPLOYEE continua bloqueado antes da consulta.
- Adicionada regressão HTTP com alertas e eventos em duas lojas; verifica histórico same-store, `[]` para alerta próprio sem eventos, 404 para alerta estrangeiro e igualdade do corpo com ID inexistente.
- Commits: implementação `b18aed40e7c6bc9bcf0e1454e215f8466f10012e`; teste `4d465130334951865ba2abc5997d3f34699ce502`.
- Testes e workflows ainda não executados nesta sessão; validação pendente no HEAD final.

## 2026-11-26 — Hardening BOLA/IDOR nos históricos de tarefas e movimentos

- Continuação da auditoria dos históricos de recursos-pai com eventos sem tenant próprio.
- Em `GET /api/v1/tasks/{task_id}/events`, a consulta dos eventos passou a fazer JOIN com `ReplenishmentTask` e a aplicar `store_id` na mesma query para SUPERVISOR. Quando a query não devolve eventos, uma verificação scoped distingue um histórico legitimamente vazio de um ID estrangeiro/inexistente.
- Em `GET /api/v1/inventory/movements/{movement_id}/events`, a consulta passou a fazer JOIN com `InventoryMovement` e a filtrar `store_id` do movimento e do evento na mesma query. A verificação de existência só é necessária quando o histórico está vazio, preservando HTTP 404 para IDs estrangeiros/inexistentes e `[]` para um movimento autorizado sem eventos.
- ADMIN conserva o acesso global e EMPLOYEE continua bloqueado. Não foram alteradas operações de escrita nem a semântica dos ledgers append-only.
- Adicionada regressão HTTP para histórico de tarefas, comparando tarefa estrangeira com ID inexistente e confirmando acesso same-store. A regressão existente de movimentos já compara movimento estrangeiro/inexistente e verifica bloqueio EMPLOYEE; permanece aplicável à query reforçada.
- Commits: implementação `8798143143d82605d978b9633c28e5e671e0b410` e `67f526a6385ef171cfa6c63d705f63ae4d10b53e`; teste `2663e06b8030169bdc2476577129b44a7bd71d70`.
- Testes focados e workflows ainda não executados nesta sessão. Não declarar aprovação até existir evidência no SHA final.

## 2026-11-26 — Hardening BOLA/IDOR no histórico de retenção de imagens

- Continuação a partir do HEAD `ab5104b1f555ff0e687bfafb0c64d42d6d8b0766`.
- O endpoint `GET /api/v1/shelf-images/{image_id}/retention/events` resolvia o tenant, depois carregava a imagem por ID global e voltava a resolver o tenant. A sequência deixava uma janela entre a validação e a materialização.
- A leitura foi reforçada com JOIN ShelfImage → Shelf → Zone e filtro de tenant directamente na query de eventos. Quando não existem eventos, uma query scoped separada distingue histórico vazio de imagem inexistente/estrangeira sem revelar a existência do recurso. Assim, a query que devolve eventos não depende apenas de uma validação anterior susceptível a alteração concorrente da associação da imagem.
- Acrescentada regressão HTTP com imagem estrangeira que contém evento de retenção; compara ID estrangeiro e inexistente (404 e corpo idêntico).
- Commits: implementação `838f2c0592f934ba91fb6f56af498cccf89ac15f`; teste `ceacbec09ca1e345e16c1eb47661933de275a8d8`.
- A alteração anterior de embeddings e os seus testes permanecem publicados nos commits anteriores.
- Testes e workflows ainda não executados nesta sessão. Não declarar aprovação.
- Próxima prioridade: prosseguir com endpoints de artefactos e rever os limites de transacção/locks dos acessos a imagens.

## 2026-11-26 — Hardening BOLA/IDOR na revisão de exemplares de embeddings

- HEAD de partida: `2f44a16d5df769930314837f91f7ef06bb37e017`.
- Identificada leitura inicial global por `db.get(ProductEmbeddingExemplar, exemplar_id)` antes da validação do tenant de origem.
- Alterada a resolução inicial para aplicar joins ShelfImage → Shelf → Zone e filtrar pela loja do actor na própria query. Um exemplar de outra loja deixa de ser materializado para SUPERVISOR; IDs estrangeiros e inexistentes recebem 404 idêntico.
- Mantida a regra para exemplares sem imagem: a query permite identificá-los apenas para conservar a resposta 403 ADMIN-only já definida.
- Adicionada regressão HTTP que tenta rever exemplar estrangeiro, compara com ID inexistente e confirma que o exemplar continua PENDING sem reviewer/timestamp.
- Commits: implementação `c14236cca79d307e65023951a1abd4ac131855d1`; teste `c0bb997e1f8ce938b706bf29d51223350184bed5`.
- Teste e workflows ainda não executados nesta sessão. Não declarar aprovação.
- Próxima prioridade: aprofundar os restantes endpoints directos e validar concorrência na relação exemplar/imagem.

## 2026-11-26 — Cobertura de políticas RBAC por rota

- HEAD de partida: `c56c3ec00040a869c374481a918106bbd5456551`.
- Inventário estático dos decorators HTTP de `apps/api/app/main.py`: 156 rotas encontradas, das quais `/health` e `/health/ready` são endpoints operacionais fora de `/api/v1/*`. Todas as rotas versionadas da aplicação principal têm correspondência por método e template em `API_ROUTE_POLICIES`.
- A entrada `POST /api/v1/edge/events` pertence ao router Edge separado e não foi confundida com uma rota sem classificação.
- Adicionada regressão em `apps/api/tests/test_inventory.py` que percorre as rotas FastAPI registadas e falha perante qualquer rota `/api/v1/*` sem política explícita.
- Commit: `011b823d17c39f9effbd8af8c702c5b3486bdde1`.
- A regressão e os restantes workflows ainda não foram executados nesta sessão. Não declarar a cobertura runtime nem a suite CI aprovadas até existir evidência.
- Próxima prioridade: auditoria BOLA/IDOR dos handlers com IDs directos, incluindo equivalência entre recurso estrangeiro e ID inexistente e prova de ausência de mutação após recusas.


## 2026-11-25 — Validação final da autoridade WMS por localização

- SHA validado: `c8efb82b64d4aed9fcc81fdb4a0571695fdd23cf`.
- Contrato operacional aplicado: WMS/localização exacta é autoridade do stock físico da retaguarda; ERP continua independente para reconciliação administrativa; POS é evidência de vendas/procura; MANUAL é auditável e IMPORT não recebe autoridade implícita.
- Novos snapshots WMS exigem `location_code` e `availability_status` explícitos (AVAILABLE ou UNAVAILABLE). A API, o ORM e triggers de inserção PostgreSQL/SQLite impedem proveniência incompleta. Snapshots legados permanecem UNKNOWN e não são elegíveis.
- Corrigida a serialização da evidência de reconciliação: o stock ERP administrativo continua disponível para comparação mesmo quando o estado WMS é desconhecido; quantidades WMS só são disponibilizadas quando AVAILABLE.
- Corrigidas regressões nos fixtures de recomendações, decisões operacionais, tarefas, picking e deteção demo para representar a localização WMS configurada. A regressão de migração SQLite confirma que os guards append-only existentes sobrevivem à migration 0084.
- Suite API/PostgreSQL: **1679 passed, 1 skipped** (API CI, run 45574197186). Quality Gates: sucesso (45574197259; TypeScript/build Web e suite API). Security Scans: sucesso (45574197237). Docker Compose: sucesso (45574197037).
- Os 47 passos anteriores de smoke PostgreSQL, incluindo o smoke do worker durável ERP/WMS com fencing, SIGKILL e replay idempotente, também terminaram com sucesso no API CI.
- Limites: não existe adapter WMS real homologado; o contrato de localização tem de ser validado com o fornecedor. Normalização unidade/caixa/palete e reservas multi-localização continuam pendentes. Os indicadores Vercel continuam a falhar por `build-rate-limit` da conta, independente dos quatro workflows GitHub.

## 2026-11-25 — Autoridade física WMS por loja e localização

- Decisão operacional confirmada: WMS é a fonte de referência do stock físico de retaguarda; ERP continua como fonte administrativa independente; POS é evidência de vendas/procura; MANUAL e IMPORT não recebem autoridade física implícita.
- A migration 0084 acrescenta `location_code` e `availability_status` aos snapshots e `backroom_location_code` à política por loja/fonte. Snapshots históricos ficam sem localização e com estado UNKNOWN; não existe backfill permissivo.
- A migration 0085 cria o ledger append-only de alterações à localização autorizada, com utilizador, valor anterior/novo, motivo e timestamp.
- A API permite configurar a localização exacta em `POST /api/v1/inventory/freshness-policies`; uma alteração exige motivo e é persistida na mesma transacção que a política.
- O contrato WMS exige localização e estado de disponibilidade explícitos. O orquestrador persiste ambos e rejeita replay da mesma referência com conteúdo/proveniência diferente.
- A reconciliação de prateleiras, recomendações e decisões operacionais passaram a seleccionar apenas a localização WMS configurada. O snapshot mais recente é considerado mesmo quando UNAVAILABLE/UNKNOWN, impedindo fallback para evidência antiga. A quantidade utilizável só existe no estado AVAILABLE e desconta reservas.
- A reconciliação de movimentos exige configuração WMS, usa apenas o snapshot da localização autorizada e rejeita estados indisponíveis; ERP e snapshots MANUAL resultantes não são tratados como stock físico de retaguarda.
- Regressões acrescentadas para ERP sem fallback, localização incorrecta, WMS indisponível mais recente, configuração por loja e auditoria append-only. Fixtures de reconciliação/recomendação actualizados para WMS explícito.
- Commits de implementação e testes publicados directamente na `main`: `d08889f`, `62375ab`, `246df54`, `5ae428a`, `2c9c4c6`, `0a5c2c7`, `c7e7e30`, `2d44eb8`, `3fdeb41`, `9ced69c`, `3ff13e9`, `2e44077`, `c17ac8a`, `badced8`, `59c00e6`, `d9ba7af`, `7757a86`, `e96f4c0`, `8afd9c4`, `1fd57a2`, `d5fadb5`, `d02bf8e`, `7ff171e`, `ebee1ba`, `9e18fc3`.
- Documentação actualizada em README, TODO, ROADMAP e INVENTORY-SOURCE-SYNC.
- Validação CI desta implementação ainda pendente. Não foram executados testes localmente nesta sessão; a confirmação depende dos workflows no SHA final.
- Limites: não existe adapter WMS real homologado; a localização configurada tem de corresponder ao contrato do fornecedor. Normalização de unidades logísticas e reservas multi-localização continuam pendentes.

## 2026-11-25 — Diagnóstico e correcção do smoke de fencing PostgreSQL

- Consultado o log integral do API CI no commit `c7b90ee4ae8603ad1648abeb7f7b81608a91b73c`. PostgreSQL 16, migrações, provisionamento do runtime role e os 40 smokes anteriores terminaram com sucesso.
- A falha ocorreu no início de `_verify_stale_worker_fencing()`: `sqlalchemy.orm.exc.DetachedInstanceError` ao avaliar `old.fencing_token` depois de a sessão que carregou o job ter fechado.
- Causa: o claim confirma a transacção e o SQLAlchemy expira atributos; após o fecho da sessão, o teste tentava carregar novamente atributos da instância detached.
- Correcção publicada: capturar `lease_token` e `fencing_token` como valores escalares enquanto a instância ainda está associada à sessão. O teste continua a exigir incremento de fencing, rejeição do lease antigo e rejeição do percurso de escrita do orquestrador.
- Não foi alterada a lógica de produção do claim, lease, fencing ou orquestrador.
- Commit: `e3dae9d04e58d6e1419a4e9b23188fe5d2c7ef39`. API CI do novo HEAD e restantes gates ainda pendentes de execução/conclusão.

## 2026-11-24 — Contrato de adapters ERP/WMS

- Criado o pacote `app.inventory_connectors` com protocolo assíncrono read-only e lote normalizado.
- A validação rejeita quantidades negativas/não finitas, precisão superior a três casas decimais, reservado superior ao físico, timestamps sem fuso horário, SKU/referências duplicados e identificadores inválidos.
- O loader aceita apenas factories de deployment configuradas no formato `module:callable`; configuração ausente, factory inválida ou fonte incompatível falha explicitamente.
- Testes dedicados cobrem validação de evidência, paginação, ausência de configuração e conformidade de adapters.
- Limite deliberado: ainda não existe adapter de fornecedor, worker, scheduler, credencial ou sincronização automática. Não são criados snapshots nem movimentos por este contrato.
- Commits: `04ae70f` (pacote), `5074be6` (contrato), `e9951bf` (testes). CI do novo HEAD pendente.

## 2026-11-24 — Histórico e saúde das sincronizações ERP/WMS

- Criadas as tabelas inventory_source_syncs e inventory_source_sync_events, com eventos append-only e transição única STARTED → estado terminal.
- Disponibilizados endpoints para iniciar/registar uma tentativa, concluir, consultar histórico e obter saúde ERP/WMS por loja.
- A saúde calcula SOURCE_NEVER_SYNCHRONIZED e SOURCE_SYNC_STALE a partir da última execução SUCCESS e da política de frescura; PARTIAL não é tratado como sucesso integral.
- Criado InventorySourceSyncPanel.tsx para apresentar saúde, tentativas recentes, contagens, duração e erros.
- A documentação clarifica que não existe ainda connector real: os endpoints registam o resultado reportado por um processo externo e não alteram snapshots ou saldos.
- Migration 0077 e testes de lifecycle/migração adicionados. API CI e restantes workflows do HEAD final ainda por validar.

## 2026-11-23 — Histórico de movimentos de inventário

- Implementado `GET /api/v1/inventory/movements`, endpoint read-only para consultar transferências BACKROOM_TO_SHELF já reconciliadas.
- A loja é obrigatória; filtros opcionais por produto e tarefa. Limite de resultados normalizado para 1–500.
- A leitura exige ADMIN ou SUPERVISOR e aplica o âmbito de loja antes de consultar movimentos.
- Adicionados dois testes em `apps/api/tests/test_inventory.py`: consulta/filtros sem mutação e rejeição de EMPLOYEE/loja estrangeira.
- Commits: `7ce55e4e` (API) e `20c0947e` (testes). CI pendente; sem execução local nesta sessão.

## 2026-11-23 — Desenvolvimento funcional do dashboard operacional

- Expandido `GET /api/v1/dashboard/summary` com tarefas por prioridade, tarefas activas urgentes, tarefas activas sem atribuição e taxa de conclusão.
- Corrigida a semântica de `shelves_requiring_attention`: agora conta prateleiras distintas com pelo menos uma observação LOW_STOCK ou EMPTY, evitando duplicação quando existem várias observações na mesma prateleira.
- Adicionado `attention_observations` para preservar a métrica de volume de observações e não confundi-la com o número de prateleiras.
- Mantidos os filtros: ADMIN global ou por loja, SUPERVISOR limitado à própria loja e EMPLOYEE apenas às suas tarefas atribuídas.
- Testes adicionados em `apps/api/tests/test_dashboard_summary.py` para KPIs, duplicação de observações e fronteiras RBAC.
- Commits: `2447d628` (API), `4da1c2f1` e `1ac4948b` (testes). CI ainda pendente; não foi executado localmente nesta sessão.

## 2026-11-23 — Reforço da prova BOLA de deteções e exemplares

- O smoke PostgreSQL `postgres_detection_exemplar_prelock_smoke.py` compara agora respostas completas (status + JSON) entre IDs reais cross-store e IDs inexistentes para revisão de deteções, histórico de revisões e revisão de exemplares.
- As seis chamadas continuam a ser executadas enquanto as linhas da imagem e do produto estão bloqueadas; todas têm de devolver HTTP 404 idêntico por par e não podem persistir revisões.
- Commit: `1cdc4f67`. A validação CI do novo commit está pendente; não foi executado localmente nesta sessão.

## 2026-11-23 — Isolamento PostgreSQL de artefactos externos

- Expandido `apps/api/scripts/postgres_artifact_consumption_smoke.py`, já integrado no API CI, para testar combinações de IDs reais entre imagens da mesma loja e de lojas diferentes.
- Cinco combinações de `image_id`, `artifact_id` e `store_id` têm de ser rejeitadas antes da chamada ao provider.
- Criado um controlo positivo em que a leitura da loja A continua a funcionar apesar de existir uma integração REVOKED na loja B com o mesmo identificador de sistema externo.
- Acrescentada uma tentativa de inserir um artefacto filho associado a um pai de outra imagem da mesma loja; a FK composta PostgreSQL tem de rejeitar a operação.
- Commit de código: `2bf0d075`. CI ainda pendente; não declarar validação PostgreSQL até terminar a execução.

## 2026-11-23 — Hardening de IDs multi-loja em planogramas e Warehouse

- Corrigida a regressão de contrato dos planogramas: os testes HTTP passaram a exigir HTTP 404 para prateleiras estrangeiras e inexistentes, com payload idêntico. A comparação de planogramas recebeu o mesmo controlo negativo.
- O primeiro smoke PostgreSQL depois da alteração revelou uma expectativa antiga de HTTP 403 na criação de planogramas; a expectativa foi actualizada para 404, em linha com a política de ocultação. Não foi alterada a autorização funcional de EMPLOYEE.
- Expandido `postgres_inventory_authorization_smoke.py`: GET de eventos de paletes estrangeiras, POST de ciclo de vida de paletes estrangeiras, PATCH de política de rotação estrangeira, comparação com IDs inexistentes, controlos positivos same-store e verificações de ausência de mutação.
- O smoke confirmou que a palete estrangeira permanece em `READY`, sem novos eventos, e que a política estrangeira permanece activa. A actualização da palete da própria loja foi aceite.
- API CI [45268275419](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275419): PostgreSQL 16, migrations, todos os smokes e **1599 passed, 1 skipped**.
- Quality Gates [45268275423](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275423): **1599 passed, 1 skipped**, compilação Python e build Web.
- Security Scans [45268275427](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275427): Gitleaks, pip-audit, npm audit e OWASP ZAP passive baseline aprovados.
- Docker Compose [45268275477](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275477) aprovado.
- Commit de validação: `a29a7ea2fde29d7a49576c435700c7516b00f2a2`.

## 2026-11-23 — Ocultação de IDs de prateleiras nas operações de planograma

- A função `_planogram_shelf_scope` passou a aplicar `Zone.store_id == actor.store_id` na própria query para SUPERVISOR, mantendo ADMIN global.
- IDs de prateleiras estrangeiras e inexistentes devolvem HTTP 404 com detalhe idêntico (`Shelf not found`).
- Foi actualizada a regressão em `apps/api/tests/test_capture_sessions.py` para exigir o novo contrato.
- Commits: teste `5eadb280`; implementação `ccb30063`.
- Validação automatizada deste HEAD ainda pendente; não foi executado pytest localmente nesta sessão.


## Reforço BOLA — histórico de eventos de paletes (2026-11-23)

- O smoke PostgreSQL de autorização de inventário já exercitava leituras same-store e cross-store do histórico de paletes.
- Foi acrescentada uma comparação explícita entre uma palete real da loja B consultada pelo supervisor da loja A e um ID inexistente (-1), ambos com store_id da loja A.
- O critério de segurança é HTTP 404 e corpo de resposta exactamente igual; o controlo positivo same-store permanece HTTP 200.
- A alteração está publicada no commit que acompanha esta atualização documental. CI pendente até conclusão dos workflows no SHA final.

---

## 2026-11-23 — Isolamento SQL directo no histórico de alertas

- A consulta `GET /api/v1/observation-alerts/{alert_id}/events` passou a filtrar `alert_id` e `store_id` na mesma query para SUPERVISOR; o handler deixa de carregar uma linha estrangeira antes da autorização.
- ADMIN mantém acesso global; EMPLOYEE continua a receber HTTP 403.
- Teste autenticado compara alerta estrangeiro e ID inexistente, exigindo HTTP 404 e corpo idêntico.
- Código/testes e documentação publicados; CI/PostgreSQL 16 ainda pendentes.

## 2026-11-23 — Ocultação de IDs directos de deteções em observação e histórico

- `POST /api/v1/shelf-image-detections/{detection_id}/observation` e `GET /api/v1/shelf-image-detections/{detection_id}/reviews` ocultam agora deteções de outras lojas com HTTP 404 idêntico ao ID inexistente.
- Mantida a ordem de autorização: descoberta read-only da imagem, autorização pré-lock, lock da imagem, revalidação pós-lock e só depois leitura/escrita dependente da deteção.
- Testes autenticados comparam status e corpo para IDs estrangeiros/inexistentes nos dois endpoints; verificam que o fluxo próprio continua permitido.
- Implementação e testes publicados; CI/PostgreSQL 16 ainda pendentes.

## 2026-11-23 — Ocultação de IDs de prateleira em criação e consenso

- create_observation e create_capture_session validam o actor antes da consulta à prateleira; para SUPERVISOR, prateleiras estrangeiras e inexistentes devolvem HTTP 404 equivalente.
- get_shelf_observation_consensus valida também o papel antes da consulta e oculta IDs de prateleiras estrangeiras com HTTP 404. A avaliação de alertas herda este contrato e falha antes de persistir.
- Testes HTTP comparam respostas estrangeira/inexistente na criação de observações, sessões, consenso e avaliação de alertas; verificam ainda que não são criados registos nas prateleiras estrangeiras.
- Commits: código 9288459, cce1afd; testes 739a574 e d5d6243.
- CI e execução PostgreSQL 16 ainda não confirmados.

## 2026-11-23 — Ocultação de IDs de consenso de prateleira

- A leitura de consenso por shelf_id devolve agora o mesmo HTTP 404 para prateleiras estrangeiras e inexistentes, em vez de distinguir 403/404.
- A avaliação de alertas por shelf_id herda o mesmo comportamento, porque consulta o endpoint/função de consenso antes de persistir alertas.
- Testes HTTP autenticados comparam os corpos de resposta para ID estrangeiro e ID inexistente, tanto no consenso como na avaliação de alertas.
- Commits: código 2f4470e692f6faed30accf5dcc26ab57c18c94d1; teste 5feffbabd91c9fee0d6e4f2da9236f7a54258a70.
- Testes e CI deste SHA ainda não foram executados/confirmados.

## 2026-11-23 — Ocultação de IDs de sessões de captura e alertas

- A rota POST /api/v1/capture-sessions/{session_id}/close passa a usar o helper de lock multi-tenant com hide_foreign=True.
- PATCH /api/v1/observation-alerts/{alert_id} passa a resolver e bloquear o alerta através do helper, com ocultação de IDs estrangeiros.
- GET /api/v1/observation-alerts/{alert_id}/events mantém a leitura sem lock, mas devolve 404 para alertas estrangeiros e inexistentes.
- Testes HTTP comparam respostas estrangeiras/inexistentes e confirmam que uma sessão estrangeira não é fechada e que o alerta/eventos não são alterados.
- Commits: código b627107c517b91caf04a9b5ab2cc6d1f84552b20; teste fe021e303e87f47f638e31661cf97ff6e285bff3 e reforço 1a2e776dfcb3886a4e14b7581b0980a91bbbecb4.
- Execução de testes e CI deste SHA ainda não confirmada.

## 2026-11-23 — Ocultação de IDs de localizações de armazém

- A rota POST /api/v1/warehouse/placements deixou de carregar a localização sem lock e só depois aplicar o store scope.
- Passa a usar _lock_store_scoped_record com hide_foreign=True: autorização pré-lock, lock da linha e revalidação pós-lock.
- Adicionada regressão autenticada que compara a resposta para uma localização real de outra loja com a resposta para um ID inexistente (HTTP 404), e confirma ausência de colocação persistida.
- Commits de código/teste: a77c6793489f1594a4705d7b258dd7639ce3433e e 68e907febf897d94790487515c35847747c0bc39.
- Testes e workflows deste SHA ainda não foram executados/confirmados. A auditoria BOLA/IDOR de prateleiras e relações logísticas continua aberta.

## 2026-11-23 — Pré-lock PostgreSQL para IDs directos de deteção e exemplar

- Auditoria dirigida aos handlers de revisão de deteção, histórico e revisão de exemplares. Os três resolvem a imagem de origem, aplicam autorização de tenant antes do lock da imagem e mantêm validação de estado/identidade após os locks.
- Adicionado `postgres_detection_exemplar_prelock_smoke.py`: supervisor da loja A tenta usar IDs reais da loja B enquanto as linhas de `ShelfImage` e `Product` estão bloqueadas.
- O smoke exige HTTP 403 imediato nas três operações e confirma que não é criado `DetectionSkuReview` nem alterado o exemplar PENDING.
- O passo PostgreSQL 16 passou no API CI [45194763822](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45194763822), no SHA `fefb56f`; a suite terminou com **1588 passed, 1 skipped**.
- Quality Gates [45194764768](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45194764768) passou, incluindo compilação Python, testes API e build Web. Security Scans [45194765202](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45194765202) passou (Gitleaks, pip-audit, npm audit e ZAP Passive Baseline). Docker Compose [45194764844](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45194764844) passou.
- Limite: cobertura focada em três operações e um perfil; não fecha BOLA/IDOR nem a matriz ADMIN/SUPERVISOR/EMPLOYEE.

## Segurança P0 — autorização pré-lock de planogramas (2026-11-23; CI validada)

- [x] Adicionar preflight de tenant para a prateleira e para imagens de calibração antes de adquirir locks.
- [x] Aplicar o mesmo padrão às alterações de células, ativação, retirada e comparação por IDs directos.
- [x] Revalidar o store scope depois dos locks, mantendo a ordem imagem → prateleira → planograma.
- [x] Autorizar a prateleira mesmo quando não existe planograma ACTIVE, evitando que o serviço devolva um resultado vazio distinto para IDs estrangeiros.
- [x] Acrescentar regressões HTTP e um smoke PostgreSQL 16 com locks reais mantidos noutras transacções. O smoke rejeita, sem esperar pelo lock, edição, activação e retirada de planogramas estrangeiros, calibração com imagem estrangeira e comparação com imagem estrangeira.
- [x] API CI [45185460992](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45185460992) passou no SHA b05d3a8; Quality Gates, Security Scans e Docker Compose também passaram. O smoke PostgreSQL confirmou as cinco operações cross-store sob locks reais.
- [x] Revalidar no HEAD 48859d1: API CI [45186900075](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45186900075), Quality Gates [45186899975](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45186899975), Security Scans [45186899976](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45186899976) e Docker Compose [45186899968](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45186899968) passaram; API CI/Quality Gates executaram **1588 passed, 1 skipped**.
- [ ] Completar a matriz endpoint × ADMIN/SUPERVISOR/EMPLOYEE × loja para os restantes recursos e IDs aninhados; o smoke actual é direccionado, não exaustivo.

Commits de código/testes: abc60f6, ce63d3e, c1deee7, 94b71f9, f04c74d, b6aec43, cc8a01d, b05d3a8.

---

## Segurança P0 — revisão de exemplares sem lock global antes da autorização (2026-11-23; CI validada)

- [x] Recusar revisão de exemplares sem imagem de origem por utilizadores não ADMIN antes de consultar/bloquear o produto global.
- [x] Para exemplares com imagem, validar primeiro o acesso à imagem e a retenção; rejeitar auto-revisão antes do lock do produto, preservando HTTP 410 para imagens restringidas.
- [x] Manter as verificações depois do lock do exemplar para revalidar identidade e autoria perante alterações concorrentes.
- [x] Acrescentar teste que confirma que uma revisão não autorizada de exemplar sem imagem não executa a query ao catálogo de produtos nem altera o estado PENDING.
- [x] Expandir postgres_embedding_review_smoke.py: manter o produto bloqueado numa transacção PostgreSQL e provar que um supervisor não autorizado recebe HTTP 403 sem esperar pelo lock.
- [x] O passo PostgreSQL Verify PostgreSQL concurrent SKU exemplar review serialization passou no API CI [45186900075](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45186900075).
- [x] Regressão intermédia detectada pelo Quality Gates: a primeira ordenação devolvia 403 antes de validar a retenção de uma imagem restringida, quebrando o contrato HTTP 410. A verificação de auto-revisão foi movida para depois da validação de retenção e antes do lock do produto.
- [x] HEAD 48859d1: API CI e Quality Gates passaram com **1588 passed, 1 skipped**; Security Scans e Docker Compose também passaram.
- [ ] Continuar a auditoria de detection_id/exemplar_id em todos os fluxos e confirmar a matriz completa de papéis/lojas.

Commits de implementação/testes: 2cb6b19; correcção de fixture PostgreSQL: 72db929; preservação da semântica de retenção: 48859d1.

---

## 2026-11-23 — Controlos BOLA para IDs aninhados de paletes

- Acrescentados dois pedidos de ataque no smoke PostgreSQL multi-loja: supervisor autorizado na loja A usa o `store_id` da loja A, mas fornece o ID real de uma palete pertencente à loja B.
- Cobertos o endpoint de plano de rotação e o endpoint de eventos de ciclo de vida.
- Ambos exigem HTTP 404, comprovando que o filtro da entidade filha respeita a loja indicada e não devolve a existência/conteúdo da palete estrangeira.
- Commit: `db177bce`.
- CI para este novo commit ainda não confirmada. Próximo passo: validar em PostgreSQL 16 e expandir a matriz para IDs de localização, shelf, tarefa e packaging.

---

## 2026-11-23 — Controlos positivos same-store para recursos logísticos reais

- O smoke `postgres_inventory_authorization_smoke.py` cria agora um nível de embalagem CASE e uma palete válida em cada loja.
- Os pedidos de leitura cross-store usam o ID real da palete estrangeira; os controlos positivos substituem-no pelo ID da palete da loja do supervisor.
- Foram removidas as três exclusões anteriores: cálculo de unidades de reposição, plano de rotação de palete e eventos de ciclo de vida. A expectativa passa a ser HTTP 200 para todos os 23 controlos same-store e HTTP 403 para as 23 leituras cross-store.
- Commit de código: `3af7a02b`.
- API CI, Quality Gates, Security Scans e Docker Compose deste novo SHA ainda não foram confirmados. A alteração foi publicada no GitHub; não foi executada localmente nesta sessão.
- Próximo passo: validar o smoke em PostgreSQL 16 e expandir a matriz para IDs aninhados/relacionais.

---

## 2026-11-23 — Expansão da matriz PostgreSQL de leituras cross-store

- Actualizado `apps/api/scripts/postgres_inventory_authorization_smoke.py` para exercitar 23 endpoints GET que recebem `store_id` em vendas, tráfego, forecasting, replenishment, decisões operacionais e warehouse.
- Cada pedido usa um JWT real de SUPERVISOR da loja A e identifica a loja B. A expectativa é HTTP 403 antes de consultar dados da loja estrangeira.
- Mantidos os testes existentes de escrita cruzada e as verificações de estado persistido (inventário, policies, placements, tarefas, movimentos e eventos).
- O script já está integrado no job API CI através do passo `Verify PostgreSQL inventory and warehouse cross-store authorization`.
- Commit: `40f9456a`.
- API CI [45131503709](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503709) passou no SHA `40f9456a`: PostgreSQL 16, todos os smokes (incluindo 23 leituras cross-store) e suite API **1555 passed, 1 skipped**.
- Docker Compose [45131503757](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503757) passou. No Quality Gates [45131503760](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503760), Web build e detector Impeccable passaram, mas o job API foi cancelado durante instalação de dependências. Em Security Scans [45131503689](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503689), Gitleaks e npm audit passaram; pip-audit e ZAP foram cancelados. Estes dois workflows necessitam de nova execução integral.
- A ampliação posterior para paletes/packaging same-store foi publicada no commit `3af7a02b`; ainda sem CI confirmada.
- A matriz não cobre todas as combinações endpoint × role × tenant. Permanecem pendentes a matriz positiva same-store, IDs aninhados/relacionais e volume PostgreSQL persistente.

---

## 2026-11-23 — Expansão da prova PostgreSQL pré-lock para nove rotas HTTP

- O smoke `postgres_retention_legal_hold_concurrency_smoke.py` testa agora nove rotas de imagem com um supervisor de outra loja: conteúdo, deteções, evidence fusion, OCR evidence/matches/runs, eventos de retenção, retry e restrict.
- A transacção concorrente mantém a linha `shelf_images` bloqueada. Todas as rotas têm de responder HTTP 403 antes da libertação do lock; qualquer handler que tente bloquear a imagem antes de autorizar provoca timeout e falha o smoke.
- O passo `Verify PostgreSQL legal hold and purge schedule concurrency` passou no API CI [45130818413](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818413), SHA `d319d1a4`.
- Docker Compose [45130818319](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818319), Quality Gates [45130818392](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818392) e Security Scans [45130818374](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818374) passaram.
- API CI terminou com sucesso: **1555 passed, 1 skipped** no [run 45130818413](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818413).
- Os endpoints de artefactos, legal hold e purge que exigem ADMIN seguem a política de administrador global; não são casos de negação cross-store para SUPERVISOR. A revisão dos restantes handlers de escrita/revisão continua pendente.

---

## 2026-11-23 — Resultados CI da prova PostgreSQL multi-loja pré-lock

- O smoke PostgreSQL `Verify PostgreSQL legal hold and purge schedule concurrency` concluiu com sucesso no API CI [45129975394](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975394), commit de código `926abcf1`. O teste executou o pedido de supervisor estrangeiro enquanto a imagem estava bloqueada e confirmou rejeição HTTP 403 sem aguardar pelo lock.
- Docker Compose demo smoke passou em [45129975482](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975482), no mesmo SHA de código.
- A falha anterior do Compose smoke foi causada pela ausência de `MIGRATION_DB_USER` nas invocações inline do runtime-role smoke. Corrigido em `b4995042`, com regressão estática em `edf879a2`; a execução Compose acima passou no SHA `926abcf1`.
- Quality Gates passou em [45130013285](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013285), SHA documental `7b10c5c1`: compilação Python, suite API e build Web concluídos com sucesso.
- API CI terminou com sucesso em [45129975394](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975394), SHA de código `926abcf1`: migrações PostgreSQL 16, todos os smokes, provisionamento/verificação da role runtime e **1555 testes aprovados, 1 ignorado**.
- Security Scans terminou com sucesso em [45130013260](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013260), SHA documental `7b10c5c1`: Gitleaks, pip-audit, npm audit e OWASP ZAP passive baseline passaram.
- Quality Gates [45130013285](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013285) e Docker Compose [45129975482](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975482) também passaram.
- **Ainda pendente:** integração multi-loja HTTP/PG dos restantes handlers, ensaio de volume persistente preexistente e operações reais com principal runtime.

---

## 2026-11-23 — Prova PostgreSQL de autorização multi-loja antes de lock (CI validada; cobertura adicional pendente)

- O smoke de retenção PostgreSQL cria agora uma segunda loja e um supervisor pertencente a essa loja.
- Enquanto outra sessão mantém a linha de uma imagem bloqueada com `FOR UPDATE`, o supervisor externo tenta restringir a imagem através da API.
- O teste exige HTTP 403 antes da libertação do lock; se o handler tentar adquirir o lock antes da autorização, a chamada excede o timeout e o smoke falha.
- Os ensaios anteriores de concorrência entre legal hold, agendamento de purga e restauro foram preservados.
- O smoke já está ligado ao job PostgreSQL da API CI através do passo existente `Verify PostgreSQL legal hold and purge schedule concurrency`.
- Commits: `25a34b8f` e `926abcf1`.
- **Validação concluída:** API CI [45129975394](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975394) passou com 1555 testes aprovados e 1 ignorado; Quality Gates [45130013285](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013285), Security Scans [45130013260](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013260) e Docker Compose [45129975482](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975482) passaram. Não foi executado localmente nesta sessão.

---

## 2026-11-23 — Autorização de tenant antes de locks em retenção e artefactos (código publicado; CI em execução)

- A auditoria da ordem de locks encontrou dez handlers que adquiriam `FOR UPDATE` na imagem antes de validar a loja. Embora alguns validassem o tenant mais tarde, um pedido sem autorização podia adquirir locks de recursos de outra loja antes da rejeição.
- Corrigidos os cinco fluxos de retenção (restauro, legal hold apply/release e agendamento/cancelamento de purga), a consulta de elegibilidade de purga e quatro fluxos de artefactos externos (registo, snapshot de inventário, diagnóstico de acesso e evento de disposição).
- Os nove handlers que operam sobre a imagem usam agora `_lock_authorized_shelf_image`, que verifica a loja antes do lock e volta a verificar a linhagem depois. A elegibilidade mantém o erro específico de linhagem inválida e faz o preflight antes do lock.
- `test_security.py` passou a exigir a ordem autorização → lock nos dez handlers. Uma verificação estática adicional no código publicado confirmou os dez casos. Foi acrescentado um teste unitário que prova que um supervisor de outra loja é rejeitado antes de qualquer query de lock.
- Corrigida também a duplicação de duas tarefas pendentes em `TODO.md`.
- Commits de código/testes: `f6e2156e`, `659586be`, `7f372fbc`, `cbc6a1a6`, `70b1b351`; TODO: `fcb685bf`.
- CI actual no SHA de código/testes `70b1b351`: API CI [45127205680](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45127205680), Quality Gates [45127205615](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45127205615), Security Scans [45127205627](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45127205627) e Docker Compose [45127205559](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45127205559) foram iniciados; resultados ainda não confirmados.
- Validação anterior da correcção PostgreSQL default ACL: API CI/PostgreSQL 16 run [45084795278](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45084795278) passou; Quality Gates [45084849142](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45084849142) e Security Scans [45084849107](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45084849107) passaram no SHA documental `00d6ef51`.
- **Ainda em aberto:** testes de integração PostgreSQL com duas lojas para estes dez fluxos, ensaio de volume persistente e operações reais API com principal runtime. A auditoria estática não substitui estes ensaios.

---
## 2026-11-22 — Correcção do âmbito dos default ACLs PostgreSQL (código publicado; CI pendente)

- A revisão do smoke identificou que a query de `pg_default_acl` agregava permissões concedidas ao runtime por qualquer owner, em vez de verificar especificamente os objectos futuros criados pelo principal de migrations.
- A query passa a filtrar `pg_default_acl.defaclrole` pelo papel explícito `MIGRATION_DB_USER`, e continua a verificar o grantee como `current_user`, privilégios exactos e ausência de GRANT OPTION.
- O job PostgreSQL 16 da API CI fornece `MIGRATION_DB_USER=postgres`; o teste estático verifica o contrato e a ligação da configuração.
- Commits desta correcção: `bb3766fc`, `491ae99f`, `8e5a6810`.
- Evidência anterior à correcção: API CI [45083455380](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083455380) e Docker Compose [45083455389](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083455389) passaram no SHA `72d4034d`; Quality Gates [45083489901](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083489901) e Security Scans [45083489889](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083489889) passaram no SHA `9bad015c`.
- **Ainda não validado:** os workflows têm de ser reexecutados no novo SHA; continua pendente o ensaio com volume persistente real e operações API com o principal runtime.

---

## 2026-11-22 — Expansão do smoke de segurança PostgreSQL runtime (implementação publicada; CI pendente)

- O smoke `apps/api/scripts/postgres_runtime_role_smoke.py` verifica agora o atributo LOGIN e todos os atributos privilegiados, incluindo NOINHERIT.
- A verificação de ownership foi generalizada para `pg_shdepend`, em vez de se limitar a relações, schemas e bases de dados.
- São verificados CONNECT, USAGE no schema público e ausência de CREATE.
- O smoke inspeciona os default ACLs de tabelas e sequências futuras, exige apenas os privilégios operacionais previstos e rejeita GRANT OPTION.
- Todas as tabelas operacionais existentes têm de conceder SELECT/INSERT/UPDATE/DELETE; as duas tabelas de confiança ONNX permanecem SELECT-only e sem acesso à sequência de auditoria.
- Foi acrescentado teste estático para impedir regressões na cobertura do smoke.
- Commits: `2d7bce2f`, `afda3ee6`, `ee609372`, `72d4034d`.
- **Validação pendente:** não foi possível executar localmente Python/PostgreSQL nesta sessão; os workflows do SHA final ainda não foram confirmados. Continua pendente o ensaio com volume persistente real e operações API sob o principal runtime.

---

## 2026-11-21 — Avaliação de Computer Vision com COCO (implementação publicada; CI/dataset pendentes)

- Criado `apps/api/app/vision_evaluation.py`: avaliação determinística de caixas COCO com AP101, mAP50, mAP50_95 e métricas TP/FP/FN, precision, recall e F1 por classe e globalmente.
- O evaluator rejeita IDs ambíguos, classes desconhecidas, caixas fora da imagem, scores não finitos e crowd annotations ainda não suportadas.
- Criado `apps/api/scripts/evaluate_vision_model.py`: executa o provider ONNX real apenas num test split pertencente a um release aprovado para inferência; exige manifesto Ed25519, keyring, hashes e SHA-256 das imagens.
- O runner exige confidence floor 0.0 para AP, mede separadamente o operating threshold, e escreve relatório com release fingerprint, versão do modelo, pesos e pré-processamento. Não treina nem altera inventário.
- Testes sintéticos em `apps/api/tests/test_vision_evaluation.py`; protocolo em `docs/vision-model-evaluation.md`.
- Limite: não foi executado com dataset autorizado nem pesos reais; nenhuma métrica de precisão foi produzida. CI ainda por confirmar.

## 2026-11-21 — Contrato Edge AI v1 (implementação de domínio publicada; CI pendente)

- Criado `apps/api/app/edge_event_contract.py` com envelope v1, payloads tipados por evento, limites de tamanho/profundidade, timestamps timezone-aware, IDs e hashes validados.
- Tipos: DEVICE_HEARTBEAT, SHELF_CAPTURED, SHELF_OBSERVATION e TASK_ACKNOWLEDGED.
- Acrescentados fingerprint SHA-256 canónico, chave idempotente por dispositivo/evento, comparação de replay exacto e classificação de sequência NEXT/GAP/STALE.
- Criados testes em `apps/api/tests/test_edge_event_contract.py` para payloads válidos/inválidos, tenant IDs, bounding boxes, tamanho, idempotência e lacunas de sequência.
- Documentação do protocolo: `docs/edge-device-event-contract.md`.
- Limite explícito: não existe ainda autenticação/registo de dispositivos, endpoint, inbox/outbox persistente, cursor durável nem ACK de entrega. O módulo não faz persistência nem mutações de inventário. CI pendente.

## 2026-11-21 — Manifesto ONNX assinado com Ed25519 (implementação publicada; Quality Gates e Security Scans validados)

- O provider ONNX real passou a exigir um manifesto autenticado por Ed25519 e um keyring explícito de chaves públicas confiáveis.
- A assinatura cobre o payload JSON canónico com schema versionado, key ID e SHA-256 do detector e, opcionalmente, do embedder. Os hashes são comparados com os ficheiros reais e com as variáveis SHA-256 já configuradas.
- A validação rejeita assinatura inválida, key ID desconhecido, chave pública com tamanho incorrecto, digest divergente, ficheiro alterado, symlink, JSON ambíguo/malformado e campos extra ou em falta.
- A API e o vision-worker recebem `VISION_MODEL_MANIFEST_PATH` e `VISION_MODEL_TRUSTED_KEYS_JSON` através do Docker Compose. Foi fixada `cryptography==50.0.2` para Ed25519.
- Foi criado `apps/api/scripts/create_vision_model_manifest.py` para assinar offline com PEM Ed25519; o utilitário imprime apenas a chave pública Base64. A chave privada nunca é distribuída para os containers.
- Testes adicionados em `apps/api/tests/test_vision_model_manifest.py`. No HEAD `e9145ac7cb89409e80259f52967f7fccda3de478`, Quality Gates passou (compilação Python, suite pytest API e build Web) no run [44918245867](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44918245867); Security Scans passou no run [44918245858](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44918245858). API CI e Docker Compose smoke tiveram sucesso em SHA anterior e não são aqui apresentados como validação deste HEAD.
- Limitações conhecidas: não há prevenção persistente de rollback nem política automática de revogação/rotação. A assinatura autentica a origem dos pesos, não a precisão do modelo.
- Especificação operacional: `docs/vision-model-manifest.md`.

## 2026-11-21 — Encaminhamento de digests ONNX no Docker Compose (validação pendente)

- A revisão da configuração detectou que o provider ONNX real exige `VISION_DETECTOR_MODEL_SHA256` e, quando existe embedder, `VISION_EMBEDDING_MODEL_SHA256`, mas os serviços API e worker não recebiam essas variáveis através do Compose.
- O `docker-compose.yml` foi alterado para encaminhar ambos os valores aos dois processos. Os valores por omissão permanecem vazios, pelo que a configuração continua a falhar fechada se o operador activar o provider real sem fornecer digests aprovados.
- Foi acrescentado `apps/api/tests/test_vision_compose_configuration.py` para fixar a passagem das duas variáveis nos serviços API e vision-worker.
- Commits: Compose `2d810e8a`; teste inicial `d00278b2`; correcção do teste `b417490a` e `263de3e8`; documentação em curso.
- Estado: implementação publicada; testes e workflows ainda não executados/confirmados nesta ronda. Não declarar a alteração validada até CI verde.
- Limite: isto não implementa manifesto assinado nem fornece pesos ONNX; apenas torna configuráveis no container os digests que já eram obrigatórios no provider real.

## 2026-11-21 — Integridade dos exemplares de embeddings (validado)

- A validação de ProductExemplar aceitava alguns valores com tipos inadequados: booleanos/floats como IDs e metadados não textuais podiam atravessar a fronteira de domínio.
- A implementação passou a exigir ID de produto inteiro positivo; versão do modelo, revisor, timestamp de revisão e licença como strings não vazias; e digest SHA-256 com exactamente 64 caracteres hexadecimais.
- Foram adicionados testes paramétricos para booleanos, floats, strings, valores nulos, hashes de comprimento incorrecto e caracteres não hexadecimais.
- Commits: implementação 762d3344dbcb72c39d223bdd2a97a7f8e8333421; testes a1e056c3a49eebd1b7ac36903cc1453b6d570338.
- Validação no SHA a1e056c3: API CI [44902878547](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878547) passou com PostgreSQL 16, smokes de concorrência/isolamento e **1461 passed, 1 skipped**. Quality Gates [44902878553](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878553) confirmou compilação Python, build Web e a mesma suite; Docker Compose [44902878594](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878594) e Security Scans [44902878703](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878703) passaram.
- Limite: esta alteração melhora a integridade dos registos de referência; não valida qualidade visual dos embeddings, precisão por SKU nem adequação de thresholds para uma loja real.

## 2026-11-21 — Gitleaks sobre o histórico Git completo (validado)

- A ação oficial Gitleaks estava a usar --log-opts=-1 no evento push; o checkout tinha histórico completo, mas a acção só verificava o commit actual. Foi acrescentado um passo explícito com --log-opts=--all.
- A primeira execução percorreu 2740 commits e encontrou 7 ocorrências da regra generic-api-key. A análise dos contextos confirmou exemplos de bootstrap na documentação, chaves HMAC de testes e um hash de commit; não foram identificadas credenciais activas.
- Os exemplos de credenciais e a chave de teste actual foram substituídos por placeholders/valores de teste explícitos. As 7 ocorrências históricas foram adicionadas a .gitleaksignore através das fingerprints exactas, sem exclusões por caminho, regra ou regex. O histórico Git não foi reescrito.
- Reexecução: 2741 commits analisados, no leaks found. Artefacto SARIF full-history disponível no workflow Security Scans [44895863007](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44895863007).
- Segurança: pip-audit sem vulnerabilidades conhecidas; npm audit 0 vulnerabilidades; ZAP baseline/API safe-mode 0 FAIL, 0 WARN, 0 INFO e 120 PASS. Docker Compose passou.
- API CI [44895863058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44895863058) e Quality Gates [44895863008](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44895863008) passaram, com 1432 passed, 1 skipped; PostgreSQL 16, compilação Python e build Web aprovados.
- Commit de correcção e cobertura: 1097e53a4bfae31f66e4a6c434a37caa1a40e233. Limite: as impressões digitais antigas permanecem no histórico por não se ter reescrito a história; a supressão é específica a cada ocorrência classificada como falsa positiva.

## 2026-11-21 — Pinning de integridade dos modelos ONNX (validado em CI)

- A auditoria confirmou que o provider calculava SHA-256 dos pesos e incorporava o digest no fingerprint, mas não comparava o ficheiro com um digest previamente aprovado. O comportamento anterior permitia que um modelo substituído antes do arranque fosse simplesmente identificado como uma nova versão.
- Primeiro foram publicados testes de regressão. O Quality Gates observou RED: 9 falhas, 1423 aprovados e 1 ignorado. As falhas demonstraram a ausência de suporte aos digests no provider e a ausência de exigência dos digests no factory real.
- ONNXShelfVisionProvider passou a validar o formato dos digests esperados e a comparar os hashes do detetor e do embedder antes de criar sessões ONNX. O factory create_provider() falha fechado quando falta o digest do detetor ou, havendo embedder, o digest do embedder. A verificação pós-carregamento existente foi preservada para detectar substituição durante a abertura da sessão.
- O fingerprint do detetor usa rgb-letterbox-bilinear-114-v1; o fingerprint do extrator usa rgb-crop-stretch-bilinear-v1. Assim, os identificadores não confundem pipelines de pré-processamento distintos.
- Commits: implementação 1b03b66cd24c9efed2b16c41a71cbfd2f5c2c2ea; testes e asserção do fingerprint 663bf495f6d15a4bcc92aa6fedc87d18e47e4e71.
- GREEN: API CI [44894912840](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44894912840) e Quality Gates [44894912818](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44894912818) passaram, com 1432 passed, 1 skipped. Os smokes PostgreSQL 16, compilação Python e build Web passaram. Docker Compose [44894912826](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44894912826) e Security Scans [44894912752](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44894912752) também passaram.
- Limites: nenhum peso ONNX real foi fornecido ou avaliado. Os hashes aprovados são âncoras de confiança da configuração de deployment; ainda não existe manifesto assinado com verificação de assinatura. Não activar provider real em piloto sem pesos, licenças, dataset e métricas autorizados.

## 2026-11-21 — Isolamento multi-loja do histórico de alertas (validado)

- A revisão handler-a-handler confirmou que `GET /api/v1/observation-alerts/{alert_id}/events` carrega o alerta pai e chama `_require_alert_supervisor`, que verifica o papel e a loja antes de devolver eventos.
- Acrescentado teste HTTP de regressão: um supervisor da loja A tenta ler a cronologia de um alerta da loja B e deve receber HTTP 403.
- Removida uma segunda definição duplicada de `test_cross_store_alert_update_checks_scope_before_acquiring_row_lock`; a definição repetida não criava um cenário adicional, mas ocultava a duplicação na suite.
- A implementação do endpoint não foi alterada: a cobertura passa a provar explicitamente o controlo já existente.
- Validação GREEN no commit `1a53a9f1`: API CI [44893270814](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893270814) e Quality Gates [44893270837](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893270837) passaram, com **1423 passed, 1 skipped**. Docker Compose [44893271027](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893271027) e Security Scans [44893270848](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893270848) também passaram.

## 2026-11-20 — Isolamento multi-loja nas mutações de planogramas

- A auditoria confirmou que o serviço `shelf_planograms.py` obtém a loja através da prateleira bloqueada e valida o papel/loja antes de editar, ativar ou retirar planogramas.
- Acrescentado teste HTTP de regressão com dois supervisores e duas lojas: o supervisor A tenta editar e ativar um rascunho da loja B, e depois retirar a versão ativa; as três operações devem devolver 403. O supervisor B ativa a sua versão e o histórico confirma que permanece ACTIVE após as tentativas.
- Commit: `714fd49db7c3a25d9e9a1b2846f402b6f9704bbd`.
- O teste foi adicionado ao repositório; ainda não foi executado localmente. A validação depende dos workflows GitHub associados ao commit.

## 2026-11-20 — Cobertura positiva da autorização de planogramas

- Adicionado teste positivo para a rota real `POST /api/v1/shelves/{shelf_id}/planograms`.
- O teste verifica que ADMIN e SUPERVISOR são autorizados e EMPLOYEE recebe a recusa `Supervisor role required`; complementa a regressão negativa para `planograms-export`.
- Commit: `c5098584e11a2eb4377a299d150f38225be045a0`.
- A leitura de `main.py` confirmou que o handler também executa `_require_planogram_actor` e valida a loja da prateleira com `_planogram_shelf_scope` / `_enforce_store_scope`. A política central não substitui estes controlos de recurso.
- Os workflows consultados para o commit anterior continuavam sem conclusão; este novo commit de teste deve ser acompanhado separadamente.

## 2026-11-20 — Estado CI da correcção de segmentos planogramas

- Consultados directamente os workflows associados ao commit de teste `2a95fb0e3a076f03454bb7a46eb4678c0bd9ac7e`.
- API CI #1673 (`44820792391`): `in_progress`; o job está a executar as verificações PostgreSQL e ainda não chegou à suite final.
- Demo Docker Compose smoke #328 (`44820792388`): `pending`.
- Smart Shelf quality gates #1881 (`44820792462`): `cancelled`; os passos de instalação de Python/dependências e testes foram ignorados. Isto não representa falha de código nem validação concluída.
- Estado: sem resultado GREEN final até ao momento. Acompanhar API CI e Demo Compose antes de fechar a validação.

## 2026-11-20 — Correspondência de segmento em sub-recursos de planogramas

- A revisão da política RBAC encontrou uma segunda correspondência demasiado permissiva: a verificação por substring `"/planograms" in path` também aceitava o segmento lookalike `planograms-export`.
- A regra passou a verificar os segmentos completos do caminho (`"planograms" in path.split("/")`), preservando os recursos legítimos e evitando atribuir a categoria SUPERVISOR_OR_ADMIN a caminhos semelhantes.
- Adicionada regressão unitária para `/api/v1/shelves/42/planograms-export`.
- Commits: `d61e5a1` (correcção) e `2a95fb0` (teste).
- Não foram executados testes localmente nesta sessão; o resultado CI do SHA de testes ainda tem de ser consultado. A validação permanece pendente.

## 2026-11-20 — Auditoria reproduzível da classificação RBAC

- Criado `apps/api/scripts/audit_api_route_policy.py`: percorre as rotas `APIRoute` realmente registadas no FastAPI, expande cada método HTTP, classifica pelo motor central e emite JSON determinístico com contagens e rotas que caem no fallback `AUTHENTICATED_STAFF`.
- O modo normal é apenas informativo e não altera permissões; `--strict` devolve código de saída não-zero se existirem fallbacks, para activação futura depois de revisão humana.
- Commit: `1e383e0` — [auditor RBAC de rotas](https://github.com/smpsandro1239/SMART-SHELF-AI-/commit/1e383e010587957495042d2c1fc360afc7bb6c19).
- Limitação: o auditor foi adicionado ao repositório, mas não foi executado nesta sessão porque não existe runtime local do projeto; nenhuma contagem ou resultado de execução é presumido.
- Próximo passo: executar o relatório no CI/ambiente API, analisar cada fallback e só depois substituir categorias genéricas por regras explícitas e regressões endpoint × método × papel.

## 2026-11-20 — Endurecimento de prefixos na política RBAC

- Alterado `apps/api/app/api_security_policy.py` para usar correspondência de prefixos com limite de segmento, evitando que caminhos semelhantes como `/api/v1/auth/users-export` sejam confundidos com sub-recursos de `/api/v1/auth/users`.
- Aplicado o helper às famílias de observation alerts, planograms, shelves, pallets, product embedding exemplars, shelf-image detections, shelf images e tasks.
- Adicionados testes unitários para rejeitar prefixos semelhantes e preservar rotas aninhadas legítimas.
- Commits: `e19090e` (política) e `7dce6f6` (testes).
- Verificação GitHub: o status apresenta checks Vercel (um falhado por `build-rate-limit` e outro pendente); o conector não devolveu workflows GitHub Actions associados a este commit. Os testes não foram executados localmente nesta sessão; validação integral permanece pendente.

## 2026-11-20 — Política RBAC centralizada e validada

- Criado `apps/api/app/api_security_policy.py` com categorias PUBLIC, ADMIN_ONLY, SUPERVISOR_OR_ADMIN, EMPLOYEE_ALLOWLIST e AUTHENTICATED_STAFF.
- O middleware delega agora a decisão de role ao módulo; mantém JWT, consulta da identidade activa e papel autoritativo da base de dados.
- Testes verificam regras ADMIN/SUPERVISOR/EMPLOYEE e rejeição fail-closed de papel desconhecido.
- A primeira tentativa `f86ef76` falhou por importação em falta; o CI identificou o erro e o commit `afd2a38` corrigiu-o.
- GREEN no commit `afd2a38`: API CI [44787322362](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44787322362), Quality Gates [44787322405](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44787322405) e Docker Compose [44787322365](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44787322365) passaram; suite **1389 passed, 1 skipped, 1 warning**.
- Limite: a política está centralizada por grupos de paths/métodos, mas ainda não existe matriz exaustiva testada endpoint × papel × loja.

## 2026-11-20 — Política RBAC centralizada: estado da integração

- A implementação foi extraída para `apps/api/app/api_security_policy.py`; o middleware importa agora `PUBLIC_API_PATHS` e `api_role_denial` directamente.
- Os testes unitários iniciais cobrem ADMIN_ONLY, SUPERVISOR_OR_ADMIN, EMPLOYEE_ALLOWLIST, AUTHENTICATED_STAFF e papel desconhecido.
- A sequência de commits foi `f86ef761` (refactor) e `afd2a38` (correcção do import no middleware).
- O backlog foi reconciliado: implementação e testes unitários estão concluídos; validação integral CI e matriz explícita de todas as rotas continuam pendentes.
- A consulta de status ao SHA `afd2a38df8656a38beb077eb9cd4de3124caf36c` devolveu apenas dois checks Vercel em falha por `build-rate-limit`; não foi obtida evidência de execução/conclusão dos workflows GitHub Actions para este SHA. Não declarar a suite validada.
- Limite actual: `AUTHENTICATED_STAFF` é uma categoria fallback. A próxima melhoria deve tornar a classificação por método/rota explicitamente auditável e testar cobertura contra as rotas FastAPI registadas, sem alterar a matriz de permissões por suposição.

## 2026-11-20 — Política RBAC centralizada (em validação)

- Extraída a decisão de autorização por método/path/role para `apps/api/app/api_security_policy.py`.
- A classificação explícita distingue PUBLIC, ADMIN_ONLY, SUPERVISOR_OR_ADMIN, EMPLOYEE_ALLOWLIST e AUTHENTICATED_STAFF.
- O middleware mantém a autenticação Bearer e a consulta do papel autoritativo na base de dados; apenas delega a decisão de role para o módulo central.
- Adicionados testes unitários para a matriz ADMIN/SUPERVISOR/EMPLOYEE e fail-closed para papel desconhecido.
- A preservação integral da suite e dos smokes PostgreSQL aguarda CI.

## 2026-11-20 — CORS preflight corrigido e validado

- O RED do commit `831c1026` mostrou que o middleware Bearer respondia 401 ao OPTIONS preflight antes de CORSMiddleware.
- O middleware agora encaminha apenas OPTIONS com `Origin` e `Access-Control-Request-Method` para CORSMiddleware; este continua a validar origem, método e headers.
- CORS `allow_credentials=False`: a API usa Bearer JWT, não cookies; Authorization continua permitido em preflight.
- GREEN no commit `a63d646`: teste confirma HTTP 200, origem permitida, header Authorization e ausência de `Access-Control-Allow-Credentials`.
- API CI [44785894943](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44785894943), Quality Gates [44785894965](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44785894965) e Docker Compose [44785894960](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44785894960) passaram. Suite API **1388 passed, 1 skipped, 1 warning**.


## 2026-11-20 — Revalidação do actor no limite do handler

- A auditoria de Computer Vision confirmou que os endpoints de conteúdo de imagem, deteções, OCR, revisões humanas e artefactos já aplicam controlos de retenção e/ou store scope; existem regressões cross-store para leituras, conteúdo, revisões e mutações.
- Foi encontrada uma janela de concorrência comum: o middleware autentica numa sessão e fecha-a; depois, o handler carrega novamente o utilizador. Se a conta fosse removida/inactivada entretanto, `_request_user` devolvia `None`, e vários handlers podiam interpretar isso como ausência de actor e ignorar o store scope. Uma alteração de role na mesma janela também podia deixar a decisão RBAC do middleware desactualizada.
- Corrigido `apps/api/app/main.py`: em produção, actor ausente/inactivo produz 401 e a política RBAC é reavaliada com o role actual da base de dados antes de o handler prosseguir. O ambiente `test` mantém o comportamento necessário aos testes de unidade/integração.
- Acrescentados dois testes em `apps/api/tests/test_security.py`: conta eliminada após autenticação e downgrade de SUPERVISOR para EMPLOYEE antes de um POST de revisão.
- Commits: `b332cac30ca68a7961a2d49f4d5f5c9a146a1f38` (implementação), `294c98792fe238f898039db8b3f7e91f61528d56` (testes) e `3c87f97ff5e9e9e29eb051b3d6cc89c4b0d69d0b` (actualização de progresso).
- Os testes foram adicionados, mas não executados localmente nesta sessão. O CI deve validar os novos commits; não inferir GREEN a partir de workflows anteriores.


## 2026-11-20 — Proveniência de loja nos embeddings de visão

- Inspeccionados `product_embedding_service.py`, `vision_worker.py`, os handlers de criação/listagem/revisão de exemplares e os testes existentes.
- Confirmação: o worker deriva `store_id` da imagem alvo e fornece-o a `build_approved_product_registry`; a consulta por loja exige a relação exemplar → imagem → prateleira → zona. O carregador também revalida aprovação, estado activo da imagem, hash SHA-256, produto activo, revisor e dimensão do embedding.
- A API restringe criação/revisão por store scope quando existe imagem de origem; listagem não-admin filtra por loja e, para exemplares sem imagem, apenas mostra os criados pelo próprio utilizador. A revisão de um exemplar sem imagem fica limitada ao criador (com auto-revisão bloqueada) ou ADMIN.
- Acrescentado caso de regressão a `test_product_embedding_store_scope.py`: um exemplar APPROVED sem imagem de origem não pode entrar no registo de nenhuma loja. Isto protege a fronteira do worker mesmo perante dados globais/importados sem proveniência de loja.
- Commits: `3239f5952ce63e25d6c0db916f8549e1126552c9` (primeira versão do teste) e `40e6c0e40b9e7ed3d7ee5805ccae84b94ca0a5f7` (correcção do comentário Python).
- Teste publicado, não executado localmente. CI do novo commit ainda por confirmar.
- Decisão em aberto: proibir exemplares sem `shelf_image_id` na criação ou mantê-los para utilização administrativa/global. Não há evidência suficiente para alterar essa regra sem avaliar consumidores fora do worker por loja.

## 2026-11-20 — Testes do consumo de outputs de datasets

- A auditoria confirmou que `dataset_job_output_consumption.py` implementa leitura integral com verificação SHA-256, autorização por callback em toda a cadeia de outputs derivados, estado SUCCEEDED, governança (restrição/legal hold) e elegibilidade actual das imagens de origem.
- Não foi encontrada referência ao helper nos handlers de `main.py`; o módulo define uma fronteira de consumo reutilizável, mas não há evidência de endpoint de download/API já integrado. A integração de produto permanece uma decisão separada.
- Acrescentados três testes em `test_dataset_job_output_publications.py`: consumo autorizado dos bytes correctos, rejeição de callback que devolve valor truthy diferente de `True`, e rejeição de ficheiro publicado adulterado.
- Commit de testes: `a2b0175490b2ea56fa49956d92de1e1c1147326a`.
- Os testes foram adicionados ao repositório, mas ainda não executados localmente nem validados por CI nesta fase.

## 2026-11-20 — Locks da proveniência durante consumo de outputs

- A leitura de outputs derivados já bloqueava publicações ancestrais, jobs, imagens, prateleiras e zonas, mas consultava as linhas imutáveis `DatasetExecutionJobSource` sem lock explícito.
- O consumidor passou a obter essas linhas com `FOR UPDATE`, `populate_existing` e ordenação estável por `shelf_image_id`, `job_id` e `id`, mantendo os locks na transacção que abrange a validação e a leitura integral dos bytes.
- Teste de regressão acrescentado para confirmar SQL PostgreSQL com `FOR UPDATE`, filtro dos jobs esperados e ordenação determinística.
- Commits: implementação `b08cf3c`; teste `8d4ef12`.
- Os testes ainda não foram executados localmente; a validação depende do CI.

## 2026-11-20 — Correcção da verificação SQL dos locks de proveniência

- A primeira execução de Quality Gates no commit documental `5f43652` terminou com **1 falha, 1398 aprovados e 1 ignorado**. A falha estava no teste `test_output_consumer_locks_source_lineage_rows_in_stable_order`: o teste executava a query contra SQLite sem criar o esquema e tentava compilar um resultado materializado.
- Corrigida a separação no módulo `dataset_job_output_consumption.py`: `_output_sources_query` constrói a query com `FOR UPDATE` e ordenação determinística; `_lock_output_sources` executa-a no fluxo real de consumo.
- O teste agora compila `_output_sources_query` com o dialect PostgreSQL sem executar a query em SQLite.
- Commits: `d82ec0a` (código/testabilidade) e `a2fbc1a` (teste).
- A falha anterior é reproduzível nos logs do Quality Gates run `44829643260`; a correcção aguarda nova validação integral. Não foram executados testes localmente.

## 2026-11-20 — Durabilidade da publicação de outputs no filesystem

### Diagnóstico e TDD

- Os primeiros testes de regressão foram adicionados antes da implementação: falha do `fsync` do ficheiro temporário, sincronização de cada entrada da árvore de directórios, retry após falha do directório-pai e sincronização do destino existente.
- Quality Gates no commit `5e2d61b` confirmou **3 falhas, 1399 aprovados, 1 ignorado e 1 aviso**. As três falhas demonstraram ausência de sincronização da árvore e do destino recuperado.
- Foi acrescentado o teste de falha do `fsync` de staging depois do commit; Quality Gates no commit `8f73f94` confirmou **4 falhas, 1399 aprovados, 1 ignorado e 1 aviso**. A quarta falha demonstrou que a limpeza pós-commit não emitia observabilidade.

### Implementação

- `_open_dirs` percorre a raiz absoluta e os componentes com `O_NOFOLLOW`, sincroniza o directório-pai após confirmar cada componente e volta a sincronizar componentes existentes em retries.
- O destino preexistente é revalidado por tipo, tamanho, SHA-256 e estabilidade de identidade/metadados; o ficheiro e o directório são sincronizados antes da publicação SQL.
- A falha de `fsync` no temporário aborta antes do commit e preserva staging. A falha de sincronização pós-commit na remoção de staging não reverte uma publicação já confirmada; gera aviso com job ID e tipo de erro, sem revelar caminhos.
- Foi ainda corrigida uma fuga de descritor quando o `fsync` falha depois de abrir um componente existente. O teste específico falhou no commit `6147d41` (**1 falha, 1403 aprovados, 1 ignorado**) e passou após a correcção.
- Commits: testes `5e2d61b`, `8f73f94`, `6147d41`; implementação `e9ce0e6`, `4beb3f0`.

### Validação final no commit `4beb3f002b809de8ef50f9990a377db2f7f7c36d`

- API CI [44832248200](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44832248200): **1404 passed, 1 skipped, 1 warning**; migrações e smokes PostgreSQL 16 passaram, incluindo publicação fenced, linhagem derivada, legal hold/restrições herdadas e serialização concorrente.
- Quality Gates [44832248161](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44832248161): **1404 passed, 1 skipped, 1 warning**; compilação Python, build TypeScript e build de produção Web aprovados.
- Docker Compose [44832248174](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44832248174): passou; API, PostgreSQL e vision worker arrancaram, demo seed preparado, volume de outputs da API separado do volume de imagens e não montado no worker; worker verificado como não-root, filesystem root read-only, capabilities removidas e no-new-privileges.
- O aviso Python restante é a depreciação externa `anyio.abc.BlockingPortal` do Starlette TestClient. O build Web assinalou ainda depreciação Node.js 20 em `actions/upload-artifact@v4`, sem falha do build.
- Não foram executados testes localmente; a validação foi feita nos workflows GitHub Actions. Os smokes não demonstram resistência a perda física de energia nem garantias do dispositivo/volume real.
## 2026-11-21 — Matriz RBAC explícita e revalidação no handler

### Política por método/rota

- Substituída a classificação genérica `AUTHENTICATED_STAFF` por `API_ROUTE_POLICIES`, com uma entrada explícita por método e template FastAPI. O inventário actual tem 128 combinações: 2 PUBLIC, 25 ADMIN_ONLY, 88 SUPERVISOR_OR_ADMIN e 13 EMPLOYEE_ALLOWLIST.
- O matcher compara segmentos e exige coincidência do método. Uma rota/método desconhecido é `UNCLASSIFIED` e o middleware recusa-o a todos os perfis, incluindo ADMIN. A verificação de rotas públicas também é método-específica.
- Acrescentado `test_every_registered_versioned_api_route_has_an_explicit_method_policy`, que verifica os `APIRoute` efectivamente registados, e teste de templates dinâmicos/métodos não herdados.
- O auditor `apps/api/scripts/audit_api_route_policy.py` foi corrigido para reportar `UNCLASSIFIED` e fallbacks legados separadamente. O workflow API CI executa agora `python scripts/audit_api_route_policy.py --strict` antes das migrações e smokes.

### Revalidação da identidade

- A análise handler-by-handler encontrou dez handlers de administração/catálogo que dependiam apenas do middleware e não recarregavam o actor na sessão de execução: gestão de utilizadores, lojas, zonas, prateleiras, produtos e embalagens/perfis de armazém.
- Estes handlers recebem agora `Request` e chamam `_request_user` antes de ler ou escrever. A revalidação consulta o perfil actual da base de dados e aplica a política explícita método/rota.
- `test_admin_role_revocation_between_middleware_and_handler_blocks_store_creation` simula a despromoção de ADMIN para SUPERVISOR depois do middleware e antes da execução do handler; confirma HTTP 403 e que a loja não é criada.

### Commits principais

- Política explícita: `7523914c`.
- Middleware público método-específico: `d91e1426`.
- Cobertura de rotas registadas e regressões RBAC: `809945e1`, `813a2d42`, `3a966726`.
- Auditor strict: `347a00bd`; correcção do relatório: `a9f71290`; integração no API CI: `8775aaff`.
- Revalidação dos handlers: `26accef6`; teste de revogação entre middleware/handler: `311fecc9`.

### Validação

- API CI [44880841684](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44880841684): passou; migrações PostgreSQL 16 e todos os smokes dedicados passaram; suite **1407 passed, 1 skipped, 1 warning**.
- Quality Gates [44880841658](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44880841658): passou; compilação Python, suite API (**1407 passed, 1 skipped, 1 warning**) e build de produção Web aprovados.
- Docker Compose [44880841671](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44880841671): passou.
- O aviso Python restante é a depreciação externa `anyio.abc.BlockingPortal` do Starlette TestClient. O detector Impeccable continua a registar a baseline de design como não bloqueante.
- Não foram executados testes localmente; a validação foi feita nos workflows GitHub Actions.

### Limites ainda abertos

- A classificação explícita não substitui a prova endpoint × ADMIN/SUPERVISOR/EMPLOYEE × loja. A auditoria de tenant scope e caminhos indirectos continua aberta.
- SCA, secret scanning, DAST e pentest externo não foram executados.
- API CI [44881182965](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44881182965), commit `8775aaffc8db199dd6c43a61dafd03c019f519fc`, executou o gate `audit_api_route_policy.py --strict`: **128 métodos, 0 UNCLASSIFIED, 0 fallbacks legados**; migrações PostgreSQL 16, smokes e suite **1407 passed, 1 skipped, 1 warning**.
- Quality Gates [44880841658](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44880841658) e Docker Compose [44880841671](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44880841671) passaram no commit de código/testes `311fecc9`. A sincronização documental `5cdcf4b` também passou Quality Gates [44881922766](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44881922766). Não há execução local.

## 2026-11-21 — Matriz exaustiva de decisões RBAC

Foi acrescentado um teste parametrizado por todas as entradas de API_ROUTE_POLICIES. Para cada método/template, o teste verifica a decisão de ADMIN, SUPERVISOR e EMPLOYEE segundo a categoria declarada, além de detectar chaves duplicadas e categorias fora do conjunto permitido. Rotas não registadas continuam a ser negadas a todos os perfis.

O commit b1c60246938befa86233b49f6d8a4841617fbfdc passou Quality Gates [44882467613](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44882467613): compilação Python, build Web e **1408 passed, 1 skipped, 1 warning**. O aviso é a depreciação externa anyio.abc.BlockingPortal emitida pelo Starlette TestClient.

Docker Compose demo smoke [44882467596](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44882467596) passou. API CI [44882467564](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44882467564) concluiu com sucesso: auditoria estrita de rotas, migrations PostgreSQL 16, smokes de concorrência/isolamento/retention e **1408 passed, 1 skipped, 1 warning**.

A auditoria handler × perfil × loja permanece aberta: a matriz centralizada não prova isolamento de cada recurso nem caminhos indirectos. SCA, secret scan e DAST não foram executados.

## 2026-11-21 — Scanners de segurança automatizados adicionados

Foi criado .github/workflows/security-scans.yml com quatro jobs independentes: pip-audit para requirements.txt e requirements-ocr.txt, npm audit --audit-level=high para o lockfile Web, Gitleaks para histórico Git e OWASP ZAP Baseline para a API num Docker Compose efémero. As Actions de terceiros foram fixadas a commits completos; os jobs usam contents: read e o job Gitleaks recebe apenas a permissão adicional de comentários PR necessária à integração.

A primeira execução confirmou Gitleaks PASS e npm audit PASS. O pip-audit falhou com 158 ocorrências em cinco pacotes Python (pytest 8.3.5, PyJWT 2.10.1, python-multipart 0.0.20, Pillow 11.2.1 e Starlette 0.46.2). Foram actualizadas as dependências directas para versões corrigidas; FastAPI 0.165.0 passa a seleccionar Starlette compatível, sem pin directo de Starlette. A segunda execução SCA e a regressão completa continuam pendentes.

O ZAP está inicialmente em modo baseline passivo e report-only (fail_action: false), sem autenticação nem mutações. Isto estabelece recolha de evidência, não uma certificação DAST nem uma aprovação de segurança.

## 2026-11-21 — Remediação SCA, isolamento de locks e headers HTTP

### Dependências e qualidade
A primeira execução SCA detectou 158 ocorrências em cinco pacotes Python. Foram actualizados FastAPI 0.165.0, Pillow 13.0.0, PyJWT 2.15.1, python-multipart 0.0.34 e pytest 9.2.0; FastAPI selecciona a versão compatível de Starlette sem pin directo. Foi adicionado httpx2 2.16.2 para substituir o caminho deprecated do Starlette TestClient. O uso de Pillow foi migrado de Image.getdata para get_flattened_data.

No commit 1c0f59136af8364aab868b60f477c169679c4f3f:
- API CI [44884714292](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714292): sucesso; 1413 passed, 1 skipped; migrations e smokes PostgreSQL 16 passaram.
- Quality Gates [44884714318](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714318): sucesso; 1413 passed, 1 skipped; build Python/Web passou sem o aviso anterior do TestClient.
- Docker Compose [44884714261](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714261): sucesso.
- Security Scans [44884714393](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714393): pip-audit sem vulnerabilidades conhecidas, npm audit passou e Gitleaks passou.

### Isolamento multi-loja e concorrência
A auditoria encontrou endpoints que adquiriam locks antes de verificar o store scope. Foram criados _lock_authorized_shelf_image e _lock_store_scoped_record. O padrão é: leitura não bloqueante para obter store_id, validação de actor/tenant, lock com populate_existing, nova validação do tenant e só depois a operação. O padrão foi aplicado a 22 handlers de imagens, OCR, deteções, exemplares, sessões, paletes, tarefas e alertas. O teste estático impede regressões na ordem de autorização e locks.

O endpoint PATCH de alertas foi também corrigido para autorizar antes do lock. Os smokes PostgreSQL continuam a validar concorrência e retenção.

### Headers HTTP e DAST
Foram acrescentados headers HTTP de segurança, CSP, HSTS em produção e Cache-Control no-store para APIs. Swagger UI é desactivado em produção; a documentação interactiva fica disponível apenas fora de produção com CSP específica.

ZAP Baseline e API safe-mode [44884714393](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714393) analisaram 134 endpoints no baseline e 131 operações importadas via OpenAPI. Ambos os relatórios apresentaram 0 alertas High, 0 Medium e 0 Low; os alertas restantes são informativos. O scan não é autenticado: 128 operações protegidas responderam 401. Não é uma certificação de segurança nem substitui DAST autenticado/activo.

## 2026-11-21 — Matriz ONNX e falhas do worker

Foi ampliada a cobertura do contrato de saída do detector ONNX:
- Caixas com coordenadas invertidas ou área nula são descartadas.
- Caixas totalmente contidas no padding de letterbox são descartadas.
- Caixas que intersectam parcialmente o padding são recortadas correctamente à geometria da imagem original.

Foi acrescentado teste de integração do worker para RuntimeError e TimeoutError. Em ambos os casos, o worker marca a imagem como FAILED, guarda uma mensagem sanitizada, preserva deteções anteriores e não cria snapshots de inventário.

Validação no commit a345746200eb6ea8b0035bd2cdba7c188de87ef9:
- API CI [44885522283](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44885522283): sucesso, **1422 passed, 1 skipped**; migrations e smokes PostgreSQL 16 passaram.
- Quality Gates [44885522309](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44885522309): sucesso, **1422 passed, 1 skipped**.
- Docker Compose [44885522318](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44885522318): sucesso.
- Security Scans [44885522256](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44885522256): sucesso; SCA e secret scan passaram; ZAP sem alertas High/Medium/Low.

A cobertura é de contrato e tratamento de falhas. Não representa avaliação de precisão de um modelo real; a integração ONNX continua dependente de modelo e dataset autorizados.


## 2026-11-21 — Isolamento multi-loja na listagem de sessões de captura

- A auditoria handler-a-handler confirmou que `GET /api/v1/capture-sessions` restringe as sessões à `store_id` do actor não administrador.
- Acrescentado teste de regressão com duas lojas, duas prateleiras e sessões independentes. O supervisor da loja A só recebe a sua sessão e não consegue obter a sessão da loja B através de `shelf_id` estrangeiro.
- O teste chama o handler com actor de teste controlado e base SQLite isolada; a validação da execução CI e dos smokes PostgreSQL continua necessária para fechar esta unidade.
- A matriz global endpoint × perfil × loja continua aberta; este teste cobre apenas a listagem de sessões de captura.


## 2026-11-22 — Confiança persistente e anti-rollback de modelos ONNX

Foi implementado o schema v2 do manifesto Ed25519: o payload assinado inclui `model_id` e `release_version` monotónica, além de `key_id` e hashes do detector/embedder. Manifestos v1 deixam de ser aceites no provider real. O utilitário offline exige agora `--model-id` e `--release-version`.

A migration `0069_vision_model_release_trust_state` cria o high-water mark persistente por `VISION_MODEL_DEPLOYMENT_ID` e um trilho append-only de decisões. O serviço `app.vision_model_release` serializa upgrades, aceita retries exactos, rejeita rollback, colisão de versão e alteração da identidade do modelo. Triggers PostgreSQL/SQLite protegem a monotonicidade, impedem apagar o estado e tornam os eventos imutáveis; downgrade recusa remover high-water marks existentes.

O provider real regista o release depois de construir/validar as sessões ONNX, verifica a versão antes/depois da inferência e o worker bloqueia a linha do release na transacção de publicação. Um worker obsoleto não persiste resultados, reencaminha a captura para PENDING e termina para reiniciar com a configuração actual.

A rotação normal está documentada em `docs/vision-model-manifest.md`: adicionar chave nova, assinar release superior, confirmar todas as instâncias no novo release e só depois remover/revogar a chave antiga. A revogação explícita usa `VISION_MODEL_REVOKED_KEY_IDS_JSON`; o `VISION_MODEL_DEPLOYMENT_ID` tem de permanecer estável.

Testes acrescentados: `test_vision_model_release.py`, `test_vision_model_release_migration.py`, testes de configuração de deployment e smoke PostgreSQL `postgres_vision_model_release_smoke.py`, integrado em API CI. Em `APP_ENV=production`, `VISION_MODEL_DEPLOYMENT_ID` é obrigatório e não pode ser `default`; Compose deixa o valor vazio quando não configurado.

Validação confirmada:
- API CI [45065013302](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065013302): sucesso; PostgreSQL 16, migration 0069, smoke de concorrência/rollback/append-only/TRUNCATE e **1545 passed, 1 skipped**.
- Quality Gates [45065079666](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065079666): sucesso; **1545 passed, 1 skipped**, compilação Python e build Web.
- Docker Compose [45065013291](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065013291): sucesso; readiness, seed e worker.
- Security Scans [45065079730](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065079730): sucesso; SCA, Gitleaks do histórico e ZAP baseline.

Limitação de segurança resolvida em camadas: owner de migrations separado do runtime, tabelas de confiança ONNX read-only para API/worker e registo explícito de releases pelo owner. O owner continua privilegiado e deve permanecer restrito ao serviço de migrations e ao perfil one-shot. Não existem pesos/dataset autorizados, pelo que nenhuma inferência real foi activada.


## 2026-11-22 — Separação PostgreSQL owner/runtime e trust state ONNX (CI validada no HEAD aeff4a3b)

- O Compose executa Alembic no serviço one-shot `migrate` com o principal owner; API e vision-worker usam `APP_DB_USER`/`APP_DB_PASSWORD` separados. A API já não executa migrations no arranque.
- O bootstrap `infra/postgres/10-create-runtime-role.sh` cria um papel NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/NOBYPASSRLS/NOINHERIT, remove memberships/ownership anteriores, concede DML operacional e revoga CREATE no schema.
- A validação CI anterior confirmou a instalação limpa e o smoke de permissões geral no HEAD `bbf5ad80`: API CI, Quality Gates, Security Scans e Docker Compose passaram; suite API **1549 passed, 1 skipped**. O smoke runtime-role passou, mas a auditoria adicional detectou que o runtime ainda tinha DML sobre as tabelas de confiança ONNX.
- Nova análise P0: triggers monotónicos não impediam o runtime de inserir eventos falsos ou elevar arbitrariamente o high-water mark para uma versão futura, bloqueando releases legítimas.
- Implementada migration `0070_vision_model_trust_runtime_readonly` e actualização do bootstrap: runtime passa a ter apenas SELECT em `vision_model_release_states`/`vision_model_release_events`, sem DML/TRUNCATE nem acesso à sequência de eventos.
- O provider deixou de registar releases no arranque. Criado `apps/api/scripts/register_vision_model_release.py` e perfil one-shot `register-model-release`, que verifica manifesto Ed25519, digests e exige o owner das tabelas.
- `app.vision_model_release` usa advisory transaction lock por deployment para serializar verificações read-only e registos privilegiados; evita SELECT FOR UPDATE e mantém o runtime sem UPDATE.
- A migration 0070 falha fechada em produção se `APP_DB_USER` faltar, não existir, coincidir com o owner ou for owner das tabelas de confiança.
- O smoke PostgreSQL foi alargado para provar SELECT autorizado, DML/sequence privileges ausentes, recusa efectiva de INSERT/UPDATE/DELETE/TRUNCATE e validação do release pelo runtime. Foram acrescentados testes estáticos e teste de migração dialect-safe.
- Documentação actualizada: README, guia do manifesto, provider ONNX, segredos de produção, ADR-009 e TODO.
- **Validação da camada read-only ONNX:** concluída no SHA `5e16a9cb`: API CI, Quality Gates, Security Scans e Docker Compose passaram; suite API **1552 passed, 1 skipped**. O API CI confirmou o smoke PostgreSQL de permissões e o guard advisory com o principal runtime.


## 2026-11-22 — Provisionamento recorrente do principal runtime (CI validada no HEAD aeff4a3b)

- Foi removido o acoplamento do bootstrap ao directório `initdb.d`, que só corre em volumes novos.
- Adicionado o serviço one-shot `provision-runtime-role` (imagem PostgreSQL 16) entre `db` e `migrate`. Liga por TCP, autentica com o owner, reconcilia papel/senha/memberships/ownership/grants e termina antes de Alembic.
- A API e o worker só arrancam depois do provisionamento e das migrations; volumes persistentes antigos também passam pelo processo.
- O papel runtime passa a `NOINHERIT`; o smoke verifica `rolinherit=false` além de atributos, memberships, ownership, DML operacional e trust tables read-only.
- O API CI recebe explicitamente `POSTGRES_PASSWORD` para exercitar o mesmo script de provisionamento por TCP.
- README, guia do manifesto, DEMO, segredos de produção, ADR-009, TODO e instruções da API actualizados para remover comandos Alembic no container runtime.
- API CI [45076219787](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219787), Quality Gates [45076219801](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219801), Security Scans [45076219740](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219740) e Docker Compose [45076219751](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219751) passaram no HEAD `aeff4a3b`; suite API **1552 passed, 1 skipped**. O Compose smoke simulou um volume legado ao atribuir ownership de uma tabela ao runtime e uma membership indevida, e confirmou a reconciliação automática.

### 2026-11-23 — Controlos positivos para IDs aninhados de localização e prateleira

- O smoke PostgreSQL cria agora uma localização física e uma prateleira com atribuição de produto na loja do supervisor, além dos recursos equivalentes da loja estrangeira.
- Mantém os ataques cross-store existentes e acrescenta controlos positivos: criar uma colocação na localização própria e criar uma tarefa na prateleira própria (ambos esperam HTTP 201).
- O objetivo é provar simultaneamente rejeição de IDs estrangeiros e aceitação de IDs válidos do mesmo tenant, evitando falsos positivos por recurso inexistente.
- Implementação publicada; validação PostgreSQL 16/CI ainda pendente.


### 2026-11-23 — Correcção do controlo positivo de rotação de paletes

- A execução API CI do commit `4b9ab319` identificou uma fixture inválida no controlo positivo: a palete da loja A estava em `READY`/`WAREHOUSE`, mas o endpoint de planeamento só aceita `ON_DISPLAY`/`PARTIAL` em `SALES_FLOOR`.
- Corrigida a fixture da palete própria para `ON_DISPLAY`/`SALES_FLOOR`, preservando a palete estrangeira em estado de armazém para o teste de isolamento.
- O diagnóstico foi obtido nos logs do job PostgreSQL; a correcção está publicada no commit `ba551a10` e aguarda nova execução da API CI.
- A falha era do dado de teste, não evidência de quebra da autorização de tenant; a suite abortou antes dos novos controlos de colocação e tarefa.


## 2026-11-23 — Testes de regressão do worker Edge após perda de lease

- Commit aec6f2b1701e2fcb92e51ba981c9819d8347c683: acrescentados casos para falha transitória e permanente do handler depois de falhar a renovação da lease.
- A expectativa é manter PROCESSING, preservar o proprietário/token para recuperação por expiração e não confirmar nem reclassificar o evento com uma lease perdida.
- API CI, Quality Gates, Security Scans e Docker Compose foram iniciados para este commit; os resultados ainda não estavam disponíveis no momento deste registo.
- Próxima prova necessária: smoke PostgreSQL de takeover concorrente durante processamento e rejeição de ACK/falha por fencing obsoleto.


## 2026-11-23 — Expansão dos testes BOLA para recursos aninhados de prateleira

- O smoke PostgreSQL passou a criar uma observação, sessão de captura, alerta e evento de auditoria reais na loja B.
- Acrescentados ataques com shelf_id estrangeiro contra criação de observação, criação de sessão, criação/listagem de planogramas, consenso e leitura de eventos de alerta.
- Acrescentados controlos de não divulgação para listagens de observações, sessões e alertas filtradas por prateleira estrangeira.
- Os controlos positivos same-store existentes foram preservados e estendidos a observações e sessões.
- Commits de implementação: d4429b0fa1ab3d2c729d6c5b8b29f38dc5cdf731 e 99a69a7415bc552b0cf104861d93881dac6259e1.
- Validação PostgreSQL 16 ainda pendente para o SHA final 99a69a7; não houve execução local do script.
- Na ronda anterior, API CI e Docker Compose passaram no commit aec6f2b; Quality Gates e Security Scans foram cancelados.
- Próxima prova: CI do smoke de autorização, depois matriz de roles e takeover PostgreSQL do worker Edge.


## 2026-11-23 — Controlos ADMIN/EMPLOYEE no smoke de autorização

- Criado actor EMPLOYEE da loja A para validar negações RBAC em endpoints de observações, sessões de captura, alertas e planogramas.
- Acrescentados controlos ADMIN que leem as fixtures reais da loja B, demonstrando que as respostas vazias do SUPERVISOR são efeito do isolamento de tenant.
- Commit: 26a97f7136eace2bc0b4f428731db3990163aa93.
- A validação CI/PostgreSQL 16 deste commit ainda está pendente.


## 2026-11-23 — Validação PostgreSQL do smoke BOLA/RBAC

- API CI [45177953932](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45177953932), commit de código `26a97f7136eace2bc0b4f428731db3990163aa93`: o passo **Verify PostgreSQL inventory and warehouse cross-store authorization** terminou com sucesso em PostgreSQL 16. Isto valida os testes adicionados de observações, sessões, alertas, planogramas e papéis ADMIN/SUPERVISOR/EMPLOYEE.
- A suite pytest completa continuava em execução; não declarar API CI integralmente verde.
- Docker Compose Smoke [45177953980](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45177953980) passou.
- Quality Gates e Security Scans foram cancelados após o push documental posterior; devem ser repetidos num commit posterior.


## 2026-11-23 — Ocultação de IDs directos de ciclo de vida de paletes

- Auditoria ao commit `e9ce6e52` identificou uma regressão: o handler `POST /api/v1/warehouse/pallets/{pallet_id}/events` deixou de passar `hide_foreign=True` ao helper `_lock_store_scoped_record`, embora a alteração anterior tivesse explicitamente introduzido a ocultação de IDs de paletes estrangeiras.
- Reposto `hide_foreign=True`. A verificação de tenant ocorre antes da aquisição do lock e volta a ocorrer após o refresh da linha bloqueada.
- O teste HTTP autenticado passou a exigir HTTP 404 tanto para a palete real da loja estrangeira como para um ID inexistente, evitando um oráculo de existência. As verificações de estado da palete e contagem de eventos mantêm-se.
- Commits publicados: `4873087c` (correcção) e `ecc652e5` (regressão).
- API CI, Quality Gates, Security Scans e Docker Compose do novo HEAD ainda não confirmados. Não foi executada suite local nesta sessão.


## 2026-11-23 — BOLA: criação de prateleiras através de zona estrangeira

- A auditoria identificou que POST /api/v1/shelves consultava a zona pelo ID, mas não comparava o store_id da zona com a loja do actor.
- Um SUPERVISOR autenticado podia, por isso, tentar criar uma prateleira numa zona de outra loja. A rota passa agora a ocultar zonas estrangeiras com HTTP 404, igual ao ID inexistente, antes de persistir.
- Foi acrescentado teste HTTP autenticado com zona estrangeira, ID inexistente e controlo positivo same-store; verifica também que a tentativa negada não cria a prateleira.
- Commits: código aa46a2553ac37e479c7b9564ff8c2b69ffa24cb5; teste 716c359afbad17e2280014f938d2c2d71c899c80.
- CI, execução local e PostgreSQL 16 ainda não foram confirmados.


## 2026-11-23 — BOLA: associação de produto a prateleira estrangeira

- A rota POST /api/v1/shelf-products consultava primeiro o shelf_id e devolvia 403 para prateleiras estrangeiras, distinguindo-as de IDs inexistentes. A validação do actor foi antecipada e a resposta passou a HTTP 404 uniforme antes do lock do produto.
- Teste autenticado cobre shelf estrangeira e inexistente, igualdade das respostas, ausência de associação indevida e controlo positivo same-store.
- Commits: código 6a4b783741c9d1b25571ba2f16866b74be90fab0; teste 78d07d3228a4f988539aebb40127332e60376c08.
- CI, suite local e PostgreSQL 16 ainda não foram executados/confirmados nesta ronda.


## 2026-11-23 — BOLA: IDs directos de tarefas de reposição

- GET /api/v1/tasks/{task_id}/events consultava a tarefa antes de autenticar o actor e devolvia 403 para tarefas estrangeiras. A rota valida agora o actor primeiro e devolve HTTP 404 equivalente para tarefa estrangeira e inexistente.
- A leitura de eventos não usa row lock: resolve a tarefa sem bloqueio, aplica tenant scope e só depois consulta os eventos. Evita introduzir contenção desnecessária numa rota GET.
- PATCH /api/v1/tasks/{task_id}/status e POST /api/v1/tasks/{task_id}/reconcile-inventory usam agora _lock_store_scoped_record com hide_foreign=True, preservando autorização pré-lock e revalidação pós-lock.
- Testes comparam respostas para IDs estrangeiros/inexistentes nos três endpoints. A reconciliação negada é verificada sem InventoryMovement persistido; a transição negada mantém estado/eventos inalterados.
- Commits: eventos 132558c (primeira implementação, substituída pela leitura sem lock em 954f973); status/reconciliação ee40b88; testes de eventos/status f12ed7b; reconciliação cc3dc3a.
- CI e PostgreSQL 16 para estes commits ainda não confirmados.


## 2026-11-23 — BOLA: IDs de evidência de visão computacional

- GET /api/v1/shelf-images/{image_id}/retention/events resolvia a imagem antes de autenticar o actor. A autenticação/RBAC passou para o início; a consulta de tenant agora devolve HTTP 404 uniforme para imagem estrangeira e inexistente, sem introduzir row lock numa rota GET.
- POST /api/v1/shelf-image-detections/{detection_id}/reviews autentica agora antes de consultar detection_id. A imagem de origem é validada com hide_foreign=True; a resposta para deteção estrangeira é HTTP 404 com o mesmo detalhe de uma deteção inexistente. A ordem imagem → produto continua preservada.
- PATCH /api/v1/product-embedding-exemplars/{exemplar_id}/review autentica antes de resolver exemplar_id e oculta a imagem de origem estrangeira com HTTP 404 uniforme. A semântica HTTP 410 para imagem de origem indisponível por retenção é preservada para recursos autorizados.
- Testes adicionados/ajustados: comparação de IDs estrangeiros e inexistentes em retenção, revisão de deteções e revisão de exemplares; os testes existentes preservam controlos same-store, revisão independente e ausência de persistência não autorizada.
- Durante a validação PostgreSQL anterior, API CI detetou um contrato smoke desatualizado: criação de warehouse placement numa localização estrangeira passou a devolver 404, mas o smoke ainda esperava 403. A expectativa foi atualizada em 9f5ebe0. Nova execução CI para as alterações atuais está em curso.
- Commits principais: e402eda (ordem de autenticação/escopo), 956431e (detalhes uniformes), 11305cc (teste deteções), 1420ed4 (teste exemplares), 57cdab3 (teste retenção), 9f5ebe0 (smoke warehouse).


## 2026-11-23 — BOLA: upload de imagens e IDs de sessões de captura

- POST /api/v1/shelf-images autentica agora o actor antes de resolver shelf_id e devolve HTTP 404 uniforme para prateleiras estrangeiras e inexistentes.
- O capture_session_id opcional passa a usar _lock_store_scoped_record(..., hide_foreign=True), mantendo o preflight de tenant antes do row lock e a revalidação após o lock. Sessões estrangeiras e inexistentes devolvem HTTP 404 com detalhe uniforme.
- Testes comparam respostas para prateleira estrangeira/inexistente e sessão de captura estrangeira/inexistente; verificam que pedidos recusados não criam ficheiros nem novos registos ShelfImage.
- Commits: 90bd84f (preflight upload), 91da9f1/fdcbd55 (teste prateleira), 30f0dda (preflight sessão), 0d7a079/3e1ac0a (teste sessão). CI no HEAD final pendente.


### Ajuste de validação PostgreSQL — contrato de ocultação de deteções

A API CI executada no commit 73ad7b4 falhou exclusivamente no script postgres_detection_exemplar_prelock_smoke.py: o smoke ainda esperava HTTP 403 para revisão, histórico e revisão de exemplar cross-store. A implementação passou a ocultar estes IDs com HTTP 404 uniforme, preservando o requisito central do smoke — rejeitar antes de bloquear a imagem/produto. Atualizei as três expectativas e a mensagem do smoke no commit 31e6c9f. O resultado do novo CI ainda está pendente; não considerar a suite aprovada.


## 2026-11-23 — Validação integral concluída no HEAD 1ffe4d3a

A execução final do GitHub Actions foi concluída com sucesso no commit `1ffe4d3a7567c486f68de5e26051f7bcc0a2c110` (branch `main`):

- API CI: **1595 passed, 1 skipped**. Incluiu a suite pytest e os smoke tests PostgreSQL 16.
- Smoke PostgreSQL: autorização de inventário/tarefas/warehouse, sessão de captura, retenção e legal hold, IDs diretos de deteções/exemplares, concorrência de revisão, planogramas, integridade de inventário e anti-rollback ONNX passaram.
- Quality Gates: Python tests/compilation e TypeScript/production build passaram.
- Security Scans: Git history secret scan, Python dependency audit, Web dependency audit e OWASP ZAP passive baseline passaram.
- Docker Compose demo stack smoke passou.

A primeira execução integral após a alteração de contratos encontrou 24 testes com expectativas antigas (403 em vez de 404) e um teste com fixture duplicada. As expectativas foram alinhadas com a ocultação uniforme de IDs estrangeiros; os fixtures foram isolados e os testes reexecutados. A execução final passou sem falhas.

Próxima prioridade: continuar auditoria de IDs aninhados em OCR/matching/artefactos e warehouse, preservando preflight de tenant, ordem global de locks e ausência de efeitos laterais.

## 2026-11-23 — Isolamento SQL directo no histórico de tarefas

- `GET /api/v1/tasks/{task_id}/events` passou a resolver tarefas de SUPERVISOR com `task_id` e `store_id` no mesmo predicado SQL; uma tarefa estrangeira deixa de ser carregada antes da decisão de autorização.
- ADMIN mantém consulta global; a regressão confirma acesso administrativo e compara o 404/corpo de IDs estrangeiros e inexistentes para SUPERVISOR.
- Código e teste publicados. A suite e os workflows do SHA final ainda carecem de confirmação.


## 2026-11-23 — Preflight SQL multi-tenant de detection_id

- Os três endpoints de revisão, histórico e criação de observação deixaram de usar `db.get(ShelfImageDetection, detection_id)` antes da autorização da imagem.
- Novo resolver faz JOIN da detecção à imagem/prateleira/zona e, para actores não ADMIN, aplica `Zone.store_id == actor.store_id` no próprio SELECT. A imagem continua a ser bloqueada e revalidada pelo helper existente antes da leitura/escrita da detecção.
- Teste directo confirma que IDs estrangeiros e inexistentes são ocultados pelo resolver; regressões HTTP existentes continuam a comparar respostas e a verificar ausência de persistência.
- Código e testes publicados; validação CI do SHA final pendente.



## 2026-11-23 — Interface de histórico de movimentos de inventário

- Criado o componente `InventoryMovementHistory` e integrado no dashboard para ADMIN e SUPERVISOR.
- O painel consulta a API existente, respeita o filtro de loja (incluindo a seleção do ADMIN), permite filtrar por produto/tarefa e apresenta métricas agregadas sobre os 100 registos mais recentes.
- Cada linha pode ser expandida para mostrar IDs de tarefa, loja, actor, snapshot de origem/resultado, tipo e justificação. A interface é explicitamente read-only.
- A rota `GET /api/v1/inventory/movements` foi adicionada à matriz explícita de autorização. A auditoria estrita tinha falhado porque a rota nova não estava classificada; a classificação foi corrigida antes da próxima execução.
- A interface usa `VITE_API_BASE_URL` quando configurado e mantém a apresentação em pt-PT.
- Validação: código publicado; a execução de Web CI e Quality Gates do novo HEAD está pendente de conclusão. Não declarar build/testes aprovados até obter os resultados finais.


## 2026-11-23 — Correção de semântica do KPI de tarefas urgentes

- A Quality Gates do HEAD `8e92494b446a2f0c233755316ada70407b596cd1` identificou uma divergência: o contador de tarefas urgentes incluía também prioridade HIGH.
- Corrigido `urgent_active_tasks` para contar apenas tarefas com prioridade `URGENT`; tarefas `HIGH` continuam contabilizadas em `tasks_by_priority`, sem serem apresentadas como urgentes.
- A regressão existente em `apps/api/tests/test_dashboard_summary.py` já cobre o cenário com uma tarefa URGENT e outra HIGH.
- Aguardar nova API CI/Quality Gates para confirmar a correção.


## 2026-11-23 — Painel operacional de reconciliação do inventário
- Criado `InventoryReconciliationPanel`, integrado no dashboard para ADMIN e SUPERVISOR.
- O painel consome `GET /api/v1/inventory/reconciliation`, com filtros por produto e prateleira, indicadores agregados e atualização manual.
- A interface mantém os domínios separados: objetivo de exposição e quantidade observada na prateleira, versus stock físico registado, reservado e disponível na retaguarda.
- A diferença apresentada é explicitamente a diferença face ao objetivo de exposição, não uma alteração nem uma inferência do stock contabilístico.
- São apresentados a origem e a idade do snapshot, a confiança e data da observação e os estados sem medição/snapshot.
- Não foram criadas mutações de inventário nem ajustes automáticos.
- Validação de build e Quality Gates do SHA final ainda pendente.

## 2026-11-24 — Reconciliação: ausência de evidência não significa stock zero

Foi adicionada uma regressão em `apps/api/tests/test_inventory.py` para uma associação produto/prateleira sem observação visual e sem snapshot de retaguarda. O contrato esperado é `NO_OBSERVATION`, quantidade observada e diferença nulas, e campos de stock de retaguarda nulos. O teste confirma ainda que a consulta não cria `InventoryMovement` nem `InventorySnapshot`.

Commit de teste: `3f5c0b012fd4104edc1cf55c24d308668a99a1d1`. A documentação de acompanhamento foi actualizada no commit `e629bd65952b976d4546e6f55325151590561ada`. A validação automatizada do novo HEAD continua pendente; não considerar o teste aprovado até a execução CI terminar.


## 2026-11-24 — Protecção do motor de recomendações contra relógios divergentes

- O motor de recomendações de reposição passa a devolver `INVALID_OBSERVATION_TIMESTAMP` quando a observação mais recente tem data futura relativamente ao relógio UTC da API.
- A recomendação não inclui quantidade sugerida nesse cenário, mesmo que exista stock disponível na retaguarda; evita-se transformar evidência temporalmente inválida numa tarefa operacional.
- Foi acrescentado teste com timestamp cinco minutos no futuro. CI ainda não confirmado para este HEAD.

## 2026-11-24 — Detecção de timestamps futuros na evidência visual

- A reconciliação expõe agora `observation_timestamp_in_future`, para distinguir relógios divergentes de observações genuinamente recentes.
- A idade continua limitada a zero para evitar valores negativos, mas o novo indicador torna explícito que o timestamp está no futuro relativamente ao relógio UTC da API.
- Teste acrescentado para uma observação cinco minutos no futuro; a validação CI deste HEAD ainda está pendente.

## 2026-11-24 — Frescura da evidência visual na reconciliação

- `GET /api/v1/inventory/reconciliation` passa a devolver `observation_age_minutes`, calculado a partir de `observed_at` e do relógio UTC da aplicação.
- O campo permite ao supervisor distinguir uma contagem recente de uma observação antiga sem impor um limiar de obsolescência não configurado pelo negócio.
- Sem observação, o campo permanece `null`; a ausência de evidência não é convertida em idade zero.
- Testes actualizados para validar uma observação com 90 minutos e o caso sem observação.
- Commits: API `e0978a5b`; testes `c8b182a1`. CI pendente; não foi executado pytest localmente nesta sessão.


### 2026-11-24 — Reavaliação da recomendação dentro da secção crítica

- A rota `POST /api/v1/tasks/from-recommendation` calculava a recomendação antes de adquirir o lock da loja. Um snapshot de stock ou evidência visual podia mudar entre a validação e a criação da tarefa.
- A recomendação passou a ser recalculada depois de `_lock_store_for_task_creation`, mantendo a verificação de duplicados e a persistência no mesmo âmbito transaccional.
- Commit: `edc77be9`.
- CI/PostgreSQL 16 e teste concorrente específico ainda não confirmados; esta alteração reduz a janela TOCTOU, mas não substitui validação de todos os escritores de inventário.


## 2026-11-24 — Validade temporal do inventário nas recomendações

- Corrigida uma lacuna funcional: o motor de recomendações verificava a idade da observação visual, mas aceitava snapshots de retaguarda antigos ou com timestamp futuro.
- As recomendações passam agora a aplicar `InventoryFreshnessPolicy` por loja/origem (predefinição de 240 minutos), com estados `STALE_INVENTORY` e `INVALID_INVENTORY_TIMESTAMP`.
- Para ambos os estados, a quantidade sugerida permanece `null`; a rota de criação a partir de recomendação rejeita a operação porque o estado não é `NEEDS_REPLENISHMENT`.
- Adicionado teste parametrizado para snapshot com dois dias e snapshot cinco minutos no futuro, verificando também a rejeição da tarefa.
- Commits: `56a7d676` (motor), `9cc700d1` (schema), `8bd5a880` (testes). Execução local e CI ainda não confirmadas.

- Teste adicional `test_replenishment_uses_store_and_source_inventory_freshness_policy` confirma que a política configurada por loja/origem prevalece sobre o limite predefinido. Commit: `92e166a7`.
- Durante a revisão do diff foi corrigido um bloco duplicado introduzido na primeira edição do motor; o fluxo final foi relido no GitHub. Ainda sem execução local dos testes.


## Operações — distribuição automática de tarefas (2026-11-24)

- [x] Criar um planeador determinístico que distribui tarefas pendentes pelo funcionário com menor carga activa.
- [x] Ordenar tarefas por prioridade (URGENT, HIGH, NORMAL, LOW), com desempate estável pelo ID.
- [x] Preferir continuidade na mesma zona quando a carga é equivalente.
- [x] Expor `POST /api/v1/replenishment/auto-assign?store_id=...`, restrito a ADMIN/SUPERVISOR e ao âmbito da loja.
- [x] Bloquear as tarefas seleccionadas durante a distribuição e registar cada atribuição no histórico de eventos.
- [x] Acrescentar testes unitários do planeador e teste HTTP de integração para distribuição e auditoria.
- [ ] Executar a suite API e validar o fluxo em PostgreSQL 16/CI antes de considerar a funcionalidade validada em produção.

Limites conhecidos: a distribuição usa a carga activa registada e a zona das tarefas; ainda não modela turnos, competências, pausas, capacidade horária ou disponibilidade em tempo real. A funcionalidade não altera prioridades nem cria tarefas.


## Dashboard operacional — análise por dimensão e período (2026-11-24)

- [x] Adicionar `GET /api/v1/dashboard/operations` com filtros `store_id`, `from_date` e `to_date`.
- [x] Agregar tarefas por funcionário, zona e produto, incluindo estado, urgências, quantidades efectivamente repostas e taxa de conclusão.
- [x] Aplicar isolamento multi-tenant: ADMIN global/por loja, SUPERVISOR apenas na própria loja e EMPLOYEE apenas nas tarefas que lhe estão atribuídas.
- [x] Validar intervalo temporal invertido e limitar a consulta a 366 dias.
- [x] Acrescentar regressões para agregações, período e fronteiras de autorização.
- [ ] Executar API CI/PostgreSQL 16 e validar o consumo destas métricas pela interface Web.

Nota: o dashboard agrega tarefas registadas, não constitui um feed em tempo real; as datas do filtro são interpretadas em UTC. A análise de produtividade não deve ser usada isoladamente para avaliação individual, pois não ajusta ainda por horas de turno, complexidade ou dificuldade das tarefas.


## Workforce foundation — shifts, skills and availability (2026-11-24)

- [x] Persist employee shifts with start/end timestamps, break minutes, status and creator audit.
- [x] Persist normalized employee competencies with proficiency levels from 1 to 5.
- [x] Persist explicit AVAILABLE/UNAVAILABLE intervals.
- [x] Add Alembic migration `0074_employee_workforce`.
- [x] Add store-scoped supervisor/admin endpoints to create and list shifts, skills and availability.
- [x] Reject inactive, foreign-store and non-employee identities; enforce store scope for supervisors.
- [x] Reject overlapping scheduled shifts and contradictory availability intervals.
- [x] Require timezone-aware timestamps and validate interval ordering and break duration.
- [x] Add regression tests for persistence, capacity arithmetic, duplicates, overlaps and tenant isolation.
- [ ] Validate migration and test suite on PostgreSQL 16 through GitHub Actions.
- [ ] Add update/cancellation workflows for shifts and availability records.
- [x] Feed persisted workforce constraints into the capacity-aware task planner.

The shift's net planned capacity is calculated as `(ends_at - starts_at) - break_minutes`. This note describes the initial workforce data-model delivery. The subsequent capacity-aware planning phase below supersedes its original limitation and now consumes these persisted constraints during automatic assignment.


## Capacity-aware workforce planning (2026-11-24)

- [x] Add task-level estimated duration (1–480 minutes; default 15) and optional required competency.
- [x] Persist the new task fields through migration `0075_task_capacity`; existing tasks receive the safe 15-minute default.
- [x] Normalize competency codes and enforce duration bounds in request schemas and the database model.
- [x] Replace count-only auto-assignment with a planner that checks an active scheduled shift, explicit unavailability, required competency and remaining shift minutes.
- [x] Deduct estimated minutes for already assigned/in-progress tasks before assigning additional work.
- [x] Keep priority ordering URGENT > HIGH > NORMAL > LOW; tasks that do not fit remaining capacity or competency constraints remain pending.
- [x] Record the planning rationale in the task event history and return assigned/unassigned counts.
- [x] Add unit tests for shift eligibility, unavailability, competency matching, priority and capacity overbooking; extend the API lifecycle and auto-assignment integration tests.
- [ ] Confirm PostgreSQL migration and all GitHub Actions checks complete successfully.

Capacity is calculated conservatively from the current instant until the active shift ends, less the full configured break duration, then less the estimated duration of the employee's active assigned tasks. Explicit UNAVAILABLE intervals block assignment. AVAILABLE records are currently informational; the presence of a shift is the positive eligibility requirement. This iteration does not yet schedule tasks into future shifts or model break placement within a shift.


## Capacity-aware task planning — 2026-11-24

- [x] Added `estimated_duration_minutes` (1–480; default 15) and optional normalized `required_skill_code` to replenishment tasks.
- [x] Added Alembic migration `0075_task_capacity`.
- [x] Replaced the previous unconstrained balancing behaviour in the automatic assignment endpoint with persisted workforce eligibility.
- [x] Only active employees with a currently scheduled shift, no active unavailability interval, the required competency and sufficient remaining minutes can receive a task.
- [x] Active assigned/in-progress tasks consume their estimated duration before new work is allocated.
- [x] Priority order remains URGENT > HIGH > NORMAL > LOW; tasks that do not fit remain pending and are counted as unassigned.
- [x] Workforce mutations serialize on the store row, preventing concurrent shift/availability/skill changes from racing with assignment planning on PostgreSQL.
- [x] Added planner unit tests and API integration coverage for required skills and capacity limits.
- [ ] Validate all migrations and API tests in the current PostgreSQL-backed GitHub Actions run.
- [ ] Add workforce update/cancellation endpoints and a preview/simulation mode for supervisors.

Capacity is calculated conservatively from the current time to the end of the active shift, less the configured break minutes and estimated active workload. In-progress tasks are charged their full estimate because the current task model does not yet persist remaining effort.


## 2026-11-24 — Reconciliação multi-fonte ERP/WMS

A API de reconciliação passou a obter snapshots independentes por fonte ERP e WMS, com quantidades on-hand/reservadas/disponíveis, timestamp, idade e frescura. A diferença WMS−ERP só é calculada quando ambas as fontes estão dentro da política de frescura; estados em falta, stale ou futuros permanecem explícitos e não são convertidos em zero. O dashboard apresenta os dois domínios lado a lado e mantém o comportamento read-only. Foram corrigidas três regressões de testes já existentes no HEAD (import ausente, associação SKU/prateleira em fixture e transição de tarefa duplicada) e acrescentado teste de divergência ERP/WMS. GitHub Actions no SHA actual ainda em execução; não declarar a validação concluída antes dos resultados finais.

Limitação: a API recebe snapshots, mas não existe ainda ligação real a ERP/WMS. A comparação é operacional e informativa; não actualiza inventário contabilístico nem cria movimentos automaticamente.


## Ledger auditável de reconciliação

Implementado ledger persistente independente dos movimentos contabilísticos. Cada registo congela loja, prateleira, produto, observação, snapshots WMS/ERP/retaguarda, quantidades, diferenças e timestamps. Estados de revisão PENDING, APPROVED, REJECTED e NEEDS_INVESTIGATION. A revisão exige ADMIN/SUPERVISOR diferente do autor e justificação obrigatória. Eventos append-only; triggers impedem alterações à evidência e aos eventos. UI permite registar, consultar e rever reconciliações. Nenhum endpoint deste fluxo cria movimentos ou altera saldos.

Migração 0076 e testes de API/migração adicionados. Validação CI do commit final pendente.


## ERP/WMS — orquestração e mapeamento (24-11-2026)
Implementados os modelos/migrações 0078 e 0079 para mapeamento externo de produtos e finalização segura do identificador da execução no ledger. Foi criado `inventory_connectors/orchestrator.py`, invocável por worker confiável, com verificação da integração activa, mapping exacto por loja/fonte, paginação, timeout, três tentativas com backoff, limite de 1000 páginas, detecção de cursor repetido, persistência transaccional por página e idempotência por referência externa. Replays idênticos são aceites; referências repetidas com conteúdo diferente são rejeitadas. Os testes focam retries, comparação temporal e trigger de identidade da execução.

Limites: ainda não há API de administração de mappings, worker/scheduler durável, secret manager ligado ou adapter de fornecedor real. Não afirmar integração operacional até homologação.


## Administração de mappings ERP/WMS (24-11-2026)
Implementada API de listagem, criação e actualização de mappings externos por loja, com autorização ADMIN/SUPERVISOR, controlo de store scope, exigência de integração activa e produto interno activo. A API exige motivo de auditoria, não permite apagar mappings e disponibiliza endpoint de histórico. Migração 0080 adiciona eventos append-only; migração 0081 torna a identidade externa imutável e bloqueia DELETE ao nível da base de dados. Foram acrescentados testes de API, permissões, duplicados, histórico e triggers.

Pendente: worker durável, gestão de secrets, recuperação de STARTED abandonados e adapters reais.


## 2026-11-24 — Fila durável de sincronizações ERP/WMS

- Criada a migração 0083 com fila persistente e eventos append-only.
- Implementados enqueue idempotente, claims com `FOR UPDATE SKIP LOCKED`, lease token aleatório, fencing token monotónico, recuperação de lease expirado, heartbeat, retries e backoff.
- Criado worker independente `app.inventory_sync_worker`; adapters são carregados apenas por factories confiáveis de deployment.
- O orquestrador recebe um lease guard e valida/renova a posse na mesma transação que confirma cada página.
- Adicionados endpoints de enqueue, consulta e auditoria com isolamento por loja e política de autorização explícita.
- Adicionado serviço Docker Compose isolado para o worker.
- Corrigido teste da migração 0078: a expectativa anterior rejeitava indevidamente uma segunda associação com identificador/SKU/produto distintos. O teste passa agora a validar separadamente as três regras de unicidade.
- Ainda não existem adapters reais nem integração com gestor externo de segredos. CI e testes PostgreSQL desta fase aguardam validação.


## 2026-11-25 — Recuperação consistente de tentativas ERP/WMS abandonadas

- A auditoria identificou que a recuperação do lease já substituía o fencing token e protegia a fila, mas podia deixar a tentativa associada em `inventory_source_syncs` no estado `STARTED` após um encerramento abrupto.
- A função de claim agora finaliza essa tentativa na mesma transacção que regista a expiração e atribui o novo lease: estado `PARTIAL`, código `WORKER_LEASE_EXPIRED` e evento `COMPLETED` append-only.
- As contagens permanecem `NULL`, porque os snapshots não têm associação à tentativa transitória e não é seguro inferir quantas páginas foram confirmadas antes da interrupção.
- Adicionado teste de regressão SQLite que verifica a finalização do ledger, o incremento do fencing token e a rejeição de heartbeat do worker antigo.
- Documentação e TODO actualizados. **Os testes não foram executados nesta sessão** e ainda faltam os testes reais de concorrência/interrupção em PostgreSQL 16; não declarar a fase validada até à CI.


## 2026-11-25 — Smoke PostgreSQL 16 para concorrência e SIGKILL ERP/WMS

- Adicionado `apps/api/scripts/postgres_inventory_sync_job_smoke.py`, executado contra PostgreSQL 16 real no API CI.
- O smoke usa sessões independentes e uma barreira concorrente para provar que apenas um dos dois workers reclama o mesmo job.
- Verifica takeover após expiração, incremento do fencing token e rejeição de renovação pelo worker antigo.
- Inicia um processo worker separado, confirma a tentativa STARTED na base de dados, termina-o com SIGKILL e verifica que o worker de recuperação fecha o ledger como PARTIAL com `WORKER_LEASE_EXPIRED`, evento COMPLETED e contagens NULL.
- O smoke **não** simula ainda a morte após confirmação de uma página real nem o replay dos snapshots; essa validação permanece explicitamente pendente. O script e o novo passo de CI foram publicados, mas a execução do workflow deste HEAD ainda não foi observada nesta ronda.


## 2026-11-25 — SIGKILL após commit de página e replay idempotente ERP/WMS

- O smoke PostgreSQL foi aprofundado para executar o próprio `run_inventory_source_sync`, não apenas criar manualmente um ledger STARTED.
- O processo filho reclama o job e executa um adapter de teste. A primeira página é confirmada pelo orquestrador; só quando o adapter é chamado para obter a segunda página o processo sinaliza o processo pai. O pai verifica que o snapshot já existe e termina o worker com SIGKILL.
- O teste força a expiração do lease após a morte, reclama o job com outro worker e verifica a transição do ledger abandonado para PARTIAL/WORKER_LEASE_EXPIRED.
- O novo worker volta a executar o orquestrador com o mesmo external_reference e o mesmo conteúdo para a primeira página, seguido de uma segunda referência. O teste verifica que o snapshot original mantém o mesmo ID e quantidade e que existem exactamente dois snapshots, sem duplicação.
- Corrigida também a utilização de leases inválidos de 1 segundo no smoke anterior: a API de leases exige 30–3600 segundos. O teste usa 30 segundos e expira explicitamente a lease na base de dados, evitando esperas frágeis.
- O API CI já invoca este script no serviço PostgreSQL 16. O código e a integração foram publicados; a execução do workflow no novo HEAD ainda tem de ser confirmada. Não declarar a validação aprovada antes desse resultado.


### Reforço do cenário de fencing — tentativa de escrita pelo orquestrador

- O smoke passou a executar `run_inventory_source_sync` com as credenciais antigas do worker A depois de o worker B assumir o job.
- A tentativa é rejeitada pelo lease guard antes da criação de um novo ledger e antes de qualquer snapshot.
- O teste confirma em PostgreSQL que o número de snapshots e de ledgers para essa loja permanece zero. Assim, a prova já não se limita a testar heartbeat/renovação: cobre o limite de escrita usado pelo orquestrador.
- Esta alteração foi publicada no commit `c7b90ee`; continua pendente observar a execução verde do API CI.


## 2026-11-25 — Validação integral do worker durável ERP/WMS

- Confirmado o commit validado: `ffe76015e82d9d1ae608dc61a1bb5c9a9d8c710e`.
- API CI [45522939384](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45522939384): sucesso. O job executou as migrações e o smoke PostgreSQL 16 de concorrência, fencing, SIGKILL após commit de página e replay idempotente, seguido da suite da API.
- Quality Gates [45522939251](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45522939251): sucesso.
- Security Scans [45522939233](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45522939233): sucesso. O job OWASP ZAP concluiu o passive baseline e a importação OpenAPI com análise em modo seguro; Gitleaks e auditorias de dependências Web/Python também passaram.
- Docker Compose [45522939260](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45522939260): sucesso.
- Os quatro workflows estão concluídos com `success` no mesmo SHA. A falha anterior de `DetachedInstanceError` foi corrigida no teste, capturando os tokens antes do fecho da sessão SQLAlchemy; a lógica de produção não foi alterada nesta correcção.
- Próxima frente: auditoria técnica da reconciliação shelf/backroom/ERP, começando por proveniência, normalização de unidades, divergências, idempotência, isolamento multi-loja e trilho de auditoria. Adaptadores concretos continuam dependentes de especificações e homologação do fornecedor.


## 2026-11-25 — Isolamento multi-loja na reconciliação (teste publicado; CI pendente)

O HEAD anterior fb70ac8e98aa396cee3651a8341105333a343858 foi confirmado na branch main. Os quatro workflows GitHub Actions desse SHA passaram: API CI [45525868093](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45525868093), Quality Gates [45525868140](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45525868140), Security Scans [45525868155](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45525868155) e Docker Compose [45525868509](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45525868509).

Foi publicado no commit 07b141b91d2d76a6ff6e1cefe0e721cf42978e8b um teste HTTP que reutiliza o mesmo produto global em duas lojas, cria snapshots ERP/WMS distintos, persiste uma reconciliação em cada loja e verifica:
- os snapshots e quantidades devolvidos correspondem exclusivamente à loja consultada;
- o ledger filtrado por loja não devolve reconciliações da outra loja;
- a revisão por ID de uma reconciliação estrangeira devolve 404;
- a tentativa negada não altera o estado PENDING nem cria movimentos.

A alteração é apenas de teste; não modifica a lógica de produção. A execução dos workflows no novo SHA ainda tem de ser confirmada. A auditoria não considera esta prova isolada equivalente a uma matriz completa de endpoints, papéis e relações indirectas.

Ponto semântico ainda aberto: InventorySnapshot.source aceita ERP, WMS, POS, MANUAL e IMPORT, mas o campo genérico da reconciliação é apresentado como stock de retaguarda. Não foi feita alteração à seleção desse snapshot porque o contrato actual não define quais dessas fontes representam inequivocamente stock físico de retaguarda. Não converter esta incerteza numa regra inventada.


## 2026-11-25 — Auditoria de proveniência dos movimentos de inventário

- Inspeccionados `InventoryMovement`, `InventoryMovementRead` e `POST /api/v1/tasks/{task_id}/reconcile-inventory` na branch `main`.
- Confirmados os controlos já existentes: movimento único por tarefa/snapshot resultante, actor e motivo obrigatórios, origem WMS na localização configurada, estado AVAILABLE, política de frescura, dedução de reservas e de movimentos anteriores, e transacção conjunta para snapshot resultante, movimento e evento da tarefa.
- Identificada uma lacuna de proveniência: o destino físico não está congelado directamente no movimento; é inferido através da tarefa e da prateleira relacionada. A localização de origem é recuperável pelo snapshot, mas deve ficar explícita na leitura/auditoria.
- Clarificada uma distinção crítica: o snapshot `MANUAL` criado após reconciliação é uma projecção interna do movimento aprovado, não uma confirmação de actualização do WMS. A confirmação externa exige evidência WMS posterior correlacionada e reconciliação sem dupla contagem.
- Documentada a necessidade de movimentos compensatórios em vez de edição/eliminação de movimentos aprovados, unidade base explícita e teste PostgreSQL com transacções concorrentes reais.
- Actualizado `docs/INVENTORY-SOURCE-SYNC.md` no commit `b5f819e43b17dcc88ec1505cf462dfdfdb6ac392` e acrescentados os itens pendentes a `TODO.md`.
- **Limite desta passagem:** auditoria e documentação apenas. Não foram alterados modelos, migrations, endpoints ou testes; não foram executados testes nem CI para esta passagem.



## 2026-11-25 — Verificação das protecções existentes do Inventory Movement Ledger

- Revisão adicional das migrations `0052_inventory_movement_lineage_guard`, `0053_inventory_movement_append_only` e `0076_inventory_reconciliation_ledger` revelou protecções já implementadas que não estavam suficientemente distinguidas na auditoria anterior.
- `0052` valida na base de dados a relação entre tarefa, loja, produto, snapshots e conservação da quantidade do movimento.
- `0053` impede `UPDATE` e `DELETE` em `inventory_movements` na base de dados (PostgreSQL/SQLite). A imutabilidade do movimento aprovado não é, portanto, uma funcionalidade por começar.
- `0076` cria `inventory_reconciliation_events` append-only para decisões de revisão de divergências. Existe também `replenishment_task_events` para o ciclo da tarefa. Estes ledgers não representam ainda o ciclo de vida específico do movimento nem a confirmação externa WMS.
- O endpoint de reconciliação bloqueia a linha do produto e o snapshot WMS com `with_for_update()`. O bloqueio do produto serializa conservadoramente operações sobre o mesmo SKU. Continua em falta um smoke PostgreSQL que dispute o mesmo saldo com duas operações simultâneas.
- Corrigidos `docs/INVENTORY-SOURCE-SYNC.md` e `TODO.md` para preservar as implementações existentes e separar claramente o que falta.
- Commits: `df2f377555255bb9eca11e4f52a429bdf852aa86` (documentação técnica) e `7ca759af4ebaa3ca2eb6f907e28291dd30078d4d` (TODO).
- **Limite:** esta passagem foi de verificação e correcção documental. Não foram alterados modelos, migrations, endpoints ou testes; não foram executados testes nem CI.


## 2026-11-25 — UUID e proveniência congelada em InventoryMovement

- Criada a migration 0086_inventory_movement_identity_provenance: UUID individual por movimento, localização WMS de origem e ID da prateleira de destino.
- Os movimentos existentes recebem UUIDs individuais. A localização de origem é copiada do snapshot WMS imutável. O destino histórico permanece NULL, porque a relação actual da tarefa com a prateleira não prova a localização no instante da aprovação; novos movimentos congelam destination_shelf_id no momento da criação.
- Adicionados triggers de INSERT PostgreSQL e SQLite para exigir proveniência completa em novos movimentos e validar que a prateleira pertence à mesma loja. Para o backfill histórico, a migration suspende temporariamente os triggers 0053 conhecidos e recria-os exactamente antes de terminar; o teste de migração usa os nomes reais desses triggers e verifica que UPDATE/DELETE continuam bloqueados.
- O modelo SQLAlchemy, o endpoint de reconciliação e o contrato InventoryMovementRead foram actualizados.
- O teste HTTP de reconciliação verifica UUID e proveniência congelada; foi criado teste dedicado à migration e ao backfill histórico, incluindo preservação de trigger UPDATE preexistente.
- Commits de implementação: 1129295 (modelo), 72c78b0 (schema), 84f85bc (endpoint), ded06a2 (teste HTTP), 6a9e629 (migration), 5e92563 (teste migration), 9ed6683 (alinhamento do índice ORM).
- Validação pendente: não foram executados testes localmente nesta sessão. A execução GitHub Actions para o HEAD resultante tem de ser consultada antes de declarar a alteração aprovada.


## 2026-11-25 — Falha detectada e correcção no backfill 0086

- O API CI no commit `d248723eb7832265b0b0bca0b3639a77c8bbb2b1` executou com PostgreSQL 16.16: as migrations Alembic, incluindo 0086, passaram no smoke de migrações.
- A suite terminou com **1 falha, 1679 aprovados e 1 ignorado**. A falha estava no teste SQLite da migration: o UPDATE de backfill referia `:destination_shelf_id`, mas o dicionário de parâmetros não fornecia esse valor.
- Corrigido em `ee68ab2bf41b7571833018d3928e7b32cd5a76b1`: o backfill passa explicitamente `destination_shelf_id = NULL`, preservando a decisão de não inferir destinos históricos.
- A execução anterior confirma que a migration PostgreSQL sobe; ainda não confirma a suite completa nem os triggers de proveniência da migration 0086 em PostgreSQL. A validação integral permanece pendente até nova CI.
- O ledger de eventos ainda não foi iniciado; fica bloqueado até a suite corrigida passar.


## 2026-11-25 — Correcção do fixture SQLite da migration 0086

- A nova execução de Quality Gates terminou com 1 falha, 1679 testes aprovados e 1 ignorado. A falha não ocorreu no backfill nem no PostgreSQL: o teste isolado SQLite criava `inventory_movements` sem a coluna `product_id`, embora o modelo real e a tabela de produção a contenham.
- O trigger 0086 consulta `NEW.product_id` para confirmar a coerência entre movimento, tarefa e snapshot. SQLite devolveu `no such column: NEW.product_id` antes de avaliar a rejeição esperada do movimento inválido.
- Corrigido o fixture para reproduzir o esquema real: `product_id` passa a existir e é preenchido nos movimentos históricos e nas inserções de teste. A regra de produção mantém-se inalterada.
- Esta correcção é exclusivamente de teste. A validação PostgreSQL 16 continua pendente na execução API CI; não declarar a migration integralmente validada até a suite completa e os workflows relevantes passarem.


## 2026-11-25 — Ledger de eventos de movimentos: fase 1

- Estado inicial: `main`, HEAD `1eb4125368a89e428256be0c62d8cf76cf48d9f1`.
- Migration 0086: API CI/PostgreSQL 16 passou no SHA de código `1a1648c0528e15b9ffc8d180aa4c00248f915963` (run 45607172994). Quality Gates e Security Scans passaram no HEAD documental `1eb4125368a89e428256be0c62d8cf76cf48d9f1` (runs 45607186390 e 45607186450). Docker Compose passou no SHA `1a1648c0528e15b9ffc8d180aa4c00248f915963` (run 45607173121). Vercel permanece com `build-rate-limit`.
- Implementada migration 0087 e tabela append-only `inventory_movement_events`, com validação DB da identidade de operação, loja, actor e motivo.
- Reconciliação grava `MOVEMENT_RECORDED` na mesma transacção do movimento, snapshot resultante e evento da tarefa.
- Adicionado endpoint read-only com RBAC ADMIN/SUPERVISOR e ocultação de IDs cross-store.
- Testes acrescentados para leitura, autorização, isolamento multi-loja, rollback e guards SQLite.
- **Validação desta implementação pendente:** CI no novo SHA. Não foram executados testes localmente pelo conector.
- Próxima acção: verificar API CI, Quality Gates, Security Scans e Docker Compose; corrigir qualquer falha antes da confirmação WMS. Unidade/caixa/palete permanece por definir e depende do contrato operacional.


## 2026-11-25 — Validação inicial do ledger de movimentos e hardening PostgreSQL

- Commit de implementação fase 1: `5bacdf429de11f97d619c775bcdfaba9b5154154`.
- API CI/PostgreSQL 16: run 45610114252 — **1684 passed, 1 skipped**, migration 0087 e todos os smokes existentes concluídos com sucesso.
- Quality Gates: run 45610177910 — sucesso.
- Security Scans: run 45610177856 — sucesso.
- Docker Compose: run 45610114012 — sucesso.
- Vercel permanece condicionado pelo `build-rate-limit`; não foi feito deploy nem alteração de produção.
- A validação inicial não exercitava directamente os triggers de eventos em PostgreSQL. Foi iniciado um reforço do smoke `postgres_inventory_movement_lineage_smoke.py` para validar leitura do evento, operação/tenant, evento posterior com actor/motivo próprios, rejeição de operação divergente e protecção append-only.
- A migration 0087 foi ajustada para validar actor/motivo contra o movimento apenas no evento inicial MOVEMENT_RECORDED; eventos posteriores mantêm a identidade da operação/loja, mas podem registar actor e motivo próprios.
- **Estado deste reforço:** código e teste actualizados; CI do novo SHA pendente.


### Correcção do smoke PostgreSQL — autenticação de produção

A primeira execução do novo smoke (API CI run 45611398632) falhou porque a leitura dos eventos foi executada depois de restaurar `APP_ENV=test`. Nesse modo, o middleware de autenticação é intencionalmente ignorado e o contexto `request.state.user_id` não é preenchido. O smoke já executava a reconciliação em modo production, mas a leitura não estava dentro do mesmo contexto. A leitura foi movida para dentro do bloco production, mantendo a restauração da configuração em `finally`. A falha era do harness de teste, não de uma autorização permissiva no endpoint. Novo API CI pendente.


## 2026-11-25 — Smoke concorrente da reconciliação de movimentos

- SHA inicial desta retoma: `0a7ef9edf8ddc2f2174ed19927d86a0b6899e93c` (main).
- Confirmei que a main já contém migration 0086, ledger 0087, endpoint de leitura de eventos e smoke PostgreSQL de proveniência. A validação anterior do ledger (1684 passed, 1 skipped) pertence ao SHA `5bacdf429de11f97d619c775bcdfaba9b5154154`; não foi atribuída ao HEAD actual.
- O API CI do SHA inicial executou migrations PostgreSQL 16 e o smoke de proveniência com sucesso; a suite API e Quality Gates/Security Scans ainda estavam em execução durante esta ronda. Docker Compose terminou com sucesso.
- Detectada lacuna de prova: a reconciliação usa lock do produto e do snapshot WMS, mas não existia smoke dedicado que disputasse o mesmo saldo através de dois pedidos HTTP concorrentes.
- Criado `apps/api/scripts/postgres_inventory_movement_concurrency_smoke.py`: duas tarefas do mesmo SKU disputam seis unidades disponíveis (7 on-hand menos 1 reservada), cada uma pede quatro; apenas uma pode gerar movimento. Verifica snapshot resultante, reserva preservada, ledger e retry idempotente.
- Integrado o script em `.github/workflows/api-ci.yml`.
- Actualizados README, TODO, ROADMAP e `docs/architecture/inventory-movement-event-ledger.md`.
- Commits publicados directamente em main: `041737d1e473da5281e42911275b3d5cf29cf39d`, `4d5e686235adcc82632f6cd702ec2044b218feec`, `8b6b8d41880eba4caf5967cbeaff7d91cd40b536`, `7dafdde7c3b3cb565178a85d87d9f1916822f4b6`, `d60c4c1a9cde3a552d5abb9f3dc0680ddf5dc82d`, `bfe189481d571135566f73d344def49a12a0ea36`.
- Testes locais: não executados; o conector GitHub não disponibiliza shell/ambiente local nesta sessão.
- Validação do novo SHA: pendente. Os workflows anteriores ao smoke não validam este novo script.
- Próxima acção: acompanhar API CI PostgreSQL 16; corrigir imediatamente qualquer falha. Depois acrescentar rollback real PostgreSQL para falha de inserção do evento, antes de avançar para unidades logísticas ou confirmação WMS.


### Reforço do smoke — rollback transaccional PostgreSQL

- Expandido o smoke concorrente com um segundo cenário isolado: injecção temporária de falha de integridade (SQLSTATE 23514) antes da inserção do evento.
- A API tem de devolver conflito e reverter movimento, snapshot MANUAL resultante e evento `INVENTORY_RECONCILED`; o evento de movimento anterior permanece intacto.
- O trigger/função temporários são removidos num bloco `finally`, sem alterar o esquema persistente.
- Commit: `670f656591ba2652994355776a2390c919ddbc31`.
- Validação PostgreSQL 16 deste reforço ainda pendente; o run anterior só executou a versão sem este cenário.


## 2026-11-25 — Migration 0088: origem WMS AVAILABLE obrigatória

- A auditoria à migration 0086 detectou que o trigger aceitava qualquer snapshot WMS com localização correcta, mesmo se `availability_status` fosse `UNAVAILABLE` ou `UNKNOWN`. A API já rejeitava esses estados, mas a base de dados não protegia o mesmo invariante contra INSERT directo.
- Criada a migration `0088_inventory_movement_available_source_guard`, que substitui o trigger PostgreSQL/SQLite e exige `source.availability_status = 'AVAILABLE'` para movimentos novos.
- O downgrade restaura exactamente a regra anterior da 0086. Os movimentos/snapshots históricos não são alterados.
- Criado teste SQLite para AVAILABLE, UNAVAILABLE, UNKNOWN e downgrade.
- O smoke PostgreSQL foi alargado com INSERT directo cuja linhagem, tarefa, quantidade e snapshot resultante são coerentes, mas cuja origem está UNAVAILABLE; deve falhar especificamente no guard 0088.
- A migration e o smoke estão publicados; validação no PostgreSQL 16 e workflows do SHA actual ainda pendentes.


## 2026-11-25 — Migration 0089: unidade base e quantidade exacta

- A auditoria confirmou que `Product.unit` já é a unidade base usada pelo cálculo de embalagens. A implementação passa a congelar esse código em cada novo movimento, sem escolher uma unidade global nem inferir dados históricos.
- Migration `0089_inventory_movement_base_unit_snapshot`: coluna `unit_code` nullable para compatibilidade histórica e trigger PostgreSQL/SQLite que exige correspondência exacta com `products.unit` nos novos INSERTs.
- `InventoryMovement.quantity` passou a estar tipado como Decimal. A API mantém o campo numérico `quantity` e acrescenta `quantity_exact`; a evidência `MOVEMENT_RECORDED` inclui quantidade exacta e unidade.
- A reconciliação rejeita quantidades com mais de três casas decimais, de acordo com `NUMERIC(12,3)`; não arredonda nem altera silenciosamente a quantidade física.
- A interface deixou de somar quantidades de SKUs com unidades incompatíveis e apresenta a unidade de cada movimento. Movimentos históricos sem prova mantêm unidade desconhecida.
- Testes acrescentados: migration SQLite, produto em kg com quantidade 2.375, rejeição de 1.2345, unidade vazia e guard PostgreSQL para unidade incompatível.
- Validação do SHA actual ainda pendente. Não declarar migration 0089 concluída até CI/PostgreSQL/TypeScript/build verde.


### Correcção de precisão — validação antes da persistência da tarefa

- A primeira validação da migration 0089 detectou que `actual_quantity` era arredondada pelo tipo Numeric da tarefa antes de chegar à reconciliação. A validação apenas no endpoint de reconciliação era tardia.
- A validação foi movida também para `ReplenishmentTaskStatusUpdate`: quantidades com mais de três casas decimais são rejeitadas com HTTP 422 antes de marcar a tarefa como COMPLETED ou persistir a quantidade.
- Mantida a validação defensiva na reconciliação para dados legados ou operações internas.
- Teste actualizado para provar que a tarefa permanece IN_PROGRESS e sem `actual_quantity` após a tentativa inválida.
- Commits: `390364547a881faba586515dd3c59a037439fbac`, `d603bf6b2bd012fa9175751162d947c25100dca6`.
- O run Quality Gates do SHA anterior encontrou 1 falha neste cenário (1688 passed, 1 skipped); o novo SHA com a validação antecipada aguarda nova execução.


## Validação final — 25/11/2026

### Estado GitHub
- Branch: `main`.
- SHA de código validado: `d603bf6b2bd012fa9175751162d947c25100dca6`.
- SHA de documentação/estado operacional: `3a9d2ea1e5a1036b30ab03b6debc4a420d1d0ddd` (antes desta actualização final).
- As alterações posteriores ao SHA de código foram apenas documentação/estado operacional; não alteraram código ou migrations.

### Resultados confirmados
- API CI — run `45616138752`, sucesso: migration PostgreSQL, smoke de proveniência, smoke concorrente com reservas/retry/rollback e suite API.
- Suite API — `1689 passed, 1 skipped` em 156.89s no API CI.
- PostgreSQL 16 — migration 0089 aplicada; smoke de movimentos validou rejeição de origem WMS UNAVAILABLE, unidade incompatível, concorrência, reserva preservada, retry idempotente e rollback atómico.
- Docker Compose smoke — run `45616138577`, sucesso.
- Quality Gates — run `45616228212`, sucesso no SHA `3a9d2ea1e5a1036b30ab03b6debc4a420d1d0ddd`; TypeScript/build e suite API aprovados.
- Suite API nos Quality Gates — `1689 passed, 1 skipped` em 161.98s.
- Security Scans — run `45616228147`, sucesso no SHA `3a9d2ea1e5a1036b30ab03b6debc4a420d1d0ddd`; auditorias de dependências, secret scan e ZAP passive baseline aprovados.
- A primeira execução do teste de precisão encontrou uma falha real de desenho: a coluna da tarefa arredondava antes da reconciliação. A validação foi antecipada para o schema de conclusão da tarefa; o teste passou no SHA validado.

### Estado das tarefas
- Migration 0086/0087: identidade/proveniência e ledger confirmados.
- Smoke concorrente: concluído e validado.
- Migration 0088: origem WMS tem de estar explicitamente AVAILABLE; validada.
- Migration 0089: unidade base congelada por movimento e quantidade Decimal exacta; validada.
- Histórico: movimentos antigos mantêm `unit_code=NULL`; não foi inventada unidade retroactiva.
- Não há conversões automáticas entre unidade, caixa e palete.

### Próxima acção obrigatória
Auditar `packaging_units.py` e o endpoint `/api/v1/warehouse/replenishment-units`: manter os campos numéricos existentes por compatibilidade, acrescentar representações Decimal exactas para quantidades e factores de embalagem, e testar UNIT/CASE/PALLET, embalagem aberta, excesso e quantidades fraccionárias.


## 2026-11-25 — Planeamento UNIT/CASE/PALLET com Decimal exacto

- O módulo `app.packaging_units` já calculava internamente com Decimal, mas convertia os resultados para float na fronteira da API. Acrescentados campos textuais exactos para quantidade necessária, factor de embalagem, unidades soltas, quantidade planeada e excesso; os campos numéricos existentes mantêm-se para compatibilidade.
- O endpoint `/api/v1/warehouse/replenishment-units` recebe agora `required_base_units` como Decimal e devolve `base_units_per_package_exact`.
- Testes de serviço cobrem 20.125 unidades base em embalagem CASE de 12.000: caixa aberta (1 caixa + 8.125 soltas) e caixa fechada (2 caixas, 24.000 planeadas, 3.875 de excesso).
- Teste API cobre UNIT, CASE e PALLET e confirma que `automatic_stock_movement_allowed=false`.
- API CI run `45617926240`: sucesso; PostgreSQL migrations e smokes concluídos; `1691 passed, 1 skipped` em 156.30s.
- Quality Gates run `45617926218`: sucesso; Web TypeScript/production build e suite API; `1691 passed, 1 skipped` em 125.53s.
- Docker Compose smoke run `45617926384`: sucesso.
- Security Scans run `45617926360`: sucesso; dependency audits, secret scan e ZAP passive baseline aprovados.
- Próxima prioridade: integrar as quantidades de embalagem nas recomendações/tarefas de reposição, preservando o princípio de que o planeamento não reserva nem movimenta stock sem autorização e confirmação explícitas.


## 2026-11-25 — Correcção CI: quantidades fraccionárias na exposição (migration 0090)

- O CI no SHA `62ad03d28f0157bdba2919e9f736d92e677768ac` revelou 1 falha em 1694 testes: `test_replenishment_plan_includes_read_only_packaging_options_for_unit_case_and_pallet` enviava `target_quantity=20.125` para um schema INTEGER e recebia HTTP 422. O mesmo erro surgiu no API CI e nos Quality Gates; o workflow de segurança e Docker Compose passaram.
- A causa era uma inconsistência de domínio: produtos em kg podiam ter movimentos/snapshots decimais, mas o alvo e o mínimo de exposição permaneciam INTEGER.
- Implementados modelo SQLAlchemy Decimal/Numeric(12,3), schema Pydantic Decimal com limite de precisão, migration 0090 e downgrade que recusa truncar valores fraccionários.
- Regressão API agora valida alvo 20.125 e mínimo 0.375; teste de migration cobre conversão, preservação decimal e bloqueio de downgrade destrutivo.
- Validação da migration 0090 e suite completa ainda pendente nos workflows do HEAD final. Não declarar a correcção concluída até API CI/PostgreSQL 16 e Quality Gates passarem.


## 2026-11-25 — Compatibilidade JSON das quantidades de exposição

- A primeira execução da suite após a migration 0090 encontrou três regressões de contrato: o schema Pydantic serializava Decimal como string (`"12.000"`) em vez de número JSON e a validação de `target_quantity=0` tentava serializar um Decimal dentro do detalhe de erro.
- Corrigido o contrato HTTP para continuar a aceitar/devolver números JSON; o endpoint converte explicitamente os valores validados para Decimal antes da persistência. O modelo SQL mantém Numeric(12,3), sem perder a precisão armazenada.
- O validador rejeita NaN/Inf, mais de três casas decimais e valores acima da capacidade Numeric(12,3), evitando quantização ou truncagem.
- A primeira suite API reportou 3 falhas e 1694 testes aprovados; estas falhas foram analisadas e corrigidas nos commits `dc242cf`, `76a6fb9` e `e2eca8f`. A validação do novo HEAD está pendente; não marcar como concluído até nova CI verde.


## Validação final — unidade base e quantidades de exposição (25/11/2026)

- SHA de código validado: `dda035f509a34f4d893f52d2d3cf4aa2c440f0e6` (branch `main`).
- API CI run `45625120737`: sucesso. PostgreSQL 16, migrations até 0090, smokes de proveniência, concorrência e recuperação; suite **1697 passed, 1 skipped** em 114.38s.
- Quality Gates run `45625120955`: sucesso. TypeScript/build Web e suite **1697 passed, 1 skipped** em 116.43s.
- Docker Compose smoke run `45625120891`: sucesso.
- Security Scans run `45625120718`: sucesso; Python/Web dependency audits, Git history secret scan e OWASP ZAP passive baseline.
- A primeira regressão de API por serialização Decimal foi corrigida mantendo o contrato JSON numérico; a primeira regressão do teste de plano era apenas uma chave de fixture incorrecta (`tasks`, não `items`) e foi alinhada com o contrato real da API.
- Migration 0090 converte os dois campos de exposição para Numeric(12,3), preserva os valores históricos inteiros e bloqueia downgrade destrutivo quando existem fracções.
- O endpoint de reposição mantém a quantidade sugerida e o plano UNIT/CASE/PALLET; o teste confirma 20.125 kg, mínimo 0.375 kg, factores exactos e ausência de reserva/movimento automático.
- A actualização seguinte deste ficheiro é documental; não altera código ou migrations.

### Próxima prioridade técnica
Auditar a reconciliação de reservas WMS. O modelo actual recebe `reserved_quantity` agregado por snapshot WMS e calcula disponível como físico menos reservado; não existe ainda um ledger interno de reservas com identificador externo por reserva. Não criar reservas locais fictícias nem assumir que uma tarefa de reposição reserva stock no WMS. Determinar primeiro quais os dados que o contrato do adapter pode fornecer; avançar com validações de consistência e alertas baseados em snapshots enquanto não existir contrato de detalhe de reservas.


## 2026-11-25 — Precisão exacta do físico e reservado nos snapshots

- A auditoria do fluxo de reservas confirmou que adapters ERP/WMS já validam físico e reservado como Decimal com escala Numeric(12,3), mas o endpoint directo `POST /api/v1/inventory/snapshots` aceitava float sem validar escala. Isso podia arredondar silenciosamente uma reserva ou saldo físico no Numeric.
- O schema agora rejeita mais de três casas decimais e valores não finitos; o modelo declara ambos os campos como Decimal e a rota converte explicitamente os números HTTP com `Decimal(str(...))`.
- Teste API acrescentado: snapshot com 10.125 kg físico e 2.375 kg reservado é persistido exactamente; escala 4 em qualquer campo recebe HTTP 422 e não cria snapshot.
- Semântica: o reservado continua agregado e autoritativo pelo WMS na localização configurada. O sistema não cria reservas externas e uma tarefa não reserva stock. Não existe ainda identificador externo por reserva/documento/linha; a reconciliação individual fica dependente do contrato real do fornecedor.
- Validação CI do novo SHA pendente. Não declarar esta tarefa concluída antes de API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose.


## Validação final — snapshots físicos e reservas WMS (25/11/2026)

- SHA de código validado: `900c24f19f47e6720da64775d6904692e104c35f`; documentação operacional posterior no SHA `bc37246a298f3cfe2ae142ea9051cb70beac1e22`. A alteração posterior à validação de código foi apenas documental.
- API CI run `45626116643`: sucesso; PostgreSQL 16, migrations e 48 smokes, suite **1698 passed, 1 skipped** em 168.66s.
- Quality Gates run `45626178152`: sucesso; TypeScript/build Web e suite **1698 passed, 1 skipped** em 111.98s.
- Docker Compose smoke run `45626116401`: sucesso.
- Security Scans run `45626178472`: sucesso; dependency audits, secret scan e OWASP ZAP passive baseline.
- Teste novo confirma persistência Decimal exacta de 10.125 kg físico e 2.375 kg reservado, e HTTP 422 para escala superior a três casas decimais em qualquer campo.
- O endpoint directo de snapshots e o adapter normalizado aplicam agora o mesmo contrato Numeric(12,3). O cálculo disponível continua a ser físico menos reservado.
- Não existe ledger de reservas individuais nem contrato WMS de reserva por ID/documento/linha. A plataforma não simula reservas: uma tarefa de reposição não reserva stock. A próxima auditoria deve manter a reconciliação agregada por loja/SKU/localização e só evoluir para detalhe quando o fornecedor o disponibilizar.


## Validação final — precisão física e reservas agregadas WMS (25/11/2026)

- SHA de código validado: `900c24f19f47e6720da64775d6904692e104c35f`; documentação operacional posterior: `bc37246a298f3cfe2ae142ea9051cb70beac1e22`. Os commits posteriores ao SHA de código são exclusivamente documentais.
- API CI run `45626116643`: sucesso; migrations PostgreSQL 16, 48 smokes e **1698 passed, 1 skipped** em 168.66s.
- Quality Gates run `45626178152`: sucesso; TypeScript/build Web e **1698 passed, 1 skipped** em 111.98s.
- Docker Compose smoke run `45626116401`: sucesso.
- Security Scans run `45626178472`: sucesso; auditorias Python/Web, secret scan e OWASP ZAP passive baseline.
- O endpoint directo de snapshots agora rejeita precisão superior a três casas decimais em stock físico ou reservado. A persistência recebe Decimal explícito e preserva valores como 10.125 e 2.375 sem arredondamento silencioso.
- O teste API valida a persistência exacta e confirma que quantidades inválidas não criam snapshots.
- Reservas: o WMS continua a ser a fonte do total reservado por snapshot/localização; o sistema calcula disponível como físico menos reservado. Não existe detalhe de reserva individual fornecido pelo contrato actual, pelo que não é criado ledger local fictício nem se considera uma tarefa como reserva.


## 2026-11-25 — Conversões logísticas: precisão sem arredondamento silencioso

- A auditoria encontrou uma lacuna real: ProductPackagingLevelCreate recebia base_units_per_package como float, enquanto a coluna é NUMERIC(14,3). Factores com mais de três casas podiam ser arredondados pela base de dados sem rejeição explícita.
- O contrato passa a receber Decimal, rejeita factores com escala superior a três casas e o modelo ORM declara o campo como Decimal.
- O cálculo de embalagens valida também a escala da quantidade necessária, do factor e do resultado convertido, alinhando o domínio com a precisão NUMERIC(12,3) das quantidades de inventário.
- Testes adicionados: factor 12.125 aceite e preservado; factor 12.1254 rejeitado com HTTP 422 e sem registo; funções puras rejeitam quantidade/factor/resultados com precisão não suportada.
- Não foi necessária migration: a coluna já era NUMERIC(14,3); a falha estava na validação de entrada e na tipagem do contrato.
- API CI 45637232222: sucesso, PostgreSQL 16 e smokes; suite **1702 passed, 1 skipped** em 108.37s.
- Quality Gates 45637232143: sucesso, TypeScript/build Web e suite **1702 passed, 1 skipped**.
- Security Scans 45637232196: sucesso; auditorias de dependências, Gitleaks e OWASP ZAP passive baseline.
- Docker Compose 45637232943: sucesso.
- Commits de implementação/testes: 55e29d6, b13d1a6, 2b2b232.
- Limite: isto fecha a conversão logística interna. O mapeamento das unidades/códigos externos WMS continua dependente do contrato do fornecedor. A reconciliação multi-localização não deve somar snapshots até serem definidas a elegibilidade das localizações e a semântica das reservas.


## 2026-11-25 — Ledger de contagens manuais

O commit `50fc1fcd9dac4c88dfb800aaa1f690ff1c0b6304` introduz o endpoint transaccional e o revision Alembic `0091_inventory_manual_count_audit`, com parent confirmado `0090_shelf_product_decimal_quantities`. Para `source=MANUAL`, exige actor activo ADMIN/SUPERVISOR e motivo; o snapshot e o evento são persistidos com flush e um commit. A tabela de eventos tem FK composta para snapshot/loja/produto e triggers PostgreSQL/SQLite para imutabilidade e validação de proveniência. Foram acrescentados testes HTTP/DB para RBAC, motivo, atomicidade, rollback, imutabilidade e associação entre loja/produto. A validação local e CI/PostgreSQL 16 permanece pendente.


## 2026-11-25 — Hardening adicional do ledger MANUAL (0091)

- Branch: `main`.
- HEAD de implementação: `ecc751c1517cbd64bc774075a7131eb6e10f0f1f` (teste HTTP para actor inactivo); commit anterior `94fe02723e6621b6a4a682b912cf76a03f96d04a` corrige o trigger SQLite.
- A revisão da migration 0091 detectou assimetria: PostgreSQL exigia `users.is_active`, mas o trigger SQLite aceitava um actor inactivo e não limitava explicitamente o papel a ADMIN/SUPERVISOR.
- Corrigido o predicado SQLite para exigir actor activo e (ADMIN global ou SUPERVISOR da loja do evento).
- Acrescentada regressão API que confirma HTTP 401 para supervisor inactivo; a cobertura existente mantém os casos sem actor, EMPLOYEE, motivo inválido, atomicidade e rollback.
- Testes locais: não executados neste ambiente. A suite API usa `Base.metadata.create_all`; por isso não prova, por si só, a execução dos triggers da migration 0091.
- CI: ainda não confirmada para os commits desta ronda. Os estados Vercel anteriores são `build-rate-limit` e não representam os workflows GitHub.
- Próxima acção obrigatória: localizar/acrescentar teste de migration que execute efectivamente 0091 em SQLite, validar upgrade/downgrade e trigger de actor inactivo; depois confirmar API CI PostgreSQL 16 e os restantes workflows. Só então fechar a prioridade e avançar para a revisão seguinte do ledger de movimentos.


## 2026-11-25 — Testes reais da migration 0091

- HEAD actual registado durante a actualização: `c6b2d3369e44276cbb9b5fcc91d204b4b9ff807b` (branch `main`).
- Acrescentado `apps/api/tests/test_inventory_manual_count_audit_migration.py`: aplica a migration 0091 num SQLite isolado e testa proveniência, actor activo, papel, isolamento por loja, origem MANUAL, append-only e downgrade sem perda dos snapshots.
- Acrescentado `apps/api/scripts/postgres_inventory_manual_count_audit_smoke.py` e integrado no workflow API CI.
- Evidência: o PostgreSQL 16 executou `alembic upgrade head` com sucesso no run API CI do SHA `3b9520d`. O smoke PostgreSQL específico passou no run do SHA `7a20c95`, confirmando SUPERVISOR activo da loja e ADMIN global, rejeição de actor inactivo/EMPLOYEE/outra loja/origem não-MANUAL e imutabilidade do evento.
- A primeira execução do smoke revelou dois erros do próprio teste de integração (auth middleware em APP_ENV=test e expectativa duplicada de evento); ambos foram corrigidos e a execução posterior do smoke passou.
- A execução seguinte chegou a falhar num smoke preexistente de autorização multi-loja: o pedido MANUAL estrangeiro não continha `reason`, pelo que o schema devolvia 422 antes de testar a autorização esperada (403). Corrigido o payload com motivo válido em `c6b2d33`.
- Teste SQLite da migration e suite completa ainda não foram confirmados no HEAD final. O run após a correcção está pendente.
- Próxima acção: verificar API CI do HEAD, corrigir falhas com evidência; confirmar Quality Gates, Security Scans e Docker Compose. Só depois fechar 0091 e avançar para a auditoria P1 de snapshots/reservas WMS.


## 2026-11-25 — Migration 0091 homologada em SQLite e PostgreSQL 16

- HEAD validado: `c4f839bcfd076c2b5575eccfd314fae96983b3ed` na branch `main`.
- O teste `test_inventory_manual_count_audit_migration.py` executou a revisão 0091 directamente em SQLite, incluindo upgrade/downgrade, provenance guard, actor activo, papéis, isolamento multi-loja, origem MANUAL e append-only.
- O smoke `postgres_inventory_manual_count_audit_smoke.py` passou em PostgreSQL 16. O endpoint autenticado aceitou SUPERVISOR activo da loja e ADMIN global; INSERTs directos rejeitaram actor inactivo, EMPLOYEE, supervisor de outra loja e snapshot WMS; UPDATE/DELETE foram bloqueados.
- API CI run `45650155916`: sucesso; migration PostgreSQL 16, smokes de autorização/proveniência e suite **1707 passed, 1 skipped**.
- Quality Gates run `45650155829`: sucesso.
- Security Scans run `45650155800`: sucesso.
- Docker Compose smoke run `45650155946`: sucesso.
- Corrigidos os fixtures de regressão que ficaram desactualizados quando o motivo e o actor passaram a ser obrigatórios para source=MANUAL. A suite completa confirmou **1707 passed, 1 skipped**.
- Prioridade P0 da migration 0091 concluída. Próxima prioridade: rever semântica temporal de snapshots WMS, reservado agregado e mudanças de localização sem inventar detalhe de reservas que o adapter não fornece.


## 2026-11-25 — Proveniência de snapshots WMS/ERP por execução

- Merge na `main`: `76fb62dfef9280fd8e6b291024be46a9e392e848` (PR #13).
- Migration `0092_inventory_snapshot_sync_lineage`: coluna nullable `inventory_snapshots.source_sync_id`, índice, FK RESTRICT em PostgreSQL e trigger de proveniência em ambos os motores.
- O orchestrator define `source_sync_id=sync.id` em cada snapshot persistido. O trigger só aceita execução existente, da mesma loja/origem e ainda em STARTED; a imutabilidade dos snapshots impede alteração posterior do vínculo.
- A API de leitura expõe o identificador. Snapshots antigos e MANUAL mantêm NULL, sem backfill inventado.
- Replay após SIGKILL: a página já commitada mantém ligação à execução PARTIAL original; apenas páginas novas ficam ligadas à nova execução SUCCESS. O smoke PostgreSQL confirma também rejeição de novas inserções associadas a execução terminal.
- Teste de migration SQLite, teste de integração WMS e smoke PostgreSQL 16 passaram.
- Evidência no branch SHA `f63543caabe6df1a2e660f5801c35f53fc3422a1`: API CI **1715 passed, 1 skipped**, Quality Gates sucesso, Security Scans sucesso, Docker Compose sucesso.
- Workflows do commit de merge `76fb62d` na `main` estavam queued no momento desta actualização; confirmar conclusão antes de declarar a integração final totalmente validada.
- Próxima prioridade: comparar timestamps ERP/WMS. A classificação actual permite DIVERGENCE se ambas as fontes forem CURRENT, sem um limite explícito de skew entre capturas. Definir política de skew por loja/fonte e estado TEMPORAL_SKEW sem assumir um limite comercial.


## 2026-11-25 — Estado final confirmado na main

- Código integrado: `76fb62dfef9280fd8e6b291024be46a9e392e848`.
- API CI `45654043683`: sucesso, **1715 passed, 1 skipped**.
- Quality Gates `45654278572`: sucesso.
- Security Scans `45654278738`: sucesso.
- Docker Compose `45654043988`: sucesso.
- O check Vercel mantém `build-rate-limit`; não afecta a validade dos workflows GitHub acima.
- Próxima análise: skew temporal ERP/WMS. Não aplicar limite arbitrário; a tolerância deve ser configurada por política operacional antes de alterar a classificação de divergência.


## 2026-11-25 — Confirmação final pós-merge

- Main code commit: `76fb62dfef9280fd8e6b291024be46a9e392e848`.
- Main documentation head at this update: `d634f85dd7cb7bb6bb5c09120edefe52efaf2ce2`.
- API CI run `45654043683`: success, **1715 passed, 1 skipped**.
- Quality Gates run `45654278572`: success.
- Security Scans run `45654278738`: success.
- Docker Compose smoke run `45654043988`: success.
- Vercel check: one project check is success; the other still reports `build-rate-limit`. This is external build quota, not a GitHub CI failure.


## 2026-11-25 — Fecho da regressão de referência inexistente (0092)

- Acrescentado caso SQLite que tenta inserir snapshot com `source_sync_id` inexistente; o trigger rejeita-o com erro de proveniência, mesmo sem FK SQLite física.
- HEAD de código validado: `f7430342a9e52f9d269dd567c23719790fe638a0`.
- API CI `45655823242`: sucesso, **1715 passed, 1 skipped**.
- Quality Gates `45655823075`, Security Scans `45655823227` e Docker Compose `45655823263`: sucesso.
- A migration 0092 fica validada também para referência inexistente; a linha temporal do replay continua preservada.


## 2026-11-25 — Política conservadora de skew temporal ERP/WMS (migration 0093)

- Tolerância opcional `comparison_skew_tolerance_minutes` na política ERP por loja; NULL significa não configurada, sem limite inventado.
- A reconciliação expõe `erp_wms_capture_skew_seconds`. Sem tolerância, timestamps diferentes produzem `TEMPORAL_SKEW_UNCONFIGURED`; acima do limite produzem `TEMPORAL_SKEW`. Ambos mantêm o delta quantitativo NULL.
- Só capturas dentro da tolerância permitem IN_SYNC/DIVERGENCE. Zero exige timestamps coincidentes.
- Alterações auditadas na mesma transacção, com actor, valores anterior/novo, motivo e timestamp.
- Migration 0093 acrescenta constraints PostgreSQL e triggers SQLite para restringir a tolerância à política ERP e ao intervalo 0–10080.
- Testes adicionados para estado não configurado, limite zero, dentro do limite, validação de origem/motivo, auditoria e migration SQLite.
- SHA de código validado: `b54b2d4c927aee606f23fef35018b701c17aaf5f`.
- API CI `45677287479`: PostgreSQL 16/migrations/smokes e suite API — **1717 passed, 1 skipped**.
- Quality Gates `45677287381`: sucesso (Python/API, TypeScript e build Web).
- Security Scans `45677287568`: sucesso (auditorias Python/Web, Gitleaks e ZAP passive baseline).
- Docker Compose `45677287570`: sucesso.
- Os quatro workflows passaram no mesmo SHA. Não foram executados testes localmente; a validação foi feita por GitHub Actions.
- Próxima prioridade: auditar monotonicidade temporal e snapshots WMS consecutivos, reservas agregadas e mudanças de localização; não criar ledger de reservas individuais sem contrato do fornecedor.



## 2026-11-25 — Isolamento de localização WMS e snapshots recebidos fora de ordem

- Adicionada regressão HTTP para mudança auditada da localização WMS: os snapshots da localização anterior deixam de ser elegíveis e não existe fallback quando a nova localização ainda não tem evidência.
- Adicionada regressão para chegada tardia de snapshot: um registo com `captured_at` mais antigo é preservado no histórico, mas não substitui o snapshot temporalmente mais recente da localização autorizada.
- O teste confirma que a disponibilidade continua a ser calculada como `on_hand_quantity - reserved_quantity` (20 - 5 = 15), sem criar movimentos.
- SHA validado: `fb1470185126dfe295a15b1f69f635aed05b3da3`.
- API CI `45678506014`: PostgreSQL 16 smokes e suite API — **1718 passed, 1 skipped**.
- Quality Gates `45678506006`, Security Scans `45678506005` e Docker Compose `45678506008`: sucesso no mesmo SHA.
- Próxima prioridade: aprofundar a semântica das reservas agregadas e a correlação entre snapshots WMS consecutivos e movimentos; não criar ledger de reservas individuais sem identificadores/documentação do fornecedor.



## 2026-11-25 — Reservas agregadas e movimentos sucessivos WMS

- Adicionada regressão PostgreSQL/API com dois movimentos sucessivos sobre o mesmo snapshot WMS, em tarefas/prateleiras distintas.
- O teste confirma `on_hand=20`, `reserved=5`, disponibilidade inicial 15; após movimentos de 6 e 6 unidades, os snapshots internos resultam em on_hand 14/8, reserva 5 preservada e disponibilidade 9/3.
- O snapshot WMS de origem mantém-se imutável; a soma dos movimentos (12) é deduzida uma vez por movimento, além da reserva agregada.
- O snapshot resultante MANUAL permanece uma projecção interna de movimento, não confirmação de escrita no WMS.
- SHA validado: `043c15f4980b45c4d50d2cd47fb921c5504eccac`.
- API CI `45680479412`: PostgreSQL 16 smokes e suite API — **1719 passed, 1 skipped**.
- Quality Gates `45680479177`, Security Scans `45680479240` e Docker Compose `45680479172`: sucesso no mesmo SHA.
- Próxima prioridade: especificar a correlação de confirmações WMS e snapshots posteriores com base num contrato real do fornecedor; não tratar qualquer alteração de stock como confirmação automática.



## 2026-11-25 — Snapshot imutável do destino físico de movimentos (migration 0094)

- Novo campo `InventoryMovement.destination_shelf_code`, capturado sob lock juntamente com a identidade da prateleira de destino.
- O movimento e o evento `MOVEMENT_RECORDED` incluem o código físico do destino; a API devolve-o em `InventoryMovementRead`.
- Migration 0094 faz backfill a partir da tarefa e da prateleira; aborta perante linhagem ausente/inconsistente e instala guardas PostgreSQL/SQLite para impedir destino nulo, código forjado, prateleira de outra tarefa ou loja.
- A alteração do código da prateleira no futuro não altera o valor histórico gravado no movimento.
- Teste de migration SQLite cobre backfill, consistência, alteração posterior do código e rejeição de inserts inválidos.
- Smoke PostgreSQL de movimento foi ampliado para verificar o código e evidência do destino, e para tentar inserir códigos/IDs forjados.
- SHA validado: `3f4c9740ce70e932c5cb35745e96edd1163bf864`.
- API CI `45683385203`: migration PostgreSQL 16, smoke de linhagem e concorrência, suite API — **1720 passed, 1 skipped**.
- Quality Gates `45683385692`, Security Scans `45683385335` e Docker Compose `45683385339`: sucesso no mesmo SHA.
- Próxima prioridade: avaliar identidade histórica e retenção de prateleiras/zonas quando há reestruturações, sem depender de códigos actuais mutáveis.



## 2026-11-25 — Identidade de zona e retenção da localização de destino (migration 0095)

- Cada movimento conserva `destination_shelf_id/code` e `destination_zone_id/name`; o contrato de leitura e o evento `MOVEMENT_RECORDED` incluem os quatro valores.
- `destination_location_backfilled=false` identifica dados capturados no instante do movimento. A migration 0095 marca `true` nos movimentos históricos, cuja zona/código foram reconstruídos a partir da hierarquia actual disponível.
- Guardas PostgreSQL/SQLite rejeitam zona, nome, código, loja ou tarefa inconsistentes e impedem que novos movimentos sejam marcados como backfilled.
- O smoke PostgreSQL renomeia prateleira e zona e confirma que os valores do movimento permanecem inalterados; tenta eliminar prateleira e zona e confirma que a cadeia de FKs impede apagar o histórico.
- SHA validado: `48fdf8310d1b17179ba6520d7a559b3bcc822c7f`.
- API CI `45686230839`: migration PostgreSQL 16, smoke de movimento/retention e suite API — **1722 passed, 1 skipped**.
- Quality Gates `45686230835`, Security Scans `45686230811` e Docker Compose `45686230752`: sucesso no mesmo SHA.
- Limitação histórica: não é possível reconstruir renomeações anteriores à migration sem eventos históricos; o campo de backfill torna essa incerteza explícita.
- Próxima prioridade: definir arquivamento/soft-delete de catálogo se operações comerciais exigirem remoção visual de zonas/prateleiras, preservando IDs e evidência imutável.



## 2026-11-25 — Retenção de evidência operacional e imutabilidade da auditoria de tarefas (0096–0098)

- Migration 0096 bloqueia a eliminação de prateleiras/zonas com histórico de tarefas.
- Migration 0097 protege `replenishment_task_events` contra UPDATE/DELETE, impede apagar tarefas auditadas e congela `store_id`, `shelf_id` e `product_id` depois de começar a auditoria; alterações normais de estado continuam permitidas.
- Auditoria encontrou uma lacuna adicional: apagar uma prateleira sem tarefas podia propagar CASCADE a imagens, sessões de captura, observações, alertas e associações. A migration 0098 bloqueia a eliminação de prateleiras/zonas enquanto existir qualquer evidência/associação nas tabelas shelf-scoped relevantes.
- Testes SQLite verificam os nove tipos de referência directa; smoke PostgreSQL verifica a retenção de imagem ACTIVE com legal hold mesmo sem tarefa.
- O histórico Web de movimentos passa a apresentar ID/código da prateleira, ID/nome da zona e a proveniência: captura contemporânea ou reconstrução histórica da migration 0095.
- SHA validado: `7bf95468320fc1dd4ab992b520e855d463b6e1f6`.
- API CI `45688691089`: **1725 passed, 1 skipped**, incluindo PostgreSQL 16 e smoke de movimentos, retenção e auditoria.
- Quality Gates `45688691013`, Security Scans `45688691043` e Docker Compose `45688691103`: sucesso.
- Limitação: não existe ainda arquivamento/soft-delete de zonas/prateleiras. A eliminação física fica bloqueada quando há evidência; não foi criada uma operação comercial de descontinuação sem requisito explícito.
- Próxima prioridade: auditar a consistência dos estados de tarefa e transições concorrentes, sem alterar a semântica operacional aprovada.


## 2026-11-25 — Concorrência das transições de estado das tarefas

- Revisão confirmou que o endpoint de transição bloqueia a tarefa com `FOR UPDATE`, re-carrega os valores sob lock e volta a validar a transição permitida.
- O smoke PostgreSQL de tarefas foi ampliado para competir duas atribuições e, separadamente, `COMPLETED` contra `CANCELLED`; apenas uma transição concorrente pode vencer e o evento terminal tem de corresponder ao vencedor.
- O smoke também confirma cancelamento idempotente (repetição recebe 409), histórico append-only exacto e rollback integral do estado quando a escrita do evento falha após flush.
- Commit final de teste: `cfeeab3f4e092709de9eccb0dfc54397f72f12af`.
- API CI `45689904464`: PostgreSQL 16 e suite API — **1725 passed, 1 skipped**.
- Quality Gates `45689904362`, Security Scans `45689904247` e Docker Compose `45689904380`: sucesso no mesmo SHA.
- Sem alterações ao código de produção nesta ronda: o mecanismo de lock já existia; a lacuna era a prova explícita da corrida entre estados terminais e a documentação operacional.
- Próxima prioridade: rever consistência temporal dos campos `started_at`/`completed_at` e a política de atribuição/reafectação, sem inventar regras comerciais nem reabrir estados terminais.


## 2026-11-25 — P0: autorização do histórico de eventos de tarefas

- A revisão da política central confirmou que `GET /api/v1/tasks/{task_id}/events` é `SUPERVISOR_OR_ADMIN`, não uma rota para funcionários.
- O handler passou a impor também essa regra, para defesa em profundidade e para que testes/direct calls não dependam exclusivamente do middleware.
- EMPLOYEE recebe HTTP 403 para qualquer ID, mesmo tarefa atribuída a si próprio; SUPERVISOR continua limitado à loja e ADMIN mantém acesso global.
- Teste regressivo cobre tarefa própria, tarefa de colega, tarefa sem atribuição e ID inexistente para o perfil EMPLOYEE.
- Commits: teste inicial `2fca1052d4e37dac4e0d2cce92b1e5953b494562`; primeira implementação `e36d8708bb5a054c229144cce466eb074f69812f`; alinhamento final `355af238824f5094faa71a95cbf8e746c372c89b` e teste `f925b875f871964ce80805c4927af15616f58774`.
- API CI `45716057516`, Quality Gates `45716057563`, Security Scans `45716057667` e Docker Compose `45716057580`: sucesso no SHA de código `f925b875f871964ce80805c4927af15616f58774`.
- Próxima prioridade: auditar endpoints de leitura de eventos/auditoria de operações adjacentes quanto a privilégios por função e isolamento de loja; manter retenção e estados terminais.


## 2026-11-25 — P0: defesa em profundidade no ciclo de vida de paletes

- A auditoria da rota `/api/v1/warehouse/pallets/{pallet_id}/events` encontrou que a política central já exigia `SUPERVISOR_OR_ADMIN`, mas os handlers não repetiam a verificação de função.
- Os handlers GET e POST passaram a rejeitar explicitamente EMPLOYEE com HTTP 403 antes da leitura/lock e antes de qualquer alteração.
- Teste API cria palete/evento, confirma negação de leitura e escrita para EMPLOYEE sem mutação, e valida leitura/transição válida por SUPERVISOR.
- SHA de código: `50df52e59eca47aa2dfc868fc16621cf2f636586`.
- API CI `45716912538`, Quality Gates `45716912911`, Security Scans `45716912543` e Docker Compose `45716912421`: todos concluídos com sucesso.
- Próxima prioridade: continuar a auditoria de handlers de escrita protegidos pela política central, começando por operações de inventário e integrações, para identificar rotas em que o handler não repete o requisito de função.


## 2026-11-25 — P0: RBAC explícito nas APIs de snapshots e lojas

- A revisão dos handlers encontrou uma diferença entre a política central e a defesa no handler: o POST de snapshots verificava o perfil apenas para `source=MANUAL`, enquanto listagem e leitura do snapshot mais recente dependiam sobretudo do middleware.
- Adicionada autorização ADMIN/SUPERVISOR no handler para ingestão de snapshots de qualquer origem, listagem e consulta latest; GET `/api/v1/stores` também reforçado para ADMIN/SUPERVISOR.
- Teste regressivo confirma 403 para EMPLOYEE nos endpoints e ausência de persistência do snapshot WMS rejeitado.
- A primeira execução do Quality Gates encontrou a guarda em falta na listagem; a correcção foi feita e a suite foi novamente executada no SHA final.
- SHA final de código/testes: `19bf8dd2bf2b6990faff261effc0752523f59a5b`.
- API CI `45718367981`: **1728 passed, 1 skipped**. Quality Gates `45718367943`, Security Scans `45718367972` e Docker Compose `45718367912`: sucesso.
- Próxima prioridade: continuar a auditoria dos handlers que delegam RBAC no middleware, priorizando endpoints de escrita que alteram estado operacional ou criam evidência auditável.


## 2026-11-25 — RBAC explícito nos endpoints de ingestão POS

- Os seis handlers de escrita de vendas e tráfego (registo horário, batch e CSV) agora verificam ADMIN/SUPERVISOR no próprio handler, além da política central.
- Nos imports CSV, a verificação ocorre antes de ler o conteúdo do upload.
- Teste regressivo com actor EMPLOYEE chama os seis endpoints e confirma HTTP 403 e zero linhas persistidas em `hourly_sales_records`/`hourly_store_traffic_records`.
- SHA de código/testes: `d36af7332544204fc14b6764a3faf99c24aa4741`.
- API CI `45719344000`: **1729 passed, 1 skipped**; Quality Gates `45719344142`, Security Scans `45719343998` e Docker Compose `45719344004`: sucesso.
- Próxima prioridade: continuar a auditoria de handlers com escrita e papel `SUPERVISOR_OR_ADMIN`, começando por OCR/evidence fusion e operações de warehouse.


## 2026-11-25 — RBAC explícito na evidência OCR e fusão multimodal

- Reforçada a autorização ADMIN/SUPERVISOR nos handlers de criação de OCR run, matching OCR→catálogo e fusão de evidência visual/textual.
- A validação acontece antes do lock/leitura da captura e antes de qualquer persistência.
- Teste regressivo com EMPLOYEE confirma 403 nos três endpoints e ausência de OCR runs, matches ou fused evidence.
- SHA de código/testes: `a9271dd595c7d913a93cd969cf73d58b5e49438d`.
- API CI `45720266566`: **1730 passed, 1 skipped**; Quality Gates `45720266628`, Security Scans `45720266508` e Docker Compose `45720266578`: sucesso.
- Próxima prioridade: continuar a auditoria de handlers de escrita de warehouse, localizações, colocações, registo de paletes e políticas de rotação, alinhando a autorização interna com a política central.


## 2026-11-25 — RBAC explícito nas mutações de warehouse

- Adicionada autorização ADMIN/SUPERVISOR nos handlers de criação de localizações, colocações, registo de paletes, criação/actualização de políticas de rotação e simulação.
- O controlo ocorre antes de locks, leituras de recursos ou escrita.
- Teste regressivo cobre seis operações com actor EMPLOYEE e confirma 403 sem persistência em localizações, colocações, paletes ou políticas.
- SHA de código/testes: `3f63efd0da73070cc1654e76ea58ecfe0e79ca93`.
- API CI `45721215742`: **1731 passed, 1 skipped**; Quality Gates `45721215822`, Security Scans `45721215637` e Docker Compose `45721215724`: sucesso.
- Próxima prioridade: auditar rotas ADMIN_ONLY de criação/alteração de catálogo e configuração (lojas, zonas, produtos, embalagens, perfis e utilizadores), reforçando o papel no handler.



## 2026-11-26 — Migration 0099: linhagem de alertas e reconciliações

- Confirmado no schema que `InventoryReconciliation` contém `store_id`, `shelf_id`, `product_id`, `observation_id` e três referências opcionais a snapshots (`backroom_snapshot_id`, `erp_snapshot_id`, `wms_snapshot_id`). A migration 0076 tinha FKs individuais e imutabilidade da evidência, mas não garantia a coerência conjunta destas relações.
- Publicada `0099_shelf_reconciliation_lineage`, dependente de 0098. O preflight conta alertas/reconciliações incompatíveis e aborta sem reescrever registos.
- Alertas passam a exigir a associação SKU–prateleira e a loja efectiva da zona.
- Reconciliações passam a exigir a mesma loja/prateleira/SKU, observação da mesma prateleira e SKU (quando indicada) e snapshots opcionais da mesma loja e SKU.
- As guardas também impedem apagar/alterar uma associação SKU–prateleira ou reatribuir uma observação/hierarquia quando isso invalidaria evidência já criada.
- PostgreSQL usa locks `FOR SHARE` nas linhas de prateleira, zona, associação, observação e snapshots consultados durante a inserção; SQLite recebe triggers equivalentes.
- Publicado teste SQLite que cobre IDs existentes mas incompatíveis, ausência de persistência inválida, alterações upstream e preflight fail-closed.
- Commits: migration `b49471424522ba6e5a30db87e86fe9de9c353efd`; teste `189eeaeed01ab75bd82dbc18a4d5bd87007522fd`.
- Não foram executados testes localmente nesta sessão. A validação CI e o teste concorrente PostgreSQL 16 permanecem pendentes; não declarar a migration validada em runtime até esses resultados existirem.


- Acrescentado `apps/api/scripts/postgres_shelf_reconciliation_lineage_smoke.py`: verifica que a inserção de alerta mantém locks de origem e que transferências cross-store da zona e remoções de associações SKU concorrentes aguardam e são rejeitadas.
- O novo smoke foi ligado ao workflow `API CI` imediatamente após o smoke de concorrência de associações SKU. A execução do workflow ainda não foi observada nesta sessão.
- Commit do smoke: `7d00a46fb80a812a167250a48aefc5e6939444d4`; ajuste de contrato do helper: `c8583ed347d3610c301d068f296685268f763fea`; integração CI: `2424b95235aec18897c5675bd40df587528c9e04`.


## 2026-11-26 — Validação CI de 0099 e correcção de fixture legado

- A primeira execução do API CI (45788845876, commit 2424b952) aplicou com sucesso a migration 0099 no smoke de migrations PostgreSQL 16. A execução parou depois, no smoke anterior postgres_shelf_record_lineage_smoke.py: o fixture criava um alerta sem registar primeiro a associação SKU–prateleira, situação agora deliberadamente rejeitada por 0099.
- Corrigido o fixture em apps/api/scripts/postgres_shelf_record_lineage_smoke.py: cria ShelfProduct antes do alerta. Commit f58b77248152ee238648427d72b98cdd78b40b32.
- O Quality Gates reportou 1735 testes aprovados e 4 falhas: duas falhas de testes antigos que esperam respostas de criação de loja com id, e duas falhas de testes de planeamento que tentam criar produtos como SUPERVISOR apesar da política actual exigir ADMIN. Estas falhas não ocorreram nos testes novos de migration 0099, mas mantêm o gate global vermelho e carecem de correcção/triagem própria.
- O novo API CI, Security Scans e Demo Docker Compose smoke foram iniciados para o commit f58b7724; ainda estavam em execução na última consulta.
- Não foi possível confirmar ainda o resultado do novo smoke concorrente postgres_shelf_reconciliation_lineage_smoke.py, porque a execução anterior parou antes de chegar a esse passo.


## 2026-11-26 — Segundo fixture PostgreSQL corrigido para 0099

- A execução API CI `45792255046` ultrapassou o smoke de linhagem de prateleiras após a correcção anterior, mas parou em `postgres_inventory_authorization_smoke.py`: o fixture criava `ObservationAlert` antes de materializar as associações `ShelfProduct` exigidas pelo trigger de 0099.
- Adicionado `db.flush()` imediatamente após a criação das duas associações SKU–prateleira, antes de inserir o alerta. A regra de integridade da migration não foi alterada.
- Commit: `2169864fc7dfcdbf409016ac1298d940b028b3f2`.
- O resultado da execução CI desencadeada por este commit ainda não foi confirmado. Por isso, o smoke concorrente `postgres_shelf_reconciliation_lineage_smoke.py` continua sem evidência de execução bem-sucedida, tal como downgrade/reaplicação.


## 2026-11-26 — Smoke 0099: observação determinística de lock PostgreSQL

- Substituída a inferência baseada numa espera fixa de 200 ms por observação directa de `pg_stat_activity`.
- O contender captura o seu `pg_backend_pid()`; a sessão observadora exige que PostgreSQL reporte `wait_event_type = 'Lock'` antes de a transacção de evidência ser confirmada.
- A verificação tem timeout limitado de 5 segundos e falha com diagnóstico se o backend não entrar num lock wait observável.
- Commit: `6141e2d1d49506177dc457565e540ee0d5019469`.
- A alteração está publicada na `main`; ainda não foi executada/validada em PostgreSQL CI. Não confundir a melhoria do teste com prova de que o teste passou.
- Próximo passo: obter resultado de API CI que execute o smoke e, depois, cobrir explicitamente concorrência na inserção de reconciliação e downgrade/reaplicação.


## 2026-11-26 — API CI: smoke concorrente 0099 aprovado; suite global mantém quatro falhas

- API CI run `45793773197`, commit de código `6141e2d1d49506177dc457565e540ee0d5019469`: a migration Alembic foi aplicada com sucesso em PostgreSQL 16.
- Os smokes PostgreSQL anteriores passaram, incluindo os dois fixtures anteriormente bloqueantes (`postgres_shelf_record_lineage_smoke.py` e `postgres_inventory_authorization_smoke.py`).
- O passo `Verify PostgreSQL shelf and reconciliation evidence lineage lock serialization` terminou com sucesso. O log confirma: transferência cross-store da zona e remoção da associação SKU aguardaram pelos locks de evidência e foram rejeitadas. Este resultado valida as duas corridas cobertas pelo smoke.
- Demo Docker Compose smoke `45793773029`: sucesso.
- A API CI terminou globalmente em falha no passo `pytest -q`: **4 failed, 1735 passed, 1 skipped**. Falhas: `tests/test_inventory.py::test_reserved_wms_quantity_is_subtracted_once_across_multiple_movements`; `tests/test_observations.py::test_failed_image_analysis_can_be_retried_by_store_supervisor` (ambas `KeyError: 'id'`); `tests/test_tasks.py::test_auto_assign_balances_workload_and_prioritizes_urgent_tasks`; `tests/test_tasks.py::test_auto_assign_respects_persisted_shift_capacity_and_required_skill` (ambas esperam 201 para SUPERVISOR, mas a API devolve 403 — ADMIN obrigatório).
- Quality Gates e Security Scans para este SHA foram cancelados durante a sequência de commits de documentação; não os marcar como aprovados. A triagem das quatro falhas de testes permanece independente da validação PostgreSQL 0099.
- Conclusão parcial: o smoke de concorrência PostgreSQL 0099 passou; API CI global ainda não está verde. Downgrade e reaplicação PostgreSQL continuam sem validação dedicada.


## 2026-11-26 — Gates verdes após alinhamento dos fixtures com RBAC actual

- Corrigidos exclusivamente os quatro fixtures/testes legados que falhavam na execução anterior; não foi alterada a autorização de produção:
  - `test_reserved_wms_quantity_is_subtracted_once_across_multiple_movements`: cria zonas/prateleiras enquanto actor ADMIN e regressa a SUPERVISOR para operações de tarefa.
  - `test_failed_image_analysis_can_be_retried_by_store_supervisor`: cria loja/zona/prateleira como ADMIN e só depois muda para SUPERVISOR para upload/retry.
  - Os dois testes de auto-assign criam catálogo como ADMIN e executam atribuição como SUPERVISOR, de acordo com as políticas dos endpoints.
- Commit dos ajustes: `024b76241b8a116d9930ea448dd6668f434926c2` (com commits sequenciais dos fixtures: `a3560ab4`, `b9fdacd8`, `839a919f`).
- API CI `45794895213`: **sucesso**. Incluiu aplicação de migrations PostgreSQL 16, todos os smokes PostgreSQL (incluindo smoke concorrente 0099) e suite pytest completa.
- Quality Gates `45794895243`: **sucesso**, incluindo build TypeScript e API tests/Python compilation.
- Security Scans `45794895272`: **sucesso**.
- Demo Docker Compose smoke `45794895899`: **sucesso**.
- Resultado: as quatro falhas anteriores foram resolvidas nos testes, sem relaxar a política ADMIN_ONLY nem alterar o comportamento de produção. A migration 0099 passou a validação de upgrade + integridade/concorrência no PostgreSQL 16. Falta ainda uma prova dedicada de downgrade para 0098 e reaplicação de 0099 em base isolada.


## 2026-11-26 — Validação isolada de downgrade/reaplicação 0099 adicionada ao API CI

- Criado `apps/api/scripts/postgres_shelf_reconciliation_lineage_migration_cycle_smoke.py`.
- O smoke cria uma base PostgreSQL temporária, aplica migrations até 0099, confirma os seis triggers e cinco funções da migration, faz downgrade para 0098, confirma a remoção desses objectos e reaplica 0099, confirmando a sua recriação.
- A base temporária é removida em bloco `finally` com `DROP DATABASE ... WITH (FORCE)`; a base principal `smart_shelf_ci` não é sujeita a downgrade.
- Integrado no workflow API CI imediatamente após o upgrade normal de migrations.
- Commits: script `53b08213e706e111672b8528e007f51a8d4515af`; workflow `91df1f671c712fee739735086bbed9a48a00aec5`.
- A validação do novo smoke está pendente de execução CI. Não considerar o downgrade/reaplicação aprovados até o job passar.


## 2026-11-26 — Migration 0099: downgrade e reaplicação aprovados em PostgreSQL 16

- API CI run `45795924709`, commit de workflow `91df1f671c712fee739735086bbed9a48a00aec5`: **sucesso**.
- O novo passo `Verify PostgreSQL 0099 downgrade and re-apply in an isolated database` terminou com sucesso.
- O smoke executou upgrade até 0099 numa base temporária, confirmou seis triggers e cinco funções, fez downgrade para 0098 e confirmou a remoção dos objectos, reaplicou 0099 e confirmou a recriação integral. A base temporária foi removida.
- O smoke concorrente `postgres_shelf_reconciliation_lineage_smoke.py` também terminou com sucesso na mesma execução: a transferência cross-store e a remoção da associação SKU esperaram pelo lock real e foram rejeitadas.
- O passo completo `pytest -q` terminou com sucesso; o job API CI concluiu com sucesso.
- Os gates Quality/Security deste SHA foram cancelados durante commits de documentação; os últimos resultados aprovados continuam a ser Quality Gates `45794895243` e Security Scans `45794895272` no commit `024b7624`. Docker Compose também passou em `45794895899`.
- Conclusão: upgrade, validação de linhagem, serialização concorrente, downgrade e reaplicação da migration 0099 estão comprovados em PostgreSQL 16 isolado/CI. Manter a migration fechada, sem alteração de regra.


## 2026-11-26 — Extensão do smoke 0099 para concorrência de reconciliações

- A cobertura anterior validava concorrência na criação de alertas (transferência cross-store da zona e remoção SKU), mas não exercitava directamente o lock específico de `InventoryReconciliation` sobre a observação de origem.
- Estendido `postgres_shelf_reconciliation_lineage_smoke.py` com um segundo cenário independente: inserir uma reconciliação com `observation_id`, manter a transacção aberta e tentar alterar concorrentemente `observations.product_id`.
- O teste exige `wait_event_type = 'Lock'` em `pg_stat_activity`; depois do commit da reconciliação, a alteração upstream tem de ser rejeitada e a observação/reconciliação têm de permanecer coerentes.
- Commits: cenário `fe2fb8939b56d5801ff65b2cc1924d1a697ecfe6`; limpeza de saída duplicada `eea9cc5d462c49dd2d43383f07ef3633e9f73ea6`.
- Esta extensão ainda aguarda execução no API CI PostgreSQL 16. Os resultados anteriores de 0099 continuam válidos para os cenários alert/zone/SKU e ciclo downgrade/reaplicação; não antecipar aprovação deste novo cenário.


## 2026-11-26 — Concorrência de InventoryReconciliation aprovada em PostgreSQL 16

- API CI run `45797706450` no commit de código `eea9cc5d462c49dd2d43383f07ef3633e9f73ea6`: **sucesso**.
- O smoke 0099 passou com os três cenários: (1) criação de alerta versus transferência cross-store de zona; (2) criação de alerta versus remoção da associação SKU; (3) criação de reconciliação versus alteração concorrente de `observations.product_id`.
- No terceiro cenário, o teste manteve aberta a transacção que insere `InventoryReconciliation`, observou `wait_event_type = 'Lock'` para o backend concorrente e confirmou que a alteração da observação foi rejeitada depois do commit. A reconciliação e a observação mantiveram a mesma linhagem.
- Log explícito: `PostgreSQL 0099 lineage smoke passed: alert creation serialized with cross-store zone transfer and SKU unlink; reconciliation creation serialized with an upstream observation mutation. All competing writes waited on PostgreSQL locks and were rejected.`
- A mesma execução concluiu `pytest -q` com **1739 passed, 1 skipped**; Demo Docker Compose smoke `45797706344`: sucesso.
- Quality Gates e Security Scans para este SHA foram cancelados por commits sequenciais de documentação; os últimos resultados aprovados são Quality Gates `45796897497` e Security Scans `45796897524` (sucesso). Será feita nova execução após esta actualização documental.


## 2026-11-26 — Fecho definitivo da migration 0099 e gates globais

A nota anterior que mantinha a migration 0099 aberta foi superada pelas execuções seguintes e fica aqui corrigida por evidência posterior.

- API CI `45797706450` no commit `eea9cc5d462c49dd2d43383f07ef3633e9f73ea6`: **sucesso**; suite completa **1739 passed, 1 skipped**.
- O smoke PostgreSQL 16 cobriu criação de alerta concorrente com transferência cross-store da zona, remoção da associação SKU e criação de reconciliação concorrente com alteração da observação de origem. Nos três cenários, `pg_stat_activity` confirmou `wait_event_type = 'Lock'` e as alterações concorrentes foram rejeitadas, preservando a linhagem.
- O ciclo de migration foi validado isoladamente no API CI `45795924709`: upgrade para 0099, downgrade para 0098, confirmação da remoção dos seis triggers/cinco funções e reaplicação de 0099 com recriação dos objectos.
- Demo Docker Compose `45797706344`: sucesso.
- No HEAD documental `3b288869a97f76ad057b273d5e19c93f69676372`, Quality Gates `45798609654` e Security Scans `45798609531` terminaram ambos com sucesso. Os jobs de build TypeScript, build de produção Web, API/Python compilation, auditorias de dependências, ZAP passive baseline e secret scan concluíram sem falhas.
- As quatro falhas anteriores de pytest foram corrigidas nos fixtures, sem alterar RBAC de produção.

**Conclusão:** migration 0099 fechada. Upgrade, integridade, isolamento multi-loja, serialização concorrente, downgrade e reaplicação estão comprovados em PostgreSQL 16/CI. Não reabrir sem nova evidência de regressão.


## 2026-11-26 — Validação CI dos históricos multi-loja e cobertura RBAC

- Reconciliado o estado documental dos cinco blocos P0 de isolamento de históricos (alertas, tarefas/movimentos, retenção de imagens, revisão de exemplares) e cobertura explícita RBAC com a execução API CI `45797706450` no código `eea9cc5d462c49dd2d43383f07ef3633e9f73ea6`.
- O passo de auditoria de políticas RBAC terminou com sucesso; a suite PostgreSQL 16 + pytest terminou com **1739 passed, 1 skipped**.
- Demo Docker Compose `45797706344` terminou com sucesso no mesmo código. Quality Gates `45798609654` e Security Scans `45798609531` passaram no HEAD documental `3b288869a97f76ad057b273d5e19c93f69676372`.
- `TODO.md` actualizado no commit `8dba643eb832f7718af2e39ddd90ea7a76a2f8e3` para remover os estados pendentes que já estavam cobertos por estes workflows.
- A auditoria BOLA/IDOR não está encerrada: continuam explicitamente abertas a análise de concorrência na revisão de exemplares e a revisão de outros endpoints com IDs directos. A cobertura estática RBAC não é prova de autorização de cada recurso.


## 2026-11-26 — Migration 0100: linhagem da shelf da imagem-fonte embedding

- A auditoria do fluxo `PATCH /api/v1/product-embedding-exemplars/{exemplar_id}/review` confirmou a ordem de locks imagem → produto → exemplar e a revalidação do tenant depois do lock da imagem.
- Identificada uma lacuna a jusante: a migration 0037 protegia a imutabilidade do exemplar e a eliminação da imagem, mas não bloqueava a alteração de `shelf_images.shelf_id` com exemplares existentes. Essa mudança podia transferir a linhagem/visibilidade tenant do exemplar após uma revisão válida.
- Criada `0100_embedding_source_image_shelf_lineage.py` com trigger PostgreSQL e SQLite que rejeita a mudança de shelf enquanto existir exemplar derivado. O downgrade remove apenas a guarda 0100.
- Adicionado teste SQLite para bloqueio, caso sem exemplar e downgrade.
- Adicionado `postgres_embedding_source_image_shelf_lineage_smoke.py`: mantém a linha do produto bloqueada para forçar a revisão HTTP a reter o lock da imagem; observa depois o lock wait real da alteração concorrente e exige rejeição após a revisão confirmar.
- Integração no API CI publicada no commit `e96f1b372c984817c9157419a752892b90e9b1aa`. Commits da migration/teste/smoke: `b0f7c766`, `a2e86139`, `43b4266d` e correcção de sincronização `8772488d`.
- Estado: código e documentação publicados; execução CI PostgreSQL 16 pendente. Não declarar a migration 0100 validada até o novo smoke e suite completa passarem.


## 2026-11-26 — Migration 0100 aplicada e smoke de concorrência aprovado

- API CI `45804056793` aplicou `0100_embedding_source_image_shelf_lineage` em PostgreSQL 16 e executou com sucesso o novo smoke concorrente.
- Log explícito: `PostgreSQL embedding source-image lineage smoke passed: the review held the image lock, the competing shelf reassignment waited on a real PostgreSQL lock, and migration 0100 rejected the reassignment after the review committed.`
- A suite completa terminou com **1740 passed, 1 skipped**. Demo Docker Compose `45804012587` passou com o código que já incluía a migration 0100. Quality Gates `45804113802` e Security Scans `45804113803` passaram no HEAD documental `443db02d`.
- Para evitar duplicação, o ciclo PostgreSQL 0099 mantém-se no seu smoke próprio. Foi criado o smoke dedicado `postgres_embedding_source_image_shelf_lineage_migration_cycle_smoke.py`, que aplica 0100, faz downgrade para 0099 verificando que as seis triggers/cinco funções de 0099 permanecem, e reaplica 0100. Script: commit `24b1093c`; integração API CI: commit `7e23d3d9`; validação do workflow final ainda pendente.
- Estado: a integridade e concorrência de 0100 estão aprovadas; o ciclo PostgreSQL de downgrade/reaplicação de 0100 continua pendente.


## 2026-11-26 — Regressão BOLA para IDs aninhados de mappings ERP/WMS

- Estendido `apps/api/scripts/postgres_inventory_authorization_smoke.py` com dois mappings reais, um por loja, e respectivos eventos append-only.
- Para SUPERVISOR da loja A, o acesso ao histórico do mapping A permanece permitido; a substituição pelo ID real do mapping B no path A devolve 404, indistinguível de ID inexistente; a tentativa de PATCH ao mapping B também devolve 404.
- O mesmo SUPERVISOR recebe 403 quando usa o path da loja B. ADMIN consegue consultar o histórico do mapping B como controlo positivo.
- A verificação pós-request confirma que o mapping B continua activo e que o evento original não foi alterado nem duplicado.
- Commit da extensão: `6db6fe6fdb0cdb79af88a69e858b50de77e1f229`.
- API CI `45804056793` (commit de código `e96f1b372c984817c9157419a752892b90e9b1aa`): sucesso; smoke `Verify PostgreSQL inventory and warehouse cross-store authorization` passou e a suite completa terminou com **1740 passed, 1 skipped**.
- No mesmo ciclo, o smoke de linhagem da imagem-fonte embedding / migration 0100 também passou. Quality Gates `45804113802` e Security Scans `45804113803` concluíram com sucesso no HEAD documental `443db02d8081af2bebe6d6e67141213da712b7bb`. Docker Compose `45804012587` terminou com sucesso com a migration 0100 já presente.
- A matriz BOLA/IDOR continua aberta: esta é uma cobertura específica adicional, não uma declaração de auditoria completa.


## 2026-11-26 — Fecho da migration 0100 e confirmação dos ciclos PostgreSQL

- API CI `45805339672`, commit de código `bef29291b55f7a51dd35d917f0d64c3e0b2f7f11`: **sucesso** em PostgreSQL 16.
- O smoke `postgres_shelf_reconciliation_lineage_smoke.py` já usa `pg_stat_activity.wait_event_type = 'Lock'` para provar os bloqueios reais nos três cenários 0099: transferência cross-store da zona, remoção da associação SKU e mutação da observação de origem da reconciliação. Não depende de um atraso fixo como prova de lock.
- O smoke da migration 0100 confirmou concorrência real entre revisão HTTP do exemplar e reassociação da imagem-fonte: a alteração esperou pelo lock e foi rejeitada depois de a revisão confirmar.
- O smoke dedicado do ciclo 0100 passou: upgrade para 0100; downgrade para 0099 com remoção apenas da trigger/função 0100 e preservação das seis triggers/cinco funções 0099; reaplicação 0100 com sucesso. O log do workflow confirma explicitamente cada fase.
- Suite API: **1740 passed, 1 skipped**. Docker Compose `45805339652`: sucesso no mesmo commit de código.
- Quality Gates `45805397438` e Security Scans `45805397536`: sucesso no HEAD documental `a09fc5a10dbbfe6d79e7e320dd3efb9979527cf1`, descendente sem alterações de código relativamente ao SHA validado pela API CI.

**Conclusão:** migrations 0099 e 0100 estão validadas nos critérios de integridade, isolamento multi-loja, serialização concorrente, downgrade controlado e reaplicação em PostgreSQL 16. A migration 0100 também tem teste SQLite para a guarda e o downgrade. A auditoria global BOLA/IDOR e de todos os endpoints com IDs directos permanece trabalho separado; não confundir o fecho destas migrations com homologação de integração WMS/ERP ou validação de precisão de visão computacional.


## 2026-11-26 — Prova de bloqueio 0099 ligada ao PID exacto da evidência

- Reforcei `postgres_shelf_reconciliation_lineage_smoke.py`: cada transacção de evidência captura o seu próprio `pg_backend_pid()`; o observador só aceita o lock wait quando `pg_stat_activity.wait_event_type = 'Lock'` e o PID da evidência está efectivamente presente em `pg_blocking_pids(contender_pid)`.
- Isto elimina a ambiguidade de um lock wait provocado por outra sessão e prova que a transacção de evidência esperada é o bloqueador nas três corridas: transferência da zona, remoção da associação SKU e mutação da observação de origem.
- Commit de código `9a78d2f185ba2bcdf5ff043097f4895639125a09`; API CI `45812501875`: sucesso, PostgreSQL 16 e **1740 passed, 1 skipped**. O log final do smoke 0099 confirma que todos os writes concorrentes aguardaram por locks e foram rejeitados.
- Quality Gates `45812501507`, Security Scans `45812501427` e Docker Compose `45812501364`: todos com sucesso no mesmo SHA de código.

Estado: a prova concorrente 0099 passou de observação genérica de lock para confirmação do bloqueador exacto. As migrations 0099 e 0100 mantêm-se fechadas; a auditoria BOLA/IDOR dos restantes endpoints continua separada e aberta.

## 2026-11-26 — Isolamento tenant no histórico de jobs ERP/WMS

- HEAD de referência antes da alteração: 2990d14cf2aebf7e2842f5bd29dce125422b19ea.
- Identificada uma janela TOCTOU em GET /api/v1/stores/{store_id}/inventory/sync-jobs/{job_id}/events: o handler validava o job numa query e lia os eventos numa segunda query apenas por job_id.
- Alterado apps/api/app/main.py: parent job e eventos são agora lidos numa única instrução com OUTER JOIN e filtros simultâneos de job_id e store_id. Um job válido sem eventos continua a devolver lista vazia; job estrangeiro/inexistente devolve 404.
- Alterado apps/api/tests/test_inventory_sync_jobs_api.py: acrescentada regressão que cria um job noutra loja e compara a resposta com um ID inexistente ao consultar através da loja autorizada; preserva o teste 403 para actor que tenta usar o path de outra loja.
- Commits publicados em main: código a7bdf75cf62d2a855f257ca97be484f89a022da8; teste 56ca987260186601fd0f3e42088a18528b472552.
- Validação pendente: não foi executada suite local; aguardar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA final. Não declarar P0 concluído até confirmação.
- Próxima acção obrigatória: rever a integridade/imutabilidade de InventorySyncJob.store_id e procurar outras queries de eventos que façam preflight separado do recurso-pai.