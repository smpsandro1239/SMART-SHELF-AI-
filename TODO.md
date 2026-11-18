# TODO

## Security and reliability

- [ ] Audit authorization and tenant isolation for computer-vision endpoints: capture sessions, uploads, image content, detections, OCR, evidence fusion, human reviews and embeddings.
- [ ] Add PostgreSQL concurrency coverage for image retention versus detection review. Observation creation versus image retention and human review versus image retention now have dedicated smoke tests; validate the new human-review test in CI.
- [ ] Complete the product/shelf-product catalogue audit: role-gate and tenant-listing regression coverage is in place; inactive products and duplicate shelf assignments are rejected without writes; a PostgreSQL concurrent duplicate-assignment smoke test is now wired into API CI. Await CI evidence, then confirm global ADMIN catalogue semantics are intentional/documented.
- [ ] Complete the worker retry, lease-expiry and retention-transition audit under concurrent execution. The lease-takeover and deterministic recovery-lock ordering regression tests now pass CI; add PostgreSQL coverage for any remaining race conditions found.
- [ ] Verify production authentication configuration rejects anonymous access to all protected API routes.
- [ ] Confirm production secret validation (including whitespace rejection) passes in CI and deployment environments explicitly set `APP_ENV=production`.
- [ ] Document the production secret generation, storage and rotation procedure.
- [ ] Review rotation and operational lifecycle for JWT and bootstrap secrets.
- [ ] Re-run API, frontend, Docker Compose and PostgreSQL smoke suites after backend changes.

## Product quality

- [ ] Review pagination, filtering and bounded query costs on image-derived data endpoints.
- [ ] Verify retention and legal-hold audit trails across restore, purge scheduling and cancellation.
- [ ] Keep ROADMAP.md aligned with implemented and validated capabilities.
- [x] Implement dashboard UX refinements: human-readable durations, Europe/Lisbon timestamps, stronger contrast palette, non-colour status cues, compact single-task layout and clickable summary cards with exact task-state filters; Web CI and frontend quality build passed.
- [ ] Complete manual browser/keyboard and full-state contrast audit before claiming formal WCAG AA conformance.


## Integridade das unidades logísticas (17-11-2026)
- [x] Adicionar índices únicos parciais para garantir uma única unidade activa de encomenda e uma única unidade activa de reposição por produto, ao nível da base de dados.
- [x] Acrescentar teste API para rejeitar configurações duplicadas de unidades logísticas.
- [x] Integrar smoke test de concorrência PostgreSQL no API CI.
- [ ] Confirmar migração 0054 e todos os pipelines após execução no CI.
- [ ] Avaliar dados existentes antes de aplicar a migração em ambientes com histórico real; duplicados preexistentes devem ser saneados antes da criação dos índices.


## Inventário físico e registo de paletes (17-11-2026)
- [x] Confirmar que o registo de uma palete física valida produto, embalagem PALLET, capacidade e loja, e cria evento inicial de auditoria.
- [x] Acrescentar regressão que confirma que registar uma palete não altera snapshots agregados nem movimentos de stock; a palete é um registo físico, não uma recepção automática de inventário.
- [ ] Validar a nova regressão no API CI e concluir Quality Gates e Demo Docker Compose smoke.
- [ ] Definir, numa fase própria, uma reconciliação explícita entre paletes físicas e stock agregado; não somar automaticamente estes domínios enquanto não existir regra de negócio para evitar dupla contabilização.


## Integridade das colocações de armazém (18-11-2026)
- [x] Rejeitar a criação de colocações em localizações inactivas.
- [x] Rejeitar a criação de colocações para produtos inactivos.
- [x] Acrescentar teste de regressão que confirma HTTP 409 e ausência de persistência nos dois cenários.
- [ ] Validar a alteração na suite API CI, Quality Gates e Demo Docker Compose.
- [ ] Definir e testar uma política explícita de capacidade/peso/temperatura para colocações; não impor bloqueios sem garantir que o perfil físico do produto está configurado e que a regra representa a operação real.


## Slotting físico — validação do endpoint (18-11-2026)
- [x] Acrescentar teste de integração com JWT para o endpoint de slotting físico.
- [x] Cobrir capacidade volumétrica, peso calculado, compatibilidade de temperatura e ordenação por distância.
- [x] Confirmar que as recomendações não autorizam movimentos automáticos nem reserva de stock.
- [ ] Validar o novo teste no API CI e Quality Gates.


## Reconciliação entre paletes e slotting físico (18-11-2026)
- [x] Confirmar que tarefas distintas do mesmo produto não conseguem consumir concorrencialmente o mesmo stock agregado; o smoke PostgreSQL existente verifica que apenas um movimento é persistido.
- [x] Evitar recomendações de capacidade para localizações cujo código coincide com paletes físicas registadas no armazém, enquanto não existir ligação inequívoca palete-colocação.
- [x] Acrescentar teste de integração com JWT para a exclusão conservadora de uma localização ocupada por palete física.
- [ ] Validar o novo teste na suite API CI e Quality Gates.
- [ ] Definir um modelo explícito de transferência/reconciliação palete-colocação, com identificadores e eventos auditáveis, antes de agregar quantidades entre os dois registos.


## Paletes sem localização mapeada — slotting seguro (18-11-2026)
- [x] Tratar paletes de armazém com localização vazia ou não mapeada como ocupação desconhecida.
- [x] Excluir conservadoramente todas as localizações do slotting enquanto existir uma palete de armazém sem correspondência com uma localização configurada.
- [x] Cobrir com teste de integração a palete sem código de localização.
- [ ] Validar o novo cenário na API CI e Quality Gates.


## Ciclo de vida de paletes — cobertura de integração (18-11-2026)
- [x] Testar rejeição de transições de estado não permitidas.
- [x] Testar transição READY → ON_DISPLAY com localização SALES_FLOOR.
- [x] Testar actualização de quantidade e estado para PARTIAL.
- [x] Testar rejeição HTTP 409 de actualização baseada num estado desactualizado, sem evento adicional.
- [ ] Validar o novo teste na API CI e Quality Gates.
