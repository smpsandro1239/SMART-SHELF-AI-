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
  - [x] Add bounded offset pagination with stable ordering to shelf-image lists, detections, OCR matches/evidence/runs and fused evidence; preserve store scoping and retention checks. Regression covers detection page boundaries and invalid bounds.
  - [x] Paginate the append-only image retention event history with deterministic chronological ordering, a default page of 100 and a hard maximum of 500; cover page boundaries and negative/zero parameter clamping. API CI and Quality Gates passed on commit `92d0add53d`.
  - [x] Add offset pagination to external artifact references, immutable disposition events and human SKU review history; preserve admin/store authorization and append-only ordering.
  - [x] Add regression tests for artifact and disposition page boundaries, negative/zero bounds and human review history pages.
  - [x] Finish API CI, Quality Gates and Docker Compose validation for the pagination changes: API CI run `44256610563` passed (1136 passed, 1 skipped, 1 warning); Quality Gates run `44256985942` passed (API tests/compilation and Web TypeScript/production build); Docker Compose run `44256610406` passed.
- [ ] Verify retention and legal-hold audit trails across restore, purge scheduling and cancellation.
- [ ] Keep ROADMAP.md aligned with implemented and validated capabilities.
- [x] Implement dashboard UX refinements: human-readable durations, Europe/Lisbon timestamps, stronger contrast palette, non-colour status cues, compact single-task layout and clickable summary cards with exact task-state filters; Web CI and frontend quality build passed.
- [ ] Complete manual browser/keyboard and full-state contrast audit before claiming formal WCAG AA conformance.


## Integridade das unidades logísticas (17-11-2026)
- [x] Adicionar índices únicos parciais para garantir uma única unidade activa de encomenda e uma única unidade activa de reposição por produto, ao nível da base de dados.
- [x] Acrescentar teste API para rejeitar configurações duplicadas de unidades logísticas.
- [x] Integrar smoke test de concorrência PostgreSQL no API CI.
- [x] Confirmar migração 0054 e smoke de concorrência no API CI; índices únicos parciais aplicados em PostgreSQL e SQLite.
- [x] Endurecer a migração 0054 com preflight que identifica até 20 produtos duplicados por função (unidade de encomenda/reposição), aborta antes de criar índices e não altera dados.
- [ ] Validar o preflight e o downgrade na suite de migrações SQLite e na cadeia PostgreSQL completa após esta alteração.
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
