## Validação e concorrência do ciclo de retenção (2026-11-18)

- API CI run `44266521498` passou no commit `b50b402dd6e5`; o job `test` terminou com sucesso.
- Docker Compose smoke run `44266521499` passou no mesmo commit: build/start, readiness, seed e verificação dos perfis de demonstração concluídos.
- Quality Gates run `44266547157` passou no commit `c40e2f27d081`: testes/compilação Python e TypeScript/build de produção Web passaram.
- O reforço de `test_legal_hold_blocks_overdue_purge_until_hold_is_released` ficou validado: aplicar/libertar legal hold preserva a data e a versão da política agendadas e produz os eventos append-only esperados.
- Foi acrescentado `apps/api/scripts/postgres_retention_legal_hold_concurrency_smoke.py` e integrado no API CI por `e0df33d023e5`. O teste força as duas ordens concorrentes: (1) legal hold confirma enquanto o pedido de agendamento espera, que deve responder 409; (2) agendamento confirma enquanto o pedido de legal hold espera, que deve preservar data/política e histórico. **Este novo smoke ainda aguarda execução CI; não está validado.**


## Auditoria de legal hold — regressão adicional (2026-11-18)

A pré-visualização de purge já bloqueava imagens com legal hold activo e os endpoints de agendamento/cancelamento/restauro já registavam eventos append-only. Foi reforçado `test_legal_hold_blocks_overdue_purge_until_hold_is_released` para verificar também que aplicar/libertar um legal hold preserva a data e a versão da política previamente agendadas, e que ambos os eventos registam transição de estado, administrador e motivo. Esta preservação é intencional: o legal hold suspende a elegibilidade, não apaga nem cancela silenciosamente o agendamento. **O novo reforço de teste aguarda API CI; não está validado.** Continua pendente cobertura PostgreSQL de concorrência entre aplicação/libertação de hold e agendamento/cancelamento.


## Validação CI — paginação filtrada e migração 0054 (2026-11-18)

- API CI run `44265754667`, commit `442a8cab89adc3be743e39af76007ad0da94e01d`: job concluído com sucesso. Incluiu a suite API, smoke das migrações Alembic em PostgreSQL e smoke de unicidade concorrente das unidades de embalagem.
- Quality Gates run `44265786855`, commit `381ff95d82d5a5c3607ad00330bcf5b3afd6d300`: ambos os jobs concluídos com sucesso — testes/compilação Python e TypeScript/build de produção Web.
- A cobertura da paginação filtrada da fusão visual/OCR, incluindo revalidação do catálogo, locks por ordem crescente e offset que atravessa o lote keyset de 500 registos, está validada nestes pipelines.
- A migração 0054 e os seus testes de preflight/downgrade estão validados pela suite API e pelo smoke PostgreSQL. Continua pendente a inspecção/saneamento de dados históricos reais antes de aplicar a migração em qualquer ambiente com dados de produção.
- Não foi executado um novo Docker Compose nesta validação; não inferir essa cobertura a partir dos Quality Gates.


# PROGRESS

## Paginação filtrada da evidência visual/OCR — 2026-11-18

A revisão da rota `GET /api/v1/shelf-images/{image_id}/evidence-fusion` identificou que o `offset` era aplicado antes da filtragem pelo estado recalculado a partir do catálogo activo. Isso podia devolver páginas incompletas quando os primeiros registos da página bruta mudavam de estado após revalidação. A rota passou a percorrer lotes keyset de 500 registos, recalcular o estado e só depois aplicar o offset/limite ao conjunto filtrado. Para evitar inversão da ordem de locks entre lotes, bloqueia primeiro todos os produtos referenciados pela imagem em ordem crescente de ID, mantendo a ordem global imagem → produtos. Foram acrescentados testes de regressão para estados históricos que mudam após desactivação de produtos e para paginação que atravessa o limite entre lotes (offset 500). **Código e testes ainda aguardam CI; não estão validados.**


## Segurança de migrações — unidades de embalagem (2026-11-18)

A migração `0054_unique_active_product_packaging_units` passou a executar um preflight antes de criar os índices únicos parciais. O preflight identifica conflitos por produto, separando unidade activa de encomenda e unidade activa de reposição, apresenta IDs e contagens (até 20 por função) e aborta sem modificar linhas quando encontra duplicados. Foram acrescentados testes SQLite para dados preexistentes conflituosos, exclusão de linhas inactivas, enforcement dos índices e downgrade. **Esta alteração e os novos testes ainda aguardam execução no CI; não estão validados.** A verificação/saneamento de dados reais continua a ser uma tarefa operacional antes de aplicar a migração num ambiente com histórico de produção.


## Latest validated changes — 2026-11-18

- **Pagination audit closure — commits `2180c02`, `8a9e676`, `e645e7b`, `2d3794c`, `4c9bf90`:** added page-size-bounded offset pagination and deterministic ordering to artifact references, append-only disposition events and human SKU review history, with regression coverage for page boundaries and invalid bounds. The related API CI run `44256610563` passed: **1136 passed, 1 skipped, 1 warning**; all PostgreSQL concurrency/authorization smoke steps passed. Demo Docker Compose run `44256610406` passed build, readiness, seed and worker-profile checks. Quality Gates run `44256985942` passed API tests/Python compilation and Web TypeScript/production build.
- The Vercel status checks on the documentation commit report `build-rate-limit` (account/build quota), not an application compilation or test failure. GitHub Actions API and Web quality jobs completed successfully.
- Remaining work is deliberately not marked complete: inspect query plans and deep-offset cost on representative data; finish retention/legal-hold lifecycle coverage; reconcile ROADMAP.md; and perform manual keyboard/browser/contrast verification before claiming WCAG AA conformance.


## Latest validated changes

- **2026-11-17 — `554e9df`**: dashboard UX changes passed Web CI (`44198503068`); frontend TypeScript and production build passed the corresponding quality-gates job (`44198503127`). Full quality-gates run's API test job remained in progress at documentation time. See Current focus for the implementation and the remaining manual accessibility audit.


- **2026-11-17 — `b982ced` / `0926b94`**: PostgreSQL observation creation versus image retention smoke passed API CI (`44194248812`), including the real HTTP request waiting on the source-image lock, returning HTTP 410 after retention commits, and persisting no observation. Frontend/API quality gates (`44194278316`) and Docker Compose smoke (`44194224077`) also passed.

- **2026-11-17 — `a944e82`**: stale-processing recovery now locks eligible `ShelfImage` rows in ascending ID order, matching the global source-image lock order. The SQL-order regression test passed; API CI (`44159933637`), Smart Shelf quality gates (`44159933623`) and Docker Compose smoke (`44159933607`) all succeeded.
- **2026-11-17 — `9de762b`**: production JWT/bootstrap secret validation and its placeholder/whitespace regression tests passed API CI (`44149640352`), Smart Shelf quality gates (`44149698056`) and Docker Compose smoke (`44149640514`). Quality gates included Python compilation, full API tests and frontend TypeScript/production build. PostgreSQL smoke checks and Docker demo readiness/worker profiles also passed.
- Catalogue authorization review: middleware explicitly restricts POST `/products`, `/shelf-products`, `/warehouse/product-profiles` and `/warehouse/product-packaging` to ADMIN; supervisor/employee requests are denied before route execution. Shelf-product listing is scoped to the supervisor's store. No code change made in this pass; targeted regression coverage remains to be assessed.

- **2026-11-17 — `355154e`**: aligned demo detection-to-observation locking with the global image-first lock order and added a regression assertion for the query sequence.
- **2026-11-17 — `08a03a6`**: narrowed the detection-listing row lock to the source `ShelfImage`, avoiding unnecessary locks on joined shelf and zone rows.
- Added root-level `TODO.md` and `PROGRESS.md` to track audit work and evidence-backed validation.
- GitHub Actions for `355154e` completed successfully: API CI, Smart Shelf quality gates and Demo Docker Compose smoke.
- **2026-11-17 — `2840912`**: added regression coverage for observation listing isolation by store and shelf filter; all three workflows passed.

- **2026-11-17 — `6861330`**: added focused settings tests for production JWT/bootstrap secret strength, distinct secrets, and development-only defaults. CI validation is pending.

## Audit notes

- Capture-session tenant isolation, foreign-store create/close denial, employee role restrictions, and upload/session ownership have regression tests in `apps/api/tests/test_auth_middleware_jwt.py`.
- Foreign-store image content, detections, OCR, evidence fusion, retry and human-review access are covered by the authorization test suite.
- No local test execution is claimed; validation above is based on GitHub Actions.

## Current focus

Dashboard UX refinement (2026-11-17): implemented human-readable day/hour/minute durations, consistent `pt-PT` timestamps with explicit `Europe/Lisbon` timezone abbreviations, stronger secondary-text contrast and readable font sizes, status symbols alongside colour, keyboard-accessible clickable KPI/zone/status summaries with task filters, and a tighter single-task card layout. Frontend CI/build validation is pending. Contrast values target WCAG AA; formal conformance still requires automated and manual contrast verification. The first Web CI run (`44197879520`) caught a missing JSX closing brace in the empty-task filter state; corrected in the follow-up commit, with a fresh build required.


Human detection review versus image retention: added `postgres_human_review_retention_smoke.py` and wired it into API CI. The test holds the source-image row lock, sends the real `POST /api/v1/shelf-image-detections/{id}/reviews` request, restricts the image, and asserts HTTP 410 with no persisted `DetectionSkuReview`. Validation is pending; do not mark this race complete until the new API CI step passes.


Production configuration review: `Settings` rejects the development JWT key, JWT/bootstrap secrets shorter than 32 characters, known placeholder markers, reused secrets, and whitespace in either production secret when `APP_ENV=production`. Tests isolate inherited CI environment variables. Initial CI exposed environment leakage in two tests; corrected the tests, enforced distinct JWT/bootstrap values, and added rejection coverage for placeholder/example/test secrets. The final API, quality-gates and Docker workflows passed.

Worker lease audit found and fixed a race: a worker that loses its processing lease can no longer mark the replacement worker's job FAILED when its own provider call raises. The failure handler now locks and refreshes the image row and changes state only if status and claim timestamp still match. The lease-takeover regression test and the API, quality-gates and Docker Compose workflows passed for 71b3425. Continue reviewing catalogue authorization, derived-image retention races and worker retry behavior; do not mark an item complete until relevant automated checks pass.


### Catalogue write authorization — 2026-11-17

Added `test_catalogue_and_warehouse_master_data_writes_are_admin_only` to exercise all four middleware-protected creation routes as both SUPERVISOR and EMPLOYEE. The test uses empty payloads deliberately: HTTP 403 must be returned by the authorization boundary before request-schema validation or route-side effects. This establishes role-gate coverage only; ADMIN ownership validation, store scoping and concurrent shelf-product reassignment remain open. Commit: `df1030a860d517f2cf519b01672218b3b4d82852`. CI validation is pending; no local test execution is claimed.


- **2026-11-17 — `5ef55ab`**: added a tenant-isolation regression test for `GET /api/v1/shelf-products`: SUPERVISOR sees only the assigned store, an explicit foreign-shelf filter returns an empty list, and ADMIN retains global visibility. The earlier `df1030a` test covers supervisor/employee denial on four catalogue/master-data creation routes. These are regression tests added to the suite; CI is pending and no local execution is claimed. Concurrent shelf-product reassignment remains unvalidated.


### Shelf assignment integrity — 2026-11-17

- **`52b0d45`** adds API regression tests proving an ADMIN cannot assign an inactive product to a shelf (HTTP 409; no row persisted) and cannot create a duplicate shelf/product association (HTTP 409; existing row count remains one).
- The previous CI run for commit `5ef55ab` passed API CI and Demo Docker Compose smoke; Quality Gates passed for `9e9d242`. The new tests have not yet been validated by CI.
- No application code changed in this pass: current route logic already rejects inactive products and duplicate assignments. PostgreSQL concurrency/unique-constraint race coverage remains open.


### PostgreSQL shelf assignment concurrency — 2026-11-17

- **`7575dac`** adds `apps/api/scripts/postgres_shelf_product_assignment_concurrency_smoke.py`: two simultaneous requests attempt the same shelf/product association; expected result is exactly one HTTP 201, one HTTP 409 and exactly one persisted row.
- **`050542e`** wires the smoke test into API CI against the PostgreSQL 16 service. This specifically validates the existing product-row lock plus database uniqueness boundary under real PostgreSQL concurrency; it does not claim a general reassignment workflow exists.
- **`52b0d45`** also added SQLite/API regression coverage for inactive-product and duplicate-assignment rejection. CI status for these latest changes is pending at the time of this note.


## 17-11-2026 — Unicidade concorrente de unidades de embalagem
- Identificado risco de corrida na validação aplicacional de unidades de encomenda/reposição.
- Adicionados índices únicos parciais no modelo SQLAlchemy e migração 0054 para PostgreSQL/SQLite.
- Adicionado teste API que confirma HTTP 409 para uma segunda unidade activa do mesmo tipo.
- Adicionado smoke test PostgreSQL concorrente para tentar duas gravações simultâneas por cada indicador.
- O resultado só será considerado validado após execução da migração, smoke test e suite completa no CI.


## 17-11-2026 — Fronteira entre paletes físicas e inventário agregado
- A auditoria confirmou que `POST /api/v1/warehouse/pallets` regista uma unidade física, valida a embalagem PALLET e cria um evento `REGISTERED`; não deve criar uma recepção nem alterar snapshots agregados.
- Adicionada regressão ao teste de recursos de armazém para comparar a contagem de `InventorySnapshot` e `InventoryMovement` antes/depois do registo da palete.
- Commits: `8897e2e` (teste inicial) e `94d2ca1` (correcção de comentário Python).
- O API CI anterior passou para o commit `c83574f`, incluindo a migração 0054 e os smoke tests PostgreSQL. A nova regressão ainda aguarda CI; Quality Gates e Docker Compose também aguardam execução na HEAD actual.
- Não foi criada uma sincronização automática entre paletes e inventário: isso exigiria uma regra de negócio explícita para impedir dupla contabilização.


## 18-11-2026 — Integridade das colocações de armazém
- A auditoria encontrou que o endpoint `POST /api/v1/warehouse/placements` aceitava produtos e localizações inactivos.
- O endpoint passou a responder HTTP 409 para ambos os casos, antes de criar a colocação.
- Adicionado teste de regressão com JWT de SUPERVISOR; confirma os dois conflitos e que nenhuma linha é persistida.
- Commits de código/teste: `724f84d` e `0d5b9aa`.
- Validação pendente: API CI, Quality Gates e Demo Docker Compose. As execuções iniciadas para commits intermédios foram supersedidas; a validação deve ser confirmada na HEAD final.
- A política de capacidade/peso/temperatura continua em aberto: o perfil físico pode não existir e a colocação também representa registo de stock físico existente; não bloquear dados sem uma regra operacional explícita.


## 18-11-2026 — Cobertura do slotting físico por API
- A revisão confirmou que a lógica de recomendação física já calcula ocupação por perfil, capacidade volumétrica e ponderal, temperatura e segregação; localizações com ocupação desconhecida são excluídas em vez de tratadas como vazias.
- A rota permanece consultiva: não move stock nem reserva capacidade.
- Adicionado teste de integração com JWT para garantir que a rota API expõe candidatos compatíveis, rejeita capacidade volumétrica insuficiente e incompatibilidade térmica, calcula volume/peso e ordena por distância.
- Corrigida a docstring do módulo, que ainda afirmava que as localizações e restrições físicas não estavam modeladas.
- Commits: `135779d` (teste API) e `3fab8b8` (documentação do módulo).
- Validação CI do novo teste pendente.


## 18-11-2026 — Reconciliação conservadora entre paletes e slotting
- A auditoria confirmou que o smoke PostgreSQL `postgres_active_task_smoke.py` já cobre duas tarefas distintas, do mesmo produto e snapshot, a tentar reconciliar em simultâneo: apenas um movimento de 4 unidades é aceite, o segundo é rejeitado e o snapshot final mantém 1 unidade. A concorrência é serializada pelo bloqueio da linha do produto.
- Identificada uma lacuna no slotting físico: a ocupação era calculada a partir de `WarehouseProductPlacement`, sem considerar paletes registadas no mesmo código de localização. Como não existe uma ligação inequívoca entre palete e colocação, somar quantidades poderia duplicar stock e ignorar paletes poderia sobrestimar capacidade livre.
- O endpoint `GET /api/v1/warehouse/physical-slotting` passa agora a excluir conservadoramente localizações com paletes físicas positivas registadas em `location_type=WAREHOUSE` e no mesmo `location_code`, tratando a ocupação como desconhecida. A política da resposta explica a limitação e não converte nem soma quantidades.
- Adicionado teste de integração com JWT que regista uma palete em `SLOT-FAR` e confirma que essa localização deixa de ser candidata, enquanto as restantes regras de capacidade e temperatura continuam aplicadas.
- Commits: `99d1543` (lógica) e `d597d0c` (teste).
- Validação da alteração pendente nos workflows API CI e Quality Gates.


## 18-11-2026 — Paletes sem localização mapeada
- A validação anterior mostrou que a exclusão por código exacto só cobria paletes com um código conhecido. Uma palete positiva de armazém sem código, ou com código que não corresponde a nenhuma localização configurada, podia deixar as localizações elegíveis como se estivessem livres.
- O slotting passa a detectar paletes positivas de armazém sem correspondência em `WarehouseLocation`. Nesse cenário, todas as localizações são tratadas como ocupação desconhecida e rejeitadas, até o registo ser corrigido. A mesma protecção é aplicada às capacidades volumétrica e ponderal.
- O teste de integração foi estendido: depois de confirmar a exclusão de uma localização com código coincidente, regista uma segunda palete sem código e confirma que nenhuma localização é recomendada.
- Commits: `a4e077b` (detecção e teste inicial), `7b55b59` (guarda também na capacidade ponderal).
- Validação CI pendente.


## 18-11-2026 — Ciclo de vida das paletes
- A auditoria confirmou que o endpoint de eventos já usa bloqueio da linha da palete, comparação optimista de estado/quantidade, matriz explícita de transições e persistência conjunta do estado actual e evento de auditoria.
- Acrescentado teste de integração com JWT para cobrir a rejeição de READY → PARTIAL, transição READY → ON_DISPLAY com localização SALES_FLOOR, pedido desactualizado (HTTP 409 sem novo evento) e transição ON_DISPLAY → PARTIAL com redução de quantidade.
- O teste verifica ainda a sequência de três eventos (registo e duas transições), os valores antes/depois e o estado final persistido.
- Commit do teste: `b698950`.
- Validação CI pendente.


## 18-11-2026 — Imutabilidade do histórico de paletes
- Auditoria confirmou que `PalletRotationEvent` era descrito como append-only, mas não tinha triggers de base de dados contra UPDATE/DELETE; os endpoints não expunham operações de edição/apagamento, mas SQL directo continuava a poder alterar o histórico.
- Nova migração `0055_pallet_rotation_events_append_only` cria triggers PostgreSQL e SQLite que rejeitam UPDATE e DELETE em `pallet_rotation_events`.
- Novo script `apps/api/scripts/postgres_pallet_event_immutability_smoke.py` cria palete/evento, tenta ambas as mutações, exige rejeição e confirma os valores originais.
- API CI executa o smoke test imediatamente depois de `alembic upgrade head`, garantindo que a protecção está instalada antes da verificação.
- Commits: migração `11bc8bf`; workflow `0e409e6`; smoke test `41faedf`; TODO `ed7e100`.
- Validação pendente na nova execução da API CI.


## 18-11-2026 — Correcção da expectativa do teste de slotting
- A primeira execução da suite API revelou uma falha exclusivamente na expectativa do teste `test_physical_warehouse_slotting_api_respects_capacity_and_temperature`: esperava que todas as localizações fossem classificadas como `UNKNOWN_CURRENT_OCCUPANCY` quando existe uma palete sem localização.
- A implementação preserva correctamente a precedência de segurança: a localização `SLOT-FROZEN` continua classificada como `TEMPERATURE_INCOMPATIBLE`, enquanto as restantes são excluídas por ocupação desconhecida. Nenhuma localização é recomendada.
- Corrigido o teste para verificar explicitamente as quatro localizações, mantendo a incompatibilidade térmica e a regra de ocupação desconhecida para as outras três.
- Não foi alterada a lógica de produção; a falha era uma asserção demasiado restritiva.
- Commit da correcção: `08679a4`.
- API CI anterior: 1127 passed, 1 skipped, 1 failed; Quality Gates API falhou pelo mesmo teste. Nova validação pendente.


## 18-11-2026 — Validação de localizações de paletes
- Auditoria aos endpoints de registo e eventos confirmou que os códigos de localização WAREHOUSE eram aceites como texto livre, mesmo quando não existiam na loja ou apontavam para uma localização inactiva.
- Adicionada validação partilhada: quando uma palete declara um código WAREHOUSE, este tem de corresponder a uma `WarehouseLocation` da mesma loja e estar activo. Código desconhecido ou localização inactiva devolve HTTP 409; código vazio devolve HTTP 422.
- A validação aplica-se ao registo inicial e à mudança efectiva para uma localização WAREHOUSE. Actualizações sem mudança de localização não revalidam registos históricos antigos.
- Paletes sem `location_code` continuam registáveis para preservar a possibilidade de registar fisicamente uma palete cuja posição ainda não foi identificada; o slotting continua a tratar essa situação como ocupação desconhecida e bloqueia recomendações.
- Novo teste JWT cobre registo em localização desconhecida/inactiva, registo em localização activa, movimentação rejeitada para localização inactiva e movimentação aceite para localização activa.
- O teste do ciclo de vida foi actualizado para criar a localização WAREHOUSE que utiliza.
- Commits: validação `918bbe3`; testes `ac1661d` e `a531265`.
- Validação CI pendente.


## 18-11-2026 — Validação CI da integridade de paletes
- API CI run `44206821156`, SHA `a5312651fb`: sucesso. Suite completa: **1129 passed, 1 skipped, 1 warning**. Todos os smoke tests PostgreSQL passaram, incluindo migrações, histórico append-only das paletes, concorrência de inventário/embalagens e as verificações de autorização.
- Quality Gates run `44206872358`, SHA `df883edbe2`: sucesso. Suite API e compilação passaram; build Web TypeScript/produção também passou.
- O teste de slotting com palete sem localização e o teste de registo/movimentação de paletes com localizações desconhecidas/inactivas estão incluídos na suite aprovada do API CI.
- O teste do ciclo de vida de paletes passou depois de configurar explicitamente a localização WAREHOUSE usada pelo cenário.
- O smoke Demo Docker Compose mais recente observado ainda não terminou; não é considerado validado nesta actualização.


## 18-11-2026 — Validação CI concluída: paletes e slotting
- API CI run `44206821156`, commit `a5312651fb`: sucesso. Suite completa: **1129 passed, 1 skipped, 1 warning** em 61,50 s. Todos os smoke tests PostgreSQL passaram, incluindo migrações, imutabilidade append-only dos eventos de paletes e verificações de concorrência.
- Quality Gates run `44206872358`, commit `df883edbe2`: sucesso. Suite API: **1129 passed, 1 skipped, 1 warning** em 58,05 s; compilação Python e build TypeScript/produção aprovados.
- Demo Docker Compose run `44206821282`, commit `a5312651fb`: sucesso. Build e arranque de API/PostgreSQL/vision worker, readiness, seed de dados de demonstração, verificação do worker/perfis e limpeza dos volumes concluídos.
- O único aviso reportado pela suite foi uma depreciação do alias `anyio.abc.BlockingPortal` usado pelo Starlette TestClient; não causou falha.
- As alterações de validação de localização WAREHOUSE, os testes de registo/movimentação de paletes e a correcção da expectativa de slotting estão incluídos na suite aprovada.
- Os runs intermédios cancelados foram substituídos pelas execuções finais acima; não foram contabilizados como falhas.


## 18-11-2026 — Reconciliação final do estado documental
- Revistos os registos históricos do TODO: as caixas do ciclo de vida e da imutabilidade append-only ainda apareciam como pendentes apesar de os pipelines posteriores as terem validado. Foram alinhadas com os resultados efectivos.
- A validação Docker Compose foi confirmada no run `44206821282`, commit `a5312651fb`: stack API/PostgreSQL/vision worker, readiness, seed e verificações operacionais passaram.
- Quality Gates mais recente, run `44207723589`, commit `84000c0ddf`: API tests/Python compilation e Web TypeScript/production build passaram. A suite API reportou **1129 passed, 1 skipped, 1 warning**.
- Não foi necessária qualquer alteração adicional ao código de produção nesta reconciliação.


## 18-11-2026 — Revisão final do estado documental
- Confirmado no API CI run `44206821156`, commit de código `a5312651fb`: **1129 passed, 1 skipped, 1 warning**; todos os smoke tests PostgreSQL passaram, incluindo o novo teste de imutabilidade do histórico de paletes.
- Confirmado no Quality Gates run `44207723589`, commit `84000c0ddf`: suite API/Python e build Web TypeScript/produção concluídos com sucesso.
- Confirmado no Demo Docker Compose run `44206821282`, commit de código `a5312651fb`: stack, readiness, seed e verificações operacionais passaram.
- Corrigida uma frase antiga no TODO que ainda indicava Docker Compose pendente, apesar do run concluído com sucesso.
- O único aviso da suite API é uma depreciação do Starlette TestClient/AnyIO; não existem falhas de testes nos runs finais observados.


## 18-11-2026 — Auditoria de autorização e isolamento da visão computacional
- Revistos os controlos de autenticação global e os papéis do middleware para as rotas de sessões de captura, uploads, conteúdo binário, deteções, OCR, fusão de evidências, revisões humanas e exemplares de embeddings.
- Confirmada a autenticação Bearer obrigatória em produção para todas as rotas `/api/v1/*`, excepto bootstrap/login; os testes executam explicitamente em `APP_ENV=production` e rejeitam tokens ausentes/inválidos, contas inactivas e papéis JWT falsificados.
- A cobertura existente valida isolamento multi-loja para sessões, upload e sessão associada, conteúdo, deteções, OCR, fusão, histórico/revisão humana, filas de revisão e exemplares de embeddings. As operações de escrita de OCR/fusão/revisão são reservadas a ADMIN/SUPERVISOR; EMPLOYEE mantém apenas os acessos operacionais previstos.
- Não foi identificado um defeito adicional que justificasse alterar código de produção nesta auditoria.
- O API CI run `44206821156` passou com **1129 passed, 1 skipped, 1 warning**; os smoke tests PostgreSQL de retenção versus observação/revisão humana passaram.
- A auditoria do catálogo também foi fechada com base nos testes de isolamento, rejeição de produto inactivo/duplicados e smoke test concorrente PostgreSQL já aprovados.


## 18-11-2026 — Auditoria de segredos e concorrência do bootstrap
- Revistos `apps/api/app/config.py`, os testes de configuração e a documentação de deployment. A validação de produção já rejeita segredos curtos, placeholders, whitespace e reutilização entre JWT e bootstrap; os testes cobrem esses casos.
- Criado `docs/security/production-secrets.md` com geração independente de 256 bits, armazenamento, bootstrap inicial e rotação. A documentação de deployment Vercel referencia o procedimento.
- Detectada uma corrida no endpoint `POST /api/v1/auth/bootstrap`: duas requisições concorrentes podiam observar a tabela `users` vazia antes de cada uma inserir um administrador.
- Corrigido com advisory lock transaccional no PostgreSQL e `BEGIN IMMEDIATE` em SQLite, antes da verificação de existência de utilizadores.
- Adicionado teste API para chave inválida e recusa de segundo bootstrap; criado smoke PostgreSQL concorrente que exige exactamente uma criação e um HTTP 409.
- O Docker Compose passou a encaminhar `APP_ENV`, `JWT_SECRET_KEY` e `BOOTSTRAP_ADMIN_KEY` para API e worker; os defaults permanecem apenas para desenvolvimento e falham a validação quando `APP_ENV=production`.
- Commits: correcção `9586d65`; smoke `336cad9`; workflow `c867dde`; teste API `ddd0164`; documentação de segredos `e3bd947`; Compose `40281c0`; documentação de deployment `abe6230`.
- Validação CI da correcção de bootstrap pendente nesta actualização.
- Limitação operacional: não foi verificada uma instância de produção real; a configuração `APP_ENV=production` está documentada e coberta por testes de Settings, mas os valores do secret store de cada ambiente continuam a ser responsabilidade do operador.


## 18-11-2026 — Validação final da correcção de bootstrap
- API CI run `44251465118`, commit `ddd016401bb2`: **1130 passed, 1 skipped, 1 warning** em 79,07 s. O smoke test PostgreSQL `Verify PostgreSQL concurrent first-admin bootstrap` passou antes da suite completa.
- Quality Gates run `44251681042`, commit `dd8dfc673d97`: **1130 passed, 1 skipped, 1 warning** em 55,42 s; compilação dos módulos Python e build TypeScript/produção passaram.
- Demo Docker Compose run `44251551219`, commit `40281c07a68a`: sucesso com a nova passagem de `APP_ENV`, `JWT_SECRET_KEY` e `BOOTSTRAP_ADMIN_KEY` para API e worker.
- O teste SQLite da rota confirmou que o bloqueio `BEGIN IMMEDIATE` funciona no percurso de teste; o smoke PostgreSQL confirmou serialização real entre duas requisições concorrentes.
- Os três pipelines foram executados em SHAs diferentes, mas cada um contém as alterações relevantes para a sua verificação: API CI incluiu código, smoke e teste; Compose incluiu o ficheiro de stack; Quality Gates executou a HEAD documental final.
- O único aviso é a depreciação de `anyio.abc.BlockingPortal` usada pelo Starlette TestClient; sem falhas.


## 18-11-2026 — Auditoria concorrente do vision worker
- Revistos `apps/api/app/vision_worker.py`, o fluxo de recuperação de tarefas `PROCESSING`, a reivindicação de imagens `PENDING`, a comparação do timestamp da lease e a revalidação do estado de retenção antes de persistir resultados.
- Confirmado que a recuperação usa `SELECT FOR UPDATE SKIP LOCKED` e ordenação crescente por ID; os workers concorrentes não aguardam por linhas já bloqueadas e podem recuperar as restantes.
- Alargado `apps/api/scripts/postgres_vision_worker_recovery_smoke.py` para PostgreSQL real: recuperação de duas tarefas com uma linha bloqueada, fencing de inferência bem-sucedida após takeover, rejeição de deteções quando a imagem passa a `RESTRICTED` durante a inferência e fencing de excepções do provider antigo após takeover.
- O smoke PostgreSQL passou no API CI run [44254466581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44254466581). A suite completa terminou com **1133 passed, 1 skipped, 1 warning**.
- Quality Gates run [44254466640](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44254466640) passou com **1133 passed, 1 skipped, 1 warning**, compilação Python e build TypeScript/produção aprovados.
- Demo Docker Compose run [44254466613](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44254466613) passou.
- Conclusão limitada: o fencing impede que um worker antigo altere resultados depois de perder a lease. Não foi introduzido heartbeat periódico durante inferências longas; a recuperação continua dependente de `VISION_PROCESSING_TIMEOUT_SECONDS`, pelo que esse timeout deve exceder a duração normal/máxima esperada do provider. A duplicação de inferência durante um takeover pode ocorrer, mas só a tentativa que ainda detém a lease pode persistir.


## 18-11-2026 — Paginação do histórico de retenção de imagens
- Identificado um endpoint de auditoria append-only sem limite de resultados: `GET /api/v1/shelf-images/{image_id}/retention/events`.
- Adicionada paginação por `limit` e `offset`, com ordenação cronológica estável por `created_at` e `id`, limite predefinido de 100 e máximo de 500 eventos por resposta. O comportamento mantém compatibilidade com consumidores existentes que não enviam parâmetros.
- O teste do ciclo de legal hold passou também a verificar duas páginas consecutivas e a normalização de `limit=0` / `offset=-10`.
- API CI run [44254865551](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44254865551) e Quality Gates run [44254865747](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44254865747) executaram o código; Quality Gates passou com **1133 passed, 1 skipped, 1 warning**, compilação Python e build web aprovados. Demo Docker Compose run [44254865566](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44254865566) passou. API CI estava a concluir a suite na última consulta; confirmar o estado final antes de fechar a validação global.
- A auditoria global de paginação e custos de consulta continua aberta: esta alteração cobre apenas o histórico de retenção por imagem, não todas as listagens de deteções, OCR, fusão e referências de artefactos.


## 2026-11-18 — Paginação de endpoints de visão computacional
- Acrescentado `offset` com clamp para valores negativos e limites máximos já existentes nas listagens de imagens, deteções, correspondências OCR, evidências OCR, execuções OCR e evidência fundida.
- As listagens de imagens ganharam desempate por ID para ordenação estável; as restantes mantêm ordenação por identificador persistente.
- Na evidência fundida, a filtragem por estado é aplicada antes do corte da página, evitando páginas vazias/incorrectas causadas por filtrar apenas depois de paginar. A leitura continua limitada a um máximo de 1000 registos por pedido.
- Preservados os controlos de autorização, isolamento por loja e estado ACTIVE das imagens.
- Adicionado teste de regressão para paginação das deteções, incluindo fronteira entre páginas, `limit=0` e `offset` negativo.
- Commits: `a475e7f` (endpoints), `b7d6d98` (teste), `a97fb8d` (ordenação da paginação da evidência fundida).
- Validação API CI, Quality Gates e Docker Compose pendente; não declarar a alteração validada até os workflows terminarem.
- O gate global de paginação/custos continua aberto: faltam auditoria sistemática de todos os endpoints derivados de imagem, contagens totais, índices e avaliação de planos de consulta.


## 2026-11-18 — Paginação adicional de auditoria de artefactos e revisões humanas
- Acrescentado `offset` limitado e ordenação estável a `GET /api/v1/shelf-images/{image_id}/artifacts`, ao histórico imutável de `disposition-events` e ao histórico de revisões humanas de deteções.
- A autorização ADMIN, o isolamento por loja, a verificação da relação imagem/artefacto e o bloqueio de leitura de imagens não activas mantêm-se antes da consulta paginada.
- Testes de regressão adicionados para referências, eventos de disposição e histórico de revisões: duas páginas consecutivas, `limit=0` e `offset` negativo.
- Commits de implementação/testes: `2180c02`, `8a9e676`, `e645e7b`.
- Quality Gates [44256610346](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44256610346): **1136 passed, 1 skipped, 1 warning**; compilação Python e build TypeScript/produção aprovados.
- Demo Docker Compose [44256610406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44256610406): build, arranque, readiness, seed e perfis do worker aprovados.
- API CI [44256610563](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44256610563): todos os smoke tests PostgreSQL concluídos com sucesso; suite API ainda estava em execução na última consulta. Não declarar o workflow integralmente concluído até confirmar o resultado final.
- Limitação mantida: a auditoria global de custos de consulta continua aberta; faltam contagens totais, revisão sistemática de índices e análise de planos em dados representativos.
