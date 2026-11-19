## Reconciliação conservadora de outputs (2026-11-19)

- [x] Criar `app.dataset_job_output_reconciliation` com modo read-only por defeito e `--apply` explícito.
- [x] Remover apenas temporários `.promotion-*.tmp` regulares e antigos, respeitando o período de segurança configurado.
- [x] Remover staging apenas quando existe publicação append-only correspondente e destino/staging confirmam o mesmo digest e tamanho.
- [x] Preservar jobs `SUCCEEDED` sem publicação, symlinks, ficheiros recentes, jobs desconhecidos e conteúdos divergentes.
- [x] Acrescentar testes para dry-run, aplicação, preservação de staging sem publicação e mismatch de digest.
- [x] Documentar o procedimento e os limites operacionais em `docs/operations/dataset-output-reconciliation.md`.
- [x] Quality Gates [44484598129](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44484598129) e Docker Compose [44484598370](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44484598370) passaram.
- [x] API CI [44484598295](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44484598295) passou, incluindo smokes PostgreSQL e suite API.
- [ ] Definir isolamento filesystem e reconciliação de staging de jobs falhados/revogados; o módulo actual não assume que workers antigos deixaram de escrever.

## Publicação de outputs — reduzir janela de locks (2026-11-19)

- [x] Separar preparação do ficheiro (leitura, cópia, limite de tamanho e SHA-256) da transacção final, sem locks de linhas durante operações de I/O potencialmente longas.
- [x] Revalidar job, evento terminal, fencing token, worker, credencial, revogação, validade e scope depois da preparação e sob locks na transacção final.
- [x] Limitar a secção crítica a hard link sem sobrescrita e registo append-only; remover staging apenas depois do commit.
- [x] Acrescentar regressão que revoga a credencial durante a preparação e exige recusa na revalidação final, sem publicar bytes nem registar auditoria.
- [x] API CI [44483199562](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44483199562) passou no commit de código `5767468ad8058a593474695b2cb0dee9ef3118e7`, incluindo migrations PostgreSQL, smoke de publicação concorrente/fencing/auditoria e suite API.
- [x] Quality Gates [44483436546](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44483436546) passou no commit documental `5e84a0cec8cc15ca829aa6eda1694d8013819858`: compilação Python, suite API, TypeScript e build Web de produção.
- [x] Docker Compose [44483199541](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44483199541) passou no commit de código: build, arranque, readiness, seed e worker demonstrativo.
- [x] Smoke PostgreSQL dedicado integrado em `postgres_dataset_job_output_publication_smoke.py`: a revogação confirma numa segunda sessão enquanto a preparação está pausada; depois, a revalidação final recusa a publicação. API CI [44485569053](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44485569053) passou.
- [ ] Acrescentar reconciliação periódica e limpeza segura de temporários/staging órfãos; não apagar automaticamente ficheiros sem confirmar job, token, digest e registo de publicação.

## Gestão HTTP de integrações externas — percurso ADMIN e isolamento de loja (2026-11-18)

- [x] Acrescentar teste JWT HTTP do percurso ADMIN para criar, listar, consultar cobertura e revogar uma integração.
- [x] Verificar isolamento por loja: listagem da loja B vazia e PATCH de integração da loja A através do caminho da loja B devolve 404 sem alterar o registo.
- [x] Confirmar que a resposta não expõe campos de credenciais/chaves e que a auditoria identifica o ADMIN.
- [ ] Confirmar API CI e Quality Gates no commit desta ronda; o teste usa SQLite isolado e não substitui um smoke PostgreSQL específico dos handlers.
- [ ] Continuar auditoria handler-a-handler; a cobertura não fecha a auditoria global.

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
- [x] Confirmar suite API, API CI e Quality Gates (API CI run 44338653668; Quality Gates run 44338651433).


## Integrações externas — fluxo ADMIN de ponta a ponta por HTTP (18-11-2026)
- [x] Acrescentar teste positivo para criação, listagem, consulta de cobertura e revogação com JWT ADMIN.
- [x] Verificar resposta sem material secreto, estado inicial nunca observado e cobertura após revogação.
- [ ] Validar suite API e Quality Gates no CI.

## Fluxos de revisão humana — autorização de funcionários (18-11-2026)
- [x] Rever as rotas de fila de revisão, resumo, avaliação SKU revista, candidatos de treino revistos e submissão de revisão de deteção.
- [x] Acrescentar teste HTTP/JWT que confirma que EMPLOYEE recebe 403 nas cinco operações.
- [x] Verificar que a tentativa de submissão recusada não cria registos de revisão.
- [ ] Validar a nova cobertura no API CI e Quality Gates.
- [ ] Continuar a auditoria handler-a-handler e confirmar isolamento multi-loja nos restantes fluxos de visão.

**Limite:** a cobertura acrescentada valida a barreira de perfil EMPLOYEE do middleware em ambiente production com SQLite isolado. Não prova concorrência PostgreSQL nem conclui a auditoria global.

## Isolamento multi-loja — localizações e colocações de armazém (18-11-2026)
- [x] Acrescentar teste HTTP/JWT que tenta listar localizações da loja B com supervisor da loja A.
- [x] Testar criação de localização na loja B por supervisor da loja A.
- [x] Testar colocação de produto numa localização da loja B por supervisor da loja A.
- [x] Confirmar 403 nas três operações e ausência de novas localizações/colocações.
- [ ] Validar a nova cobertura no API CI e Quality Gates.
- [ ] Prosseguir a revisão de isolamento multi-loja nos restantes recursos de armazém e inventário.

**Limite:** teste HTTP com SQLite isolado; não substitui smoke PostgreSQL nem conclui a auditoria global.

## Isolamento multi-loja — paletes e rotação (18-11-2026)
- [x] Acrescentar teste HTTP/JWT para listagem e registo de paletes de outra loja.
- [x] Cobrir actualização de política de rotação por identificador pertencente à loja B.
- [x] Cobrir leitura e escrita de eventos de ciclo de vida de uma palete da loja B.
- [x] Confirmar 403 e ausência de alterações em eventos, política e estado da palete.
- [ ] Validar a nova cobertura no API CI e Quality Gates.
- [ ] Prosseguir auditoria das operações de simulação, portefólio e histórico com referências cruzadas entre lojas.

**Validação anterior:** no commit d39adb2, Quality Gates e Docker Compose smoke passaram; API CI continuava em execução no momento da revisão. O novo teste ainda não foi executado.

## Isolamento multi-loja — vendas e previsões (18-11-2026)
- [x] Acrescentar teste HTTP/JWT para ingestão diária/horária, tráfego e batches.
- [x] Cobrir histórico horário, previsão de procura, risco de rutura, portefólio e perfil horário de rotação.
- [x] Exigir 403 para supervisor da loja A em operações sobre a loja B.
- [x] Confirmar ausência de novas linhas de vendas e tráfego após pedidos recusados.
- [ ] Validar no API CI e Quality Gates; prosseguir revisão de imports CSV e restantes caminhos de ingestão.

**Limite:** teste HTTP/JWT com SQLite isolado; não substitui smoke PostgreSQL nem conclui a auditoria multi-loja.


## Isolamento multi-loja — importações CSV horárias (18-11-2026)
- [x] Cobrir importação CSV de vendas horárias e tráfego com JWT SUPERVISOR da loja A e `store_id` da loja B.
- [x] Exigir HTTP 403 antes da validação do conteúdo CSV e confirmar ausência de novas linhas persistidas.
- [ ] Validar o novo teste no API CI e Quality Gates.
- [ ] Acrescentar/confirmar cobertura PostgreSQL dedicada para isolamento multi-loja das importações.

**Limite:** o teste HTTP/JWT usa SQLite isolado. O payload de vendas é intencionalmente inválido para demonstrar que a autorização ocorre antes do parsing; a ausência de efeitos laterais é verificada nas duas tabelas operacionais.


## Autorização PostgreSQL nas importações CSV horárias (18-11-2026)
- [x] Acrescentar smoke PostgreSQL com JWT real para importação horária de vendas e tráfego.
- [x] Testar uploads multipart de SUPERVISOR da loja A para a loja B; exigir 403 antes de parsing e confirmar ausência de linhas persistidas.
- [x] Confirmar importações válidas na própria loja com persistência de exactamente uma linha por endpoint.
- [x] Validar API CI, Quality Gates e Docker Compose smoke no commit `1e3499c8c80ef75494a29d06807469898471e4e1` (todos passaram).


## Importação CSV diária — isolamento multi-loja (18-11-2026)
- [x] Alargar o teste JWT HTTP ao endpoint `POST /api/v1/sales/import-csv`.
- [x] Alargar o smoke PostgreSQL com JWT real para os três endpoints CSV de vendas/tráfego.
- [x] Cobrir rejeição antes do parsing, ausência de efeitos laterais e caminho positivo na loja autorizada.
- [x] Validar a execução no API CI, Quality Gates e Docker Compose smoke do commit `1e3499c8c80ef75494a29d06807469898471e4e1` (todos passaram).


## Hierarquia de lojas — zonas e prateleiras (18-11-2026)
- [x] Testar leitura de zonas e prateleiras por SUPERVISOR limitada à loja atribuída.
- [x] Testar recusa explícita de filtro para outra loja e de escrita por SUPERVISOR/EMPLOYEE.
- [x] Testar criação positiva de zona e prateleira por ADMIN.
- [ ] Validar a nova cobertura no API CI e Quality Gates.
- [ ] Complementar com revisão PostgreSQL das constraints/triggers de linhagem hierárquica já existentes.


## Batches multi-loja e cobertura de forecasting — 18-11-2026
- [x] Confirmar que os schemas dos batches exigem que todos os registos pertençam exactamente à mesma loja.
- [x] Acrescentar regressões HTTP para batches mistos (loja A + loja B), exigindo HTTP 422 e ausência de escritas em ambas as lojas.
- [x] Alargar a matriz negativa a vendas diárias, traffic peaks, hourly demand e recomendações de slotting.
- [ ] Validar API CI e Quality Gates do novo conjunto de testes.
- [ ] Continuar a reconciliação dos restantes handlers e acessos indirectos.


## Linhagem PostgreSQL de registos associados a prateleiras (18-11-2026)
- [x] Rever a migration 0050 e os triggers PostgreSQL para observation_alerts, capture_sessions e replenishment_tasks.
- [x] Criar smoke PostgreSQL que rejeita INSERT/UPDATE com store_id incompatível com shelf → zone.
- [x] Verificar que mover shelf/zone entre lojas é bloqueado quando existem registos operacionais dependentes.
- [ ] Validar o smoke no API CI; o workflow ainda está em execução no commit anterior.


## Linhagem multi-loja de registos de prateleira — validação CI (18-11-2026)

- [x] Validar em PostgreSQL 16 a migration `0050_shelf_record_store_lineage_guard` e o smoke `postgres_shelf_record_lineage_smoke.py`.
- [x] Confirmar rejeição de INSERT/UPDATE com `store_id` divergente em `observation_alerts`, `capture_sessions` e `replenishment_tasks`.
- [x] Confirmar rejeição de movimentos cross-store de prateleiras/zonas com registos dependentes e preservação dos três registos válidos.
- [x] API CI [44408063719](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44408063719) e Quality Gates [44408063767](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44408063767) passaram no commit `04c542320ad892a06c81c2295f518f5583428bc4`.
- [ ] Continuar a auditoria handler-a-handler; esta validação cobre apenas as três tabelas e a hierarquia shelf → zone → store.


## Linhagem pai/filho de artefactos externos — validação HTTP (18-11-2026)

- [x] Tornar `parent_reference_id` estrito no schema de criação: IDs booleanos deixam de ser aceites como inteiros.
- [x] Acrescentar teste HTTP/JWT do endpoint de registo: raiz, descendente, listagem e retry idempotente.
- [x] Cobrir conflito quando a mesma referência é reapresentada com outra linhagem.
- [x] Cobrir pai inexistente, pai de outra imagem na mesma loja e pai de outra loja; confirmar ausência das referências recusadas na listagem.
- [x] Validar o teste HTTP/JWT e a suite API no API CI [44410444406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444406); a suite, incluindo o teste de linhagem, terminou com sucesso. O teste HTTP usa SQLite isolado.
- [x] Registar a evidência do API CI [44410444406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444406) e Quality Gates [44410444404](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444404); actualizar a matriz de autorização. O teste HTTP usa SQLite isolado e não substitui smoke PostgreSQL específico do endpoint.


## Elegibilidade operacional de datasets — estabilidade da linhagem (18-11-2026)

- [x] Alargar os locks da validação de imagens internas às linhas `shelf_images`, `shelves` e `zones`, que em conjunto determinam a loja efectiva.
- [x] Ordenar os locks por IDs de imagem, prateleira e zona e expor no relatório os IDs bloqueados.
- [x] Acrescentar teste de compilação SQL PostgreSQL para verificar os alvos `FOR UPDATE` e a ordenação determinística.
- [x] Criar `apps/api/scripts/postgres_dataset_eligibility_concurrency_smoke.py`: duas sessões independentes tentam alterar `shelves.zone_id` e `zones.store_id`; o smoke exige espera real em `pg_stat_activity` enquanto o gate mantém os locks.
- [ ] Auditar os consumidores de COCO/treino/galeria para impedir que contornem o release gate operacional.


## Elegibilidade operacional de datasets — smoke PostgreSQL concorrente (18-11-2026)

- [x] Criar smoke PostgreSQL com transações independentes para a validação e a alteração hierárquica.
- [x] Verificar bloqueio real em `pg_stat_activity` para alterações concorrentes a `shelves.zone_id` e `zones.store_id`.
- [x] Integrar o smoke no workflow API CI após as migrações e o smoke de linhagem de registos de prateleira.
- [x] Confirmar execução verde do smoke no PostgreSQL 16 no API CI [44410444406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444406), commit `33425007fc016b220c3f49f95078444189fd1ec9`; o passo dedicado, os restantes smokes e a suite API terminaram com sucesso.
- [ ] Auditar os consumidores COCO/treino/galeria que possam contornar o release gate; a concorrência do gate não prova que todos os caminhos usam o gate.


## Continuação prioritária — fronteiras de consumo e retenção de datasets (18-11-2026)

- [x] Auditar os consumidores COCO, galeria, diff, qualidade, revisão, aprovação, release e execução. A classificação, os efeitos laterais e os limites estão em [Fronteiras dos consumidores de datasets](docs/architecture/dataset-consumer-boundaries.md). A única fronteira inspeccionada que inicia um processo externo é `dataset_execution`, agora ligada ao gate; galeria e relatórios são ferramentas offline/documentais, não autorização operacional.
- [ ] Definir um contrato operacional de linhagem/retenção para derivados internos (crops, cópias, relatórios, exports, caches, backups e artefactos publicados), incluindo a política para descendentes quando a origem fica RESTRICTED ou sob legal hold.
- [x] Avaliar a necessidade de leases/claims duráveis e fencing; o desenho técnico e os testes de aceitação estão em [Contrato de execução assíncrona de datasets](docs/architecture/dataset-async-execution-lease.md). A implementação persistente e a integração com worker continuam pendentes.
- [ ] Não activar purge físico nem inferir política de conservação: manter a eliminação fail-closed até existir política formal aprovada e prova de cobertura de todos os destinos.


## Gate de aprovação obrigatório no consumidor de datasets — 18-11-2026

- [x] Fazer `dataset_execution` executar `run_release_gate` antes de criar uma release ou iniciar o consumidor.
- [x] Exigir registo de aprovação e os três splits COCO; suportar revisão visual dos três splits como requisito explícito.
- [x] Vincular SHA-256 do registo e do relatório de aprovação à fingerprint e aos metadados imutáveis da release.
- [x] Passar ao processo consumidor os hashes de aprovação e o modo validado através de variáveis de ambiente.
- [x] Adiar a aquisição dos locks operacionais até terminarem as verificações de ficheiros/COCO/revisão, mantendo-os durante release e consumo síncrono.
- [x] Acrescentar testes para ordem gate → release → consumidor, bloqueio sem aprovação e fingerprint distinta para evidência de aprovação diferente.
- [x] Validar a implementação no API CI [44412024791](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44412024791): **1168 passed, 1 skipped, 1 warning**, migrações PostgreSQL 16 e smokes operacionais concluídos; Quality Gates [44412024893](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44412024893) e Docker Compose [44412025214](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44412025214) também passaram. O smoke PostgreSQL de elegibilidade de datasets e o build Web foram aprovados.
- [ ] Criar mecanismo de lease/claim com fencing para consumidores remotos/destacados; não está coberto pela transacção síncrona.


## Auditoria das fronteiras de consumo de datasets — 18-11-2026

- [x] Classificar os CLIs COCO, galeria, diff, qualidade, auditoria, revisão, aprovação, release e execução.
- [x] Documentar que galeria e relatórios são operações locais/documentais e não equivalem a aprovação ou autorização de treino.
- [x] Confirmar que `dataset_execution` é a fronteira inspeccionada que inicia um processo externo e que exige agora o gate completo.
- [ ] Criar catálogo persistente de artefactos derivados e propagar retenção/legal hold a HTML, relatórios, cópias, exports, caches e backups.
- [ ] Implementar execução assíncrona com claim/lease/fencing e publicação condicionada ao token actual; ver requisitos no documento de fronteiras.
- [ ] Autenticar revisores e substituir a confiança em identidade declarada em ficheiros por evidência autenticada.


## Contrato de execução assíncrona — desenho técnico (18-11-2026)

- [x] Definir identidade imutável do job e idempotência.
- [x] Definir estados, claim atómico, lease, heartbeat, takeover e fencing monotónico.
- [x] Definir revalidação de fontes internas em enqueue/claim/heartbeat/conclusão e lock order.
- [x] Definir staging e publicação condicionada ao token actual.
- [x] Definir testes de aceitação PostgreSQL/SQLite e sequência de implementação.
- [x] Implementar tabelas de jobs/fontes/eventos, constraints, triggers de imutabilidade e serviço transaccional de lease/claim/heartbeat/conclusão. O worker/broker e a publicação final permanecem fora do âmbito.
- [x] Validar no API CI [44416138879](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138879) a migration PostgreSQL 16 e o smoke de dois workers, claim único, takeover, fencing monotónico, rejeição de worker obsoleto e revogação por retenção.
- [ ] Integrar broker/worker e publicação apenas após validação do fencing.


## Persistência de jobs de datasets e fencing — 18-11-2026

- [x] Criar tabelas persistentes para jobs, fontes internas e eventos append-only.
- [x] Fixar identidade do pedido e dependências de imagem/loja/hash; impor idempotência por chave e digest do payload.
- [x] Implementar claim atómico com `FOR UPDATE SKIP LOCKED`, lease com expiração e fencing token monotónico.
- [x] Implementar heartbeat, falha e conclusão condicionados por worker, token actual e lease não expirado.
- [x] Revalidar elegibilidade das fontes em enqueue, claim, heartbeat e conclusão; revogar jobs quando a imagem deixa de estar ACTIVE ou entra em legal hold.
- [x] Proteger identidade, fontes e eventos através de constraints/triggers PostgreSQL e SQLite.
- [x] Acrescentar testes de idempotência, takeover, worker obsoleto, expiração e revogação por retenção.
- [x] Validar migration PostgreSQL 16, suite API (**1177 passed, 1 skipped, 1 warning**) e smoke concorrente no API CI [44416138879](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138879); Quality Gates [44416138669](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138669) e Docker Compose [44416138628](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138628) também passaram.
- [x] Implementar serviço de leitura de artefactos com scope, lease, retenção e auditoria append-only.
- [ ] Implementar worker/broker e promoção de outputs com fencing; não publicar directamente a partir do worker.


## Fencing reforçado na base de dados — 2026-11-18

- [x] Impor incremento exacto do fencing token e contador de tentativas em claim inicial e takeover.
- [x] Rejeitar heartbeat de lease expirado e impedir encurtamento da expiração, tanto no serviço como na base de dados.
- [x] Exigir lease válido para conclusão/falha e `finished_at` para estados terminais.
- [x] Exigir digest e referência de staging em jobs `SUCCEEDED`.
- [x] Impor sequência consecutiva de eventos e impedir eventos posteriores ao estado terminal, preservando o evento terminal legítimo.
- [x] Acrescentar testes SQLite de migração e expandir smoke PostgreSQL para testar SQL directo contra os guards.
- [x] Confirmar migration PostgreSQL 16, API CI [44419928230](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928230), Quality Gates [44419928281](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928281) e Docker Compose [44419928382](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928382); **1179 passed, 1 skipped, 1 warning**.
- [x] Implementar identidade individual de workers, credenciais com hash, scopes, expiração, rotação e revogação (migration 0060, validada em API CI [44431378398](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378398)).
- [x] Criar a dependência FastAPI para pedidos assinados de workers, com scopes e anti-replay; manter as rotas de jobs fechadas.
- [x] Implementar leitura controlada por chamada com revalidação de retenção/loja/hash e auditoria.
- [ ] Implementar promoção de outputs condicionada ao fencing token actual.


## Máquina de estados e identidade imutável dos jobs — 2026-11-18

- [x] Implementar migration `0058_dataset_execution_state_machine` com transições explícitas de `QUEUED` e `LEASED`.
- [x] Impedir a reactivação ou alteração de jobs em estados terminais.
- [x] Tornar imutáveis a chave idempotente, os hashes do pedido/release/aprovação, o modo e a data de criação.
- [x] Acrescentar testes de migration SQLite para transições ilegais, identidade imutável e reactivação terminal.
- [x] Expandir o smoke PostgreSQL para tentar alterar a identidade de um job activo e reabrir um job concluído.
- [x] Validar a migration 0058 em PostgreSQL 16, API CI [44421831066](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44421831066), Quality Gates [44421831076](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44421831076) e Docker Compose [44421831148](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44421831148): **1179 passed, 1 skipped, 1 warning**.
- [x] Implementar identidade individual e dependência de autenticação HTTP assinada antes de qualquer futura exposição de claims.
- [ ] Implementar leitura de artefactos autorizada por chamada e promoção de outputs condicionada ao fencing token actual.


## Guard de estado inicial dos jobs assíncronos — 19-11-2026

- [x] Expandir o teste de migration SQLite 0059 para rejeitar individualmente `lease_owner`, `lease_expires_at`, `fencing_token`, `attempt_count`, `output_sha256`, `staged_output_reference`, `failure_code` e `finished_at` em novos jobs.
- [x] Expandir o smoke PostgreSQL para tentar os mesmos oito metadados forjados em INSERTs independentes.
- [ ] Validar migration, smoke PostgreSQL, suite API, Quality Gates e Docker Compose no CI dos commits desta ronda.
- [ ] Investigar os estados dos checks de deployment separadamente: falhas de quota Vercel não equivalem a falhas dos testes API.


## Autenticação de workers de datasets — estado reconciliado

- [x] Definir identidade de serviço e credenciais individuais com emissão local, expiração, rotação e revogação.
- [x] Aplicar scopes separados para claim, heartbeat, falha e conclusão; reservar leitura/publicação até existirem os respetivos serviços.
- [x] Derivar `worker_id` exclusivamente do principal autenticado.
- [x] Testar credenciais inválidas/expiradas/revogadas, scopes insuficientes, replay e isolamento entre workers.
- [x] Implementar dependência FastAPI de pedidos assinados com timestamp e nonce único.
- [x] Manter endpoints de jobs não expostos até leitura de artefactos e publicação fenced estarem implementadas.


## Autenticação individual de workers de datasets — 19-11-2026

- [x] Criar identidades de serviço separadas das contas JWT humanas e persistir workers, credenciais e eventos de segurança.
- [x] Emitir credenciais bearer individuais de elevada entropia; guardar apenas SHA-256 do segredo e comparar em tempo constante.
- [x] Implementar scopes allow-list para claim, heartbeat, conclusão, falha, leitura de artefactos e publicação de outputs; não aceitar wildcard.
- [x] Implementar validade limitada (60 segundos a 90 dias; predefinição 30 dias), rotação transacional, revogação individual e desativação do worker.
- [x] Vincular wrappers de lease ao `worker_id` derivado do principal autenticado; não aceitar identidade declarada separadamente.
- [x] Criar CLI local confiável para issue/rotate/revoke/disable; não criar endpoint HTTP público de emissão.
- [x] Acrescentar testes unitários para segredo incorrecto, token desconhecido/malformado, expiração, revogação, rotação, desativação, scopes e identidade no claim.
- [x] Integrar smoke PostgreSQL para ciclo de vida de credenciais e imutabilidade dos eventos de segurança.
- [x] Validar migration PostgreSQL 16, smoke dedicado, suite API (**1202 passed, 1 skipped, 1 warning**), Quality Gates e Docker Compose no commit de código `d7c8412`: [API CI 44431378398](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378398), [Quality Gates 44431378324](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378324) e [Docker Compose 44431378349](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378349) passaram.
- [x] Criar dependência FastAPI reutilizável `require_dataset_worker(scope)` para autenticar e autorizar futuros handlers HTTP; nenhuma rota de jobs foi exposta.
- [x] Implementar assinatura HMAC-SHA-256 por pedido, timestamp e nonce único; replay rejeitado também sob concorrência PostgreSQL.
- [x] Implementar leitura de artefactos autorizada por chamada (`artifacts:read`), validada por lease, retenção e hash.
- [x] Implementar promoção de outputs condicionada ao fencing token actual (`outputs:publish`), com auditoria append-only e guards SQL.
- [x] Manter o worker marcado como não operacional: os serviços internos de leitura e promoção estão implementados, mas continuam sem rotas HTTP de jobs, broker ou worker remoto.

- [x] Acrescentar guards SQL PostgreSQL/SQLite para imutabilidade de scopes/hash/validade/identidade, revogação unidireccional, credenciais não elimináveis e desativação não reversível; cobrir a migration 0060 com teste SQLite e smoke PostgreSQL.


## Pedidos assinados de workers e proteção anti-replay — 19-11-2026

- [x] Criar migration `0061_dataset_worker_request_nonces` com FK para a credencial, digest do nonce, timestamp, expiração, índice de limpeza e unicidade por credencial/nonce.
- [x] Implementar assinatura HMAC-SHA-256 vinculada à credencial, método, request-target exacto, timestamp, nonce e hash do corpo.
- [x] Implementar dependência FastAPI `require_dataset_worker(scope)`, com respostas 401/403, validação da janela temporal e consumo transaccional do nonce antes do handler.
- [x] Impedir replay concorrente: duas sessões PostgreSQL a submeterem o mesmo pedido produzem exactamente uma aceitação e uma rejeição.
- [x] Cobrir assinatura adulterada, corpo/caminho/query/método divergentes, timestamp expirado, scope insuficiente e repetição HTTP.
- [x] Validar migration PostgreSQL 16, smoke concorrente, suite API (**1211 passed, 1 skipped, 1 warning**), Quality Gates e Docker Compose nos runs [44471171581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171581), [44471171526](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171526) e [44471171533](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171533).
- [x] Manter as rotas de jobs não expostas; a dependência é uma fronteira reutilizável, não uma API de jobs já operacional.
- [x] Implementar serviço de leitura de bytes por chamada com revalidação de retenção/loja/hash, scope `artifacts:read`, caminho sem symlinks e auditoria append-only.
- [x] Implementar promotor de outputs que valide estado `SUCCEEDED`, digest, evento terminal, worker/credencial activa e fencing token actual antes da publicação (`outputs:publish`).
- [ ] Só depois integrar broker e worker remoto de treino; não declarar execução assíncrona operacional com base na persistência dos leases.


## Leitura de fontes de treino e auditoria de acesso — 19-11-2026

- [x] Implementar leitura de bytes por chamada com scope `artifacts:read`, job lease activo, worker autenticado e fencing token actual.
- [x] Confirmar associação à fonte imutável, loja, retenção e legal hold sob locks da imagem/prateleira/zona.
- [x] Abrir ficheiros através de descritores de directório e `O_NOFOLLOW`; impedir traversal e symlinks; validar tamanho e SHA-256 antes de devolver bytes em memória.
- [x] Criar auditoria append-only `dataset_execution_job_artifact_reads`, com triggers SQL que validam lease, fonte, loja, retenção, credencial, worker e scope; UPDATE/DELETE proibidos.
- [x] Revalidar credencial e scopes no momento das operações claim/heartbeat/complete/fail e durante a leitura, para fechar corridas de revogação/desactivação.
- [x] Validar migration PostgreSQL 16, concorrência de retenção, imutabilidade da auditoria, Quality Gates, Docker Compose e **1223 passed, 1 skipped, 1 warning** nos runs [44473560217](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560217), [44473560287](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560287) e [44473560252](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560252).
- [x] Implementar promotor de outputs que valide estado `SUCCEEDED`, digest, evento terminal, worker/credential activa e fencing token actual antes da publicação (`outputs:publish`).
- [ ] Definir protocolo de staging/publicação recuperável e compensação de ficheiros órfãos entre filesystem e transacção SQL.
- [ ] Só depois integrar broker e worker remoto de treino; não declarar execução assíncrona operacional com base na persistência dos leases.


## Promoção fenced de outputs de datasets — 19-11-2026

- [x] Criar migration `0063_dataset_job_output_publications` e modelo SQLAlchemy para registar publicação por job, worker, credencial, fencing token, digest, referências e tamanho.
- [x] Exigir job `SUCCEEDED`, fencing token actual e correspondência exacta com o evento terminal `SUCCEEDED` do worker e digest.
- [x] Revalidar worker activo, credencial não revogada/não expirada e scope persistido `outputs:publish` dentro da transacção de publicação.
- [x] Restringir referências de staging a `staging/{job_id}/{fencing_token}/...`; rejeitar traversal, caminhos não canónicos e symlinks.
- [x] Copiar para temporário privado, verificar tamanho/SHA-256 e promover com hard link atómico sem sobrescrita para referência content-addressed.
- [x] Tornar a operação idempotente após interrupção entre filesystem e commit SQL; repetir validação do digest do destino existente.
- [x] Criar triggers PostgreSQL/SQLite para validação da publicação e imutabilidade append-only da auditoria.
- [x] Cobrir promoção, retry idempotente, reconciliação de destino existente, output adulterado/ausente, scope revogado/insuficiente, worker/token incorrectos e migration SQLite.
- [x] Integrar smoke PostgreSQL com duas sessões concorrentes; exactamente uma linha de publicação é persistida, o output é verificado e UPDATE/DELETE e token forjado são rejeitados.
- [x] Validar no commit `46006afcc5167e04f77037f985e65981a78248e3`: API CI [44480661837](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661837) (**1231 passed, 1 skipped, 1 warning**), Quality Gates [44480661851](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661851) e Docker Compose [44480661813](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661813) passaram.
- [ ] Automatizar reconciliação/limpeza de ficheiros temporários e staging órfãos após encerramento abrupto do processo; definir retenção e legal hold para outputs publicados.
- [ ] Integrar publicação no catálogo de artefactos derivados e propagar a governação de retenção aos outputs.
- [ ] Criar rotas HTTP internas com `require_dataset_worker('outputs:publish')`, só depois de definir o contrato completo das restantes operações de jobs.
- [ ] Integrar broker e worker remoto de treino/inferência; a execução assíncrona continua não operacional.

## Reconciliador de outputs — cobertura de integridade adicional

- [x] Acrescentar regressão que corrompe o destino publicado mantendo um staging antigo válido e confirma que o reconciliador não remove o staging quando o destino diverge da auditoria append-only.
- [x] Validar a nova regressão, a suite API, os Quality Gates e os smokes PostgreSQL 16 no CI no commit `54d2454629fb324e1fc1aca1c1be43db538a4dca`: API CI [44514111929](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44514111929), Quality Gates [44514111949](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44514111949) e Docker Compose [44514111942](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44514111942) passaram.


## Reconciliador de outputs — protecção contra symlinks (2026-11-19)

- [x] Acrescentar regressão de limpeza em modo `--apply` para temporário antigo com nome interno mas implementado como symlink.
- [x] Confirmar que o symlink não é candidato nem removido e que o destino externo permanece intacto.
- [x] Validar API CI [44514111929](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44514111929), Quality Gates [44514111949](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44514111949) e Docker Compose [44514111942](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44514111942): os três workflows passaram.


## Governação de retenção dos outputs de jobs — decisão arquitectural (2026-11-19)

- [x] Auditar o catálogo de referências externas, os snapshots de inventário, os eventos de disposição e a linhagem das fontes dos jobs.
- [x] Confirmar que a publicação append-only existente é a identidade canónica do output e que o catálogo por imagem não representa correctamente outputs multi-origem.
- [x] Documentar o modelo alvo, a herança de restrições, os limites de inventário externo e as decisões de negócio em aberto.
- [ ] Implementar eventos append-only de governação/retenção ligados à publicação, sem alterar a linha imutável da publicação.
- [x] Implementar elegibilidade fail-closed que revalida todas as fontes do job sob locks por ID crescente; migration 0064 aplica guard equivalente no INSERT.
- [x] Acrescentar testes de migration SQLite e smoke PostgreSQL 16 para holds/restrições concorrentes em outputs multi-origem.
- [ ] Definir política aprovada de retenção e cobertura externa antes de activar qualquer disposição física.

Documento: `docs/architecture/dataset-output-artifact-governance.md`.


## Promoção de outputs — revalidação das fontes (2026-11-19)

- [x] Identificar a janela entre conclusão do job e promoção em que uma fonte pode passar a RESTRICTED ou receber legal hold.
- [x] Revalidar todas as fontes imutáveis sob locks depois da preparação dos bytes e antes da promoção filesystem/auditoria.
- [x] Acrescentar guard SQL PostgreSQL/SQLite para rejeitar publicações sem fontes elegíveis.
- [x] Acrescentar regressões SQLite para fonte RESTRICTED e legal hold e smoke PostgreSQL concorrente para hold aplicado durante a preparação.
- [x] Validar migration 0064, suite API, smoke PostgreSQL 16, Quality Gates e Docker Compose no CI no commit `01abce944e7d883ea53aca17a09ac589701fdfc9`: API CI [44516774051](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774051) (**1241 passed, 1 skipped, 1 warning**), Quality Gates [44516774058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774058) e Docker Compose [44516774048](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774048) passaram.


## Revalidação multi-origem da publicação — 2026-11-19

- [x] Acrescentar regressões de serviço com duas fontes imutáveis, ordem de entrada inversa aos IDs e bloqueio quando a segunda fonte passa a `RESTRICTED` ou recebe `legal_hold`.
- [x] Alargar o teste SQLite da migration 0064 para provar que uma única fonte inelegível bloqueia a publicação multi-origem, mesmo com outra fonte elegível.
- [x] Alargar o smoke PostgreSQL 16 para publicar jobs com duas fontes e aplicar o legal hold concorrente à segunda origem durante a preparação.
- [x] Validar os novos cenários, migration 0064, suite API, Quality Gates e Docker Compose no CI no commit `01abce944e7d883ea53aca17a09ac589701fdfc9`: API CI [44516774051](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774051), Quality Gates [44516774058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774058) e Docker Compose [44516774048](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774048) passaram; **1241 passed, 1 skipped, 1 warning**.
- [ ] Prosseguir com eventos append-only de governação ligados à publicação, sem alterar a linha canónica.
- [ ] Não activar disposição física até existir política aprovada de retenção, cobertura de cópias externas e aprovação independente.
