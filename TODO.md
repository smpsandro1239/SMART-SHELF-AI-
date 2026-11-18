## Leitura obrigatória do README e correcção do smoke PostgreSQL — 2026-11-18

- [x] Reforçar o protocolo autónomo: ler integralmente o README antes de cada ronda, por blocos quando necessário, e não apenas os títulos ou o resumo.
- [x] Corrigir a asserção do smoke `postgres_store_employee_authorization_smoke.py`: o ADMIN global pode ver funcionários activos criados por outros smokes que partilham a base PostgreSQL do CI; validar inclusão dos dois funcionários desta ronda e exclusão do inactivo, sem assumir que a lista global contém apenas duas linhas.
- [ ] Aguardar nova execução API CI/PostgreSQL após esta correcção; o run [44308942806](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44308942806) falhou apenas neste assert do smoke, enquanto o Docker Compose smoke [44308942877](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44308942877) passou.
- [ ] Manter aberta a auditoria global de autorização handler-a-handler; esta correcção não aumenta a cobertura funcional dos endpoints.

## Atualização da auditoria de autorização — 2026-11-18

- [x] Confirmar no API CI [44291136290](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291136290) que a suite API passou (1148 aprovados, 1 ignorado, 1 aviso), incluindo os testes JWT de upload que estavam documentados como pendentes.
- [x] Confirmar no mesmo run o smoke PostgreSQL de autorização multi-loja das sessões de captura; o passo dedicado terminou com sucesso.
- [ ] Manter aberta a auditoria exaustiva de autorização por rota e handler: estes resultados validam apenas os cenários cobertos pelos testes existentes.

## Auditoria de desempenho PostgreSQL — 2026-11-18

- [x] Criar auditoria `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` em transacção `READ ONLY`, com timeout, validação da relação imagem/loja e sem operações de escrita.
- [x] Cobrir planos das listagens de imagens, deteções, OCR matches/evidence, eventos de retenção e subconsulta da fila de revisão SKU.
- [x] Acrescentar testes unitários aos SELECTs limitados e à validação de IDs.
- [x] Validar script/testes no API CI [44291136290](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291136290): **1148 passed, 1 skipped, 1 warning**; Quality Gates [44291194461](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291194461) passou; Docker Compose [44291133419](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291133419) passou.
- [ ] Executar em staging/réplica com volume representativo, analisar os planos e medir paginação profunda antes de propor índices ou keyset pagination.

## Planeamento de picking — integridade de colocações (2026-11-18)

- [x] Tornar o planeamento fail-closed quando recebe mais de uma linha para o mesmo par SKU/localização, evitando contar stock físico duplicado.
- [x] Excluir todas as linhas ambíguas desse par, sem afetar o mesmo local quando contém SKUs diferentes.
- [x] Acrescentar testes de regressão para duplicados e para SKUs distintos na mesma localização.
- [x] Validar a alteração no API CI run [44271596288](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44271596288) (commit `30f3b4e`) e Quality Gates run [44271717562](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44271717562) (commit `93abecc`); Docker Compose smoke [44271596168](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44271596168) também passou.

## Validação de concorrência de retenção — 2026-11-18

- [x] O smoke PostgreSQL cobre as duas ordens concorrentes entre restauro e agendamento de purga.
- [x] API CI run [44268766212](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44268766212), commit `ff59e475a6694985747b4b055aacd06c37aec053`: migrações PostgreSQL, todos os smokes operacionais (incluindo `postgres_retention_legal_hold_concurrency_smoke.py`) e suite API concluídos com sucesso.
- [x] Quality Gates run [44268807130](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44268807130), HEAD `0024f326bbe98ae09834c273163326809b28b5cd`, tentativa 2: API e Web concluídos com sucesso; **1 140 testes aprovados, 1 ignorado, 1 aviso**; compilação Python e build TypeScript/produção aprovados.
- [x] Docker Compose smoke run [44268766432](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44268766432), commit `ff59e475`: build, arranque, readiness, seed e validação dos perfis concluídos com sucesso.
- [x] Fechar a auditoria automatizada de concorrência legal hold/restauro/agendamento de purga.
- [ ] A execução de purga física continua deliberadamente indisponível; não existe executor operacional e a API mantém-se fail-closed.

## Concorrência entre restauro e agendamento de purga (18-11-2026)
- [x] Alargar o smoke PostgreSQL de retenção para cobrir as duas ordens de concorrência entre restauro e agendamento de purga.
- [x] Validar no API CI que um restauro confirmado primeiro faz o agendamento concorrente devolver HTTP 409 (API CI 44268766212).
- [x] Validar no API CI que um agendamento confirmado primeiro é cancelado pelo restauro, com limpeza da data/política e eventos append-only PURGE_CANCELLED e RESTORED (API CI 44268766212).
- [x] Confirmar suite API, Quality Gates e smoke PostgreSQL: API CI 44268766212; Quality Gates 44268807130 (1 140 passed, 1 skipped); Docker Compose 44268766432.

# TODO

## Security and reliability

- [x] Auditar autorização e isolamento multi-loja nos endpoints de visão computacional: sessões de captura, uploads, conteúdo, deteções, OCR, fusão de evidências, revisões humanas e embeddings; cobertura de regressão existente validada no CI.
- [x] Adicionar e validar no PostgreSQL a concorrência entre retenção de imagens e criação de observações/revisões humanas; os smoke tests de bloqueio e revalidação passaram no API CI.
- [x] Concluir a auditoria do catálogo/produto-prateleira: autorização, isolamento por loja, produtos inativos, associações duplicadas e concorrência PostgreSQL cobertos; semântica global do catálogo ADMIN documentada e validada no CI.
- [x] Complete the worker retry, lease-expiry and retention-transition audit under concurrent execution. PostgreSQL smoke coverage verifies `SKIP LOCKED` stale-job recovery, recovery after lock release, successful-result fencing, stale-provider-failure fencing and rejection of detections when retention changes to `RESTRICTED` during inference. API CI and Quality Gates passed on commit `3d35ad7b` (1133 passed, 1 skipped, 1 warning).
- [x] Verify production authentication configuration rejects anonymous access to all protected API routes; route inventory regression passed in API CI.
- [x] Test production secret validation, including whitespace rejection; document the required `APP_ENV=production` setting for Vercel and Docker Compose.
- [x] Document production secret generation, storage, first-admin bootstrap and JWT/bootstrap/database credential rotation in `docs/security/production-secrets.md`.
- [x] Review JWT and bootstrap secret lifecycle; document single-key JWT rotation and one-time bootstrap behaviour.
- [x] Re-run API, frontend, Docker Compose and PostgreSQL smoke suites after the latest backend/security changes; all final runs passed.

## Product quality

- [ ] Review pagination, filtering and bounded query costs on image-derived data endpoints.
  - [x] Add a read-only PostgreSQL plan audit for image, detection, OCR, retention and SKU-review queue query shapes; see `docs/PERFORMANCE-QUERY-AUDIT.md`.
  - [ ] Run the audit against representative staging/read-replica data and review deep-page costs before changing indexes or pagination contracts.
  - [x] Add page-size-bounded offset pagination with stable ordering to shelf-image lists, detections, OCR matches/evidence/runs and fused evidence; preserve store scoping and retention checks. Regression covers detection page boundaries and invalid bounds.
  - [x] Paginate the append-only image retention event history with deterministic chronological ordering, a default page of 100 and a hard maximum of 500; cover page boundaries and negative/zero parameter clamping. API CI and Quality Gates passed on commit `92d0add53d`.
  - [x] Add offset pagination to external artifact references, immutable disposition events and human SKU review history; preserve admin/store authorization and append-only ordering.
  - [x] Add regression tests for artifact and disposition page boundaries, negative/zero bounds and human review history pages.
  - [x] Finish API CI, Quality Gates and Docker Compose validation for the pagination changes: API CI run `44256610563` passed (1136 passed, 1 skipped, 1 warning); Quality Gates run `44256985942` passed (API tests/compilation and Web TypeScript/production build); Docker Compose run `44256610406` passed.
  - [x] Correct fused-evidence status-filter pagination: recompute status before applying the filtered offset, scan bounded keyset batches, and acquire all relevant product locks in ascending ID order to preserve the global image→product lock order.
  - [x] Add regression coverage for filtered pagination after catalogue revalidation and for offsets crossing the 500-row keyset batch boundary.
  - [x] Validate the filtered fused-evidence pagination regression and lock-order change in API CI (`44265754667`) and Quality Gates (`44265786855`); both completed successfully.
- [x] Complete the automated retention/legal-hold lifecycle audit across restore, purge scheduling, cancellation and concurrent transitions. Physical purge execution remains intentionally unimplemented and fail-closed.
  - [x] Cover restore cancellation, purge schedule/cancellation audit events, overdue purge blocking under legal hold, and preservation of the scheduled date/policy while a hold is applied/released.
  - [x] Validate legal-hold release audit assertions in API CI run `44266521498`; Docker Compose smoke `44266521499` and Quality Gates `44266547157` also passed.
  - [x] Validate the PostgreSQL race smoke for simultaneous legal-hold/purge-schedule and restore/purge-schedule transitions; API CI run `44268766212` passed all smoke steps.
- [x] Reconcile ROADMAP.md with implemented capabilities, current CI evidence and remaining operational blockers (2026-11-18).
- [x] Implement dashboard UX refinements: human-readable durations, Europe/Lisbon timestamps, stronger contrast palette, non-colour status cues, compact single-task layout and clickable summary cards with exact task-state filters; Web CI and frontend quality build passed.
- [x] Add a visible-on-focus skip link, labelled desktop navigation landmark, keyboard focus outlines for interactive controls and equivalent mobile navigation controls.
- [x] Substituir o cartão interactivo de zona por um botão nativo e anunciar o carregamento da avaliação operacional com `role=status`/`aria-live=polite`; Web CI [44296222519](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44296222519) passou e Quality Gates [44296524262](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44296524262) passou com testes API e build Web concluídos.
- [x] Validar a alteração de navegação acessível no Web CI [44292103581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44292103581) e Quality Gates [44292103676](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44292103676), ambos aprovados no commit `5ca7babcd3529f4459a50eaf5542aa289db91d05`.
- [ ] Complete manual browser/keyboard, screen-reader and full-state contrast audit before claiming formal WCAG 2.2 AA conformance.


## Integridade das unidades logísticas (17-11-2026)
- [x] Adicionar índices únicos parciais para garantir uma única unidade activa de encomenda e uma única unidade activa de reposição por produto, ao nível da base de dados.
- [x] Acrescentar teste API para rejeitar configurações duplicadas de unidades logísticas.
- [x] Integrar smoke test de concorrência PostgreSQL no API CI.
- [x] Confirmar migração 0054 e smoke de concorrência no API CI; índices únicos parciais aplicados em PostgreSQL e SQLite.
- [x] Endurecer a migração 0054 com preflight que identifica até 20 produtos duplicados por função (unidade de encomenda/reposição), aborta antes de criar índices e não altera dados.
- [x] Validar o preflight/downgrade na suite API (incluindo testes SQLite) e a cadeia de migrações PostgreSQL no API CI `44265754667`; smoke de migrações e unicidade concorrente passaram.
- [ ] Avaliar dados existentes antes de aplicar a migração em ambientes com histórico real; duplicados preexistentes devem ser saneados antes da criação dos índices.


## Inventário físico e registo de paletes (17-11-2026)
- [x] Confirmar que o registo de uma palete física valida produto, embalagem PALLET, capacidade e loja, e cria evento inicial de auditoria.
- [x] Acrescentar regressão que confirma que registar uma palete não altera snapshots agregados nem movimentos de stock; a palete é um registo físico, não uma recepção automática de inventário.
- [x] Validar a regressão de registo físico de paletes no API CI, Quality Gates e Demo Docker Compose.
- [ ] Definir, numa fase própria, uma reconciliação explícita entre paletes físicas e stock agregado; não somar automaticamente estes domínios enquanto não existir regra de negócio para evitar dupla contabilização.


## Integridade das colocações de armazém (18-11-2026)
- [x] Rejeitar a criação de colocações em localizações inactivas.
- [x] Rejeitar a criação de colocações para produtos inactivos.
- [x] Acrescentar teste de regressão que confirma HTTP 409 e ausência de persistência nos dois cenários.
- [x] Validar a alteração de rejeição de colocações inactivas na suite API CI, Quality Gates e Demo Docker Compose.
- [ ] Definir e testar uma política explícita de capacidade/peso/temperatura para colocações; não impor bloqueios sem garantir que o perfil físico do produto está configurado e que a regra representa a operação real.


## Slotting físico — validação do endpoint (18-11-2026)
- [x] Acrescentar teste de integração com JWT para o endpoint de slotting físico.
- [x] Cobrir capacidade volumétrica, peso calculado, compatibilidade de temperatura e ordenação por distância.
- [x] Confirmar que as recomendações não autorizam movimentos automáticos nem reserva de stock.
- [x] Validar o teste de integração do slotting físico no API CI e Quality Gates.


## Reconciliação entre paletes e slotting físico (18-11-2026)
- [x] Confirmar que tarefas distintas do mesmo produto não conseguem consumir concorrencialmente o mesmo stock agregado; o smoke PostgreSQL existente verifica que apenas um movimento é persistido.
- [x] Evitar recomendações de capacidade para localizações cujo código coincide com paletes físicas registadas no armazém, enquanto não existir ligação inequívoca palete-colocação.
- [x] Acrescentar teste de integração com JWT para a exclusão conservadora de uma localização ocupada por palete física.
- [x] Validar o teste de exclusão conservadora de paletes no slotting na suite API CI e Quality Gates.
- [ ] Definir um modelo explícito de transferência/reconciliação palete-colocação, com identificadores e eventos auditáveis, antes de agregar quantidades entre os dois registos.


## Paletes sem localização mapeada — slotting seguro (18-11-2026)
- [x] Tratar paletes de armazém com localização vazia ou não mapeada como ocupação desconhecida.
- [x] Excluir conservadoramente todas as localizações do slotting enquanto existir uma palete de armazém sem correspondência com uma localização configurada.
- [x] Cobrir com teste de integração a palete sem código de localização.
- [x] Validar o novo cenário na API CI e Quality Gates.


## Ciclo de vida de paletes — cobertura de integração (18-11-2026)
- [x] Testar rejeição de transições de estado não permitidas.
- [x] Testar transição READY → ON_DISPLAY com localização SALES_FLOOR.
- [x] Testar actualização de quantidade e estado para PARTIAL.
- [x] Testar rejeição HTTP 409 de actualização baseada num estado desactualizado, sem evento adicional.
- [x] Validar o novo teste na API CI e Quality Gates.


## Imutabilidade do histórico físico de paletes (18-11-2026)
- [x] Adicionar protecção de base de dados contra UPDATE e DELETE em `pallet_rotation_events` para PostgreSQL.
- [x] Adicionar triggers equivalentes para SQLite nas migrações.
- [x] Criar smoke test PostgreSQL que tenta alterar e apagar um evento e confirma a preservação dos valores originais.
- [x] Integrar o smoke test no API CI imediatamente após `alembic upgrade head`.
- [x] Validar migração e smoke test na API CI.


## Correcção da expectativa de rejeição no slotting (18-11-2026)
- [x] Corrigir o teste de palete sem localização para respeitar a precedência das regras de segurança.
- [x] Confirmar que a localização FROZEN continua rejeitada por incompatibilidade térmica.
- [x] Confirmar que as restantes localizações ficam bloqueadas por ocupação desconhecida.
- [x] Reexecutar API CI e Quality Gates após a correcção.


## Validação de localizações de paletes (18-11-2026)
- [x] Ao registar paletes em WAREHOUSE, rejeitar códigos de localização não configurados para a loja.
- [x] Ao registar paletes em WAREHOUSE, rejeitar localizações inactivas.
- [x] Ao movimentar paletes para WAREHOUSE, validar a localização de destino quando o código muda.
- [x] Preservar o registo de paletes sem código de localização, para manter a rastreabilidade de dados incompletos e o bloqueio conservador do slotting.
- [x] Testar rejeição de códigos desconhecidos/inactivos e aceitação de localização activa.
- [x] Validar suite API e Quality Gates; Docker Compose validado no commit de código `a5312651fb`.


## Resultados de validação — 18-11-2026
- [x] API CI: 1129 testes passaram, 1 ignorado, 1 aviso; run `44206821156` (SHA `a5312651fb`).
- [x] Quality Gates: suite API e compilação concluídas com sucesso; run `44206872358` (SHA `df883edbe2`).
- [x] Quality Gates Web TypeScript/build de produção concluído com sucesso.
- [x] Demo Docker Compose: run `44206821282` no commit `a5312651fb` concluído com sucesso.


## Validação CI — paletes e slotting (18-11-2026)
- [x] API CI: 1129 testes passaram, 1 ignorado, 1 aviso de depreciação.
- [x] Quality Gates: 1129 testes passaram, 1 ignorado, 1 aviso de depreciação; compilação Python e build TypeScript/produção aprovados.
- [x] Docker Compose demo stack: build, arranque, readiness da API, seed e verificação do worker/perfis aprovados.
- [x] Smoke tests PostgreSQL, incluindo migrações e imutabilidade dos eventos de paletes, aprovados.


## Limpeza de estado de validação — 18-11-2026
- [x] Alinhar as caixas de verificação antigas do ciclo de vida e da imutabilidade com os resultados finais dos pipelines.
- [x] Remover a indicação de Docker Compose pendente, substituindo-a pelo run concluído com sucesso.


## Concorrência do bootstrap do primeiro administrador (18-11-2026)
- [x] Serializar o bootstrap no PostgreSQL com advisory lock transaccional.
- [x] Serializar a transacção SQLite com `BEGIN IMMEDIATE`.
- [x] Acrescentar teste API para chave inválida e recusa de segundo bootstrap.
- [x] Acrescentar smoke test PostgreSQL concorrente: duas requisições simultâneas, uma criação, um HTTP 409 e uma única conta ADMIN.
- [x] Validar o smoke test concorrente de bootstrap e a suite completa no API CI, Quality Gates e Docker Compose.


## Validação CI — bootstrap e gestão de segredos (18-11-2026)
- [x] API CI run `44251465118`, commit `ddd016401bb2`: **1130 passed, 1 skipped, 1 warning**; smoke PostgreSQL de bootstrap concorrente aprovado.
- [x] Quality Gates run `44251681042`, commit `dd8dfc673d97`: **1130 passed, 1 skipped, 1 warning**; compilação Python e build Web TypeScript/produção aprovados.
- [x] Demo Docker Compose run `44251551219`, commit `40281c07a68a`: stack concluída com sucesso após a alteração de passagem de variáveis de ambiente.
- [x] A suite mantém apenas um aviso de depreciação Starlette/AnyIO; não houve falhas.

## Auditoria de autorização — integrações externas (18-11-2026)
- [x] Confirmar que os quatro handlers de gestão de integrações externas exigem explicitamente perfil ADMIN.
- [x] Acrescentar teste JWT HTTP para criação, listagem, alteração e consulta de cobertura por loja, com SUPERVISOR e EMPLOYEE.
- [x] API CI run `44299045159` no commit `297f924`: **1149 passed, 1 skipped, 1 warning**; teste JWT HTTP executado com sucesso.
- [ ] Rever a cobertura de autorização dos endpoints restantes, handler-a-handler e nos caminhos indirectos.

### Reconciliação do inventário HTTP (18-11-2026)
- [x] Comparar as declarações de rotas literais em `apps/api/app/main.py` com `docs/security/http-route-inventory.md`.
- [x] Identificar e integrar as 16 declarações em falta na tabela principal; inventário actualizado de 107 para 123 rotas, sem entradas obsoletas (commit `a60ac242`).
- [x] Quality Gates run `44299324366`: API tests/compilação Python e build Web TypeScript/produção aprovados.
- [x] Demo Docker Compose run `44299045038`: build, readiness, seed e verificação dos perfis/worker aprovados.
- [ ] Concluir a auditoria de autorização handler-a-handler; inventário estático não é prova de controlo de acesso.

## Diretório de funcionários — autorização multi-loja (18-11-2026)
- [x] Rever o handler `GET /api/v1/store-employees`: ADMIN global; SUPERVISOR limitado à própria loja; apenas EMPLOYEE activos são devolvidos.
- [x] Acrescentar teste JWT HTTP para supervisor, administrador e funcionário, incluindo filtro cross-store e exclusão de inactivos.
- [x] Validar o novo teste no API CI e Quality Gates (API CI run 44337777007; Quality Gates run 44337776819).
- [ ] Avaliar se o endpoint necessita de smoke PostgreSQL específico; não declarar essa validação sem execução real.



## Diretório de funcionários — autorização PostgreSQL (18-11-2026)
- [x] Criar smoke test HTTP com JWT reais contra PostgreSQL 16 para o endpoint `GET /api/v1/store-employees`.
- [x] Cobrir SUPERVISOR limitado à própria loja, exclusão de funcionários inactivos, filtro cross-store recusado, ADMIN com filtro de loja e EMPLOYEE recusado.
- [x] Integrar o smoke no workflow API CI após a validação das migrações.
- [x] Confirmar a execução do smoke PostgreSQL, incluindo o diretório de funcionários, e da suite API no API CI (run 44337777007).

- [x] Reforçar o smoke PostgreSQL do diretório de funcionários: ausência de Bearer, JWT inválido e conta SUPERVISOR inactiva (401); ADMIN global só recebe funcionários activos; manter testes de isolamento por loja e recusa EMPLOYEE.
- [x] Confirmar o cenário reforçado no API CI/PostgreSQL (run 44337777007).


## Governação de artefactos externos de imagens — autorização HTTP (18-11-2026)
- [x] Rever handlers de registo/listagem de artefactos, snapshots de inventário, decisão de acesso e eventos de disposição: todos exigem ADMIN antes de consultar ou alterar dados.
- [x] Acrescentar teste JWT HTTP para SUPERVISOR e EMPLOYEE nas seis operações.
- [x] Verificar que os pedidos recusados não criam artefactos, snapshots ou eventos de disposição.
- [x] Suite API (`pytest -q`), API CI e Quality Gates aprovados (runs 44337777007 e 44337776819).
- [ ] Continuar auditoria handler-a-handler; esta ronda não fecha a auditoria global.


## Integrações externas por loja — autorização HTTP (18-11-2026)
- [x] Rever criação, listagem, consulta de cobertura e actualização de integrações externas; os quatro handlers exigem ADMIN.
- [x] Acrescentar teste HTTP/JWT para SUPERVISOR e EMPLOYEE nos quatro métodos.
- [x] Verificar 403 e ausência de criação/alteração de integrações após pedidos recusados.
- [ ] Confirmar suite API, API CI e Quality Gates no novo commit.
