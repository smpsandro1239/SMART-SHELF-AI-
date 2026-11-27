## P1 — Métricas operacionais Edge (2026-11-27)

- [x] Definir heartbeat do worker com contadores de polling, eventos reclamados, polls ociosos e falhas.
- [x] Registar duração do último polling, instante do último evento e tipo da última falha, sem texto de excepção.
- [x] Propagar snapshot de métricas do filho para o estado operacional do supervisor.
- [x] Acrescentar logs correlacionados por evento com event_id, inbox_id, processing_id, store_id, device_id, worker_id, tentativa, duração e outcome PROCESSED/RETRY/DEAD_LETTER/LEASE_LOST/ACK_CLAIMED/ACK_RECORDED/ACK_REJECTED.
- [x] Acrescentar testes para contadores de polling, duração, falhas sem texto de excepção e correlação de ACK aplicado/DEAD_LETTER.
- [x] Confirmar API CI, Quality Gates, Security Scans e Docker Compose no SHA `4024763c177dfad63179e3b3cb73648371a729dc` — todos SUCCESS.
- [ ] Decidir mecanismo de exportação/consumo das métricas sem introduzir dependências ou portas expostas desnecessárias.

Limite: os contadores no heartbeat são snapshots voláteis por processo, não um ledger durável nem métricas agregadas históricas. A implementação não activa ACK nem altera efeitos de domínio.

---

## P1 — Supervisor independente do Edge Worker (2026-11-27)

- [x] Criar supervisor independente em `app.edge_event_supervisor`, com processo filho separado.
- [x] Publicar heartbeat operacional do supervisor e do worker, com timestamp, PID e estado.
- [x] Detectar crash, SIGKILL, heartbeat ausente/desactualizado e reiniciar o filho.
- [x] Aplicar backoff exponencial limitado e registar falhas consecutivas, reinícios e último exit code.
- [x] Impedir duas instâncias supervisoras no mesmo volume através de lock exclusivo.
- [x] Implementar SIGTERM/SIGINT gracioso, timeout e SIGKILL como último recurso.
- [x] Criar healthcheck que valida heartbeats recentes e PIDs vivos/coincidentes.
- [x] Integrar o supervisor no serviço Docker Compose mantendo hardening e ACK fail-closed.
- [x] Validar compileall, suite API, Quality Gates, Security Scans e Docker Compose no SHA `9be6f3fb7a446f537bf989544df178a100050c7b`.
- [x] Smoke Docker comprovou arranque, SIGKILL e recuperação de heartbeat obsoleto no SHA `9be6f3fb7a446f537bf989544df178a100050c7b`.
- [ ] Validar o novo smoke de SIGTERM real ao container, encerramento do filho e novo arranque saudável no SHA actual.
- [ ] Confirmar os quatro workflows no SHA final após a extensão do smoke.

Limite: não foram executados comandos localmente; os resultados positivos provêm dos workflows GitHub Actions. O heartbeat do filho representa progresso do ciclo de polling; o timeout deve exceder a duração máxima esperada dos handlers. `TASK_ACKNOWLEDGED` continua fail-closed e não há alterações ao inventário.

---

## P0 — PostgreSQL Edge worker fault injection (2026-11-27)

### Implementação publicada — execução CI pendente
- [x] Adicionar smoke PostgreSQL 16 que distingue `pg_terminate_backend` (uma sessão) da paragem efectiva do serviço PostgreSQL.
- [x] Restringir a paragem do serviço ao container descartável `postgres:16` de GitHub Actions; o script recusa execução fora desse ambiente.
- [x] Ligar o smoke ao API CI imediatamente após o smoke de atribuições Edge e antes do smoke Edge ACK, evitando leases pendentes deixadas por cenários posteriores.
- [x] Verificar falha do heartbeat, abandono do resultado local, expiração natural da lease, takeover e rejeição do fencing token anterior.
- [x] Verificar evento de controlo numa segunda loja e contagem de movimentos de inventário inalterada.
- [ ] Executar o novo smoke no PostgreSQL 16 e corrigir eventuais falhas.
- [ ] Confirmar API CI, Docker Compose smoke, Quality Gates e Security Scans aprovados no mesmo SHA.

Limite: o smoke de serviço cobre um handler DEVICE_HEARTBEAT sem efeitos de domínio. A atomicidade de handlers transaccionais continua coberta separadamente pelo smoke Edge ACK; este ensaio não activa nem injecta essa registry. A validação operacional permanece pendente até CI verde.

---

## P1 — Resiliência operacional Edge: diagnóstico seguro (2026-11-27)

- [x] Remover logs de traceback/texto de excepção nas falhas de renovação de lease e execução de handlers; manter apenas tipo da excepção e inbox_id.
- [x] Cobrir com regressões que mensagens sensíveis simuladas não aparecem nos logs de polling nem de execução/renovação.
- [ ] Confirmar testes focados, suite API e workflows no SHA final.
- [ ] Prosseguir para ensaio de indisponibilidade PostgreSQL durante polling, heartbeat/lease renewal, falha ao concluir e recuperação após restabelecimento.
- [ ] Demonstrar recuperação sem ACK implícito, sem duplicação de efeitos de domínio e sem alterações de inventário.

Limite: esta ronda não prova ainda uma indisponibilidade PostgreSQL real nem a recuperação de uma ligação após restabelecimento. Os testes novos ainda aguardam execução CI; não declarar esta tarefa validada antes disso.

---

## P0 — Edge Event Worker autónomo (2026-11-27)

### Implementação publicada — validação pendente
- [x] Criar runtime de polling dedicado em `app.edge_event_worker`, mantendo o módulo de serviço `app.edge_event_worker`.
- [x] Expor o entrypoint `python -m app.edge_event_worker`.
- [x] Implementar espera interruptível, tratamento de falhas de polling e encerramento gracioso por SIGTERM/SIGINT (termina o evento em curso antes de sair).
- [x] Validar intervalo de polling, lease e identidade do worker antes do ciclo.
- [x] Adicionar serviço independente `edge-event-worker` no Docker Compose, com restart policy, utilizador não-root, filesystem read-only, capabilities removidas e dependência de DB/migrations.
- [x] Manter `TASK_ACKNOWLEDGED` fail-closed: o runtime não injecta `BUILTIN_TRANSACTIONAL_HANDLERS`; a injecção transaccional continua explícita.
- [x] Acrescentar testes unitários do ciclo runtime para shutdown, fila vazia e falha no modo `--once`.
- [ ] Executar testes focados e suite API no SHA final.
- [ ] Validar `docker compose config`, build, arranque estável e hardening do `edge-event-worker` no smoke Docker Compose.
- [ ] Executar smoke PostgreSQL 16 com processo Edge real terminado por SIGKILL, expiração natural da lease, takeover e rejeição de credenciais antigas.
- [ ] Confirmar API CI, Quality Gates, Security Scans e Docker Compose verdes no mesmo SHA.
- [ ] Só depois avaliar configuração fail-closed do ACK; não adicionar a flag nem injectar a registry nesta fase.

**Limite conhecido:** o runtime de produção consome eventos com os handlers não transaccionais predefinidos (actualmente DEVICE_HEARTBEAT). Os restantes tipos sem handler configurado seguem a política existente de DEAD_LETTER. O handler transaccional TASK_ACKNOWLEDGED continua fora da injecção de deployment. A existência do processo não constitui autorização de ACK nem de produção.

---

## P0 — Edge Task Acknowledgement: validação e fronteira operacional (2026-11-27)

### Validação concluída — código
- [x] Validar atomicidade entre acknowledgement e conclusão PROCESSED na mesma transacção SQLAlchemy, protegida por owner, lease e fencing token.
- [x] Validar replay, claim concorrente, fencing e imutabilidade do ledger no smoke PostgreSQL 16.
- [x] Validar concorrência PostgreSQL 16 entre ACK e revogação nas duas ordens, com prova de lock através de `pg_stat_activity` e `pg_blocking_pids()`.
- [x] Validar isolamento de identidade cross-store nos testes do serviço.
- [x] Confirmar API CI, Quality Gates, Security Scans e Docker Compose no SHA de código `cd28865c03abaf4ccde959e098e1dcf462943299`: runs API `45998882415`, Quality Gates `45998882598`, Security Scans `45998882484`, Docker Compose `45998882648`.
- [x] Confirmar os workflows documentais posteriores: Quality Gates `45999727222` e Security Scans `45999727282`, ambos concluídos com sucesso.

### Fronteira operacional — revisão em curso
- [x] Confirmar que `TASK_ACKNOWLEDGED` não está activo por omissão: `process_one_edge_event()` só consulta `transactional_handlers` fornecido explicitamente; `BUILTIN_TRANSACTIONAL_HANDLERS` não é injectada automaticamente.
- [x] Confirmar que `COMPLETED` é persistido como `REVIEW_REQUIRED` e não altera tarefa, versão ou inventário.
- [x] Confirmar que o worker dispõe de lease, heartbeat, fencing, retry exponencial limitado e DEAD_LETTER.
- [x] Confirmar a fronteira de deployment: existe um serviço/processo `edge-event-worker` independente no `docker-compose.yml`, com entrypoint `python -m app.edge_event_worker`, ciclo de polling, lease/fencing, shutdown gracioso e supervisão por restart policy. O `vision-worker` continua dedicado à inferência de imagens.
- [x] Manter a decisão fail-closed: não adicionar `EDGE_TASK_ACKNOWLEDGEMENT_ENABLED` nem injectar automaticamente a registry transaccional. A existência do processo Edge não autoriza ACK; `transactional_handlers` continua a exigir injecção explícita.
- [ ] Definir autorização por acção (ACCEPTED/STARTED/COMPLETED), incluindo scopes/capacidades do dispositivo e política de revogação; a implementação actual valida dispositivo ACTIVE, loja, associação vigente e versão, mas não demonstra uma matriz de permissões por acção.
- [ ] Acrescentar métricas e correlação estruturada para ACK recebido/aplicado/rejeitado, duplicados, stale version, retries, dead-letter, lease perdido e latência; logs actuais não substituem métricas/alertas operacionais.
- [ ] Definir procedimento de revisão humana de `REVIEW_REQUIRED`, actor, decisão, motivo e reconciliação posterior, sem automatizar stock.
- [ ] Testar recuperação end-to-end: crash antes/depois do commit, lease expirada, takeover, retry e dead-letter; separar prova SQLite de prova PostgreSQL.
- [ ] Só considerar piloto após configuração, permissões por acção, observabilidade, revisão humana e ensaio operacional serem aprovados explicitamente.

### Decisão de deployment — 2026-11-27

A decisão histórica de não adicionar uma flag sem consumidor real foi respeitada. O processo dedicado `edge-event-worker` foi entretanto implementado e publicado; esta evolução não altera a decisão de manter ACK fail-closed. A validação de crash real e do container continua pendente até os smokes PostgreSQL e Docker Compose passarem no mesmo SHA.

### Restrições não negociáveis
- `TASK_ACKNOWLEDGED` permanece desactivado por omissão.
- `COMPLETED` permanece apenas `REVIEW_REQUIRED`.
- Nenhuma mensagem Edge conclui tarefa, altera stock, cria movimento ou reconcilia inventário.
- CI verde valida os cenários automatizados; não autoriza produção nem substitui homologação operacional.


---

## P0 — Histórico de reconciliações: consultas em lote e actor histórico (2026-11-26)

- [x] Substituir serialização N+1 por uma consulta paginada, uma consulta de utilizadores e uma consulta de eventos.
- [x] Preservar contrato JSON, ordem dos registos, ordem cronológica dos eventos e filtro de loja.
- [x] Guardar actor_snapshot (user_id, role, store_id, full_name) nos novos eventos CREATED e de revisão.
- [x] Acrescentar regressão que fixa em três consultas o custo da listagem com múltiplos registos e verifica os snapshots de actor.
- [ ] Executar testes focados, suite API, PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA final.
- [ ] Acrescentar cobertura explícita de página vazia e isolamento multi-loja para a listagem do ledger após a validação inicial.

Limite: eventos antigos permanecem sem snapshot; não reconstruir identidade histórica com dados actuais do utilizador. O snapshot não inclui email nem outros identificadores de contacto.

---

## P0 — Isolamento atómico do histórico de retenção de imagens (2026-11-26)

- [x] Identificar a leitura em duas fases no GET /api/v1/shelf-images/{image_id}/retention/events: consulta dos eventos seguida de consulta separada da imagem quando a página vinha vazia.
- [x] Substituir por uma única query tenant-scoped com ShelfImage como entidade-pai e OUTER JOIN a uma subquery de eventos paginada.
- [x] Preservar histórico vazio e offset além do último evento como lista vazia para imagem autorizada.
- [x] Preservar 404 idêntico para imagem de outra loja e identificador inexistente.
- [x] Acrescentar regressão para histórico vazio, paginação, cross-store e ID inexistente.
- [ ] Validar teste focal, suite API, PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA final.

## P0 — Leituras atómicas do histórico de alertas e movimentos (2026-11-26)

- [x] Consolidar leitura do movimento e dos eventos numa única query com OUTER JOIN e filtro simultâneo de movement_id + store_id para supervisores.
- [x] Preservar 404 idêntico para movimento estrangeiro/inexistente e histórico vazio como lista vazia para movimento autorizado.
- [x] Acrescentar regressão API para leitura same-store e tentativa cross-store de histórico de movimento.
- [x] Consolidar leitura do alerta e dos eventos numa única query com OUTER JOIN, filtro tenant-scoped e sem fallback em segunda query.
- [x] Manter os testes existentes de histórico vazio, IDs estrangeiros/inexistentes e permissões de alertas.
- [ ] Validar pytest focal, suite API, PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA final.

## P0 — Isolamento do histórico de auditoria de mapeamentos ERP/WMS (2026-11-26)

- [x] Identificar a janela TOCTOU no endpoint GET /api/v1/stores/{store_id}/inventory/external-mappings/{mapping_id}/events: o preflight validava o mapping por loja, mas a query seguinte lia eventos apenas por mapping_id.
- [x] Substituir preflight + leitura independente por uma única query InventoryExternalProductMapping OUTER JOIN InventoryExternalProductMappingEvent, filtrada simultaneamente por mapping_id e store_id.
- [x] Preservar items: [] para mapping válido sem eventos e devolver 404 indistinguível para mapping estrangeiro/inexistente.
- [x] Acrescentar regressão API para histórico vazio e tentativa de leitura do ID de mapping de outra loja sob o path da loja autorizada.
- [ ] Validar teste focal, suite API e workflows CI no SHA final desta correcção.

## P0 — Isolamento tenant no histórico de eventos de jobs ERP/WMS (2026-11-26)

- [x] Remover a separação entre preflight do job e leitura dos eventos: a query passa a usar InventorySyncJob como tabela-pai, OUTER JOIN aos eventos e predicados simultâneos job.id + job.store_id.
- [x] Preservar histórico vazio como items: [] através do OUTER JOIN, sem confundir job válido sem eventos com job estrangeiro/inexistente.
- [x] Adicionar regressão API para job de outra loja consultado através da loja autorizada e exigir 404 igual ao ID inexistente; manter a verificação 403 quando o actor tenta usar directamente o path de outra loja.
- [x] Executar teste focal integrado na suite API, suite API/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA final (HEAD 3bc6963; API CI 45821668415, Docker 45821668480, Quality Gates 45821668581, Security Scans 45821668381).
- [x] Confirmar que `store_id` é identidade de tenant: o enqueue define a loja, os endpoints apenas lêem o job e o worker captura `store_id` sem o reassociar; os eventos são ligados apenas por `job_id`, pelo que alterar o tenant mudaria a visibilidade do histórico.
- [x] Criar migration 0101 com guarda de imutabilidade de `inventory_sync_jobs.store_id` em PostgreSQL e SQLite, sem bloquear actualizações de estado/lease/fencing.
- [x] Acrescentar teste SQLite da migration, incluindo actualização de campos operacionais, rejeição de reassociação e downgrade.
- [x] Acrescentar smoke PostgreSQL concorrente: UPDATE de tenant aguarda por row lock, é rejeitado pela trigger após libertação e não altera a loja; actualizações normais do ciclo de vida continuam permitidas.
- [x] Executar migration 0101 em PostgreSQL 16, teste SQLite, smoke de concorrência, suite API, Quality Gates, Security Scans e Docker Compose no SHA 3bc6963; API CI confirmou upgrade 0100 → 0101 e o smoke de reassociação concorrente.

Validação: API CI/PostgreSQL 16, suite API, Docker Compose, Quality Gates e Security Scans concluídos com sucesso no SHA 3bc6963176d7c142b223dbca82537691542a6aff. O log confirma a aplicação da migration 0101 e a rejeição da reassociação pelo trigger. A auditoria BOLA/IDOR global permanece aberta.
## P0 — Serialização da propriedade da prateleira nas escritas (2026-11-26)

- [x] Introduzir `_lock_store_scoped_shelf()`: obter a linhagem inicial, bloquear primeiro `Zone` com `SELECT FOR UPDATE`, validar novamente o tenant e bloquear depois `Shelf`; uma alteração de `zones.store_id` tem de aguardar pela transacção da escrita.
- [x] Aplicar o helper à criação de observações, criação de sessões de captura e upload de imagens.
- [x] Derivar `CaptureSession.store_id` e o directório de armazenamento da zona bloqueada, nunca de uma relação ORM carregada antes do lock.
- [x] Manter a ordem de locks `Zone → Shelf → CaptureSession` no upload e validar que a sessão pertence à mesma prateleira e loja.
- [x] Abranger escrita do ficheiro, `flush`, `refresh` e `commit` no mesmo bloco de limpeza; qualquer falha antes do commit faz rollback e remove um ficheiro parcial.
- [x] Acrescentar regressão HTTP para observação, sessão e upload cross-store, sessão de outra loja, sessão da mesma loja mas de outra prateleira e controlo positivo same-store.
- [x] Reforçar o smoke PostgreSQL já executado pelo API CI: criação HTTP de sessões same-store/cross-store e prova de que um UPDATE concorrente de `zones.store_id` fica em `wait_event_type='Lock'`, bloqueado pelo PID da transacção que mantém a escrita da prateleira.
- [x] Corrigir o smoke PostgreSQL: após comprovar que o UPDATE concorrente fica bloqueado pelo lock da escrita da prateleira, exigir que a transferência seja rejeitada pela protecção de evidência retida, em vez de esperar uma transferência bem-sucedida incompatível com o contrato de integridade.
- [x] Verificar que, após a rejeição, a sessão de captura permanece associada à loja A, a zona continua na loja A e o supervisor autorizado mantém acesso.
- [ ] Executar e confirmar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA final.
- [ ] Rever os resultados dos workflows e corrigir eventuais regressões antes de considerar P0.1 fechado.

Limite: a falha anterior não era uma falha de autorização da sessão. O smoke esperava que a zona mudasse de loja depois do lock, mas a protecção de integridade da base de dados rejeita correctamente essa transferência quando já existe evidência operacional. O teste foi alinhado com esse contrato; ainda aguarda nova execução CI. O inventário actual de rotas não encontrou endpoint HTTP de transferência/actualização de zonas.

## P0 — Revalidação tenant na leitura do consenso de observações (2026-11-26)

- [x] Identificar que o endpoint fazia preflight de `shelf_id`, mas consultava depois observações apenas por `shelf_id`, sem repetir a linhagem de loja na query de evidência.
- [x] Aplicar JOIN `Observation → Shelf → Zone` e filtro `Zone.store_id` na mesma query que lê as observações para SUPERVISOR.
- [x] Reaplicar o mesmo tenant scope na validação de `ShelfProduct` quando é fornecido `product_id`.
- [x] Preservar o `store_id` autorizado do actor na resposta do SUPERVISOR.
- [x] Acrescentar regressão determinística que transfere a zona depois do preflight e antes da leitura, exigindo zero observações devolvidas.
- [ ] Validar teste focal, suite API, PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA final.
- [ ] Avaliar smoke concorrente PostgreSQL dedicado se a revisão das operações de transferência confirmar um caminho concorrente suportado que justifique serialização por lock.

Limite: a alteração elimina a leitura de evidência sem predicado tenant na query. O teste publicado simula o interleaving entre preflight e leitura; ainda não prova lock wait/serialização PostgreSQL real nem fecha a auditoria BOLA/IDOR global.

## P0 — Imutabilidade da associação shelf da imagem-fonte de exemplares embedding (2026-11-26)

- [x] Confirmar que a revisão de exemplares bloqueia primeiro a linha `shelf_images`, seguindo a ordem imagem → produto → exemplar.
- [x] Identificar que a migration 0037 torna imutável a linhagem do exemplar, mas não impede a alteração posterior de `ShelfImage.shelf_id` quando existem exemplares derivados.
- [x] Criar migration 0100 com guarda PostgreSQL/SQLite que rejeita a mudança de shelf enquanto existir `ProductEmbeddingExemplar` associado à imagem.
- [x] Acrescentar teste SQLite para rejeição com exemplar, permissão sem exemplar e downgrade limitado à guarda nova.
- [x] Acrescentar smoke PostgreSQL concorrente que usa a revisão HTTP real e observa o lock wait efectivo através de `pg_stat_activity`.
- [x] API CI `45805339672`, commit de código `bef29291b55f7a51dd35d917f0d64c3e0b2f7f11`: migration 0100 aplicada em PostgreSQL 16; smoke concorrente passou e provou que a reassociação cross-store aguardou pelo lock e foi rejeitada após o commit da revisão.
- [x] Smoke de ciclo `45805339672`: upgrade 0100, downgrade 0100→0099 (confirmando que as seis triggers/cinco funções de 0099 permanecem), e reaplicação 0100 concluídos com sucesso.
- [x] Suite API: **1740 passed, 1 skipped**.
- [x] Docker Compose `45805339652`: sucesso no mesmo commit de código.
- [x] Quality Gates `45805397438` e Security Scans `45805397536`: sucesso no descendente documental `a09fc5a10dbbfe6d79e7e320dd3efb9979527cf1`, sem alterações de código relativamente ao commit validado pela API CI.
 
Conclusão: migration 0100 validada em PostgreSQL 16 e SQLite. A guarda protege a associação directa imagem→shelf enquanto existirem exemplares embedding; não substitui a auditoria mais ampla de outros endpoints com IDs directos nem a revisão global BOLA/IDOR.

## P0 — Isolamento multi-loja no histórico de eventos de alertas (2026-11-26)

- [x] Fazer JOIN de ObservationAlertEvent com ObservationAlert na query que devolve o histórico.
- [x] Aplicar `ObservationAlert.store_id == actor.store_id` na mesma query para SUPERVISOR.
- [x] Preservar `[]` para alerta autorizado sem eventos e 404 indistinguível para alerta estrangeiro/inexistente.
- [x] Acrescentar regressão HTTP com alertas nas duas lojas, evento próprio, evento estrangeiro e ID inexistente.
- [x] Validado no código `eea9cc5d`: API CI `45797706450` (1739 passed, 1 skipped; PostgreSQL 16), Quality Gates `45798609654` e Security Scans `45798609531` no HEAD documental `3b288869`; Docker Compose `45797706344` passou no mesmo código.

Limite: implementação, regressão e CI validadas. A autorização é derivada do alerta-pai, porque ObservationAlertEvent não possui `store_id` próprio.

## P0 — Isolamento multi-loja nos históricos de tarefas e movimentos (2026-11-26)

- [x] Fazer JOIN do evento ao recurso-pai (ReplenishmentTask / InventoryMovement) na consulta que devolve o histórico.
- [x] Aplicar o filtro store_id directamente nessa consulta para SUPERVISOR, sem depender apenas de uma validação anterior do recurso-pai.
- [x] Preservar a distinção entre histórico vazio de um recurso autorizado e recurso estrangeiro/inexistente (404 indistinguível).
- [x] Acrescentar regressão HTTP para histórico de tarefas; reforçar a cobertura existente de movimentos, incluindo paridade estrangeiro/inexistente e bloqueio EMPLOYEE.
- [x] Validado no código `eea9cc5d`: API CI `45797706450` (1739 passed, 1 skipped; PostgreSQL 16), Quality Gates `45798609654` e Security Scans `45798609531` no HEAD documental `3b288869`; Docker Compose `45797706344` passou no mesmo código.

Limite: alterações, regressões e CI validadas. ADMIN mantém consulta global. As queries de eventos aplicam a linhagem do recurso-pai na mesma instrução SQL que devolve os eventos.

## P0 — Isolamento multi-loja no histórico de retenção de imagens (2026-11-26)

- [x] Substituir a sequência de resolução global da loja + `db.get(ShelfImage, image_id)` por queries com JOIN ShelfImage → Shelf → Zone.
- [x] Aplicar o filtro `Zone.store_id == actor.store_id` tanto na query de eventos como na verificação de existência quando o histórico está vazio; IDs estrangeiros e inexistentes devolvem 404.
- [x] Acrescentar regressão HTTP que cria um evento de retenção numa imagem estrangeira e compara a resposta com um ID inexistente.
- [x] Validado no código `eea9cc5d`: API CI `45797706450` (1739 passed, 1 skipped; PostgreSQL 16), Quality Gates `45798609654` e Security Scans `45798609531` no HEAD documental `3b288869`; Docker Compose `45797706344` passou no mesmo código.
- [ ] Continuar a auditoria de concorrência e de outros endpoints com IDs directos.

Limite: implementação, regressão e CI validadas. O histórico de retenção não contém `store_id` próprio, pelo que a autorização deriva da imagem-pai validada por JOIN.

## P0 — Isolamento multi-loja na revisão de exemplares de embeddings (2026-11-26)

- [x] Substituir a leitura inicial global por uma query tenant-scoped: exemplares associados a imagens de outras lojas não são materializados para SUPERVISOR.
- [x] Preservar a regra ADMIN-only para exemplares sem imagem de origem; a query mantém esses registos apenas para aplicar a resposta 403 existente.
- [x] Acrescentar regressão HTTP que compara ID de exemplar estrangeiro com ID inexistente (404/corpo idêntico) e confirma que o estado PENDING e a atribuição de revisão não mudam.
- [x] Validado no código `eea9cc5d`: API CI `45797706450` (1739 passed, 1 skipped; PostgreSQL 16), Quality Gates `45798609654` e Security Scans `45798609531` no HEAD documental `3b288869`; Docker Compose `45797706344` passou no mesmo código.
- [ ] Auditar concorrência entre alteração de associação da imagem e revisão do exemplar, além dos restantes endpoints com IDs directos.

Limite: alteração, regressão e CI validadas. A query tenant-scoped reduz a exposição antes da autorização; permanece pendente a auditoria de concorrência entre alteração de associação da imagem e revisão do exemplar.

## P0 — Cobertura explícita de autorização RBAC (2026-11-26)

- [x] Inventariar estaticamente os decorators HTTP de `apps/api/app/main.py` e comparar método/template com `API_ROUTE_POLICIES`.
- [x] Confirmar que todos os endpoints `/api/v1/*` declarados em `main.py` têm política explícita; as únicas rotas sem política na aplicação principal são `/health` e `/health/ready`, fora da API versionada.
- [x] Confirmar que a política `POST /api/v1/edge/events` corresponde ao router Edge separado, com autenticação própria.
- [x] Acrescentar regressão que percorre as rotas FastAPI registadas e falha quando uma rota versionada não tem política RBAC explícita.
- [x] Validado no código `eea9cc5d`: API CI `45797706450` (1739 passed, 1 skipped; PostgreSQL 16), Quality Gates `45798609654` e Security Scans `45798609531` no HEAD documental `3b288869`; Docker Compose `45797706344` passou no mesmo código.
- [ ] Continuar auditoria BOLA/IDOR por identificador de recurso e provar isolamento multi-loja nas operações de leitura e escrita.

Limite: a comparação estática e a regressão passaram no API CI. Isto confirma cobertura de classificação RBAC, não prova autorização correcta em cada handler nem isolamento de todos os recursos; a auditoria BOLA/IDOR continua aberta.

## P0 — Autoridade física WMS por loja/localização (2026-11-25)

- [x] Definir WMS como fonte de referência da retaguarda e ERP como fonte administrativa independente.
- [x] Acrescentar `location_code` e `availability_status` aos snapshots; registos legados ficam UNKNOWN e não são elegíveis.
- [x] Configurar a localização de retaguarda WMS exacta por loja através da política de frescura existente.
- [x] Exigir motivo e guardar alterações à autoridade num ledger append-only com actor e valores anterior/novo.
- [x] Exigir localização e disponibilidade explícitas em lotes de adapters WMS; ERP não ganha autoridade física.
- [x] Persistir proveniência no orquestrador e incluí-la na comparação de replay idempotente.
- [x] Restringir reconciliação de retaguarda, recomendações e movimentos à localização WMS configurada.
- [x] Impedir fallback para ERP, outra localização ou snapshot WMS antigo quando o registo mais recente está UNAVAILABLE/UNKNOWN.
- [x] Acrescentar regressões para ERP sem fallback, estado WMS indisponível, localização errada, configuração por loja e auditoria da política.
- [x] Confirmar migrations 0084/0085, suite API (1679 passed, 1 skipped), PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA `c8efb82b64d4aed9fcc81fdb4a0571695fdd23cf`.
- [ ] Homologar adapter WMS real e validar mapeamento de localizações com o fornecedor.
- [x] Implementar normalização logística interna por SKU: Product.unit como unidade base e níveis UNIT/CASE/PALLET com factores Decimal, cálculo read-only e sem movimentos automáticos.
- [ ] Mapear códigos/unidades e factores externos do WMS para a unidade base interna, com vigência/versionamento e homologação do fornecedor.
- [ ] Expandir a auditoria de movimentos manuais e reconciliação de reservas multi-localização.

Limite: o código suporta o contrato e a configuração, mas ainda não existe adapter WMS real homologado. Não apresentar o ledger de sincronização como prova de conectividade externa.

## Inventário — validação integral do worker durável ERP/WMS (2026-11-25; quatro workflows aprovados)

- [x] Smoke PostgreSQL 16: claims concorrentes, takeover, fencing monotónico e rejeição de worker obsoleto no limite de escrita.
- [x] Interrupção SIGKILL depois do commit de uma página real; recuperação do ledger abandonado como PARTIAL/WORKER_LEASE_EXPIRED.
- [x] Replay idempotente: reutilização do snapshot da primeira página (mesmo ID/conteúdo) e persistência da página seguinte sem duplicação.
- [x] API CI: migrações e smoke PostgreSQL, seguidos da suite completa da API — sucesso.
- [x] Quality Gates: compilação Python, testes API, TypeScript/build Web e verificações de qualidade — sucesso.
- [x] Security Scans: OWASP ZAP passive baseline e importação OpenAPI com baseline em modo seguro, auditorias de dependências Web/Python e Gitleaks — sucesso.
- [x] Docker Compose demo smoke — sucesso.
- [x] Confirmar os quatro workflows no mesmo SHA: `ffe76015e82d9d1ae608dc61a1bb5c9a9d8c710e`.

Execuções:
- API CI: [45522939384](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45522939384)
- Quality Gates: [45522939251](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45522939251)
- Security Scans: [45522939233](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45522939233)
- Docker Compose: [45522939260](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45522939260)

A correcção de `DetachedInstanceError` e a captura dos tokens escalares no teste de fencing não alteraram a lógica de produção. O ZAP terminou com sucesso, incluindo a importação OpenAPI e a análise em modo seguro. Esta validação comprova os cenários cobertos pelos workflows; não equivale a homologação de um ERP/WMS real nem a uma auditoria de segurança externa independente.

## Integrações ERP/WMS — contrato de adapters (2026-11-24; contrato publicado, sem conectores reais)

- [x] Definir protocolo assíncrono read-only para adapters ERP/WMS.
- [x] Normalizar SKU, identificador externo, quantidades decimais, referência e timestamp com fuso horário.
- [x] Validar precisão compatível com Numeric(12, 3), quantidades não negativas e reservado ≤ físico.
- [x] Rejeitar referências externas e SKU duplicados dentro do mesmo lote.
- [x] Carregar factories confiáveis por caminho module:callable, falhando de forma explícita quando não configuradas ou incompatíveis.
- [x] Acrescentar testes de contrato e validação.
- [ ] Integrar o contrato a um worker/orquestrador, com credenciais em secret manager, timeout, paginação e retries controlados.
- [ ] Implementar e homologar adapters específicos após receber documentação e credenciais dos fornecedores.

Limite: este commit não inclui conectores ERP/WMS, chamadas de rede, scheduler, gravação de snapshots nem credenciais. Nenhum adapter mock é registado como integração real.

## Inventário — histórico de sincronizações ERP/WMS (2026-11-24; implementação publicada, CI pendente)

- [x] Persistir tentativas ERP/WMS com início, conclusão, fornecedor, referência externa, contagens, duração e erros.
- [x] Restringir o ciclo de vida a STARTED → SUCCESS/PARTIAL/FAILED, uma única vez, com eventos append-only e proteção na base de dados.
- [x] Expor histórico e estado de saúde por loja, com alertas calculados para fonte nunca sincronizada ou desatualizada.
- [x] Apresentar histórico e estado das fontes no painel React.
- [ ] Validar API CI/PostgreSQL 16, migração 0077, Quality Gates, Security Scans e Docker Compose no HEAD final.
- [ ] Desenvolver adapters reais após obter contratos, credenciais e ambiente de homologação do fornecedor.

## Reposição — bloquear evidência com timestamp futuro (2026-11-24; implementação/teste publicados, CI pendente)

- [x] Introduzir o estado `INVALID_OBSERVATION_TIMESTAMP` nas recomendações de reposição.
- [x] Impedir a geração de quantidade sugerida quando a observação mais recente está datada no futuro.
- [x] Explicar que é necessário verificar a sincronização do relógio antes de criar uma tarefa.
- [ ] Validar testes focados, suite API e CI PostgreSQL no HEAD final.

## Inventário — frescura das observações de prateleira (2026-11-24; implementação/testes publicados, CI pendente)

- [x] Expor `observation_age_minutes` na reconciliação para distinguir evidência recente de evidência antiga.
- [x] Calcular a idade em UTC, arredondada a duas casas decimais, sem transformar observações ausentes em idade zero.
- [x] Sinalizar timestamps futuros (`observation_timestamp_in_future`) em vez de os apresentar silenciosamente como observações com idade zero.
- [x] Cobrir observação com 90 minutos e ausência de observação com `null`.
- [ ] Validar teste focado, API CI/PostgreSQL 16, Quality Gates e Security Scans no HEAD final.

## Inventário — ausência de evidência na reconciliação (2026-11-24; teste publicado, CI pendente)

- [x] Acrescentar regressão para associação produto/prateleira sem observação e sem snapshot de retaguarda.
- [x] Exigir estado `NO_OBSERVATION`, quantidades/diferenças `null` e ausência de inferência de stock zero.
- [x] Confirmar que a consulta read-only não cria movimentos nem snapshots.
- [ ] Executar teste focado, API CI/PostgreSQL 16, Quality Gates e Security Scans no HEAD desta alteração.

## Desenvolvimento funcional — histórico de movimentos de inventário (2026-11-23; CI pendente)

- [x] Disponibilizar consulta read-only dos movimentos aprovados em `GET /api/v1/inventory/movements`.
- [x] Filtrar por loja (obrigatória), produto e tarefa; limitar resultados entre 1 e 500.
- [x] Restringir leitura a ADMIN e SUPERVISOR, respeitando o âmbito multi-loja.
- [x] Testar histórico, filtros, ausência de mutação, bloqueio EMPLOYEE e isolamento de loja.
- [ ] Confirmar API CI e restantes Quality/Security Gates no HEAD desta alteração.

## Desenvolvimento funcional — KPIs operacionais do dashboard (2026-11-23; código/testes publicados, CI pendente)

- [x] Expor contagens de tarefas por prioridade e estados, mantendo os filtros existentes por loja e utilizador.
- [x] Expor tarefas activas urgentes e tarefas activas sem atribuição.
- [x] Calcular taxa de conclusão com denominador explícito (todas as tarefas visíveis, incluindo canceladas).
- [x] Corrigir `shelves_requiring_attention`: contar prateleiras distintas, não somar observações repetidas.
- [x] Distinguir `attention_observations` de `shelves_requiring_attention`.
- [x] Acrescentar testes para SUPERVISOR, EMPLOYEE e ADMIN, isolamento multi-loja e observações duplicadas.
- [ ] Confirmar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no novo HEAD.

## Segurança P0 — paridade BOLA para IDs de deteção e exemplares (2026-11-23; smoke reforçado, CI pendente)

- [x] No smoke PostgreSQL pré-lock, comparar o status e o corpo completos para IDs reais estrangeiros e IDs inexistentes nos endpoints de revisão e histórico de deteções.
- [x] Aplicar a mesma comparação à revisão de exemplares, mantendo bloqueadas as linhas PostgreSQL da imagem e do produto durante os pedidos.
- [x] Confirmar HTTP 404 indistinguível nos seis pedidos e ausência de persistência de revisões.
- [ ] Confirmar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no novo commit.

## Segurança P0 — isolamento de IDs de artefactos externos (2026-11-23; smoke PostgreSQL adicionado, CI pendente)

- [x] Expandir `postgres_artifact_consumption_smoke.py` com duas imagens na mesma loja e uma segunda loja, incluindo artefactos persistidos em ambas.
- [x] Rejeitar combinações cruzadas de `image_id`, `artifact_id` e `store_id` em cinco direcções, antes de qualquer chamada ao provider.
- [x] Confirmar que uma integração REVOKED noutra loja, com o mesmo `external_system`, não interfere com a leitura válida da loja proprietária.
- [x] Preservar controlo positivo: leitura same-store devolve os bytes esperados e invoca o provider uma única vez.
- [x] Verificar em PostgreSQL que uma referência filha não pode apontar para um artefacto pai de outra imagem da mesma loja (FK composta).
- [ ] Confirmar API CI/PostgreSQL 16, Quality Gates e Security Scans no commit de código `2bf0d075`.

Limite: o smoke usa um provider determinístico e valida a fronteira transaccional/identidade; não demonstra conectividade com fornecedores externos. A API não expõe um parâmetro `integration_id` para consumo, pelo que a selecção da integração continua a ser resolvida internamente por `store_id + external_system`.

---

## Segurança P0 — IDs directos de Warehouse: paletes e políticas (2026-11-23; CI validada)

- [x] Reforçar o smoke PostgreSQL 16 para comparar a leitura de eventos de uma palete estrangeira com um ID inexistente (HTTP 404 e corpo idêntico).
- [x] Cobrir a escrita de eventos de ciclo de vida de paletes estrangeiras e inexistentes com respostas equivalentes, sem alterar estado nem criar eventos.
- [x] Cobrir a actualização de políticas de rotação por ID estrangeiro/inexistente, confirmando que a política estrangeira permanece activa.
- [x] Preservar o controlo positivo same-store: um SUPERVISOR actualiza a própria palete e recebe HTTP 201.
- [x] Corrigir expectativas de autorização dos planogramas para o contrato de ocultação HTTP 404, incluindo criação, listagem e comparação.
- [x] API CI [45268275419](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275419): migrations e smokes PostgreSQL 16 aprovados; **1599 passed, 1 skipped**.
- [x] Quality Gates [45268275423](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275423): **1599 passed, 1 skipped**, compilação Python e build Web aprovados.
- [x] Security Scans [45268275427](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275427): Gitleaks, pip-audit, npm audit e OWASP ZAP passive baseline aprovados.
- [x] Docker Compose demo smoke [45268275477](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275477) aprovado.
- [ ] Continuar a matriz BOLA/IDOR nos restantes recursos e relações indirectas; esta ronda cobre os caminhos Warehouse identificados, não todos os endpoints do produto.

Decisão: ADMIN mantém o âmbito global previsto. SUPERVISOR só pode resolver e alterar recursos da própria loja; IDs estrangeiros e inexistentes são indistinguíveis. Escritas continuam a exigir autorização antes do lock e revalidação depois do lock. A visão computacional não movimenta inventário.

---

## Segurança P0 — ocultação de IDs de prateleiras em operações de planograma (2026-11-23)

- [x] Aplicar o filtro de tenant directamente à query que resolve a prateleira para operações de planograma.
- [x] Uniformizar HTTP 404 e o detalhe `Shelf not found` para prateleiras estrangeiras e inexistentes, sem consultar primeiro o `store_id` de uma linha estrangeira.
- [x] Actualizar a regressão unitária para exigir o contrato de ocultação.
- [x] Validado no commit `a29a7ea2fde29d7a49576c435700c7516b00f2a2`: API CI [45268275419](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275419), Quality Gates [45268275423](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275423), Security Scans [45268275427](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275427) e Docker Compose [45268275477](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275477) passaram. API CI e Quality Gates: 1599 passed, 1 skipped.

Decisão: ADMIN mantém visibilidade global. SUPERVISOR só resolve prateleiras da sua loja; um ID estrangeiro é indistinguível de um ID inexistente. A query deixa de materializar previamente o tenant da prateleira estrangeira.


## Segurança P0 — histórico de eventos de paletes sem oráculo cross-store (2026-11-23; smoke PostgreSQL reforçado)

- [x] Manter a resolução da palete limitada por pallet_id e store_id antes de consultar os eventos.
- [x] Reforçar o smoke PostgreSQL multi-loja: comparar a resposta HTTP da palete estrangeira com a de um ID inexistente e exigir HTTP 404 com corpo idêntico.
- [x] Preservar o controlo positivo same-store já existente no smoke, garantindo HTTP 200 para o histórico da própria loja.
- [x] Validado no commit `a29a7ea2fde29d7a49576c435700c7516b00f2a2`: API CI [45268275419](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275419), Quality Gates [45268275423](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275423), Security Scans [45268275427](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275427) e Docker Compose [45268275477](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275477) passaram; smoke PostgreSQL 16 e 1599 testes passaram.

Decisão: o histórico é consultado apenas depois de a palete pai ser resolvida no tenant autorizado. A igualdade de respostas 404 evita que o endpoint funcione como oráculo de existência para IDs de paletes estrangeiras.

---

## Segurança P0 — consulta de histórico de alertas sem oráculo cross-store (2026-11-23; implementação/testes publicados, CI pendente)

- [x] Fazer a consulta de alertas para SUPERVISOR filtrar `alert_id` e `store_id` na mesma query, sem carregar previamente alertas estrangeiros.
- [x] Preservar visibilidade global de ADMIN e recusa HTTP 403 para EMPLOYEE.
- [x] Acrescentar regressão que compara alerta de outra loja com ID inexistente: HTTP 404 e corpo idêntico.
- [ ] Validar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA desta alteração.

Decisão: os handlers read-only por ID directo também aplicam o tenant no predicado SQL sempre que possível. A política de ocultação é HTTP 404 para IDs estrangeiros/inexistentes; não é necessário adquirir row lock numa consulta de histórico imutável.

---

## Segurança P0 — ocultação de IDs directos de deteções em fluxos de observação e histórico (2026-11-23; implementação/testes publicados, CI pendente)

- [x] Aplicar `hide_foreign=True` na criação de observações a partir de `detection_id`.
- [x] Aplicar `hide_foreign=True` na consulta do histórico de revisões por `detection_id`.
- [x] Preservar autorização pré-lock e revalidar o tenant depois do lock da imagem.
- [x] Acrescentar regressões autenticadas que comparam deteção estrangeira com ID inexistente nos dois endpoints e confirmam HTTP 404 idêntico.
- [ ] Validar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no novo SHA.

Decisão: todos os endpoints multi-loja que recebem um identificador directo de deteção ocultam a existência de deteções estrangeiras com o mesmo contrato 404 dos IDs inexistentes. A autorização continua a ser aplicada antes do lock e revalidada depois do lock da imagem de origem.

---

## Segurança P0 — IDs de prateleira em criação e consenso (2026-11-23; código/testes publicados, CI pendente)

- [x] Autenticar/validar o papel antes de resolver IDs de prateleira em criação de observações e sessões de captura.
- [x] Uniformizar 404 para prateleiras estrangeiras e inexistentes na criação de observações/sessões e no consenso.
- [x] Fazer a avaliação de alertas herdar o contrato 404 do consenso, antes de qualquer persistência.
- [x] Acrescentar regressões HTTP para IDs estrangeiros/inexistentes e ausência de novas observações/sessões.
- [ ] Executar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no novo SHA.

## Segurança P0 — ocultação de IDs de consenso de prateleira (2026-11-23; código/testes publicados, CI pendente)

- [x] GET /api/v1/shelves/{shelf_id}/observation-consensus devolve HTTP 404 para prateleiras estrangeiras e inexistentes.
- [x] POST /api/v1/shelves/{shelf_id}/observation-alerts/evaluate herda o mesmo contrato de ocultação ao consultar o consenso.
- [x] Acrescentar regressões autenticadas que comparam respostas de prateleira estrangeira e ID inexistente.
- [ ] Executar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no novo SHA.

## Segurança P0 — ocultação de IDs de sessões de captura e alertas (2026-11-23; código/testes publicados, CI pendente)

- [x] Fechar sessão por ID com autorização pré-lock e revalidação pós-lock, ocultando IDs de outras lojas com HTTP 404.
- [x] Actualizar alertas por ID com _lock_store_scoped_record(..., hide_foreign=True).
- [x] Ocultar alertas estrangeiros na consulta de eventos; manter leitura global para ADMIN.
- [x] Testar IDs estrangeiros e inexistentes com respostas 404 indistinguíveis, incluindo ausência de mutações em sessões e alertas.
- [ ] Executar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no novo SHA.
- [ ] Continuar a auditoria de IDs directos e relações indirectas de prateleiras.

## Segurança P0 — ocultação de IDs de localizações de armazém (2026-11-23; código/teste publicados, CI pendente)

- [x] Na criação de colocações, resolver a localização por ID através do helper de autorização multi-loja, verificando o tenant antes do lock e revalidando depois do lock.
- [x] Uniformizar HTTP 404 para localização estrangeira e ID inexistente, sem revelar a existência do identificador.
- [x] Acrescentar regressão HTTP autenticada para supervisor da loja A com localização real da loja B e ID inexistente; verificar que não é criada qualquer colocação.
- [ ] Executar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no commit de código/testes.
- [ ] Alargar a mesma revisão a IDs directos de prateleiras e restantes relações logísticas.

## Segurança P0 — ocultação de IDs directos de ciclo de vida de paletes (2026-11-23; código publicado, CI pendente)

- [x] Repor `hide_foreign=True` no acesso à palete por ID directo antes e depois do lock PostgreSQL.
- [x] Uniformizar a resposta HTTP 404 para paletes estrangeiras e IDs inexistentes na rota de registo de eventos de ciclo de vida.
- [x] Acrescentar regressão HTTP autenticada para ambos os casos, mantendo a verificação de que nenhuma palete ou evento é alterado.
- [x] Revalidado no commit `a29a7ea2fde29d7a49576c435700c7516b00f2a2`: API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose passaram; o smoke compara IDs estrangeiros e inexistentes e confirma ausência de mutações.
- [ ] Continuar a matriz BOLA/IDOR para IDs aninhados de localização, prateleira, tarefa, embalagem e relações indirectas.

Decisão: endpoints por ID directo que expõem recursos multi-loja ocultam a existência de IDs estrangeiros com 404, desde que a identidade do actor esteja autenticada. A autorização continua a ocorrer antes do lock e é revalidada depois do lock. ADMIN mantém a política global definida para o recurso.

---

## Segurança P0 — autorização pré-lock de IDs directos de deteções e exemplares (2026-11-23; smoke PostgreSQL adicionado, CI pendente)

- [x] Auditar os handlers POST/GET de revisão de deteções e PATCH de revisão de exemplares: resolver a imagem de origem, validar o tenant e só depois adquirir locks de imagem/produto; manter revalidação pós-lock.
- [x] Confirmar que a listagem de deteções é ancorada numa imagem previamente autorizada e activa; as rotas por ID directo de deteção passam pelo helper de autorização da imagem.
- [x] Acrescentar smoke PostgreSQL 16 com um supervisor da loja A e IDs reais de deteção/exemplar da loja B, mantendo simultaneamente bloqueadas as linhas da imagem e do produto.
- [x] Exigir HTTP 403, sem espera pelos locks, em revisão da deteção, histórico de revisão e revisão do exemplar; verificar ausência de alterações persistidas.
- [x] API CI [45194763822](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45194763822) passou no SHA `fefb56f`; o novo smoke PostgreSQL 16 passou e a suite terminou com **1588 passed, 1 skipped**.
- [x] Quality Gates [45194764768](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45194764768) passou: suite API **1588 passed, 1 skipped**, compilação Python e build TypeScript/produção aprovados.
- [x] Security Scans [45194765202](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45194765202) passou: Gitleaks, pip-audit, npm audit e OWASP ZAP Passive Baseline.
- [x] Docker Compose [45194764844](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45194764844) passou.
- [ ] Alargar a matriz aos IDs directos e relações indirectas restantes; este smoke cobre três operações, não todos os endpoints nem todos os papéis.
- [ ] Ensaiar volume PostgreSQL persistente preexistente com principal runtime, sem usar dados de produção.

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

## Segurança P0 — rejeição de IDs aninhados de paletes entre lojas (2026-11-23; código publicado, CI pendente)

- [x] Acrescentar controlo BOLA para pedido de planeamento de rotação com `store_id` autorizado da loja A e `pallet_id` real da loja B.
- [x] Acrescentar controlo BOLA para consulta de eventos de ciclo de vida com `store_id` da loja A e ID real da palete da loja B.
- [x] Exigir HTTP 404 em ambos os casos, evitando resolver recursos estrangeiros através de um âmbito autorizado.
- [ ] Executar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no commit `db177bce`.
- [ ] Alargar a mesma matriz a IDs estrangeiros de localização, shelf, tarefa, packaging e outros recursos relacionados.

Commit: `db177bce`. São dois controlos adicionais de IDs aninhados; não constituem cobertura global BOLA/IDOR.

---

## Segurança P0 — controlos positivos same-store com IDs logísticos reais (2026-11-23; implementação publicada, CI pendente)

- [x] Semear níveis de embalagem CASE e paletes reais para ambas as lojas no smoke PostgreSQL de autorização.
- [x] Remover exclusões dos controlos positivos para cálculo de unidades de reposição, plano de rotação de palete e eventos de ciclo de vida.
- [x] Usar o ID da palete da loja B nos pedidos cross-store e o ID da palete da loja A nos controlos same-store, evitando que um 404 por recurso inexistente seja confundido com autorização.
- [ ] Confirmar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no commit `3af7a02b`.
- [ ] Continuar a matriz BOLA/IDOR para IDs aninhados e relações indirectas nos restantes handlers.

Commit: `3af7a02b`. A prova cobre agora 23 leituras estrangeiras e 23 controlos positivos na loja própria; não representa ainda uma matriz exaustiva de todos os endpoints.

---

## Segurança P0 — matriz PostgreSQL de leituras multi-loja (2026-11-23; implementação publicada, CI pendente)

- [x] Expandir `postgres_inventory_authorization_smoke.py` com 23 pedidos GET cross-store para vendas diárias/horárias/tráfego, perfis de procura, previsão de procura/risco, portefólios, recomendações, plano e workload de reposição, decisões operacionais, localizações, paletes, políticas e eventos de paletes.
- [x] Executar os pedidos com JWT real de SUPERVISOR da loja A e `store_id` da loja B; todos têm de devolver HTTP 403 antes da leitura de dados.
- [x] Manter os testes existentes de negação de escrita em inventário, placement e tarefas, incluindo verificações de ausência de persistência, e os controlos positivos na loja própria.
- [x] API CI/PostgreSQL 16 passou no SHA `40f9456a` (run `45131503709`): todos os smokes, incluindo as 23 leituras cross-store, passaram; suite API **1555 passed, 1 skipped**.
- [x] Docker Compose demo smoke passou no SHA `40f9456a` (run `45131503757`); Web TypeScript/produção e detector Impeccable passaram no Quality Gates (run `45131503760`).
- [ ] Quality Gates API foi cancelado durante instalação de dependências e Security Scans foi parcialmente cancelado (pip-audit e ZAP); repetir/obter execução integral num SHA posterior.
- [ ] Acrescentar matriz positiva de leituras same-store e ampliar a auditoria BOLA/IDOR a endpoints que recebem IDs aninhados ou relações indirectas.
- [ ] Ensaiar volume PostgreSQL persistente preexistente e operações API reais com principal runtime; não executar contra produção.

Commit de teste: `40f9456a`. A matriz é uma cobertura de integração direccionada, não prova formal de todos os endpoints.

---

## Segurança P0 — autorização multi-loja antes de locks PostgreSQL (2026-11-23; CI validada)

- [x] Expandir `postgres_retention_legal_hold_concurrency_smoke.py` com duas lojas e um supervisor de uma loja diferente da imagem alvo.
- [x] Manter a linha da imagem bloqueada numa transacção PostgreSQL e provar que o pedido `POST /retention/restrict` do supervisor externo termina com HTTP 403 antes de o lock ser libertado.
- [x] Preservar os ensaios existentes de concorrência legal hold ↔ purge schedule e restore ↔ purge schedule.
- [x] Docker Compose demo smoke passou no commit de código `926abcf1`: [run 45129975482](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975482).
- [x] Corrigir a falha anterior do Compose smoke: as duas invocações inline do runtime-role smoke passam agora `MIGRATION_DB_USER` via `docker compose exec -e`, com regressão estática. Commits `b4995042` e `edf879a2`; o Compose smoke voltou a passar no SHA `926abcf1`.
- [x] O passo PostgreSQL `Verify PostgreSQL legal hold and purge schedule concurrency` passou no API CI [45129975394](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975394), SHA `926abcf1`; inclui o novo ensaio de supervisor de outra loja com a imagem bloqueada.
- [x] Expandir o ensaio para nove rotas HTTP (conteúdo, deteções, evidence fusion, OCR evidence/matches/runs, eventos de retenção, retry e restrict); o novo passo PostgreSQL passou no API CI [45130818413](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818413), SHA `d319d1a4`.
- [x] Quality Gates passou no SHA de código/testes `d319d1a4`: [run 45130818392](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818392), incluindo compilação Python, suite API e build Web.
- [x] Security Scans terminou com sucesso no [run 45130818374](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818374), SHA `d319d1a4`: Gitleaks, pip-audit, npm audit e OWASP ZAP passive baseline.
- [x] API CI passou integralmente no SHA de código `926abcf1`: [run 45129975394](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975394), incluindo migrações PostgreSQL 16, smokes operacionais, runtime role e **1555 passed, 1 skipped**.
- [x] API CI voltou a passar no SHA `d319d1a4`: [run 45130818413](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818413), **1555 passed, 1 skipped**, incluindo o smoke multi-rota de nove endpoints.
- [x] Security Scans terminou com sucesso no SHA documental `7b10c5c1`: [run 45130013260](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013260), incluindo Gitleaks, pip-audit, npm audit e OWASP ZAP passive baseline.
- [ ] Expandir a prova PostgreSQL aos restantes handlers de escrita/revisão que usam `_lock_authorized_shelf_image`; o smoke actual cobre nove rotas HTTP de leitura, retry, eventos de retenção e restrição. Os endpoints ADMIN-only de artefactos/legal hold/purge seguem a política de administrador global.
- [ ] Ensaiar um volume PostgreSQL persistente preexistente e executar operações API reais com o principal runtime; nunca executar estes ensaios contra produção.

Commits: `25a34b8f` (smoke PostgreSQL) e `926abcf1` (documentação/contrato do smoke).

---

## Segurança P0 — autorização de tenant antes de locks de retenção e artefactos (2026-11-23; CI validada, cobertura adicional pendente)

- [x] Corrigir `restore_shelf_image`, `apply_shelf_image_legal_hold`, `release_shelf_image_legal_hold`, `schedule_shelf_image_purge` e `cancel_shelf_image_purge_schedule` para resolver e validar o tenant antes de bloquear a imagem, usando `_lock_authorized_shelf_image`.
- [x] Corrigir `get_shelf_image_purge_eligibility` para validar a loja antes do primeiro lock e revalidar a linhagem depois do lock.
- [x] Corrigir `register_shelf_image_artifact_reference`, `create_shelf_image_artifact_inventory_snapshot`, `get_shelf_image_artifact_access_decision` e `create_shelf_image_artifact_disposition_event` com a mesma regra de autorização pré-lock.
- [x] Expandir o teste estático de ordem de locks para cobrir os dez handlers.
- [x] Auditoria estática do código actual confirma que os dez handlers autorizam antes do primeiro `FOR UPDATE`.
- [x] Validar em PostgreSQL o caminho comum de autorização pré-lock: supervisor de outra loja recebe 403 enquanto a imagem está bloqueada; smoke [45129975394](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975394), SHA `926abcf1`.
- [ ] Acrescentar/confirmar testes PostgreSQL multi-store de negação cruzada para cada fluxo de retenção e artefactos; a prova actual cobre um handler representativo e os testes estáticos verificam a utilização do helper nos restantes.
- [ ] Ensaiar volume persistente PostgreSQL e operações reais com principal runtime.

Commits: `f6e2156e`, `659586be`, `7f372fbc`, `cbc6a1a6`, `70b1b351`.

---
## Segurança P0 — verificação efectiva do principal PostgreSQL runtime (2026-11-22)

- [x] Expandir `apps/api/scripts/postgres_runtime_role_smoke.py` para verificar LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS e NOINHERIT.
- [x] Verificar ausência de memberships e ownership através de `pg_shdepend`, CONNECT à base de dados, USAGE sem CREATE no schema público e privilégios DML nas tabelas operacionais.
- [x] Verificar ACLs por defeito para tabelas/sequências futuras, sem GRANT OPTION, e confirmar SELECT-only nas tabelas de confiança ONNX.
- [x] Acrescentar regressões estáticas em `test_database_role_separation.py` para garantir que o smoke mantém estas verificações.
- [x] Restringir a leitura de `pg_default_acl` ao `defaclrole` do principal de migrations (`MIGRATION_DB_USER`), evitando agregar ACLs de owners diferentes.
- [x] Passar `MIGRATION_DB_USER=postgres` explicitamente no job PostgreSQL 16 da API CI.
- [x] Validação anterior à correcção: API CI [45083455380](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083455380) e Docker Compose [45083455389](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083455389) passaram no SHA `72d4034d`; Quality Gates [45083489901](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083489901) e Security Scans [45083489889](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083489889) passaram no SHA `9bad015c`. Estes resultados antecedem a correcção do filtro por owner.
- [x] API CI e smoke PostgreSQL 16 passaram no SHA `8e5a6810` (run [45084795278](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45084795278)); Quality Gates [45084849142](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45084849142) e Security Scans [45084849107](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45084849107) passaram no SHA documental `00d6ef51`. Estes resultados validam a correcção do âmbito dos ACLs, mas antecedem a alteração de autorização pré-lock de 2026-11-23.
- [x] API CI/PostgreSQL 16 e Docker Compose passaram no descendente de código `926abcf1`; Quality Gates e Security Scans passaram no descendente documental `7b10c5c1`. Ver evidência e runs na secção acima.
- [ ] Ensaiar com volume PostgreSQL persistente preexistente, incluindo role legado, memberships, ownership e grants; não executar contra produção.
- [ ] Executar operações API reais com o principal runtime após bootstrap e confirmar leitura/escrita nos módulos operacionais sem permissões adicionais.

**Limite:** os novos controlos alargam a verificação automatizada, mas não provam ainda o comportamento em volume persistente real nem fecham a auditoria multi-loja global.

---

## Computer Vision — avaliador COCO v1 (implementado; CI validada em 2026-11-22)

- [x] Implementar AP101 por classe, mAP50, mAP50_95 e precision/recall/F1 no ponto operacional.
- [x] Validar IDs, categorias, scores, caixas, dimensões, limites numéricos e rejeitar crowd annotations não suportadas.
- [x] Criar runner de inferência que exige release de dataset explicitamente aprovado para inferência, modelo ONNX assinado e integridade SHA-256 das imagens.
- [x] Incluir hashes das anotações train/val/test na evidência de aprovação e no fingerprint do release; rejeitar alteração de ficheiros durante o gate.
- [x] Executar apenas no test split, sem treino nem escrita em inventário; incluir fingerprint do dataset e digest/model version no relatório.
- [x] Adicionar testes sintéticos de métricas, falsos positivos, falsos negativos, thresholds e aprovação de release.
- [x] API CI [45065013302](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065013302) e Docker Compose [45065013291](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065013291) passaram no commit de código `91ea51e0`; API CI confirmou PostgreSQL 16, smoke anti-rollback e 1545 passed, 1 skipped. Quality Gates [45065079666](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065079666) e Security Scans [45065079730](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065079730) passaram no descendente documental `1566b8ea`, sem alterações de código.
- [ ] Executar com dataset autorizado e pesos reais; não publicar métricas até obter relatório verificável e revisão independente.

## Edge AI — contrato de eventos v1 (implementado como contrato puro; CI validada em 2026-11-22)

- [x] Definir envelope versionado com identidade do dispositivo, tenant, sequência monotónica, timestamp com fuso, event ID e payload JSON limitado.
- [x] Validar HEARTBEAT, SHELF_CAPTURED, SHELF_OBSERVATION e TASK_ACKNOWLEDGED com esquemas específicos e limites de dados.
- [x] Definir fingerprint canónico, chave de idempotência por dispositivo e classificação NEXT/GAP/STALE.
- [x] Garantir que observações visuais não transportam quantidades de stock nem executam mutações.
- [x] Documentar outbox offline, inbox transaccional, retries, isolamento por loja e requisitos de autenticação.
- [x] Validar suite e integração CI no commit `91ea51e0`; 1545 testes aprovados, 1 ignorado. A ingestão persistente continua deliberadamente pendente.
- [x] Implementar registo controlado de dispositivos por loja e tipo, emissão/rotação/revogação de credenciais com segredo armazenado apenas como SHA-256 e auditoria append-only.
- [x] Implementar autenticação de pedidos Edge assinados, timestamp/nonce anti-replay, validação de scope e vinculação de tenant derivada exclusivamente da credencial.
- [x] Implementar `POST /api/v1/edge/events`, envelope validado, inbox persistente imutável, fingerprint idempotente, cursor monotónico e criação transaccional da linha de processamento.
- [x] Implementar worker com claim/lease/heartbeat/fencing, retries limitados, dead-letter e ACK de processamento; `DEVICE_HEARTBEAT` é o único handler built-in activo.
- [x] Implementar o handler `TASK_ACKNOWLEDGED` através da registry transaccional explícita, validando associação, loja, dispositivo e `task_version`; a activação continua opt-in/desactivada por omissão e `COMPLETED` permanece `REVIEW_REQUIRED`.
- [ ] Implementar handlers de domínio para `SHELF_CAPTURED` e `SHELF_OBSERVATION` apenas depois de contratos de payload, revisão humana, proveniência e efeitos transaccionais estarem definidos; até lá, manter dead-letter fail-closed.
- [x] Definir `docs/architecture/edge-task-acknowledgement-contract.md`: associação explícita dispositivo-tarefa, task_version, idempotência, fencing, revisão humana e proibição de conclusão/inventário automáticos.
- [ ] Implementar outbox persistente no dispositivo Edge e protocolo de sincronização/ACK de entrega; o ACK HTTP actual confirma apenas aceitação durável na inbox, não processamento de domínio.
- [ ] Validar a implementação Edge no HEAD actual com testes focados, suite API, PostgreSQL 16, Quality Gates, Security Scans e Docker Compose.

## Computer Vision — manifesto ONNX Ed25519 v2 e anti-rollback (implementação publicada; CI validada em 2026-11-22)

- [x] Verificar assinatura Ed25519 do manifesto com keyring explícito de chaves públicas confiáveis.
- [x] Vincular os hashes SHA-256 assinados aos bytes exactos do detector e do embedder; rejeitar modelos alterados, symlinks, JSON ambíguo, campos desconhecidos, assinaturas inválidas e key IDs não confiáveis.
- [x] Exigir manifesto e keyring no factory do provider real; preservar a segunda confirmação SHA-256 por variável de ambiente.
- [x] Passar configuração de manifesto/keyring para API e vision-worker no Docker Compose.
- [x] Adicionar utilitário de assinatura offline; a chave privada fica fora do repositório e do runtime.
- [x] Adicionar testes de assinatura, key trust, integridade dos ficheiros, configuração e utilitário.
- [x] Quality Gates no HEAD `e9145ac7cb89409e80259f52967f7fccda3de478` passou: API compile + suite pytest e build Web; Security Scans no mesmo SHA passou. Runs: [Quality Gates 44918245867](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44918245867) e [Security Scans 44918245858](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44918245858). API CI e Docker Compose smoke têm sucesso em SHA anterior, não foram confirmados neste HEAD.
- [x] Implementar manifesto schema v2 com `model_id` e `release_version` assinados; schema v1 é rejeitado pelo provider real.
- [x] Implementar high-water mark persistente por `VISION_MODEL_DEPLOYMENT_ID`, upgrade transaccional, retry idempotente, rejeição de rollback/colisão e identidade de modelo imutável.
- [x] Acrescentar eventos append-only e guards PostgreSQL/SQLite; impedir downgrade da migration quando já existem releases aceites.
- [x] Implementar key revocation explícita através de `VISION_MODEL_REVOKED_KEY_IDS_JSON`, mantendo o keyring de chaves públicas como allow-list.
- [x] Verificar o release antes/depois da inferência e manter lock da versão durante a publicação das deteções; workers obsoletos reencaminham a captura para PENDING e terminam.
- [x] API CI [45065013302](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065013302) e Docker Compose [45065013291](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065013291) passaram no commit de código `91ea51e0`; Quality Gates [45065079666](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065079666) e Security Scans [45065079730](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065079730) passaram no descendente documental `1566b8ea`; 1545 testes aprovados, 1 ignorado.
- [x] Exigir `VISION_MODEL_DEPLOYMENT_ID` explícito e não-default em `APP_ENV=production`; Compose deixa de injectar um fallback silencioso.
- [x] Separar no Docker Compose o serviço one-shot `migrate` (principal owner) dos processos API/worker (principal runtime dedicado). A API deixou de executar Alembic no arranque.
- [x] Provisionar `APP_DB_USER`/`APP_DB_PASSWORD` como principal NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/NOBYPASSRLS; revogar CREATE no schema e configurar default privileges para objectos operacionais futuros.
- [x] Restringir `vision_model_release_states` e `vision_model_release_events` a SELECT para o principal runtime; revogar INSERT/UPDATE/DELETE/TRUNCATE e privilégios da sequência de auditoria na migration 0070 e no bootstrap idempotente (inclui volumes existentes).
- [x] Remover o registo automático de releases do arranque do provider. Criar `apps/api/scripts/register_vision_model_release.py` e o perfil one-shot `register-model-release`, que valida manifesto Ed25519, digests e exige o owner real das tabelas.
- [x] Substituir `SELECT FOR UPDATE` por advisory transaction lock por deployment nas verificações/registos; runtime mantém serialização sem privilégios de escrita.
- [x] Alargar `postgres_runtime_role_smoke.py` para verificar SELECT, ausência de DML/sequence privileges e recusa efectiva de INSERT/UPDATE/DELETE/TRUNCATE; validar também o guard com o principal runtime.
- [x] Acrescentar testes estáticos para separação de credenciais, migração 0070, bootstrap, perfil privilegiado e ausência de auto-registo no provider.
- [ ] Para cada nova tabela de confiança/manifesto, actualizar a lista de revogações do bootstrap e a migration correspondente; manter runtime SELECT-only e smoke de regressão.
- [x] Validar a camada read-only ONNX no SHA `5e16a9cb`: API CI, Quality Gates, Security Scans e Docker Compose passaram; suite API 1552 passed, 1 skipped.
- [x] Tornar a migration 0070 fail-closed em produção: exige `APP_DB_USER`, rejeita identidade igual ao owner, role inexistente e ownership runtime das tabelas de confiança; testes estáticos em `test_database_role_separation.py`.
- [x] Validar o serviço `provision-runtime-role` e a política `NOINHERIT` no HEAD `aeff4a3b`: API CI [45076219787](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219787), Quality Gates [45076219801](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219801), Security Scans [45076219740](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219740) e Docker Compose [45076219751](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219751) passaram; suite API 1552 passed, 1 skipped.
- [x] Integrar o serviço one-shot `provision-runtime-role` antes de Alembic: cria/reconcilia o principal em cada arranque Compose, também em volumes existentes, com `NOINHERIT`; API/worker não iniciam se o provisionamento falhar.
- [ ] Validar o novo serviço em volume persistente já existente com papel legado/memberships/ownership; confirmar que os privilégios são reconciliados sem interromper tarefas ou dados existentes.
- [ ] Executar os fluxos operacionais completos com o principal runtime (não apenas como owner no pytest) e validar as permissões necessárias em cada tabela/sequence.
- [ ] Definir `APP_DB_PASSWORD` forte/único e credenciais owner fora do repositório antes de produção; não activar modelo real sem pesos, dataset e métricas aprovados.

## Deploy — passagem dos digests e política de confiança ONNX para API e worker (2026-11-22, CI validada)

- [x] Passar `VISION_DETECTOR_MODEL_SHA256` e `VISION_EMBEDDING_MODEL_SHA256` para os serviços `api` e `vision-worker` no Docker Compose.
- [x] Testar o contrato de configuração dos dois serviços, dos dois digests e das variáveis de manifesto/keyring; `docker compose config` e smoke de arranque passaram no Docker Compose CI [45065013291](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065013291).
- [x] Manter os digests vazios por omissão: Compose não inventa hashes nem enfraquece o modo fail-closed.
- [x] Manifesto Ed25519 v2, trust roots, rotação/revogação configurável e anti-rollback persistente implementados; ver `docs/vision-model-manifest.md`, `apps/api/app/vision_model_manifest.py`, `apps/api/app/vision_model_release.py` e migration `0069_vision_model_release_trust_state`.
- [x] Confirmar migration PostgreSQL 16, smoke anti-rollback concorrente, suite API e Docker Compose no commit de código `91ea51e0`; Quality Gates e Security Scans passaram no descendente documental `1566b8ea`; 1545 testes aprovados, 1 ignorado.

## IA e catálogo — validação estrita de exemplares de embeddings (2026-11-21, validado)

- [x] Exigir product_id inteiro positivo (rejeitar booleanos, floats, strings e valores não positivos) em ProductExemplar.
- [x] Validar model_version, SHA-256 hexadecimal e os campos de proveniência reviewed_by, reviewed_at e licence como strings não vazias.
- [x] Acrescentar testes paramétricos para identificadores e metadados malformados.
- [x] Validar no commit a1e056c3: API CI [44902878547](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878547), Quality Gates [44902878553](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878553), Docker Compose [44902878594](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878594) e Security Scans [44902878703](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878703) passaram; **1461 testes aprovados, 1 ignorado**.
- [ ] Continuar avaliação com dataset independente por loja/sessão e validar thresholds de matching; estes testes verificam integridade dos exemplares, não precisão do reconhecimento.

## Gitleaks — cobertura do histórico completo (2026-11-21, validado)

- [x] Confirmar a limitação da ação oficial no evento push: o scan integrado analisava apenas 1 commit. Acrescentar execução explícita de Gitleaks com --log-opts=--all após checkout de histórico completo.
- [x] Inspecionar as 7 ocorrências históricas generic-api-key: exemplos de bootstrap em documentação, valores HMAC usados exclusivamente em testes e um hash de commit. Não foram identificadas credenciais activas.
- [x] Substituir no HEAD as credenciais de exemplo e chaves de teste com aparência de segredo; adicionar .gitleaksignore com as 7 fingerprints exactas. Não foram criadas exclusões por pasta, regra ou padrão genérico.
- [x] Gitleaks: 2741 commits analisados, zero leaks não autorizados. Security Scans [44895863007](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44895863007) passou; pip-audit sem vulnerabilidades conhecidas, npm audit 0 vulnerabilidades e ZAP safe-mode sem findings.

## Integridade do provider ONNX — pinning de pesos e pré-processamento (2026-11-21)

- [x] Exigir VISION_DETECTOR_MODEL_SHA256 no factory do provider real e validar formato SHA-256.
- [x] Exigir VISION_EMBEDDING_MODEL_SHA256 quando VISION_EMBEDDING_MODEL_PATH está configurado.
- [x] Comparar os digests aprovados com os ficheiros antes de abrir sessões ONNX; manter a revalidação do digest depois do carregamento para detectar substituição concorrente.
- [x] Separar a identidade de pré-processamento do detetor (letterbox) e do extrator (crop stretch), incluindo-a nos fingerprints efectivos.
- [x] Adicionar regressões para digest ausente, malformado, divergente, válido e identidade de pré-processamento. API CI e Quality Gates: 1432 passed, 1 skipped; Docker Compose e Security Scans passaram no commit [663bf49](https://github.com/smpsandro1239/SMART-SHELF-AI-/commit/663bf495f6d15a4bcc92aa6fedc87d18e47e4e71).
- [x] Implementar manifesto Ed25519 assinado e verificação com keyring explícito; os digests de deployment mantêm-se como segunda confirmação. Ver `docs/vision-model-manifest.md` e `apps/api/app/vision_model_manifest.py`.
- [ ] Validar pesos reais autorizados, dataset anotado e métricas por SKU/cenário antes de activar inferência em piloto.

## Política de autorização da API — centralização

- [x] Extrair a decisão RBAC do middleware para `apps/api/app/api_security_policy.py`, mantendo autenticação Bearer e papel autoritativo lido da base de dados.
- [x] Implementar as categorias PUBLIC, ADMIN_ONLY, SUPERVISOR_OR_ADMIN e EMPLOYEE_ALLOWLIST com uma política explícita por método e template; `UNCLASSIFIED` é negado a todos os perfis, incluindo ADMIN.
- [x] Acrescentar testes unitários iniciais para a matriz de papéis e categorias.
- [x] Validar a refactor no commit `311fecc9e13641e6d5eb55465fda646fb2909601`: API CI [44880841684](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44880841684), Quality Gates [44880841658](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44880841658) e Docker Compose [44880841671](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44880841671) passaram; 1407 passed, 1 skipped, 1 warning.
- [x] Declarar as 128 combinações método/rota em `API_ROUTE_POLICIES`; o teste `test_every_registered_versioned_api_route_has_an_explicit_method_policy` percorre as rotas FastAPI registadas e falha se existir uma combinação sem política.
- [x] Criar `apps/api/scripts/audit_api_route_policy.py`, auditor read-only que enumera método/rota, categorias, rotas `UNCLASSIFIED` e fallbacks legados; `--strict` falha perante qualquer rota sem política explícita.
- [x] Integrar `python scripts/audit_api_route_policy.py --strict` no workflow `.github/workflows/api-ci.yml`; API CI [44881182965](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44881182965), commit `8775aaffc8db199dd6c43a61dafd03c019f519fc`, executou o gate `audit_api_route_policy.py --strict`: **128 métodos, 0 UNCLASSIFIED, 0 fallbacks legados**; migrações PostgreSQL 16, smokes e suite **1407 passed, 1 skipped, 1 warning**.
- [x] Corrigir correspondência de prefixos para respeitar limites de segmentos (`/users` não deve corresponder a `/users-export`); acrescentar regressões para caminhos semelhantes e rotas aninhadas reais.
- [x] Corrigir a deteção de sub-recursos `shelves/*/planograms` para exigir o segmento `planograms` completo; acrescentar regressão para `/planograms-export` não herdar permissões de supervisor.
- [x] Acrescentar teste positivo para a rota real `POST /api/v1/shelves/{shelf_id}/planograms`, confirmando acesso de ADMIN/SUPERVISOR e recusa de EMPLOYEE.
- [x] Confirmar testes de fronteira, cobertura de todas as rotas e suite integral no commit `311fecc9`; API CI, Quality Gates e Docker Compose passaram (1407 passed, 1 skipped, 1 warning).

## Segurança P0 — CORS preflight e Bearer

- [x] Permitir apenas preflight OPTIONS com Origin + Access-Control-Request-Method passar pelo middleware de autenticação, deixando CORSMiddleware validar origin/method/headers.
- [x] Desactivar `allow_credentials`: autenticação é Bearer e não há sessão por cookie no frontend/API.
- [x] Confirmar preflight Authorization recebe 200, ACAO válido e sem Access-Control-Allow-Credentials; requests reais continuam a exigir Bearer.
- [x] Validar RED/GREEN e API CI [44785894943](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44785894943), Quality Gates [44785894965](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44785894965) e Docker Compose [44785894960](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44785894960): 1388 passed, 1 skipped, 1 warning.

## OWASP API security review — primeira ronda

- [x] Rever middleware JWT, identidade/role na base de dados, RBAC, store scope, planogramas e testes de isolamento; o inventário actualizado contém 128 métodos API (mais duas rotas health fora de `/api/v1/`).
- [x] Corrigir finding API-CORS-001: origem wildcard/HTTP/localhost não permitida em produção.
- [x] Centralizar RBAC em `apps/api/app/api_security_policy.py` com 128 políticas explícitas por método/template e teste dinâmico das rotas registadas. A cobertura exaustiva endpoint × papel × tenant continua aberta.
- [x] Revalidar o actor no handler em dez endpoints de gestão/catálogo que dependiam apenas do middleware; o teste de despromoção ADMIN → SUPERVISOR entre middleware e handler confirma 403 e ausência de escrita.
- [ ] Completar matriz endpoint × ADMIN/SUPERVISOR/EMPLOYEE × loja, incluindo todos os handlers e caminhos indirectos. Em 2026-11-21, 22 handlers com locks foram cobertos por helpers de autorização pré-lock e teste estático; a auditoria BOLA/IDOR por recurso continua aberta.
  - [x] Cobrir a listagem de sessões de captura contra fuga multi-loja e filtros por `shelf_id` estrangeiro; teste `test_capture_session_listing_is_store_scoped_even_with_foreign_shelf_filter`.
  - [x] Cobrir por HTTP a leitura do histórico de eventos de alertas entre lojas; `test_cross_store_alert_event_history_is_denied` confirma HTTP 403 para supervisor de outra loja. Validado no commit `1a53a9f1`: API CI [44893270814](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893270814) e Quality Gates [44893270837](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893270837) passaram (**1423 passed, 1 skipped**); Docker Compose [44893271027](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893271027) e Security Scans [44893270848](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893270848) também passaram.
- [x] Executar SCA, secret scan e baseline DAST passivo: pip-audit, npm audit, Gitleaks e ZAP com evidência no workflow 44884714393; DAST autenticado/activo continua fora deste baseline.

## Segurança P0 — CORS de produção

- [x] Exigir origens CORS explícitas HTTPS em produção; rejeitar wildcard, localhost/loopback, paths, query, fragmentos e origens vazias.
- [x] Corrigir a validação de host DNS para não tratar nomes DNS como endereços IP; testes incluem origens HTTPS DNS e porta explícita.
- [x] Confirmar RED/GREEN e workflows API CI, Quality Gates e Docker Compose no commit `1b1e4ea`: 1387 passed, 1 skipped, 1 warning.

## OWASP Secure Agent Playbook — integração de segurança (2026-11-20)

- [x] Fixar OWASP Secure Agent Playbook como submódulo Git `vendor/owasp-secure-agent-playbook` no commit `65d4efd2cd0b081d52101e9708792b944e4ddebb`, licença CC-BY-4.0 e atribuição preservada.
- [x] Expor procedimentos de API security review, code security review, SCA e secrets scan através de uma skill de entrada.
- [x] Executar primeira ronda OWASP à autorização multi-loja: 130 rotas enumeradas, middleware JWT, RBAC, store scope e planogramas revistos; relatório `docs/security/api-authorization-review-2026-11-20.md`. Auditoria exaustiva continua aberta.
- [x] Executar SCA real com pip-audit e npm audit; resultados e remediação registados em docs/security/dependency-audit-2026-11-21.md.

## Inventário de outputs finais sem publicação auditável — 2026-11-20

- [x] Inventariar ficheiros finais canónicos em `published/<job>/<token>-<sha256>.artifact` sem linha append-only de publicação; inclui digest declarado, tamanho, estado e timestamp.
- [x] Garantir categoria report-only mesmo com `--apply`, sem seguir symlinks nem apagar ficheiros recuperáveis.
- [x] Validar RED/GREEN e CI no commit `cef5618`: API CI, Quality Gates, PostgreSQL smoke e Docker Compose passaram; 1380 passed, 1 skipped, 1 warning.

## Superpowers e Frontend Design — integração de metodologia (2026-11-20)

- [x] Fixar Superpowers como submódulo Git `vendor/superpowers` no commit `22f0b463e7a5e579904dd6211a520321035526f7` (MIT).
- [x] Expor skills de arranque, TDD, debugging e verificação em `.agents/skills/`, mantendo o conteúdo upstream completo e versionado.
- [x] Fixar Frontend Design como submódulo Git `vendor/frontend-design` no commit `f8966e6cc9b90247aa102d71f7e675ec3462b419` (MIT).
- [x] Expor Frontend Design como skill complementar; Impeccable mantém-se a ferramenta principal para auditoria/polish do sistema visual actual.
- [x] Criar `AGENTS.md` e `docs/engineering/agent-skill-stack.md` com ordem de aplicação, limites e inicialização.
- [ ] Validar inicialização recursiva dos quatro submódulos num clone local e descoberta das skills no runtime Codex disponível.
- [x] Aplicar TDD em duas correções P0 (outputs órfãos e CORS) com RED observado, implementação e GREEN no CI.

## Impeccable — integração e baseline de qualidade visual (2026-11-20)

- [x] Fixar a upstream skill Impeccable como submódulo Git `vendor/impeccable`, apontado ao commit `b49177d32788f2dc585c42831d845dacf1ebed2c`; manter a licença Apache-2.0 e o código upstream intactos.
- [x] Expor a skill aos agentes em `.agents/skills/impeccable/SKILL.md`, com instruções específicas do SMART SHELF AI e ligação para o playbook oficial.
- [x] Criar `PRODUCT.md` e `DESIGN.md` a partir dos fluxos, papéis, limitações e tokens efectivamente encontrados no repositório.
- [x] Integrar o detector Impeccable v4.10.0 no Quality Gates, guardando um relatório baseline sem bloquear por findings preexistentes; falhas de execução continuam bloqueantes.
- [x] Obter e corrigir finding side-tab em decision-freshness-notice e decision-warnings; segundo relatório Impeccable vazio (`[]`) no commit `d49434e`.
- [ ] Executar `context`, `critique` e `audit` com checkout local e browser; verificar dashboard e fluxos de captura/revisão em desktop e mobile.
- [ ] Rever acessibilidade por teclado, contraste, estados loading/empty/error/disabled e semântica dos formulários; o build TypeScript não substitui esta validação visual.
- [ ] Só depois fazer polimento incremental, sem alterar contratos API, permissões ou regras de inventário.

## Idempotência da observação perante revisão SKU posterior — 2026-11-19

- [x] Identificar que a chave de idempotência por deteção devolvia uma observação anterior mesmo quando uma revisão SKU posterior alterava o produto pedido.
- [x] Tornar o replay estrito: a observação existente só é devolvida quando produto e estado coincidem; alterações de identidade devolvem HTTP 409 sem modificar o registo original.
- [x] Acrescentar regressão HTTP que cria a observação para SKU A, regista revisão posterior para SKU B e confirma que o segundo pedido é rejeitado e a observação A permanece intacta.
- [x] Validar API CI/PostgreSQL, Quality Gates e Docker Compose no commit desta correção: API CI [44648427709](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44648427709), Quality Gates [44648427667](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44648427667) e Docker Compose [44648427581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44648427581) concluíram com sucesso no commit `c854e948b5664870942b9302dee4913e0349755b`. API CI executou as migrations e os smokes PostgreSQL 16, todos aprovados, e a suite API; Quality Gates confirmou **1343 passed, 1 skipped, 1 warning**, compilação Python e build TypeScript/produção Web; Docker Compose confirmou build, arranque, readiness, seed, worker e perfis demo. O aviso é a depreciação externa `anyio.abc.BlockingPortal` no Starlette TestClient. Validação CI, não teste manual com câmaras/datasets reais.

## Confirmação humana explícita do estado das observações demo — 2026-11-19

- [x] Separar a revisão humana do SKU da confirmação humana do estado da prateleira no endpoint de observação demo.
- [x] Exigir `confirmed_status` no contrato HTTP; rejeitar ausência (422) e divergência face à classe da deteção (409).
- [x] Registar estado, utilizador confirmador e timestamp UTC na proveniência da observação; preservar a idempotência por deteção.
- [x] Acrescentar regressões HTTP para falta de confirmação, estado incompatível, revisão SKU obrigatória e repetição idempotente.
- [x] Atualizar o smoke PostgreSQL de retenção para enviar `confirmed_status=EMPTY` e continuar a testar o lock da imagem antes da validação do estado de retenção.
- [x] Validar API CI/Quality Gates e confirmar o resultado do commit 2aec1463af6ee24998eab1ac6be862dfdb21a5b8: API CI [44596254264](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44596254264) (1343 passed, 1 skipped, 1 warning), Quality Gates [44596254489](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44596254489) e Docker Compose [44596254260](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44596254260) passaram.

## Evidência de comparação de planogramas — contrato antes da persistência (2026-11-19)

- [x] Confirmar API CI, Quality Gates e Docker Compose do commit db7f8b423d14b0011609ff154874014cd122dfac: os três workflows passaram.
- [x] Documentar identidade, snapshot canónico, idempotência, revisão append-only, retenção/derivados, concorrência e critérios de aceitação.
- [x] Identificar lacunas do modelo actual: manifesto imutável de inferência e precedência entre deteção original/revisão SKU.
- [ ] Obter aprovação da política de retenção de derivados, sobrevivência após purga e legal hold antes de qualquer migration.
- [ ] Definir manifesto imutável do pipeline e semântica de revisão SKU antes de congelar snapshots.
- [ ] Especificar e testar idempotência/reprocessamento e constraints append-only em PostgreSQL/SQLite.
- [ ] Só depois implementar migration, serviço transacional e smoke PostgreSQL concorrente; manter worker desligado até validação integral.

## Governação de derivados, autorização e cópias — 2026-11-19

- [x] Confirmar API CI, Quality Gates e Docker Compose do commit anterior 9f6e871520a1d63b1f148bcc7578c546a41d090e: os três workflows passaram.
- [x] Definir matriz conservadora específica de outputs: ADMIN/SUPERVISOR/EMPLOYEE sem autorização implícita; workers sem scopes de governação; callback positivo obrigatório por publicação ancestral.
- [x] Documentar fluxo proposto de aprovação independente de libertação de legal hold, mantendo-o desactivado até decisão do responsável do produto/jurídico.
- [x] Implementar migration 0066_dataset_output_lineage, modelo e serviço para relações pai → derivado append-only, com rejeição de ciclos e actor activo.
- [x] Integrar a linhagem no consumo: locks de publicações por ID, estabilidade da cadeia, autorização e governação em todos os ancestrais e revalidação das fontes de todos os jobs.
- [x] Documentar contrato de propagação para caches, exports, réplicas, object storage e backups; não declarar integração externa.
- [x] Executar API CI/PostgreSQL 16, Quality Gates e Docker Compose no commit `4153625226c6b08b9e09d491986a1415e3fbc847`: [API CI 44730129439](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44730129439), [Quality Gates 44730129686](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44730129686) e [Docker Compose 44730129490](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44730129490) passaram; API CI executou migration PostgreSQL 16, smokes e **1374 passed, 1 skipped, 1 warning**. O smoke dedicado de linhagem foi executado na alteração seguinte.
- [x] Alargar `postgres_dataset_job_output_publication_smoke.py`: publicar um output derivado real, registar a aresta com callback explícito, provar consumo autorizado, rejeitar ciclo/UPDATE/DELETE no PostgreSQL e confirmar que restrição e legal hold do pai bloqueiam o descendente; libertar a restrição sem libertar o legal hold. API CI [44730129439](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44730129439) executou o smoke com PostgreSQL 16 e passou.
- [ ] Implementar workflow append-only de pedidos/aprovações após aprovação da política de funções, âmbito, evidência e excepções.
- [x] Tornar a publicação e a relação pai → derivado atómicas: `promote_dataset_job_output` bloqueia a cadeia ancestral antes dos locks de job/fontes, grava a aresta na mesma transacção da publicação e mantém retries idempotentes com metadados imutáveis. API CI [44731813064](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44731813064), Quality Gates [44731812997](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44731812997) e Docker Compose [44731812973](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44731812973) passaram: PostgreSQL 16, **1375 passed, 1 skipped, 1 warning**, compilação Python e build Web. O smoke PostgreSQL confirmou linhagem atómica, herança de restrição/legal hold e guards append-only; o teste negativo confirma que autorização recusada faz rollback, não publica o ficheiro e preserva o staging.
- [ ] Ligar cada transformação real ao registo de derivação; a função existe, mas não há worker de transformação integrado.
- [ ] Criar inventário de cópias externas e adapters com atestação; até lá, bloquear serve/restore de cópias não inventariadas e manter purga física desactivada.

## Consumo concorrente e governação de outputs (2026-11-19)

- [x] Confirmar API CI, Quality Gates e Docker Compose do commit anterior e5a372d00199d441b6089254133f04dfd7f99e10: os três workflows terminaram com sucesso. API CI executou migrações PostgreSQL 16, smokes operacionais e suite API; Quality Gates concluiu testes API/compilação Python e build Web; Docker Compose validou readiness, seed e worker.
- [x] Acrescentar ao smoke PostgreSQL duas sessões concorrentes para provar que RESTRICTION_APPLIED espera pelo consumidor que mantém o lock da publicação, e que a restrição só fica efectiva depois do commit da leitura.
- [ ] Confirmar os três workflows da alteração concorrente antes de marcar a cobertura como validada.
- [ ] Não implementar libertação independente de legal hold nem matriz HTTP por perfil/loja sem decisão de política aprovada; documentar as decisões necessárias.

## Isolamento filesystem API/vision-worker — 2026-11-20
- [x] Executar `vision-worker` com UID/GID dedicado não privilegiado `65532:65532`, root filesystem read-only, `cap_drop: ALL`, `no-new-privileges` e `/tmp` temporário isolado; manter os mounts de imagens e modelos read-only.
- [x] Alargar o smoke Docker Compose para verificar UID efectivo, permissões de escrita, root filesystem, capabilities e `no-new-privileges`.

- [x] Montar o volume persistente de imagens em modo só de leitura no serviço `vision-worker`; a API mantém a escrita e a ingestão.
- [x] Acrescentar verificação no smoke Docker Compose que inspecciona o mount real do container e exige `RW=false`.
- [ ] Separar identidades UID/GID e permissões de directórios; confirmar compatibilidade com volumes existentes e operações de retenção/purga antes de alterar ownership.
- [x] Separar staging/publicações de outputs de datasets num volume Docker persistente `dataset_outputs`, montado apenas na API; o `vision-worker` não recebe esse volume. O smoke verifica os mounts reais e a escrita pela API.
- [x] Reforçar o smoke para comparar os nomes dos volumes Docker: o volume de imagens partilhado API/vision-worker tem de ser diferente do volume de outputs de datasets.
- [ ] Definir handoff controlado e mounts mínimos quando existir um worker de transformação de datasets; esse worker ainda não está integrado no Compose.
- [ ] Provar quiescência física de workers antigos antes de qualquer limpeza de staging órfão; fencing SQL isolado não é suficiente.

## Reconciliação conservadora de outputs (2026-11-19)

- [x] Criar `app.dataset_job_output_reconciliation` com modo read-only por defeito e `--apply` explícito.
- [x] Remover apenas temporários `.promotion-*.tmp` regulares e antigos, respeitando o período de segurança configurado.
- [x] Remover staging apenas quando existe publicação append-only correspondente e destino/staging confirmam o mesmo digest e tamanho.
- [x] Preservar jobs `SUCCEEDED` sem publicação, symlinks, ficheiros recentes, jobs desconhecidos e conteúdos divergentes.
- [x] Acrescentar testes para dry-run, aplicação, preservação de staging sem publicação e mismatch de digest.
- [x] Inventariar staging antigo sem publicação por job/token e classificar jobs desconhecidos, concluídos, falhados/revogados/cancelados e tokens obsoletos; manter esta classe report-only mesmo com `--apply`, pois fencing SQL não prova quiescência do processo.
- [x] Acrescentar regressão que confirma que staging de job terminal e de job desconhecido é reportado mas nunca removido.
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
- [x] Implementar eventos append-only de governação/retenção ligados à publicação, sem alterar a linha imutável da publicação; migration 0065, serviço interno, guards SQLite/PostgreSQL e validação CI concluídos.
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
- [x] Prosseguir com eventos append-only de governação ligados à publicação, sem alterar a linha canónica; implementação na migration 0065 e validação CI registada na secção seguinte.
- [ ] Não activar disposição física até existir política aprovada de retenção, cobertura de cópias externas e aprovação independente.


## Governação append-only de outputs publicados — migration 0065 (2026-11-19)

- [x] Criar eventos de restrição/restauro e legal hold/libertação ligados à publicação canónica, sem alterar ou duplicar a identidade do output.
- [x] Registar actor humano activo, motivo obrigatório, timestamp, evidência opcional com referência + SHA-256 e detalhes JSON limitados.
- [x] Impor sequência consecutiva por publicação, transições válidas e bloqueio concorrente da publicação em PostgreSQL; criar guards equivalentes em SQLite.
- [x] Proteger eventos contra UPDATE/DELETE e impedir remoção da publicação/actor referenciados através de FK RESTRICT.
- [x] Implementar serviço interno com callback de autorização obrigatório e projecção de estado derivada da cronologia.
- [x] Acrescentar testes SQLite para sequência, transições, actor inactivo, imutabilidade e downgrade, mais testes de serviço para autorização, evidência e estado.
- [x] Integrar smoke PostgreSQL 16 para concorrência de dois pedidos, sequência, legal hold e imutabilidade dos eventos.
- [x] Validar migration 0065 em PostgreSQL 16, smokes de governação/concorrência e suite API no commit `b2247031a7d651a4efdc423f83bf7947723e27ff`: API CI [44519805058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44519805058) e Quality Gates [44519805055](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44519805055) passaram com **1244 passed, 1 skipped, 1 warning**; Docker Compose [44519805067](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44519805067) passou.
- [ ] Aprovar matriz de permissões por perfil/loja, separação de funções e eventual aprovação independente para libertação de legal hold.
- [ ] Integrar a projecção de governação em cada leitura/exportação efectiva de outputs antes de criar endpoints ou workers remotos.
- [ ] Definir política de retenção, inventário externo e procedimento de recuperação; manter disposição física e purga desactivadas.


## Leitura fail-closed de outputs publicados — 2026-11-19

- [x] Criar fronteira interna de consumo integral de bytes para publicações canónicas.
- [x] Bloquear leituras quando a projecção append-only indica restrição ou legal hold activo.
- [x] Revalidar todas as fontes imutáveis (loja, SHA-256, estado ACTIVE e ausência de legal hold) sob locks ordenados.
- [x] Exigir callback de autorização explícito e verificar referência canónica, ficheiro regular sem symlink, tamanho e SHA-256.
- [x] Acrescentar regressões para leitura autorizada, ausência de autorização, restrição, legal hold, herança das fontes, adulteração dos bytes e rejeição de symlinks.
- [x] Estender o smoke PostgreSQL 16 para validar leitura autorizada real e bloqueio da leitura após aplicação concorrente de restrição.
- [ ] Integrar todos os consumidores reais futuros (API, exports, workers, caches e backups) exclusivamente através desta fronteira; nenhum endpoint/worker foi activado.
- [ ] Definir política de autorização por perfil/loja e aprovação independente para libertar legal hold.
- [ ] Definir inventário externo, propagação a derivados/cópias e política de retenção; manter purga física desactivada.

## SMART-SHELF-AI — requisitos de visão computacional e inteligência de prateleira (2026-11-19)

Objectivo: evoluir o projecto para uma plataforma de inteligência operacional de retalho que observe a disponibilidade real na prateleira, identifique desvios, recomende reposição e confirme a execução. Esta secção regista requisitos; nenhum item abaixo é considerado implementado apenas por estar planeado. Preservar os contratos existentes, isolamento multi-loja, validação humana, auditoria, retenção e governação fail-closed.

### P0 — contratos, fiabilidade e evidência
- [ ] Reconciliar README, ROADMAP, TODO e PROGRESS com o estado real dos módulos de visão; distinguir explicitamente implementado, experimental, mock, integrado mas não validado e operacional.
- [x] Confirmar o estado actual de CI no HEAD desta ronda (API CI/PostgreSQL 16, Quality Gates, Web CI e Docker Compose); registar SHA, runs e resultados sem reutilizar evidência de commits anteriores. (HEAD `69b9bba60a070933589d162ad9279ab4487c0a3b`; API CI, Quality Gates e Docker Compose aprovados.)
- [ ] Auditar o contrato de saída do provider ONNX: classes, scores, bounding boxes, dimensões, coordenadas normalizadas/absolutas, formato de tensor, pré-processamento e pós-processamento.
  - [x] Rejeitar também outputs pós-NMS com batch estático diferente de 1, uma vez que o decoder só suporta `[N, 6]` e `[1, N, 6]`; teste de regressão acrescentado. O batch dinâmico permanece aceite.
- [x] Validar os limites numéricos do construtor ONNX independentemente das variáveis de ambiente: tamanho de entrada inteiro 32–4096, threshold finito 0–1 e máximo de deteções inteiro 1–2000; rejeitar booleanos e valores fracionários antes de abrir os modelos. Testes paramétricos; API CI e Quality Gates aprovados no commit `1bd2e361` (1358 passed, 1 skipped, 1 warning).
- [x] Corrigir o mapeamento de class_id para etiquetas/classes versionadas; rejeitar classes desconhecidas ou índices fora do catálogo em vez de atribuir genericamente "product". (Configuração obrigatória `VISION_CLASS_LABELS_JSON`; classes inválidas/desconhecidas rejeitadas.)
- [x] Validar o contrato do modelo ONNX antes da primeira inferência: inputs/outputs, shapes, dtype, labels, threshold e identidade de pré-processamento; exigir SHA-256 aprovado para detetor e embedder no factory real e verificar os ficheiros antes/depois do carregamento. API CI/Quality Gates: 1432 passed, 1 skipped no commit 663bf49.
- [ ] Implementar manifesto assinado e verificação de assinatura com chave pública de confiança; os digests actuais são âncoras de confiança da configuração de deployment, não assinaturas digitais.
- [x] Definir configuração fail-closed para provider mock/demo versus provider real; impedir que resultados sintéticos sejam apresentados como deteções reais ou usados para alterar inventário. (`VISION_PROVIDER_MODE=disabled|mock|real`; modo mock limitado ao provider demo e bloqueado em produção.)
- [x] Acrescentar testes de contrato e regressão para modelos inválidos, outputs malformados, classes desconhecidas, confiança fora de intervalo, boxes inválidas, imagens inválidas e falhas/timeout do provider. (A matriz cobre caixas invertidas/degeneradas, padding letterbox e clipping parcial; o worker marca FAILED em RuntimeError/TimeoutError, preserva deteções anteriores e não altera inventário.)
- [ ] Garantir que cada deteção e observação preserva proveniência: imagem/captura, loja, zona, prateleira, dispositivo, timestamp UTC, provider, model version, preprocessing version e correlation/request ID.
- [ ] Definir estados explícitos para inferência indisponível, evidência insuficiente, baixa confiança e revisão humana; nunca converter falha de inferência em "prateleira vazia".
- [ ] Verificar idempotência de reprocessamento, deduplicação de eventos e fencing/lease do worker; testar retry, timeout, crash e recuperação sem duplicar deteções ou tarefas.

### P1 — dataset real e validação do modelo
- [ ] Definir protocolo de recolha de imagens autorizado, consentimento/base legal aplicável, minimização, retenção e remoção de elementos pessoais desnecessários; não implementar reconhecimento facial.
- [ ] Criar dataset representativo por loja, câmara, corredor, prateleira, SKU, embalagem, iluminação, ângulo, distância, oclusão e condições de captura.
- [ ] Definir esquema de anotação versionado para bounding boxes/classes, SKU, facings, regiões/células da prateleira, espaços vazios, produto deslocado, oclusão e qualidade da imagem.
- [ ] Criar processo de revisão/dupla anotação e adjudicação de rótulos ambíguos, com rastreabilidade do anotador e versão do dataset.
- [ ] Separar treino/validação/teste por loja, câmara ou período temporal para evitar data leakage entre imagens quase duplicadas.
- [ ] Implementar controlo de duplicados e near-duplicates, integridade SHA-256, manifestos imutáveis e linhagem entre dataset, split, treino, modelo e avaliação.
- [ ] Definir baseline reproduzível e critérios mínimos de aceitação por classe/SKU/cenário antes de promover um modelo.
- [ ] Medir precision, recall, F1, mAP por classe, matriz de confusão, falsos positivos/negativos, calibração de confiança, latência p50/p95 e consumo de memória/CPU/GPU.
- [ ] Avaliar robustez a reflexos, embalagens semelhantes, alterações de packaging, iluminação, blur, ângulos, oclusões, pessoas/carrinhos e prateleiras parcialmente visíveis.
- [ ] Criar relatório de avaliação versionado e mecanismo de aprovação/rollback de modelos; não promover automaticamente um modelo por ter terminado o treino.
- [ ] Preparar conjunto de teste de regressão visual (golden set) e executar avaliação comparativa antes de cada alteração de modelo ou pré/pós-processamento.

### P1 — identificação de produto, facings e espaços vazios
- [ ] Completar o pipeline real de deteção ONNX com mapeamento de classes e integração validada com o catálogo de produtos/SKU.
- [ ] Implementar matching de SKU com combinação controlada de detector, embeddings, OCR/código de barras e catálogo; registar scores e evidências concorrentes.
- [ ] Definir limiares por classe/cenário e política de abstenção: correspondências ambíguas ou desconhecidas devem ir para revisão, não ser forçadas para um SKU.
- [ ] Separar formalmente object detection, identificação SKU, contagem de facings visíveis e estimativa de unidades físicas; não inferir stock total a partir de faces visíveis.
- [ ] Implementar detecção/segmentação de regiões de prateleira e células de exposição, incluindo coordenadas normalizadas e transformação para a geometria da imagem.
- [ ] Implementar detecção de espaços vazios comparando células/posições esperadas com observações; distinguir vazio real, oclusão, área fora de imagem e falha de captura. (Comparador geométrico puro de células calibradas implementado; estados EMPTY/UNKNOWN/OCCUPIED/MISPLACED preservam evidência. Falta ligar a planogramas persistidos, visibilidade real e worker.)
- [ ] Implementar contagem de facings por SKU com associação espacial, supressão de duplicados e tratamento de produtos sobrepostos.
- [ ] Implementar deteção de produto deslocado/misplaced e produto desconhecido, com evidência visual e confiança.
- [ ] Introduzir estado de qualidade/visibilidade por região (occluded, blurred, glare, out_of_view, low_resolution) para impedir conclusões indevidas.
- [x] Implementar consenso temporal configurável e alertas persistentes/idempotentes com resolução humana e auditoria. Falta ligar observações reais do worker e calibrar thresholds com imagens reais autorizadas.
- [ ] Criar testes com imagens sintéticas controladas e imagens reais anotadas para vazio, low stock, facings, deslocamento, oclusão e falsos vazios.

### P1 — geometria de prateleiras e planogramas
- [x] Implementar comparador puro entre deteções e células calibradas, com IDs únicos, coordenadas normalizadas, SKU esperado opcional, proveniência das deteções e estado UNKNOWN por omissão quando a visibilidade não é confirmada.
- [ ] Definir modelo de domínio para corredor, módulo, prateleira, segmento, célula/posição, coordenadas, capacidade, orientação e associação a loja/zona.
- [x] Implementar API/serviços e migrations para planogramas versionados, com actor, motivo, ciclo de vida e histórico; migrations 0067/0068 e smoke PostgreSQL dedicados validados.
- [x] Persistir SKU esperado e número de facings esperado por célula, com validação e constraints. Capacidade máxima, prioridade e regras avançadas de exposição continuam pendentes.
- [ ] Implementar importação/exportação validada de planogramas (formato documentado), com preview, validação de SKU/localização e rejeição de referências ambíguas.
- [x] Implementar endpoint read-only de comparação entre planograma activo e observação visual, com estados por célula, SKU/facings esperados e observados, proveniência e fingerprint. Integração persistente no worker e validação real continuam pendentes.
- [ ] Tratar alterações de planograma com versão efectiva por data/hora; reprocessamentos históricos devem usar a versão aplicável no momento da captura.
- [ ] Criar interface para visualizar prateleira/células, esperado versus observado, evidência e revisão humana.
- [ ] Acrescentar testes de isolamento multi-loja, concorrência de versões, histórico, importação inválida e comparação geométrica.

### P1 — disponibilidade, inventário e decisão
- [ ] Definir estados de disponibilidade distintos e documentados: AVAILABLE, LOW_STOCK, POSSIBLE_STOCKOUT, OUT_OF_STOCK, MISPLACED, UNKNOWN e NEEDS_REVIEW.
- [ ] Implementar Shelf Availability Intelligence que combine evidência visual, consenso temporal, inventário, vendas e qualidade da observação, sem sobrepor nem duplicar o motor de decisões existente.
- [ ] Separar explicitamente stock de exposição, stock de retaguarda, stock reservado, em trânsito e stock contabilístico; documentar fonte de verdade e timestamp de cada quantidade.
- [ ] Definir regras para confirmar OUT_OF_STOCK: evidência visual persistente + reconciliação com fontes de inventário, com possibilidade de revisão humana e explicação da decisão.
- [ ] Impedir que uma deteção visual, previsão ou recomendação altere directamente stock contabilístico; movimentos continuam a exigir operação autorizada e auditável.
- [ ] Integrar alertas com tarefas existentes de reposição usando chave de deduplicação estável, prioridade, SKU, localização, quantidade sugerida, evidência e motivo.
- [ ] Implementar ciclo de tarefa verificável: recomendada, aprovada/atribuída, iniciada, concluída, verificada e reconciliada; distinguir conclusão declarada de confirmação visual/física.
- [ ] Definir política para tarefas obsoletas, alertas resolvidos, alterações de planograma e stock reposto entretanto; evitar tarefas duplicadas ou contraditórias.
- [ ] Acrescentar explicabilidade: factores, fontes, timestamps, confiança, regras accionadas e motivo de abstenção/revisão.

### P1 — previsão de procura e reposição
- [ ] Evoluir baseline de média ponderada para previsão por SKU/loja com granularidade horária e diária, mantendo baseline comparável.
- [ ] Avaliar sazonalidade, dia da semana, feriados, promoções, preço, tráfego e eventos comerciais quando existirem dados fiáveis e autorizados.
- [ ] Integrar vendas/POS e movimentos de inventário com contratos, timestamps, deduplicação, reconciliação e isolamento por loja.
- [ ] Calcular risco e horizonte temporal até rutura, explicitando incerteza e intervalo de previsão; não apresentar estimativas como certezas.
- [ ] Calcular quantidade sugerida considerando procura prevista, stock de exposição, retaguarda, reservas, unidades logísticas, capacidade e lead time.
- [ ] Definir métricas e backtesting temporal (WAPE, MAE/RMSE, bias e desempenho por SKU/loja); comparar com baseline e tratar séries esparsas/intermitentes.
- [ ] Criar monitorização de drift e degradação, regras de fallback para baseline e revisão de previsões com dados insuficientes.
- [ ] Garantir que previsão não cria encomendas nem movimentos físicos automaticamente sem política e aprovação explícitas.

### P1 — dashboard e experiência operacional
- [ ] Acrescentar indicadores OSA (On-Shelf Availability), taxa de rutura, duração da rutura, low-stock, conformidade de planograma e tempo de reposição.
- [ ] Mostrar métricas com denominadores, período, cobertura de câmaras e qualidade da evidência; não misturar UNKNOWN com AVAILABLE.
- [ ] Criar vista de prateleira com esperado/observado, células, facings, zonas vazias, SKU incerto e ligação à imagem/evidência autorizada.
- [ ] Criar filtros por loja, zona, corredor, prateleira, SKU, estado, severidade e intervalo temporal com paginação e limites de consulta.
- [ ] Mostrar tarefas e alertas com prioridade, idade humanizada, responsável, estado, evidência e acções permitidas por perfil.
- [ ] Garantir acessibilidade por teclado/leitor de ecrã, contraste WCAG 2.2 AA, estados não dependentes apenas da cor e layouts móveis.
- [ ] Implementar vistas comparativas multi-loja apenas para utilizadores autorizados e sem fuga de dados entre tenants.

### P1/P2 — captura, dispositivos e operação Edge
- [ ] Definir contrato comum Capture Device Gateway para câmaras IP/RTSP, upload móvel e robôs, com adaptadores isolados por fabricante.
- [ ] Definir a associação operacional Capture Device → zona/prateleira/sessão, distinta do registo de identidade Edge já existente.
- [x] Registo de dispositivos Edge por loja/tipo, credenciais individuais, rotação/revogação, autenticação HMAC, anti-replay, inbox persistente e worker com lease/fencing (migrations 0071–0073).
- [x] Criar schema persistente de associação dispositivo-tarefa (migration 0102), com validade temporal, revogação única, identidade humana do actor, ledger append-only e FKs compostas que impedem ligações entre lojas; não reutilizar `assigned_user_id`.
- [x] Validar migration 0102 em PostgreSQL 16 e teste de migration SQLite; API CI run [45876761643](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45876761643): 1747 passed, 1 skipped.
- [x] Introduzir `ReplenishmentTask.task_version` gerida pela base de dados, monotónica em cada UPDATE e protegida contra escrita directa; migration inclui triggers PostgreSQL e SQLite.
- [x] Implementar serviço/API de criação e revogação da associação, com autorização ADMIN/SUPERVISOR, lock order consistente e persistência atómica da associação + evento; CI PostgreSQL 16 validada no percurso Edge ACK.
- [x] Ligar o handler `TASK_ACKNOWLEDGED` à associação e à revisão da versão, sem alterar o estado oficial da tarefa ou inventário; a registry continua opt-in e não é activada por omissão.
- [ ] Implementar health policy/alertas operacionais de dispositivo e validar a frescura do heartbeat; não confundir último contacto com disponibilidade da câmara.
- [ ] Implementar agendamento/configuração de captura, limites de frequência/resolução e backpressure para evitar sobrecarga de rede/storage/worker.
- [ ] Criar fluxo móvel/PWA para captura manual, validação humana, leitura de código de barras e conclusão de tarefa, com permissões mínimas.
- [ ] Definir integração de robôs como fonte de observações e tarefas de inspeção; não permitir controlo físico autónomo sem safety case, limites e aprovação separados.
- [ ] Desenhar Edge AI com inferência local, cache/buffer limitado, health monitoring e política de retenção local.
- [ ] Implementar sincronização offline/online com outbox, IDs idempotentes, ordenação por origem, relógios desalinhados e resolução explícita de conflitos.
- [ ] Definir política de degradação quando Edge, Cloud, câmara ou provider estiver indisponível; preservar observações pendentes sem inventar estados.
- [ ] Validar segurança de rede, TLS, autenticação mútua quando aplicável, segmentação, actualizações e inventário de dispositivos.

### P2 — eventos e integrações externas
- [ ] Definir catálogo/versionamento de eventos de domínio: SHELF_LOW_STOCK, SHELF_OUT_OF_STOCK, PRODUCT_MISPLACED, PLANOGRAM_VIOLATION, RESTOCK_RECOMMENDED, RESTOCK_STARTED, RESTOCK_COMPLETED, INVENTORY_MISMATCH, CAMERA_OFFLINE e VISION_MODEL_UNAVAILABLE.
- [ ] Definir envelope comum de evento com event_id, schema_version, occurred_at, recorded_at, tenant/store, source, correlation_id e idempotency_key.
- [ ] Avaliar MQTT para comunicação Edge e broker/outbox para distribuição backend; escolher tecnologia após requisitos de entrega, retenção, ordering e operação.
- [ ] Garantir outbox transaccional, retries com backoff, dead-letter/replay controlado, deduplicação e observabilidade; não assumir entrega exactly-once.
- [ ] Criar adaptadores POS/ERP/WMS com contratos, autenticação, mapeamento de SKU/unidades, reconciliação, rate limits e testes de contrato.
- [ ] Documentar que nenhuma integração externa é operacional até existir adapter implementado, credenciais configuradas e teste end-to-end demonstrável.

### P0/P1 — segurança, privacidade e governação
- [ ] Auditar autorização por endpoint/serviço para imagens, deteções, planogramas, dispositivos, eventos, tarefas e métricas, preservando isolamento multi-loja e deny-by-default.
- [ ] Definir matriz de permissões por perfil e loja para revisão de deteções, aprovação de planogramas, gestão de modelos, dispositivos e tarefas.
- [ ] Aplicar minimização de dados de vídeo/imagem, retenção configurável, redacção/mascaramento quando necessário e acesso auditado às evidências.
- [ ] Garantir que thumbnails, crops, embeddings, exports, caches e outputs derivados herdam restrições, legal holds e linhagem das fontes.
- [ ] Integrar cada transformação real no registo de derivação e no consumo governado de outputs; não criar bypasses ao serviço existente.
- [ ] Inventariar cópias externas, object storage, réplicas e backups; manter purga física e restauração bloqueadas para cópias sem atestação/governação.
- [ ] Definir gestão segura de modelos/datasets (assinatura/hash, origem, licença, aprovação, versão, rollback e acesso).
- [ ] Definir auditoria de decisões automáticas e humanas com actor, motivo, evidência, versão do modelo/regra e resultado.
- [ ] Rever ameaças específicas de imagens e modelos (upload malicioso, ficheiros enormes, decompression bombs, path traversal, prompt/data poisoning e supply chain de pesos).

### P2 — piloto, operação e critérios de aceitação
- [ ] Definir piloto supervisionado numa loja e secções delimitadas, com 50–100 SKUs como hipótese inicial ajustável após levantamento.
- [ ] Executar primeiro em modo sombra: comparar previsões/deteções com validação humana sem gerar alterações de inventário ou tarefas automáticas irreversíveis.
- [ ] Definir ground truth e amostragem por turno/loja/câmara; medir precision, recall, falsos positivos, falsos negativos e latência.
- [ ] Medir OSA, duração de ruturas, tempo alerta→atribuição, tempo de reposição, taxa de conclusão e impacto operacional face a baseline.
- [ ] Definir critérios de go/no-go por classe/SKU e cenário, limites de falsos alertas, disponibilidade, latência, privacidade e custo.
- [ ] Realizar testes de carga, soak, falha de rede, reinício de worker, câmara offline, broker indisponível e recuperação de backlog.
- [ ] Documentar runbooks, alertas, SLOs, backups/restauro, rotação de credenciais, rollback de modelo e resposta a incidentes.
- [ ] Só declarar o piloto operacional após aprovação dos critérios, evidência reproduzível e validação do responsável da loja.

### REA adicional — Visionplatform.ai: monitorização contínua por câmaras (2026-11-19)

- [x] Analisar o artigo e comparar cada capacidade com o código, README, REA externa e TODO actual; matriz em `docs/architecture/visionplatform-shelf-stockout-analysis.md`.
- [x] Confirmar cobertura já existente: captura por sessão (câmara fixa/robô/telemóvel), consenso temporal e alertas persistentes, `empty_facing`, comparador de células, planogramas versionados, `expected_facings`, comparação read-only e motor de reposição/tarefas.
- [ ] Implementar adaptadores CCTV/VMS existentes (RTSP/ONVIF quando suportado), descoberta/associação de streams a prateleiras, health checks, credenciais e permissões; não exigir câmaras novas sem avaliar a infraestrutura existente.
- [ ] Definir e medir SLO de quase tempo real ponta a ponta (captura, inferência, consenso, alerta e notificação), p50/p95, frequência de amostragem, backpressure e comportamento perante falhas.
- [ ] Criar monitorização da cobertura/saúde das câmaras: online/offline, última captura, idade da evidência, qualidade, oclusão, zonas sem cobertura e indisponibilidade do provider; ausência de captura deve resultar em UNKNOWN.
- [ ] Avaliar profundidade/multi-view/RGB-D para distinguir lacunas visuais de produtos colocados atrás da primeira fila; investigação opcional, sem inferir stock oculto a partir de uma imagem 2D.
- [ ] Acrescentar share-of-shelf por SKU/marca e evolução de facings/participação face ao planograma, com denominadores, perspectiva, cobertura e qualidade da imagem explícitos.
- [ ] Versionar embalagens/imagens de referência por SKU e vigência; medir confusões entre variantes e definir curadoria rápida de novos SKUs/packaging.
- [ ] Avaliar few-shot/semi-supervised learning para adaptação a novos SKUs apenas em experiências controladas, com dataset/licença aprovados, avaliação independente e promoção/rollback humano.
- [ ] Completar o contrato de alerta accionável reutilizando o motor existente: SKU, loja/zona/corredor/prateleira/célula, severidade, confiança, primeira/última ocorrência, evidência, tarefa e estado de resolução.
- [ ] Definir política de vídeo local/Edge e minimização de frames; não implementar reconhecimento facial, contagem de pessoas ou analytics de clientes.
- [ ] Ligar a captura/observações reais do worker ao consenso e alertas existentes; executar primeiro em shadow mode e só depois encaminhar tarefas com validação humana.
- [ ] Validar os resultados no piloto por iluminação, reflexos, blur, ângulo, oclusão, packaging, densidade, SKU e câmara; não importar métricas comerciais (90%+, 2,5x) como metas ou resultados próprios.

**Nota de reconciliação:** os itens antigos 713–716 sobre criação de planogramas versionados, facings esperados e comparação activa já têm implementação API/modelo; os itens de UI e importação/exportação continuam parcialmente pendentes. O consenso temporal e os alertas persistentes também já existem, mas ainda não recebem automaticamente observações reais do worker. Ver a matriz de cobertura na REA acima.

### Sequência recomendada e dependências
1. Fechar P0 de contratos, CI, proveniência e separação mock/real.
2. Preparar dataset e avaliação antes de seleccionar/promover modelo real.
3. Corrigir inferência ONNX e matching de SKU; depois implementar células, facings e espaços vazios.
4. Implementar planogramas e comparação esperado/observado.
5. Ligar consenso visual ao motor de disponibilidade, inventário e tarefas existentes.
6. Evoluir previsão e indicadores OSA.
7. Só depois operacionalizar gateway de dispositivos, Edge/offline, eventos e integrações externas.
8. Executar piloto supervisionado e promover capacidades por evidência.

Critério global: nenhuma capacidade pode ser marcada como concluída sem código, testes relevantes, isolamento/autorização, documentação e evidência CI; funcionalidades dependentes de dataset, câmaras, credenciais ou hardware devem permanecer explicitamente bloqueadas até validação real.



### Fecho da primeira sequência técnica — 2026-11-19

- [x] Mapear classes ONNX por configuração explícita e rejeitar IDs desconhecidos.
- [x] Validar shapes/dtypes e contrato dos tensores antes de executar inferência.
- [x] Separar modos disabled/mock/real e bloquear mock em produção.
- [x] Comparar deteções com células calibradas e preservar estados de incerteza.
- [x] Validar a sequência em CI: 1293 testes aprovados, 1 ignorado, 1 aviso; build Web, Quality Gates e Docker Compose aprovados.
- [ ] Não declarar deteção comercial operacional: faltam pesos aprovados, dataset anotado, calibração e integração persistente das células/planogramas.


### Segunda sequência — proveniência criptográfica do provider ONNX (2026-11-19)

- [x] Calcular SHA-256 dos pesos por leitura em blocos, sem carregar o ficheiro completo para memória.
- [x] Fingerprint determinístico do detector que inclui pesos, mapa de classes, tamanho de entrada, threshold, máximo de deteções e versão de pré-processamento.
- [x] Fingerprint independente do embedder; embeddings novos passam a usar uma versão efectiva vinculada aos pesos e ao pré-processamento.
- [x] Recusar modelos apontados por symlink e detectar substituição dos ficheiros durante a abertura das sessões ONNX.
- [x] Testar estabilidade do fingerprint, alteração de pesos/labels/configuração, symlink e substituição concorrente.
- [ ] Persistir digests e manifesto como campos auditáveis separados, com origem/licença/assinatura e processo de aprovação/rollback.
- [ ] Definir migração operacional dos exemplares aprovados para a nova versão efectiva do embedder; versões antigas devem continuar identificáveis, sem correspondência cruzada.

### Terceira sequência — semântica de classes e elegibilidade de SKU (2026-11-19)

- [x] Definir whitelist explícita `VISION_SKU_MATCH_LABELS` para determinar quais classes semânticas podem produzir embeddings.
- [x] Impedir geração de embeddings para classes não elegíveis (por omissão, `empty_facing` não é um produto).
- [x] Revalidar a whitelist no worker para providers alternativos; uma classe não elegível nunca consulta o catálogo de exemplares.
- [x] Incluir a whitelist no fingerprint do detector, para que alterações de semântica gerem uma nova identidade de modelo.
- [x] Acrescentar testes de provider e worker para impedir matching indevido de espaços vazios.
- [x] Validar a terceira sequência em CI no HEAD `c43b420d2e836daab53f2db5db6a3ddb2dea98f8`: 1307 testes aprovados, 1 ignorado e 1 aviso; Quality Gates, API CI/PostgreSQL 16 e Docker Compose aprovados.
- [ ] Ligar deteções `empty_facing` a células calibradas e à evidência de visibilidade, sem as confundir com ausência de captura ou oclusão.
- [ ] Construir matriz de classes/SKU por modelo aprovado e validar com dataset real anotado.
### Quarta sequência — evidência positiva para espaços vazios (2026-11-19)

- [x] Reconhecer `empty_facing` como evidência semântica separada de deteções de produto.
- [x] Exigir confiança mínima configurável (0,80 por omissão), intersecção geométrica suficiente e célula explicitamente visível/não ocluída para devolver `EMPTY`.
- [x] Tratar ausência de deteções e confiança insuficiente como `UNKNOWN`, nunca como prova de vazio.
- [x] Devolver `CONFLICT` quando a mesma célula recebe simultaneamente deteção de produto e evidência de vazio.
- [x] Preservar índices das deteções, SKU observados e sobreposição geométrica nos resultados.
- [x] Acrescentar testes para vazio positivo, confiança baixa, oclusão, ausência de deteção, conflito e confidence inválida.
- [x] Validar no HEAD de implementação `ad76a03964521bbcab61166d1245986a8a6c577c`: API CI **1311 passed, 1 skipped, 1 warning**; Quality Gates e Docker Compose aprovados.
- [ ] Integrar o comparador no worker com células/planogramas persistidos e origem de calibração auditável; manter a integração desactivada até existir esse contrato.
- [ ] Calibrar o threshold por classe/câmara com dataset real anotado; 0,80 é apenas um default conservador, não uma métrica validada.
### Quinta sequência — conformidade de facings com planograma (2026-11-19)

- [x] Acrescentar `expected_facings` opcional às células, exigindo valor inteiro positivo e SKU esperado.
- [x] Calcular `observed_facings` a partir das deteções de produto associadas à célula, excluindo classes `empty_facing`.
- [x] Devolver `UNDER_FACED` e `OVER_FACED` quando a contagem frontal diverge do esperado; manter `OCCUPIED` quando coincide.
- [x] Dar precedência a `MISPLACED`, `OCCUPIED_UNIDENTIFIED` e `CONFLICT` para não ocultar SKU errado, desconhecido ou evidência contraditória.
- [x] Preservar valores esperados/observados e testar limites, contagens, células vazias e prioridades de estado.
- [ ] Ligar `observed_facings` a detecções persistidas com NMS e deduplicação calibradas; não assumir que cada caixa é um facing físico sem validação.
- [ ] Persistir estes campos em planogramas versionados e expor comparação esperado/observado por API/UI.

### Sexta sequência — API HTTP de planogramas versionados (2026-11-19)

- [x] Corrigir o trigger SQLite de eliminação das células em cascata: só bloquear DELETE de células quando o planograma pai ainda existe e não está em DRAFT.
- [x] Expor criação de versões DRAFT com células validadas, origem de calibração e digest opcional.
- [x] Expor histórico paginado e leitura da versão ativa por prateleira.
- [x] Expor ativação e retirada com motivo obrigatório; ativar uma versão retira a anterior na mesma transação.
- [x] Aplicar autorização ADMIN/SUPERVISOR no middleware e repetir validação de actor/loja no serviço; EMPLOYEE é recusado.
- [x] Acrescentar testes HTTP para ciclo de vida, substituição de versão ativa, retirada, isolamento multi-loja, perfil e payload geométrico/SKU inválido.
- [x] Validar no commit `dd262068bdf8178a8eddff0f103317aec8a3558b`: API CI [44559057802](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44559057802), **1330 passed, 1 skipped, 1 warning**; Quality Gates [44559057575](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44559057575) e Docker Compose [44559057828](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44559057828) aprovados.
- [x] Acrescentar edição/substituição atómica de células apenas enquanto DRAFT; preservar versões ACTIVE/RETIRED.
- [x] Persistir `expected_facings` por célula com constraint/trigger positivo e exigência de SKU esperado.
- [ ] Integrar a comparação geométrica no worker e criar revisão humana; a interface React já permite consulta on-demand sem escrita.
- [ ] Criar interface React de histórico, edição de rascunho, ativação, comparação esperado/observado e revisão.
- [ ] Validar com dataset real anotado; thresholds e contagens continuam experimentais e não podem alterar inventário.


### Sétima sequência — facing targets persistidos e edição segura de DRAFT (2026-11-19)

- [x] Criar migration `0068_shelf_planogram_expected_facings`, encadeada após 0067.
- [x] Persistir `expected_facings` opcional por célula, exigindo valor inteiro positivo e SKU esperado; aplicar constraint PostgreSQL e triggers SQLite.
- [x] Ligar o campo ao modelo SQLAlchemy, schemas HTTP, validação `ShelfCell` e serialização da API.
- [x] Implementar substituição atómica do conjunto de células apenas em `DRAFT`, com a mesma ordem de locks imagem → prateleira → planograma e revalidação do SKU.
- [x] Expor `PUT /api/v1/planograms/{planogram_id}/cells`; CORS permite PUT e middleware mantém ADMIN/SUPERVISOR.
- [x] Testar constraints SQLite, valores inválidos, round-trip HTTP, substituição de células e recusa após ativação.
- [x] Validar no commit `3d9f338e5bdf50a9674f53d05da1ad99e23faa01`: API CI [44560333697](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44560333697) e Quality Gates [44560333600](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44560333600) com **1334 passed, 1 skipped, 1 warning**; Docker Compose [44560333624](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44560333624) aprovado.
- [x] Acrescentar smoke PostgreSQL específico para constraints de `expected_facings` e concorrência entre edição de DRAFT e ativação.
- [ ] Integrar planogramas persistidos no worker com contrato de persistência/retenção aprovado; a revisão visual React já existe, e a contagem continua a ser número de deteções frontais, não unidades em profundidade.


### Nona sequência — comparação read-only entre captura e planograma ativo (2026-11-19)

- [x] Criar serviço puro para comparar deteções persistidas com células de uma versão ACTIVE, ordenadas deterministicamente por linha/coluna.
- [x] Expor endpoint autenticado `GET /api/v1/shelves/{shelf_id}/planograms/comparison/{image_id}`, limitado a ADMIN/SUPERVISOR e ao âmbito da loja.
- [x] Exigir imagem da mesma prateleira, retenção ACTIVE e análise COMPLETED; exigir planograma ACTIVE e revalidar a elegibilidade da sua calibração/SKUs.
- [x] Devolver por célula estado, SKU esperado/observado, facings esperados/observados, IDs das deteções e sobreposição, juntamente com SHA-256 da captura e versões do modelo/planograma.
- [x] Manter a comparação read-only: não cria observações, tarefas nem movimentos e não altera inventário.
- [x] Falhar de forma conservadora: sem calibração de visibilidade por captura, ausência de deteções e `empty_facing` não podem produzir `EMPTY`.
- [x] Acrescentar testes HTTP para facings inferiores, proveniência, não inferência de vazio, imagem ainda pendente, perfil EMPLOYEE e isolamento multi-loja.
- [x] Validar no código `4f3c9a9083b5ab2187a918927b48770ce2813cbf`: API CI [44563920216](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44563920216) passou com **1337 passed, 1 skipped, 1 warning**, incluindo PostgreSQL 16 e smoke de planogramas; Quality Gates [44564178983](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44564178983) passou com os mesmos resultados, compilação Python e build TypeScript/produção Web; Docker Compose [44563920224](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44563920224) passou.
- [ ] Integrar persistência auditável de resultados por imagem/modelo/versão e consumo no worker, com tratamento explícito de retenção da calibração.
- [ ] Criar UI React de revisão visual e validação com dataset real anotado.

### Oitava sequência — smoke PostgreSQL dedicado a planogramas (2026-11-19)

- [x] Criar `apps/api/scripts/postgres_planogram_lifecycle_smoke.py` e integrá-lo no workflow API CI após as restantes verificações PostgreSQL.
- [x] Verificar no PostgreSQL as constraints de `expected_facings`: valor positivo e SKU obrigatório.
- [x] Verificar imutabilidade de células ACTIVE e unicidade de uma versão ACTIVE por prateleira.
- [x] Criar corrida real entre substituição de células DRAFT e ativação em duas sessões PostgreSQL; a ativação tem de esperar pelo commit da edição.
- [x] Validar no commit `46eb9bbc19a039d2e68183655fb07501a0c12ef8`: smoke PostgreSQL dedicado passou; API CI [44561359774](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44561359774) com **1334 passed, 1 skipped, 1 warning**; Quality Gates [44561359524](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44561359524) com o mesmo resultado; Docker Compose [44561359723](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44561359723) aprovado.
- [ ] Ligar o planograma ativo ao worker e persistir resultados de comparação por imagem/modelo/versão, sem efeitos sobre inventário.
- [ ] Criar UI de revisão e validar a contagem de facings com dataset real anotado.


## Interface de comparação com planogramas — 2026-11-19

- [x] Criar componente React dedicado para comparar uma captura concluída com o planograma ativo da respetiva prateleira.
- [x] Restringir a apresentação ao percurso ADMIN/SUPERVISOR e reutilizar o endpoint com autenticação já existente.
- [x] Apresentar proveniência, versão do planograma/modelo, estado por célula, facings e IDs das deteções.
- [x] Manter a semântica conservadora UNKNOWN sem calibração de visibilidade e não alterar inventário.
- [x] Executar build TypeScript/Vite e Quality Gates para validar a integração; Quality Gates `44832248161` passou no commit `4beb3f0`.
- [ ] Fazer validação manual de teclado, leitor de ecrã, contraste e browser móvel.


### Reforço de cobertura da comparação de planogramas — 2026-11-19

- [x] Cobrir HTTP 409 quando existe captura concluída mas não existe planograma ativo na prateleira.
- [x] Cobrir a devolução da proveniência completa quando a versão ativa foi calibrada por imagem.
- [x] Acrescentar cobertura parametrizada para impedir comparações com imagens RESTRICTED, PENDING_PURGE e PURGED; aguarda confirmação do CI para esta alteração.
- [ ] Definir política append-only, retenção e invalidação dos resultados antes de persistir comparações.


### Proteção de retenção na comparação de planogramas — 2026-11-19

- [x] Confirmar que a API verifica o estado de retenção da captura em cada pedido e não devolve deteções para imagens indisponíveis.
- [x] Acrescentar testes parametrizados para RESTRICTED, PENDING_PURGE e PURGED, esperando HTTP 404.
- [x] Documentar a distinção entre a captura comparada e a referência de calibração por imagem.
- [x] Confirmar a nova cobertura no API CI e Quality Gates (commit `6f295c2163d6f761ae54fff6543343d1ca816f1a`).
- [ ] Definir contrato append-only para resultados e decisões humanas antes de criar persistência.


### Identidade reproduzível da comparação — 2026-11-19

- [x] Acrescentar versão explícita do esquema de comparação.
- [x] Calcular SHA-256 determinístico sobre a proveniência completa e os resultados por célula, usando JSON canónico.
- [x] Acrescentar teste HTTP que confirma digest de 64 caracteres e estabilidade entre consultas idênticas.
- [x] Confirmar API CI e Quality Gates: ambos passaram no commit `6f295c2163d6f761ae54fff6543343d1ca816f1a`.
- [ ] Persistir snapshots e decisões humanas apenas numa fase seguinte, com retenção e triggers append-only.


## Concorrência da comparação de planogramas — 2026-11-19

- [x] Bloquear captura e imagem de calibração por ordem crescente de ID antes da prateleira e do planograma.
- [x] Recarregar a versão ativa após os locks e devolver HTTP 409 se a versão tiver mudado durante a aquisição.
- [x] Revalidar retenção ACTIVE e análise COMPLETED da captura sob lock antes de consultar deteções.
- [x] Alargar o smoke PostgreSQL para provar que a restrição de retenção espera pela comparação e que a consulta seguinte rejeita a imagem.
- [x] Validar API CI/PostgreSQL 16 [44588809660](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44588809660), Quality Gates [44589016727](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44589016727) e Docker Compose [44588809507](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44588809507): os três passaram; API CI/Quality Gates executaram **1342 testes aprovados, 1 ignorado e 1 aviso**, e o smoke PostgreSQL de comparação/retenção passou.
- [ ] Definir contrato de retenção/versionamento para snapshots persistidos; manter a comparação on-demand e read-only.


## Fingerprint de comparação — contrato canónico — 2026-11-19

- [x] Rejeitar versões de esquema não suportadas antes de calcular o digest.
- [x] Fixar a versão do esquema no payload canónico, impedindo override pelo chamador.
- [x] Testar independência da ordem das chaves, binding dos resultados por célula, exclusão do próprio digest e rejeição de NaN.
- [x] Confirmar API CI e Quality Gates do novo contrato no commit `4beb3f0`; a suite, compilação Python e build Web passaram.


### Correção do isolamento do teste de idempotência SKU — 2026-11-19

- A primeira execução do CI após a alteração identificou uma falha no teste integrado: a revisão SKU B usada para testar a colisão de idempotência era aplicada à mesma deteção que alimentava o fluxo operacional de tarefas.
- O endpoint comportou-se de forma conservadora; a alteração da revisão fez com que a decisão operacional deixasse de reconhecer a evidência do SKU A, pelo que o teste não podia continuar a esperar a criação da tarefa.
- O teste foi corrigido para usar uma segunda deteção independente na mesma captura para o cenário SKU A → SKU B. Assim, a revisão de regressão não altera a evidência do fluxo de tarefas principal.
- A validação da correção aguarda nova execução dos workflows API CI e Quality Gates; não declarar a suite aprovada até essa execução terminar.


### Isolamento total do cenário de idempotência — 2026-11-19

- A execução CI do commit `6e9a3147e33076316bef9feb72c4cf212e63d87b` confirmou que separar apenas a deteção não era suficiente: a deteção de regressão continuava na mesma prateleira e a observação adicional alterava a avaliação operacional usada pelo teste de criação de tarefas.
- O cenário SKU A → SKU B foi movido para uma segunda prateleira, com imagem e deteção próprias, mantendo os mesmos produtos atribuídos. O fluxo operacional original passa a usar exclusivamente a prateleira e a evidência originais.
- A correcção foi incluída na suite completa validada no API CI/Quality Gates do commit `4beb3f0`; a falha histórica foi resolvida e a suite terminou com 1404 passed, 1 skipped, 1 warning.


### Precisão do âmbito da asserção de decisões — 2026-11-19

- O CI do commit `43ddc0f54c52552eb3168a5f9ab301e49668e431` confirmou que a segunda prateleira isolou a revisão SKU, mas o teste continuava a consultar todas as prateleiras da loja e a construir um dicionário apenas por `product_id`. Como os mesmos SKUs existem nas duas prateleiras, a linha da prateleira de regressão podia substituir a evidência da prateleira operacional na asserção.
- A consulta de decisões no teste foi restringida à prateleira original, que é o âmbito efetivamente validado pelo fluxo de criação de tarefa. A prateleira secundária continua a testar exclusivamente a colisão de idempotência SKU A → SKU B.
- A correção aguarda nova execução do API CI e Quality Gates; a execução anterior terminou com **1 failed, 1342 passed, 1 skipped, 1 warning**.


### Validação integral — idempotência, comparação e isolamento — 2026-11-19

- [x] API CI [44606506802](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44606506802): passou; PostgreSQL 16 e smokes de autorização de funcionários, retenção da fila de revisão, observações, revisão humana, legal hold e ciclo de vida de planogramas passaram; **1343 testes aprovados, 1 ignorado e 1 aviso**.
- [x] Quality Gates [44606506118](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44606506118): passou; compilação Python, suite API (**1343 passed, 1 skipped, 1 warning**) e build TypeScript/produção Web aprovados.
- [x] Docker Compose [44606506450](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44606506450): passou.
- [x] Corrigida a asserção do teste integrado para consultar apenas a prateleira operacional original, evitando colisão por `product_id` entre prateleiras distintas.
- [ ] Prosseguir com auditoria handler-by-handler de autorização e isolamento multi-loja; não assumir cobertura total apenas com os smokes atuais.


### Vinculação da evidência à prateleira observada — 2026-11-19

- A auditoria identificou que a validação da evidência de demonstração confirmava imagem ativa, deteção, revisão SKU, produto e SHA-256, mas não ligava a imagem à mesma prateleira da observação.
- A consulta de imagem usada para construir `evidence` exige agora também `ShelfImage.shelf_id == shelf.id`; uma referência válida de outra prateleira deixa de satisfazer o gate de evidência.
- Acrescentado teste de regressão que injeta numa observação manual referências válidas a uma imagem/deteção/revisão de outra prateleira e exige `evidence == None`.
- A alteração está publicada e foi incluída na validação API CI/Quality Gates/Docker Compose do commit `4beb3f0`; os três workflows passaram.


### Proteção contra falsificação de metadados de evidência — 2026-11-19

- A observação manual genérica aceita texto livre; sem uma fronteira explícita, um utilizador autenticado poderia tentar introduzir os marcadores internos usados pelo fluxo de demonstração.
- O endpoint genérico rejeita agora os campos reservados de proveniência (`demo_detection_id`, imagem, revisão e confirmação humana), reservando-os para a rota de deteção revista.
- A avaliação de evidência exige também estado humano confirmado igual ao estado da observação, timestamp de confirmação e utilizador confirmador ativo ADMIN/SUPERVISOR com âmbito de loja válido.
- O teste integrado tenta criar metadados de demonstração através do endpoint genérico e espera HTTP 422, além de verificar que uma referência cruzada de prateleira não produz evidência elegível.
- Validação posterior confirmada no API CI/Quality Gates do commit `4beb3f0`; a suite completa passou.


## Contrato geométrico do provider ONNX — 2026-11-20

- [x] Confirmar que as coordenadas do detector são normalizadas relativamente ao tensor quadrado letterboxed e convertidas para coordenadas normalizadas da imagem original.
- [x] Acrescentar regressão de clipping às dimensões da imagem original para caixas que intersectam padding do letterbox.
- [x] Acrescentar testes paramétricos para coordenadas negativas/superiores a 1 e valores NaN/Inf.
- [x] Fixar o ordenamento por confiança e o limite máximo de deteções através de teste.
- [x] Acrescentar teste integrado do worker que prova que timeout/falha do provider termina em FAILED, sem deteções persistidas nem alteração de observações/inventário.
- [ ] Validar o contrato com um modelo ONNX exportado e dataset anotado autorizado; testes sintéticos não demonstram precisão nem compatibilidade com modelos externos.


## Falhas de inferência no worker de visão — 2026-11-20

- [x] Acrescentar teste integrado do worker para timeout e falha genérica do provider.
- [x] Confirmar que a falha termina a imagem em FAILED e regista apenas o tipo de erro, sem persistir deteções, observações ou snapshots de inventário.
- [x] Validar no commit `4212aeab21bfe9182a485e10cfbd8a209d1d28ac`: [API CI 44652277501](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44652277501), [Quality Gates 44652277455](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44652277455) e [Docker Compose 44652278042](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44652278042) passaram; a suite API teve 1374 passed, 1 skipped e 1 warning; migrations e smokes PostgreSQL 16, compilação Python e build Web passaram. O aviso é a depreciação externa `anyio.abc.BlockingPortal` do Starlette TestClient. Validação CI, sem testes locais ou dados reais de visão.


## Fencing de resultados após takeover de lease — 2026-11-20

- [x] Acrescentar teste integrado em que um segundo processamento assume a lease enquanto o primeiro provider ainda está a inferir.
- [x] Confirmar que o resultado válido do worker antigo é descartado antes de persistir deteções, observações ou inventário.
- [x] Validar no commit `4212aeab21bfe9182a485e10cfbd8a209d1d28ac`: [API CI 44652277501](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44652277501), [Quality Gates 44652277455](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44652277455) e [Docker Compose 44652278042](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44652278042) passaram. A suite API terminou com 1374 passed, 1 skipped e 1 warning; o smoke PostgreSQL 16 validou recuperação `SKIP LOCKED`, takeover de lease com resultado válido obsoleto, mudança de retenção durante inferência e falha do provider após takeover. Validação CI, não teste manual.

## Recuperação transacional de outputs — 2026-11-20

- [x] Acrescentar regressão para falha SQL depois da criação do ficheiro final e antes da confirmação da publicação.
- [x] Verificar que a falha não deixa linha de auditoria parcial, não remove staging e permite retry idempotente.
- [x] Confirmar API CI, Quality Gates e Docker Compose no commit `4beb3f0`; os três passaram.
- [x] Avaliar separadamente falhas de `fsync` do ficheiro/directório, hard link e remoção pós-commit; regressões específicas e limites documentados em `docs/operations/dataset-output-reconciliation.md`.

## Evolução visual do frontend — melhoria futura (adiada a pedido)

- [ ] Avaliar e integrar a skill [Impeccable](https://github.com/pbakaus/impeccable) no workflow de desenvolvimento do frontend.
- [ ] Antes de qualquer redesign, definir com o responsável o público-alvo, os principais contextos de utilização e a personalidade visual da marca; verificar se já existe `.impeccable.md` com esse contexto.
- [ ] Fazer auditoria visual das páginas existentes e propor um sistema coerente de design tokens, tipografia, cores, espaçamento, componentes, estados, acessibilidade e responsividade.
- [ ] Implementar melhorias de forma incremental, preservando contratos API e fluxos funcionais, e validar screenshots nas dimensões suportadas.
- Nota: não instalar nem alterar o frontend nesta fase; retomar apenas quando este tema for explicitamente reaberto.

## Durabilidade do filesystem na promoção de outputs — 2026-11-20

- [x] Cobrir falha de `fsync` do ficheiro temporário: abortar antes do commit, remover o temporário, preservar staging e permitir retry.
- [x] Sincronizar os directórios-pai de cada componente da árvore de armazenamento, incluindo componentes já existentes em retries após falha anterior.
- [x] Ao recuperar um destino já existente, voltar a verificar SHA-256/tamanho/metadados, sincronizar o ficheiro e o directório antes de registar a publicação.
- [x] Cobrir falha de `fsync` depois do hard link, rollback SQL e retry idempotente com verificação do destino.
- [x] Garantir libertação de descritores quando a sincronização de um directório falha depois da abertura do componente.
- [x] Cobrir falha de `fsync` na remoção pós-commit: a publicação permanece válida e a falha gera aviso sem expor caminhos.
- [x] Validar no commit `4beb3f002b809de8ef50f9990a377db2f7f7c36d`: API CI, Quality Gates e Docker Compose passaram; suite com 1404 aprovados, 1 ignorado e 1 aviso.
- [x] Documentar que a garantia depende do filesystem/volume honrar `fsync`; CI não prova resistência a perda física, falha de energia ou storage remoto.

## Limpeza pós-commit e reconciliação — 2026-11-20

- [x] Testar falha de permissões na remoção de staging depois do commit da publicação.
- [x] Confirmar que o output e a linha de auditoria permanecem válidos e que o staging residual pode ser removido pelo reconciliador após o período de segurança, com digest/tamanho coincidentes.
- [x] Validar API CI e Quality Gates para os testes de falha de fsync e limpeza pós-commit no commit `4beb3f0` (1404 passed, 1 skipped, 1 warning).
- [ ] Manter limpeza de staging órfão sem publicação em modo report-only até prova independente de quiescência dos workers.
- [x] Testar isolamento multi-loja nas mutações por `planogram_id`: outro supervisor não pode editar um rascunho, ativar ou retirar um planograma de loja alheia; confirmar que o estado ACTIVE permanece inalterado.


## Revalidação da identidade no limite do handler — 2026-11-20

- [x] Identificar a janela entre autenticação JWT no middleware e carregamento do actor numa sessão DB independente: conta removida/inactivada podia resultar em `_request_user() == None`, e alguns handlers tratavam esse estado como ausência de restrição de loja.
- [x] Tornar o carregamento do actor fail-closed fora do ambiente de testes: actor inexistente/inactivo devolve HTTP 401.
- [x] Reavaliar a política RBAC com o papel actual da base de dados no limite do handler, impedindo que uma alteração de role entre middleware e handler preserve permissões antigas.
- [x] Acrescentar testes unitários para actor removido e downgrade SUPERVISOR → EMPLOYEE entre autenticação e execução do handler.
- [x] Confirmar os testes e a suite completa no API CI/Quality Gates do commit `4beb3f0` (1404 passed, 1 skipped, 1 warning); não houve execução local.
- [ ] Rever futuramente a mesma janela para outros dados de autorização mutáveis e transacções longas, sem substituir a revalidação do actor por confiança exclusiva no JWT.


## Embeddings de visão computacional sem proveniência de loja — 2026-11-20

- [x] Confirmar que o worker resolve a loja a partir da imagem alvo e passa sempre `store_id` ao construir o registo de embeddings.
- [x] Confirmar que o carregador por loja faz join obrigatório à imagem/prateleira/zona; exemplares sem imagem de origem não entram em registos específicos de loja.
- [x] Estender o teste de isolamento para incluir um exemplar APPROVED sem `shelf_image_id`; as lojas A e B não o podem carregar nos respectivos registos.
- [x] Confirmar execução do teste no API CI/Quality Gates do commit `4beb3f0`.
- [ ] Definir, numa alteração funcional separada, se os exemplares sem imagem de origem devem ser proibidos na criação ou mantidos apenas para fluxos administrativos globais. Não alterar este comportamento sem uma decisão de produto e análise dos consumidores.

## Consumo seguro de outputs publicados — 2026-11-20

- [x] Acrescentar regressões para o consumidor de outputs publicados: leitura integral autorizada, autorização estritamente positiva (apenas `True`) e rejeição de bytes publicados adulterados.
- [x] Validar os novos testes e a suite API no API CI/Quality Gates do commit `4beb3f0` (1404 passed, 1 skipped, 1 warning).
- [ ] Avaliar a integração futura deste helper com um consumidor de produto/API; não existe evidência nesta auditoria de uma rota HTTP que o invoque, pelo que não presumir que outputs já são descarregáveis por utilizadores finais.

## Bloqueio transaccional da proveniência de outputs — 2026-11-20

- [x] Bloquear as linhas `DatasetExecutionJobSource` com `SELECT ... FOR UPDATE` durante o consumo de outputs publicados, ordenando por imagem, job e ID para aquisição determinística dos locks.
- [x] Acrescentar teste que verifica a cláusula PostgreSQL `FOR UPDATE` e a ordenação estável da query.
- [x] Validar o helper e os testes de consumo no API CI/Quality Gates do commit `4beb3f0` (1404 passed, 1 skipped, 1 warning).
- [x] Corrigir o teste SQL: separar a construção da query da sua execução para compilar PostgreSQL sem tentar executar `FOR UPDATE` em SQLite nem depender de tabelas não criadas.
- [x] Reexecutar API CI, Quality Gates e Docker Compose no SHA corrigido `4beb3f0`; os três workflows passaram.

## Segurança — matriz completa de políticas RBAC (2026-11-21)

- [x] Acrescentar o teste test_every_explicit_api_route_policy_matches_the_complete_role_matrix em apps/api/tests/test_security.py: valida todas as entradas método/template contra ADMIN, SUPERVISOR e EMPLOYEE, rejeita políticas duplicadas/categorias desconhecidas e confirma fail-closed para rotas não registadas.
- [x] Quality Gates [44882467613](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44882467613) passou no commit b1c60246938befa86233b49f6d8a4841617fbfdc: compilação Python, build TypeScript/produção, detector Impeccable e suite API **1408 passed, 1 skipped, 1 warning**.
- [x] API CI [44882467564](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44882467564) passou no mesmo commit: auditoria estrita de rotas, migrations PostgreSQL 16, smokes de concorrência/isolamento/retention e **1408 passed, 1 skipped, 1 warning**.
- [ ] Prosseguir a matriz handler × perfil × loja e caminhos indirectos. A cobertura de ordem de locks foi acrescentada para 22 handlers, mas não prova isolamento de cada recurso nem todos os caminhos indirectos. Incremento adicional: `postgres_inventory_authorization_smoke.py` cobre IDs aninhados de `InventoryExternalProductMapping`/eventos — supervisor A acede ao próprio mapping, recebe 404 indistinguível para mapping B sob o path A, não consegue alterar o mapping B e não acede ao path B; ADMIN mantém acesso positivo. Smoke aprovado no API CI `45804056793`.
- [x] Executar SCA, Gitleaks e ZAP baseline/API safe-mode no workflow 44884714393; o scan não é autenticado e não substitui DAST autenticado/activo.

## Segurança — scanners automatizados SCA, segredos e DAST (2026-11-21)

- [x] Criar workflow isolado .github/workflows/security-scans.yml, com permissões mínimas, checkout sem persistência de credenciais e execução em runners efémeros.
- [x] Configurar pip-audit sobre dependências API e OCR opcionais, npm audit --audit-level=high sobre o lockfile Web e Gitleaks sobre o histórico Git.
- [x] Configurar ZAP Baseline e API safe-mode sobre OpenAPI contra a API efémera do Docker Compose; 134 endpoints no baseline e 131 operações importadas no scan API.
- [x] Analisar a primeira execução real: Gitleaks e npm audit passaram; pip-audit detectou 158 ocorrências em cinco pacotes Python (pytest, PyJWT, python-multipart, Pillow e Starlette). As versões vulneráveis foram actualizadas, sem exclusões de advisories.
- [x] Reexecutar SCA: pip-audit e npm audit sem vulnerabilidades conhecidas no commit 1c0f591; API CI e Quality Gates passaram com 1413 testes aprovados e 1 ignorado.
- [x] Triar o baseline ZAP: 0 alertas High, 0 Medium e 0 Low; 7 alertas informativos, sem findings exploráveis identificados.
- [ ] Implementar DAST autenticado e active scan apenas num ambiente isolado com identidades de teste e salvaguardas contra operações destrutivas.

## Segurança — ordem de locks por tenant (2026-11-21)

- [x] Introduzir _lock_authorized_shelf_image: obter store scope sem lock, autorizar, adquirir lock com refresh e revalidar o store scope.
- [x] Introduzir _lock_store_scoped_record com a mesma sequência para sessões de captura, paletes e tarefas.
- [x] Migrar 22 handlers que acedem a recursos multi-loja, incluindo conteúdo/retention de imagens, deteções, OCR, fusions, exemplares, tarefas, paletes, sessões e alertas.
- [x] Acrescentar teste estático de ordem de autorização/locks, teste do helper genérico e regressões de alertas cross-store e de ordenação PostgreSQL.
- [x] API CI [44884714292](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714292), Quality Gates [44884714318](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714318) e Docker Compose [44884714261](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714261) passaram no commit 1c0f591: 1413 passed, 1 skipped.
- [ ] Completar a revisão BOLA/IDOR endpoint × perfil × tenant e testar caminhos indirectos em contexto autenticado.

## Segurança — headers HTTP e política de documentação (2026-11-21)

- [x] Aplicar X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, Cross-Origin-Resource-Policy e CSP.
- [x] Aplicar Cache-Control: no-store às respostas API e HSTS em produção.
- [x] Desactivar Swagger UI em produção; manter documentação interactiva apenas fora de produção, com CSP específica.
- [x] Acrescentar testes para respostas 401, headers e política de docs.
- [x] OWASP ZAP Baseline e API safe-mode [44884714393](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714393): 0 alertas High/Medium/Low; 7 informativos.
- [ ] DAST autenticado e teste activo continuam pendentes; o scan actual não possui sessão de utilizador e recebe 401 em endpoints protegidos.

## Computer Vision — contrato ONNX e falhas do worker (2026-11-21)

- [x] Completar matriz de boxes: coordenadas invertidas, largura/altura zero, caixas totalmente dentro do padding letterbox e clipping parcial para a imagem original.
- [x] Testar falhas RuntimeError e TimeoutError no worker: estado FAILED, erro sanitizado, deteções anteriores preservadas e nenhum snapshot de inventário criado.
- [x] Validar no commit a345746200eb6ea8b0035bd2cdba7c188de87ef9: API CI [44885522283](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44885522283), Quality Gates [44885522309](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44885522309) e Docker Compose [44885522318](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44885522318) passaram com **1422 passed, 1 skipped**.
- [ ] Validar com modelo ONNX real versionado, dataset autorizado e métricas reproduzíveis; os testes de contrato não medem precisão nem substituem avaliação por SKU/cenário.


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


## Edge AI — não alterar o estado após perda de lease (2026-11-23; teste publicado, CI pendente)

- [x] Acrescentar regressão para handler que termina com sucesso depois de falhar o heartbeat; o resultado local permanece sem ACK e a lease fica recuperável por expiração/fencing.
- [x] Acrescentar regressões parametrizadas para handler com erro transitório e erro permanente depois de falhar o heartbeat; ambos os caminhos têm de abandonar o resultado sem marcar RETRY ou DEAD_LETTER.
- [ ] Confirmar API CI, Quality Gates, Security Scans e Docker Compose no commit de teste aec6f2b1701e2fcb92e51ba981c9819d8347c683.
- [ ] Acrescentar smoke PostgreSQL que force a perda/takeover da lease durante um handler lento e prove que um worker obsoleto não confirma nem altera o estado do evento.

A implementação de produção já verificava lease_lost nos caminhos de sucesso e erro; esta alteração reforça a cobertura de regressão. Os testes SQLite não substituem o smoke de concorrência PostgreSQL.


## Segurança — BOLA em recursos aninhados de prateleira (2026-11-23; implementação publicada, CI pendente)

- [x] Acrescentar fixtures PostgreSQL reais de observação, sessão de captura, alerta e evento de auditoria pertencentes à loja estrangeira.
- [x] Testar que SUPERVISOR não cria observações, sessões de captura ou planogramas usando IDs de prateleiras de outra loja.
- [x] Testar que consenso, listagem de planogramas, planograma activo e eventos de alertas estrangeiros não são acessíveis por IDs aninhados.
- [x] Testar que filtros por shelf_id estrangeiro não devolvem observações, sessões ou alertas da outra loja.
- [x] Manter controlos positivos same-store e verificar que tentativas negadas não criam observações nem sessões adicionais.
- [x] Smoke de autorização PostgreSQL 16 passou no API CI [45177953932](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45177953932), passo 31, no commit de código 26a97f7136eace2bc0b4f428731db3990163aa93.
- [ ] Aguardar conclusão da suite pytest completa no API CI 45177953932.
- [ ] Alargar a matriz autenticada a ADMIN, SUPERVISOR e EMPLOYEE por endpoint, incluindo relações indirectas de imagens, planogramas, deteções e tarefas.

## Edge AI — validação da ronda anterior

- [x] API CI passou no commit aec6f2b1701e2fcb92e51ba981c9819d8347c683.
- [x] Docker Compose Smoke passou no mesmo commit.
- [ ] Quality Gates e Security Scans foram cancelados; repetir a validação num commit posterior.
- [ ] Criar smoke PostgreSQL de takeover concorrente durante handler lento e provar rejeição de ACK/falha por fencing obsoleto.


## Segurança — matriz RBAC multi-loja adicional (2026-11-23; implementação publicada, CI pendente)

- [x] Adicionar actor EMPLOYEE autenticado à fixture PostgreSQL multi-loja.
- [x] Confirmar que ADMIN consegue consultar os IDs reais de observações, sessões e alertas da loja estrangeira.
- [x] Confirmar que EMPLOYEE recebe HTTP 403 em observações, sessões, alertas e planogramas, mesmo para a própria loja.
- [x] Smoke PostgreSQL 16 de autorização passou no API CI 45177953932, passo 31, no commit 26a97f7136eace2bc0b4f428731db3990163aa93.
- [ ] Aguardar conclusão da suite pytest completa do API CI.
- [ ] Continuar matriz endpoint × papel × tenant para rotas restantes e relações indirectas.


## Segurança P0 — criação de prateleiras por zona (2026-11-23; implementação/teste publicados, CI pendente)

- [x] Resolver a zona antes de criar a prateleira e verificar o tenant associado.
- [x] Para SUPERVISOR, devolver HTTP 404 tanto para uma zona estrangeira como para um ID inexistente.
- [x] Preservar a criação same-store e verificar que a tentativa cross-store não persiste uma prateleira.
- [x] Validado no código `eea9cc5d`: auditoria de políticas RBAC passou no API CI `45797706450`, suite API **1739 passed, 1 skipped**, PostgreSQL 16; Quality Gates `45798609654` e Security Scans `45798609531` passaram no HEAD documental `3b288869`; Docker Compose `45797706344` passou.
- [ ] Continuar auditoria das relações produto-prateleira e IDs directos de tarefas/movimentos.


## Segurança P0 — associação de produto a prateleira (2026-11-23; implementação/teste publicados, CI pendente)

- [x] Validar identidade do actor antes de resolver o shelf_id fornecido.
- [x] Ocultar prateleiras estrangeiras com HTTP 404 igual a IDs inexistentes antes do lock do produto.
- [x] Cobrir tentativa cross-store, resposta equivalente, ausência de associação persistida e controlo positivo same-store.
- [ ] Executar testes focados e workflows API CI, Quality Gates, Security Scans e Docker Compose.
- [ ] Continuar auditoria de IDs directos de tarefas e movimentos de inventário.


## Segurança P0 — IDs directos de tarefas e eventos de reposição (2026-11-23; código/testes publicados, CI pendente)

- [x] A leitura de eventos de tarefa autentica o actor antes de resolver task_id e oculta tarefas estrangeiras com HTTP 404 igual ao ID inexistente, sem adquirir row lock numa rota GET.
- [x] A alteração de estado e a reconciliação de inventário usam autorização pré-lock com hide_foreign=True para IDs directos de tarefas.
- [x] Testes comparam respostas cross-store/inexistente para eventos, alteração de estado e reconciliação; confirmam que a tentativa de reconciliação não cria InventoryMovement.
- [ ] Confirmar API CI, Quality Gates, Security Scans e Docker Compose no HEAD final; executar smoke PostgreSQL 16.
- [ ] Continuar auditoria de IDs directos de movimentos, eventos de paletes e entidades de warehouse.


## Segurança P0 — IDs de evidência de visão computacional (2026-11-23; implementação/testes publicados, CI em execução)

- [x] Autenticar o actor antes de resolver IDs de imagens, deteções ou exemplares em endpoints de revisão/leitura de retenção.
- [x] Ocultar imagens, deteções e exemplares de outra loja com HTTP 404 e detalhe igual ao recurso pai inexistente.
- [x] Preservar a ordem de locks imagem → produto → exemplar e o HTTP 410 para imagens indisponíveis por retenção quando o recurso pertence à loja autorizada.
- [x] Adicionar regressões para IDs estrangeiros/inexistentes em retenção, revisão de deteções e revisão de exemplares.
- [ ] Confirmar API CI, Quality Gates, Security Scans e Docker Compose no HEAD final; investigar qualquer falha antes de declarar validação concluída.
- [ ] Continuar auditoria de endpoints de leitura/revisão de evidência OCR, matching e retenção com IDs aninhados.


## Segurança P0 — uploads de imagens e sessões de captura (2026-11-23)

- [x] Autenticar o actor antes de resolver shelf_id no upload de imagens e ocultar prateleiras estrangeiras como inexistentes.
- [x] Ocultar capture_session_id estrangeiro com HTTP 404 igual ao ID inexistente, usando preflight de tenant antes do row lock e revalidação pós-lock.
- [x] Testar prateleiras estrangeiras/inexistentes e sessões estrangeiras/inexistentes; confirmar ausência de ficheiros e de novas imagens após pedidos recusados.
- [ ] Confirmar API CI, Quality Gates, Security Scans e Docker Compose no HEAD final.


- [x] Corrigir o contrato do smoke PostgreSQL de pre-lock de deteções/exemplares: após a ocultação cross-store, os três endpoints devolvem HTTP 404 (em vez do antigo 403) e continuam a ser rejeitados antes de esperar pelos locks da imagem/produto.
- [ ] Reexecutar API CI no HEAD com a expectativa corrigida e confirmar o smoke concorrente PostgreSQL.


## Fecho de validação P0 — isolamento multi-tenant e IDs diretos (2026-11-23)

- [x] API CI no HEAD `1ffe4d3a7567c486f68de5e26051f7bcc0a2c110`: 1595 testes aprovados, 1 ignorado.
- [x] PostgreSQL 16: migrations, autorização cross-store, lock ordering, retenção/legal hold, deteções/exemplares, inventário, tarefas, captura, planogramas e anti-rollback ONNX smoke tests aprovados.
- [x] Quality Gates: testes/compilação Python e TypeScript/build de produção aprovados.
- [x] Security Scans: secret scan, auditoria de dependências Python/Web e OWASP ZAP passive baseline aprovados.
- [x] Docker Compose demo stack smoke aprovado.
- [ ] Continuar auditoria de IDs aninhados em OCR, matching, artefactos e restantes endpoints de warehouse; manter regressões de tenant e de ausência de efeitos laterais.

## Segurança P0 — consulta de eventos de tarefas com predicado SQL multi-tenant (2026-11-23; código/teste publicados, CI pendente)

- [x] Fazer a consulta de tarefas para SUPERVISOR filtrar `task_id` e `store_id` na mesma query, sem materializar tarefas estrangeiras antes da autorização.
- [x] Preservar visibilidade global de ADMIN e compatibilidade de execução de testes sem actor.
- [x] Reforçar a regressão: SUPERVISOR recebe 404 equivalente para tarefa estrangeira/inexistente; ADMIN mantém acesso à tarefa estrangeira.
- [ ] Validar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA final.


## Segurança P0 — preflight de detection_id com tenant no SELECT (2026-11-23; implementação/testes publicados, CI pendente)

- [x] Resolver a imagem de origem através de JOIN Detection → ShelfImage → Shelf → Zone.
- [x] Aplicar `store_id` no SELECT para actores não ADMIN, antes de materializar a detecção estrangeira.
- [x] Preservar o lock da imagem e a revalidação de tenant pós-lock, mantendo a ordem global imagem → detecção.
- [x] Reforçar o teste directo do resolver para IDs estrangeiros e inexistentes, além dos testes HTTP existentes.
- [ ] Validar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA desta alteração.



## Inventário — interface de histórico de movimentos

- [x] Criar painel React para consultar movimentos por loja.
- [x] Adicionar filtros por ID de produto e tarefa, atualização manual e limite explícito de 100 registos.
- [x] Apresentar indicadores de movimentos encontrados, unidades movimentadas e data do movimento mais recente.
- [x] Disponibilizar detalhe auditável por movimento, incluindo snapshots, responsável e justificação.
- [x] Restringir a apresentação a ADMIN/SUPERVISOR e usar o filtro de loja activo para ADMIN.
- [x] Classificar explicitamente a rota GET de histórico na matriz de políticas RBAC.
- [ ] Implementar divergências entre stock observado na prateleira e stock de referência, sem alterar automaticamente o inventário contabilístico.
- [ ] Separar explicitamente stock de retaguarda, reservado, disponível e stock físico observado na prateleira.


## Dashboard — semântica do indicador de urgência

- [x] Separar prioridade HIGH de URGENT no KPI `urgent_active_tasks`; o indicador conta apenas tarefas URGENT activas.
- [ ] Confirmar API CI e Quality Gates no SHA da correção.


## Inventário — histórico de movimentos (2026-11-23)

- [x] Integrar histórico read-only no dashboard para ADMIN/SUPERVISOR, com filtros por produto/tarefa e detalhe da linhagem dos snapshots.
- [x] Classificar a rota na matriz RBAC explícita e respeitar loja activa/escopo do utilizador.
- [x] Corrigir o KPI de tarefas urgentes para contar apenas prioridade URGENT activa, alinhando implementação, contrato e teste.
- [ ] Confirmar API CI e Quality Gates após a correção do KPI.
- [ ] Implementar divergências entre stock observado e stock de referência sem mutação contabilística automática.
- [ ] Formalizar estados separados de retaguarda, reservado, disponível, prateleira e observado visualmente.


## Inventário — painel de reconciliação operacional
- [x] Integrar a reconciliação de exposição/retaguarda no dashboard para ADMIN e SUPERVISOR.
- [x] Permitir filtrar por produto e prateleira, com atualização manual e limite explícito.
- [x] Distinguir objetivo de exposição, quantidade observada, diferença face ao objetivo e snapshot de retaguarda.
- [x] Apresentar separadamente stock físico registado, reservado e disponível na retaguarda, com fonte e idade do snapshot.
- [x] Mostrar estados sem observação/medição e ausência de snapshot, sem inferir quantidades em falta.
- [x] Explicitar que diferenças são informativas e nunca ajustam automaticamente o inventário contabilístico.
- [ ] Validar build Web CI e Quality Gates no SHA final desta integração.

- [ ] Validar por CI/PostgreSQL 16 a reavaliação da recomendação sob lock na criação de tarefas; ampliar testes concorrentes de alterações de stock/evidência.

## Reposição — validade temporal do inventário de retaguarda (2026-11-24; implementação/testes publicados, CI pendente)

- [x] Aplicar a política de frescura por loja e origem ao motor de recomendações.
- [x] Sinalizar snapshots futuros como `INVALID_INVENTORY_TIMESTAMP`.
- [x] Sinalizar snapshots fora da validade como `STALE_INVENTORY`.
- [x] Não produzir quantidades sugeridas nem permitir criação de tarefas com inventário temporalmente inválido.
- [x] Adicionar testes parametrizados para snapshot antigo e futuro, incluindo tentativa de criação de tarefa.
- [ ] Executar suite de tarefas/inventário e validar PostgreSQL/CI no HEAD final.

- [x] Acrescentar regressão para política personalizada por loja e origem (snapshot com 20 minutos, limite configurado de 10 minutos).


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


## 2026-11-24 — Reconciliação multi-fonte ERP/WMS (implementação publicada; CI pendente)

- [x] Expor o último snapshot ERP e o último snapshot WMS separadamente por produto/loja.
- [x] Apresentar on-hand, reservado, disponível, timestamp, idade e estado de frescura por fonte.
- [x] Calcular a diferença WMS−ERP apenas quando ambas as fontes têm evidência actual e válida; sinalizar divergência, ausência, stale ou timestamp futuro.
- [x] Mostrar os domínios ERP e WMS em separado no painel React, sem mutações de inventário.
- [ ] Confirmar API CI, Quality Gates, Web CI, Security Scans e Docker Compose no HEAD final.
- [ ] Definir contrato semântico de stock por fonte e validar a comparação com operadores/dados reais antes de tratar divergências como discrepâncias contabilísticas.
- [ ] Implementar adapters ERP/WMS reais, idempotência de ingestão, cursor/offset de sincronização e histórico de execução por integração.


## Ledger auditável de reconciliação

- [x] Persistir evidência por loja/prateleira/produto, incluindo quantidades, diferenças, IDs e timestamps.
- [x] Rever com estados PENDING / APPROVED / REJECTED / NEEDS_INVESTIGATION e justificação.
- [x] Exigir revisor diferente do autor (maker-checker).
- [x] Proteger evidência e eventos com triggers de integridade.
- [x] Disponibilizar histórico e ações no painel React.
- [ ] Confirmar API CI, Web CI, Quality Gates, Security Scans e Docker Compose no commit final.
- [ ] Dashboard agregado por loja/produto e métricas de divergência.
- [ ] Adapters ERP/WMS reais e histórico de execuções/erros de sincronização.


## ERP/WMS — próxima fatia de integração
- [x] Persistir mapeamentos externos de produto por loja e fonte, com unicidade de ID externo e SKU.
- [x] Implementar serviço de orquestração paginada, com isolamento por loja e fornecedor.
- [x] Aplicar timeout, retries limitados, backoff, limite de páginas e detecção de cursor repetido.
- [x] Persistir snapshots por página e garantir replay idempotente pela referência externa.
- [x] Ligar o resultado ao ledger, incluindo conclusão parcial/falhada e identidade externa da execução.
- [ ] Criar gestão autenticada dos mapeamentos externos.
- [ ] Executar o serviço num worker durável e integrar um secret manager.
- [ ] Homologar pelo menos um adapter real com documentação e credenciais do fornecedor.


## Administração de mappings ERP/WMS
- [x] API autenticada para listar, criar e actualizar mappings por loja.
- [x] Permissões ADMIN/SUPERVISOR com isolamento por loja.
- [x] Exigir integração activa da fonte e produto interno activo.
- [x] Registar criação, alteração, desactivação e reactivação em audit trail append-only.
- [x] Impedir alteração da identidade externa e eliminação física do mapping na base de dados.
- [x] Implementar worker durável com leases, fencing e recuperação de execuções STARTED abandonadas; a recuperação fecha tentativas abandonadas como PARTIAL com evento COMPLETED.
- [ ] Integrar secret manager e adapter real homologado.


## ERP/WMS — fila durável
- [x] Fila persistente por loja/fonte com chave de idempotência.
- [x] Worker independente da API HTTP e serviço Docker Compose isolado.
- [x] Leases, lease token aleatório, fencing token monotónico e recuperação de leases expirados.
- [x] Guard de lease na mesma transação de cada commit de página.
- [x] Retries limitados com backoff e eventos append-only.
- [x] API de enqueue, consulta de jobs e histórico com autorização multi-loja.
- [x] Fechar tentativas STARTED abandonadas na mesma transacção de recuperação do lease, sem inventar contagens de páginas.
- [x] Teste de regressão SQLite para finalização da tentativa abandonada e rejeição do worker antigo.
- [x] Implementar e ligar ao API CI o smoke PostgreSQL 16 para claim concorrente, fencing e recuperação SIGKILL do ledger STARTED.
- [ ] Executar o smoke no PostgreSQL 16 do API CI e confirmar o resultado verde.
- [x] Interrupção após commit real de página e replay idempotente dos snapshots cobertos no smoke PostgreSQL.
- [x] Rejeitar tentativa de escrita do worker obsoleto no limite do orquestrador, sem criar ledger nem snapshot.
- [ ] Adapter real ERP/WMS e homologação do fornecedor.
- [ ] Integração com Vault/Secrets Manager ou gestor de segredos escolhido no deployment.
- [ ] Agendamento recorrente por loja/fonte e janelas operacionais.


## Reconciliação multi-loja — SKU partilhado entre lojas (2026-11-25)

- [x] Adicionar regressão HTTP com o mesmo produto global associado a prateleiras de duas lojas.
- [x] Criar snapshots ERP/WMS com quantidades distintas por loja e confirmar que cada reconciliação congela apenas os IDs e quantidades da própria loja.
- [x] Confirmar que a consulta corrente e o ledger da loja A não expõem o registo da loja B.
- [x] Confirmar que a tentativa de rever directamente uma reconciliação estrangeira devolve 404 e mantém o estado PENDING.
- [x] Confirmar API CI (45574197186), Quality Gates (45574197259), Security Scans (45574197237) e Docker Compose (45574197037) no SHA `c8efb82b64d4aed9fcc81fdb4a0571695fdd23cf`.
- [x] Formalizar a autoridade: WMS + localização física configurada por loja para retaguarda; ERP independente para reconciliação administrativa; POS para vendas/procura; MANUAL auditável; IMPORT sem autoridade implícita. A decisão operacional foi confirmada e implementada com fail-closed.


## WMS — fecho de validação técnica (2026-11-25)

- [x] Corrigir a reconciliação para continuar a calcular stock administrativo ERP mesmo quando o campo `availability_status` (específico da semântica física WMS) está UNKNOWN.
- [x] Rejeitar novos snapshots WMS sem localização ou sem estado AVAILABLE/UNAVAILABLE ao nível da API e da base de dados; preservar snapshots legados como UNKNOWN.
- [x] Preservar os guards append-only SQLite durante a migration 0084 e testar a compatibilidade de snapshots históricos.
- [x] Corrigir fixtures de recomendação, tarefas, decisões operacionais e picking para usar WMS configurado quando o cenário depende de stock físico de retaguarda.
- [x] Validar 1679 testes aprovados, 1 ignorado; os quatro workflows estão verdes no SHA acima.
- [ ] Homologar adapter WMS real e confirmar códigos de localização/estados com o fornecedor.


## 2026-11-25 — Proveniência e consistência dos movimentos de inventário (auditoria; implementação pendente)

- [x] Inspeccionar o modelo `InventoryMovement`, o contrato de leitura e o endpoint de reconciliação de tarefas concluídas.
- [x] Confirmar os controlos existentes: actor/motivo, snapshot WMS de origem, snapshot resultante, unicidade por tarefa, disponibilidade, frescura, reservas e dedução de movimentos anteriores.
- [x] Preservar a imutabilidade de `inventory_movements` já aplicada pela migration `0053` (UPDATE/DELETE bloqueados na base de dados).
- [x] Preservar o guard de lineage e conservação de quantidade já aplicado pela migration `0052`.
- [x] Distinguir `inventory_reconciliation_events` (revisão de divergências) e `replenishment_task_events` (ciclo da tarefa) de um futuro ledger de eventos do movimento.
- [x] Documentar que o snapshot MANUAL criado pela reconciliação é uma projecção interna do movimento, não uma confirmação de escrita no WMS.
- [x] Persistir no movimento a identidade congelada da prateleira de destino (destination_shelf_id), sem depender apenas da tarefa associada.
- [x] Expor e persistir a localização física de origem (source_location_code) a partir do snapshot WMS aprovado; o trigger de INSERT exige proveniência não vazia para novos movimentos.
- [ ] Definir unidade base e quantidade Decimal para cada movimento; bloquear conversões implícitas.
- [ ] Criar ledger append-only de eventos do movimento para confirmação WMS, compensações e divergências; reutilizar as protecções de imutabilidade já existentes em `inventory_movements`.
- [ ] Implementar correcções exclusivamente por movimentos compensatórios, mantendo movimentos aprovados imutáveis.
- [ ] Implementar correlação idempotente entre movimento interno e confirmação posterior do WMS.
- [ ] Criar smoke PostgreSQL com duas sessões concorrentes sobre o mesmo snapshot, reservas, rollback e retry.
- [ ] Testar reconciliação de divergências com maker-checker e isolamento multi-loja.



- [x] Adicionar operation_id UUID único por movimento, com backfill individual dos registos históricos na migration 0086.
- [x] Preservar proveniência histórica desconhecida como NULL; não inventar localização nem destino.
- [x] Exigir UUID, localização WMS de origem e prateleira de destino da mesma loja nos novos movimentos, ao nível dos triggers PostgreSQL/SQLite.
- [ ] Confirmar a migration 0086 e os testes API no API CI PostgreSQL 16 e nos restantes workflows.


## 2026-11-25 — Correcção do backfill da migration 0086

- [x] Corrigir o parâmetro SQL em falta no backfill histórico de `destination_shelf_id`, atribuindo explicitamente NULL sem inferir destinos antigos.
- [ ] Reexecutar API CI em PostgreSQL 16 e confirmar a suite completa após a correcção.
- [ ] Confirmar Quality Gates, Security Scans e Docker Compose no novo HEAD.
- [ ] Só depois iniciar o ledger de eventos do ciclo de vida de InventoryMovement.


## 2026-11-25 — Correcção do fixture SQLite da migration 0086

- A nova execução de Quality Gates terminou com 1 falha, 1679 testes aprovados e 1 ignorado. A falha não ocorreu no backfill nem no PostgreSQL: o teste isolado SQLite criava `inventory_movements` sem a coluna `product_id`, embora o modelo real e a tabela de produção a contenham.
- O trigger 0086 consulta `NEW.product_id` para confirmar a coerência entre movimento, tarefa e snapshot. SQLite devolveu `no such column: NEW.product_id` antes de avaliar a rejeição esperada do movimento inválido.
- Corrigido o fixture para reproduzir o esquema real: `product_id` passa a existir e é preenchido nos movimentos históricos e nas inserções de teste. A regra de produção mantém-se inalterada.
- Esta correcção é exclusivamente de teste. A validação PostgreSQL 16 continua pendente na execução API CI; não declarar a migration integralmente validada até a suite completa e os workflows relevantes passarem.


## 2026-11-25 — Ledger append-only de eventos dos movimentos (fase 1)

- [x] Criar `inventory_movement_events` com ligação ao movimento, `operation_id`, loja, actor, motivo, timestamp e evidência.
- [x] Impor coerência de proveniência e bloquear UPDATE/DELETE em PostgreSQL/SQLite.
- [x] Registar `MOVEMENT_RECORDED` na mesma transacção da reconciliação, com rollback integral se a auditoria falhar.
- [x] Expor histórico read-only com RBAC ADMIN/SUPERVISOR e ocultação de IDs cross-store.
- [x] Acrescentar testes API de leitura, autorização, isolamento, atomicidade e migration SQLite.
- [x] Confirmar migration 0087 e suite API: 1684 passed, 1 skipped; API CI run 45610114252 no SHA `5bacdf429de11f97d619c775bcdfaba9b5154154`.
- [x] Confirmar Quality Gates run 45610177910 e Security Scans run 45610177856 no HEAD documental `c5171613262482e8b198aa6f7e18631cfd675b92`.
- [x] Confirmar Docker Compose run 45610114012 no SHA `5bacdf429de11f97d619c775bcdfaba9b5154154`.
- [x] Acrescentar smoke PostgreSQL 16 ao fluxo de movimentos para validar leitura, identidade da operação, evento WMS com actor/motivo próprios, rejeição de operação divergente e append-only.
- [ ] Validar o smoke PostgreSQL de eventos e os quatro workflows no novo SHA.
- [ ] Implementar confirmação WMS correlacionada/idempotente após homologação do adapter.
- [ ] Implementar movimentos compensatórios sem alterar movimentos aprovados.
- [ ] Implementar registo e revisão de divergências associadas ao movimento.

Só `MOVEMENT_RECORDED` é emitido nesta fase. Tipos futuros estão reservados no contrato e não são funcionalidades operacionais concluídas.


## 2026-11-25 — Concorrência da reconciliação de movimentos (smoke integrado; CI pendente)

- [x] Criar `apps/api/scripts/postgres_inventory_movement_concurrency_smoke.py` com duas tarefas concluídas do mesmo SKU/loja.
- [x] Disputar simultaneamente o mesmo snapshot WMS através de pedidos HTTP concorrentes em PostgreSQL.
- [x] Modelar stock on-hand 7 e reservado 1; apenas seis unidades ficam disponíveis.
- [x] Exigir uma única reposição aprovada de quatro unidades e rejeitar a segunda por stock insuficiente.
- [x] Verificar que o snapshot resultante preserva uma unidade reservada e regista três unidades on-hand.
- [x] Verificar unicidade do movimento/evento e retry idempotente da tarefa vencedora.
- [x] Integrar o smoke no workflow API CI.
- [x] Executar e confirmar o smoke no PostgreSQL 16 e os quatro workflows no SHA `dda035f509a34f4d893f52d2d3cf4aa2c440f0e6`.
- [x] Acrescentar cenário PostgreSQL de rollback integral perante falha na inserção do evento de movimento; smoke confirmado no API CI.

A tarefa de concorrência está concluída para o cenário WMS de uma localização configurada. Não define conversões entre unidade base e embalagens.


## 2026-11-25 — Guard de disponibilidade da origem WMS nos movimentos (0088)

- [x] Identificar que o trigger 0086 validava origem WMS/localização/loja/produto, mas não exigia `availability_status=AVAILABLE`.
- [x] Criar migration `0088_inventory_movement_available_source_guard`, substituindo o trigger PostgreSQL/SQLite para rejeitar novas movimentações apoiadas em snapshots UNAVAILABLE, UNKNOWN ou sem estado.
- [x] Preservar os registos históricos e o comportamento do downgrade para o contrato anterior.
- [x] Adicionar teste SQLite para AVAILABLE, UNAVAILABLE, UNKNOWN e downgrade.
- [x] Acrescentar ao smoke PostgreSQL um INSERT directo coerente em tarefa/quantidade/snapshots que só pode ser rejeitado pelo guard de disponibilidade.
- [x] Confirmar migration 0088, smoke PostgreSQL, suite API e workflows verdes (API CI/Docker no SHA de código; Quality Gates/Security no SHA final).

A validação de frescura temporal continua no serviço, com política por loja. A migration reforça a condição física mínima sem inventar um limite de idade nem alterar snapshots históricos.


## 2026-11-25 — Unidade base e precisão exacta dos movimentos (0089)

- [x] Reutilizar `Product.unit` como unidade base já definida pelo catálogo e usada pelos níveis de embalagem.
- [x] Criar migration `0089_inventory_movement_base_unit_snapshot` com `unit_code` imutável por movimento novo.
- [x] Exigir na base de dados que `unit_code` corresponda à unidade actual do produto no momento da inserção.
- [x] Preservar movimentos históricos com `unit_code=NULL`; não inferir retroactivamente a unidade.
- [x] Tipar a quantidade persistida como Decimal e expor `quantity_exact` sem remover o campo numérico legado.
- [x] Incluir unidade e quantidade exacta na evidência do evento `MOVEMENT_RECORDED`.
- [x] Rejeitar na conclusão da tarefa quantidades com mais de três casas decimais, correspondentes à escala `NUMERIC(12,3)`, antes de persistir; manter guard de reconciliação para dados legados.
- [x] Actualizar histórico React para apresentar a unidade do produto e deixar de somar quantidades de unidades incompatíveis.
- [x] Adicionar testes SQLite, API e smoke PostgreSQL para unidade incompatível, origem WMS indisponível e escala decimal.
- [x] Validar migration 0089, testes, PostgreSQL 16, TypeScript/build e workflows verdes (API CI/Docker no SHA de código; Quality Gates/Security no SHA final).

Não são feitas conversões automáticas entre unidade, caixa e palete. Os factores continuam definidos por `ProductPackagingLevel.base_units_per_package`; o movimento regista sempre a unidade base do SKU. Os movimentos anteriores mantêm unidade desconhecida até existir evidência histórica fiável.


## 2026-11-25 — Quantidades Decimal exactas no planeamento UNIT/CASE/PALLET

- [x] Receber `required_base_units` como Decimal no endpoint de planeamento.
- [x] Expor campos textuais exactos para quantidade necessária, factor de embalagem, quantidade solta, quantidade planeada e excesso, mantendo os campos numéricos anteriores.
- [x] Testar quantidades fraccionárias com CASE aberto e fechado.
- [x] Testar UNIT, CASE e PALLET na API, incluindo arredondamento para embalagens fechadas e excesso calculado.
- [x] Confirmar que o endpoint continua a devolver `automatic_stock_movement_allowed=false`.
- [x] Validar suite API, TypeScript/build, PostgreSQL smokes, Docker Compose e Security Scans.


## 2026-11-25 — Quantidades fraccionárias de exposição por unidade base (migration 0090)

- [x] Corrigir o contrato `ShelfProduct`: `target_quantity` e `min_display_quantity` passam a aceitar quantidades decimais.
- [x] Persistir ambos os campos em `NUMERIC(12,3)`, coerente com a unidade base do SKU e com os movimentos de inventário.
- [x] Criar migration 0090 com conversão conservadora dos valores inteiros existentes.
- [x] Proteger downgrade: recusar conversão para INTEGER enquanto existirem quantidades fraccionárias, sem truncar dados.
- [x] Acrescentar teste SQLite da migration e regressão API com produto em kg, alvo 20.125 e mínimo 0.375.
- [x] Rejeitar precisão superior a três casas decimais no contrato da API.
- [x] Preservar a resposta JSON numérica legada; converter para Decimal apenas na fronteira de persistência e no cálculo interno.
- [x] Validar suite API completa, migração PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA `dda035f509a34f4d893f52d2d3cf4aa2c440f0e6`.

Motivo: o teste de embalagem já representava um SKU medido em kg com alvo 20.125, mas o schema/API e a coluna SQL ainda eram INTEGER. Corrigida a inconsistência estrutural; não se deve arredondar quantidades físicas nem tratar kg como contagem inteira.


## Validação final — migration 0090 e contrato de quantidades decimais (25/11/2026)

- [x] API CI [45625120737](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45625120737): sucesso; migrations PostgreSQL 16, 48 smokes PostgreSQL e suite **1697 passed, 1 skipped**.
- [x] Quality Gates [45625120955](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45625120955): sucesso; TypeScript/build Web e suite **1697 passed, 1 skipped**.
- [x] Docker Compose [45625120891](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45625120891): sucesso.
- [x] Security Scans [45625120718](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45625120718): sucesso; auditorias de dependências, secret scan e ZAP passive baseline.
- [x] Migration 0090 validada em PostgreSQL 16 e teste SQLite; downgrade recusa truncar valores fraccionários.
- [x] Resposta HTTP de ShelfProduct mantém números JSON; persistência continua Decimal/Numeric(12,3).
- [x] Plano de reposição para SKU em kg com target 20.125 e mínimo 0.375; conversões UNIT/CASE/PALLET mantêm exactidão Decimal e não movimentam nem reservam stock.

SHA validado: `dda035f509a34f4d893f52d2d3cf4aa2c440f0e6`. O commit seguinte desta secção altera apenas documentação.


## P1 — Precisão e reconciliação do reservado nos snapshots (25/11/2026)

- [x] Confirmar que adapters ERP/WMS já normalizam físico e reservado em Decimal com escala Numeric(12,3).
- [x] Corrigir o endpoint directo de snapshots: rejeitar quantidades com mais de três casas decimais antes da persistência.
- [x] Tipar `InventorySnapshot.on_hand_quantity` e `reserved_quantity` como Decimal e converter os valores HTTP de forma explícita.
- [x] Testar persistência exacta de 10.125 kg físico e 2.375 kg reservado, e rejeição de escala 4 em qualquer dos campos.
- [x] Validar suite API, PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no código do SHA `900c24f19f47e6720da64775d6904692e104c35f` e documentação do SHA `bc37246a298f3cfe2ae142ea9051cb70beac1e22`.
- [ ] Auditar semântica de snapshots consecutivos, reservas agregadas e mudanças de localização; não criar ledger local de reservas sem contrato de detalhe do WMS.

Decisão: `reserved_quantity` continua a ser o total reservado reportado pelo WMS para a localização física configurada. O SMART SHELF AI calcula disponível = físico − reservado; não cria nem altera reservas no WMS. Uma tarefa operacional não é uma reserva de stock.


### Validação CI da precisão dos snapshots (25/11/2026)
- [x] API CI [45626116643](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45626116643): sucesso; PostgreSQL 16, smokes e **1698 passed, 1 skipped**.
- [x] Quality Gates [45626178152](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45626178152): sucesso; TypeScript/build e **1698 passed, 1 skipped**.
- [x] Docker Compose [45626116401](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45626116401): sucesso.
- [x] Security Scans [45626178472](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45626178472): sucesso; dependency audits, secret scan e ZAP passive baseline.


- [ ] Executar CI/PostgreSQL 16 e corrigir eventuais falhas do ledger de contagens manuais (revision 0091) antes de fechar a prioridade.


## 2026-11-25 — Hardening do ledger de contagens manuais (0091)

- [x] Exigir actor autenticado, activo e ADMIN/SUPERVISOR na rota MANUAL; exigir motivo válido.
- [x] Persistir snapshot e evento append-only na mesma transacção, com rollback integral se o evento falhar.
- [x] Reforçar o trigger SQLite para exigir actor activo e papel ADMIN ou SUPERVISOR da mesma loja, alinhando-o com PostgreSQL.
- [x] Acrescentar regressão HTTP para supervisor inactivo.
- [x] Validar migration 0091 e triggers reais em SQLite/PostgreSQL 16; teste de migration SQLite e smoke PostgreSQL 16 executados.
- [x] Confirmar API CI, Quality Gates, Security Scans e Docker Compose no HEAD após esta correcção.


## 2026-11-25 — Validação efectiva da migration 0091 e auditoria MANUAL

- [x] Criar teste de migration SQLite que executa efectivamente `upgrade()`/`downgrade()` da revisão 0091.
- [x] Cobrir trigger de proveniência: supervisor activo da loja e ADMIN global aceites; supervisor de outra loja, supervisor inactivo, EMPLOYEE e snapshot não-MANUAL rejeitados.
- [x] Cobrir UPDATE/DELETE bloqueados no ledger e preservação dos snapshots no downgrade.
- [x] Criar smoke PostgreSQL 16 com pedidos autenticados e INSERTs directos para validar os triggers reais, incluindo append-only.
- [x] Integrar smoke PostgreSQL no API CI.
- [x] Corrigir o smoke de autorização multi-loja que passou a falhar por omitir o motivo obrigatório num pedido MANUAL inválido; manter o teste a alcançar a camada de autorização.
- [ ] Confirmar execução do teste SQLite 0091 na suite API CI do HEAD actual.
- [ ] Confirmar API CI, Quality Gates, Security Scans e Docker Compose no mesmo HEAD; não marcar a prioridade global como concluída antes disso.

Evidência final: migration 0091 validada em SQLite e PostgreSQL 16; API CI no SHA `c4f839b` passou com 1707 testes, 1 skipped; workflows principais posteriormente confirmados na main no SHA de código `76fb62d`, com 1715 passed, 1 skipped, Quality Gates, Security Scans e Docker Compose concluídos com sucesso.


### Validação final — migration 0091 e ledger MANUAL (25/11/2026)

- [x] Teste SQLite executou efectivamente upgrade/downgrade da migration 0091, verificando proveniência, actor activo, papel, isolamento multi-loja, origem MANUAL e append-only.
- [x] PostgreSQL 16 `alembic upgrade head` executado com sucesso.
- [x] Smoke PostgreSQL confirmou SUPERVISOR activo da mesma loja e ADMIN global; rejeitou supervisor inactivo, EMPLOYEE, supervisor de outra loja e snapshot WMS; UPDATE/DELETE rejeitados.
- [x] Suite API: **1707 passed, 1 skipped**.
- [x] API CI [45650155916](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45650155916): sucesso.
- [x] Quality Gates [45650155829](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45650155829): sucesso.
- [x] Security Scans [45650155800](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45650155800): sucesso.
- [x] Docker Compose [45650155946](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45650155946): sucesso.
- [x] Smoke PostgreSQL 16 de proveniência e imutabilidade incluído no workflow API CI.
- [x] Corrigidos fixtures MANUAL legados que não forneciam motivo nem actor, preservando o objectivo dos testes de autorização e precisão Decimal.

SHA de código e workflows validados: `c4f839bcfd076c2b5575eccfd314fae96983b3ed`.

Próxima prioridade P1: auditar snapshots WMS consecutivos, semântica de reservado agregado, monotonicidade temporal e mudanças de localização; não criar ledger de reservas individuais sem contrato real do WMS.


## 2026-11-25 — Proveniência por execução de sincronização (migration 0092)

- [x] Adicionar `inventory_snapshots.source_sync_id` nullable, preservando snapshots históricos, contagens MANUAL e snapshots criados fora do worker sem uma execução de sync.
- [x] Ligar cada snapshot novo criado pelo orchestrator ao `InventorySourceSync` que o originou.
- [x] Impedir associação a execução inexistente, de outra loja, de outra origem ou já terminal.
- [x] PostgreSQL: FK RESTRICT + trigger BEFORE INSERT com lock `FOR SHARE`; SQLite: trigger BEFORE INSERT equivalente, sem rebuild da tabela append-only.
- [x] Expor `source_sync_id` no contrato de leitura `InventorySnapshotRead`.
- [x] Preservar lineage original durante replay: uma linha já persistida por uma execução PARTIAL não é reescrita; novas páginas ficam ligadas à nova execução.
- [x] Teste SQLite da migration 0092 (upgrade/downgrade, correspondência store/source/status, histórico NULL).
- [x] Teste de integração do orchestrator com adapter WMS.
- [x] Smoke PostgreSQL 16: página commitada antes de SIGKILL ligada à execução PARTIAL, replay sem duplicação, segunda página ligada à nova execução SUCCESS e escrita tardia contra execução terminal rejeitada.
- [x] API CI: **1715 passed, 1 skipped** no SHA de branch validado `f63543caabe6df1a2e660f5801c35f53fc3422a1`.
- [x] Quality Gates, Security Scans e Docker Compose: sucesso no mesmo SHA.
- [x] Confirmar novamente os quatro workflows no commit de merge `76fb62dfef9280fd8e6b291024be46a9e392e848` da branch `main`: API CI, Quality Gates, Security Scans e Docker Compose passaram.

Próxima prioridade P1: análise temporal ERP/WMS. Actualmente a comparação pode classificar DIVERGENCE quando ambas as fontes estão dentro da janela de freshness, mesmo com instantes de captura bastante diferentes. Definir um contrato de skew temporal (configuração e estado de comparação) antes de aplicar um limite; não inventar um valor operacional.


### Confirmação final na branch main — 25/11/2026

- HEAD de documentação: `5259f125500c46ff3e89fad1d8842128fc892db3`; código integrado em `76fb62dfef9280fd8e6b291024be46a9e392e848`.
- API CI run `45654043683`: sucesso — **1715 passed, 1 skipped**.
- Quality Gates run `45654278572`: sucesso (API tests/Python compilation e Web TypeScript/build).
- Security Scans run `45654278738`: sucesso (dependências Python/web, secret scan e ZAP passive baseline).
- Docker Compose smoke run `45654043988`: sucesso.
- Os quatro workflows de validação da integração estão confirmados. O check Vercel continua a reportar `build-rate-limit`, que é uma limitação de quota do serviço e não uma falha dos testes/CI GitHub.


### Correcção de estado documental — migration 0091

As duas caixas pendentes da secção de validação 0091 foram fechadas com a evidência posterior. A nota de evidência parcial foi substituída pelo resultado final: SQLite e PostgreSQL 16 validados; API CI 1715 passed/1 skipped na integração final; Quality Gates, Security Scans e Docker Compose verdes na main.


### Regressão adicional da migration 0092 — 25/11/2026

- [x] Confirmar que o trigger SQLite rejeita também `source_sync_id` inexistente, além de loja/origem divergentes e execução terminal.
- [x] API CI no HEAD `f7430342a9e52f9d269dd567c23719790fe638a0`: **1715 passed, 1 skipped**.
- [x] API CI, Quality Gates, Security Scans e Docker Compose no mesmo SHA: sucesso.


## P1 — Comparação temporal ERP/WMS (migration 0093)

- [x] Expor o skew absoluto de captura ERP/WMS em segundos.
- [x] Introduzir tolerância opcional por loja na política ERP, sem valor por defeito (NULL = não configurada).
- [x] Suspender a comparação quantitativa quando a tolerância não está configurada e os timestamps diferem.
- [x] Suspender a comparação quantitativa quando o skew excede a tolerância; zero exige timestamps coincidentes.
- [x] Auditar alterações com actor, valor anterior/novo, motivo e timestamp.
- [x] Rejeitar configuração na política WMS e valores fora de 0–10080 minutos.
- [x] Validar migration SQLite/PostgreSQL 16, testes API, Quality Gates, Security Scans e Docker Compose no SHA `b54b2d4c927aee606f23fef35018b701c17aaf5f`.
- [ ] Homologar tolerâncias por loja com cadência real e documentação do fornecedor ERP/WMS.

Evidência: API CI `45677287479` (**1717 passed, 1 skipped**); Quality Gates `45677287381`; Security Scans `45677287568`; Docker Compose `45677287570` — os quatro workflows concluídos com sucesso no mesmo SHA. A primeira execução revelou uma fixture de ledger que ainda assumia comparação sem tolerância; a fixture foi corrigida para configurar explicitamente a política ERP e a suite voltou a passar.



## P1 — Snapshots WMS consecutivos, mudança de localização e chegada tardia

- [x] Confirmar que a alteração auditada da localização WMS deixa de considerar snapshots da localização anterior, mesmo que sejam mais recentes.
- [x] Confirmar que, após a mudança, a ausência de snapshot na nova localização não faz fallback para a localização antiga.
- [x] Confirmar que um snapshot WMS atrasado, com `captured_at` anterior, permanece no histórico mas não substitui o snapshot mais recente da localização autorizada.
- [x] Confirmar cálculo de disponibilidade com reserva agregada (`on_hand - reserved`) no snapshot seleccionado.
- [x] API CI PostgreSQL 16 e suite completa: **1718 passed, 1 skipped** no SHA `fb1470185126dfe295a15b1f69f635aed05b3da3`.
- [x] Quality Gates, Security Scans e Docker Compose aprovados no mesmo SHA.
- [ ] Prosseguir a auditoria da semântica de reservas agregadas e correlação de movimentos com snapshots WMS sucessivos; não inventar identidade de reservas individuais sem contrato do fornecedor.



## P1 — Semântica das reservas agregadas WMS e movimentos sucessivos

- [x] Confirmar que `reserved_quantity` é subtraída uma única vez do `on_hand_quantity` para obter disponibilidade.
- [x] Confirmar que movimentos anteriores associados ao mesmo snapshot de origem são deduzidos adicionalmente, sem alterar o snapshot WMS imutável.
- [x] Confirmar que dois movimentos sucessivos não consomem a quantidade reservada e deixam o saldo disponível correcto.
- [x] Confirmar preservação da reserva agregada nos snapshots internos de resultado (projecção MANUAL), sem os confundir com confirmação WMS.
- [x] API CI PostgreSQL 16: **1719 passed, 1 skipped** no SHA `043c15f4980b45c4d50d2cd47fb921c5504eccac`; Quality Gates, Security Scans e Docker Compose aprovados no mesmo SHA.
- [ ] Evoluir confirmação externa WMS e correlação de snapshots posteriores apenas com contrato de fornecedor e identidade inequívoca; não inferir confirmação a partir de alteração de quantidade.



## P1 — Proveniência física imutável do destino dos movimentos (migration 0094)

- [x] Persistir `destination_shelf_code` como snapshot do código físico da prateleira no momento do movimento.
- [x] Capturar o destino sob lock e confirmar que a prateleira pertence à loja da tarefa.
- [x] Incluir o código do destino no contrato de leitura e na evidência do evento `MOVEMENT_RECORDED`.
- [x] Backfill histórico a partir da tarefa/prateleira; abortar a migration perante movimentos sem destino consistente.
- [x] Impor no PostgreSQL/SQLite a correspondência tarefa → prateleira → zona/loja e impedir código de destino forjado.
- [x] Validar migration SQLite, API, PostgreSQL 16, smoke de linhagem, concorrência, Quality Gates, Security Scans e Docker Compose.
- [ ] Definir política de retenção/identidade para prateleiras eliminadas ou reestruturadas; preservar o snapshot do destino sem depender do nome actual.

Evidência no SHA `3f4c9740ce70e932c5cb35745e96edd1163bf864`: API CI **1720 passed, 1 skipped**; smoke PostgreSQL de linhagem e concorrência passou; restantes workflows passaram.


## P1 — Identidade física completa e retenção do destino (migration 0095)

- [x] Persistir `destination_zone_id` e `destination_zone_name` juntamente com o ID/código da prateleira.
- [x] Distinguir evidência capturada no movimento (`destination_location_backfilled=false`) de valores históricos reconstruídos pela hierarquia actual na migration (`true`).
- [x] Validar tarefa, prateleira, zona, loja, códigos e nomes nas guardas PostgreSQL/SQLite.
- [x] Preservar os valores históricos quando prateleira e zona são renomeadas.
- [x] Confirmar que a eliminação da prateleira/zona referenciada por um movimento é bloqueada pela cadeia de retenção task → movement.
- [x] API CI PostgreSQL 16, smoke de linhagem/retention, migration SQLite, Quality Gates, Security Scans e Docker Compose.
- [ ] Se existir necessidade de apagar fisicamente entidades de catálogo, desenhar soft-delete/arquivamento explícito e compatível com histórico; não enfraquecer FKs nem apagar movimentos.

Evidência no SHA `48fdf8310d1b17179ba6520d7a559b3bcc822c7f`: API CI **1722 passed, 1 skipped**; smoke PostgreSQL confirmou renomeação e bloqueio de eliminação; restantes workflows passaram. Limitação: a hierarquia histórica anterior à migration não é recuperável quando não existia auditoria de renomeações; os registos antigos ficam marcados como backfill.


## P0/P1 — Retenção de evidência operacional da hierarquia de prateleiras (migrations 0096–0098)

- [x] Migration 0096 impede eliminar prateleiras/zonas com histórico de tarefas.
- [x] Migration 0097 torna os eventos de tarefa append-only, bloqueia a eliminação de tarefas auditadas e congela loja/prateleira/produto depois do primeiro evento.
- [x] Migration 0098 impede cascades sobre observações, alertas, associações SKU-prateleira, planogramas, reconciliações, tarefas, sessões de captura, imagens e inbox de eventos Edge.
- [x] Testes SQLite cobrem cada tabela com referência direta à prateleira e a possibilidade de eliminar apenas quando não existe evidência.
- [x] Smoke PostgreSQL confirma que uma imagem ACTIVE com legal hold, mesmo sem tarefa de reposição, impede eliminar a prateleira e a zona.
- [x] API CI PostgreSQL 16, suite API, Quality Gates, Security Scans e Docker Compose aprovados.
- [x] Histórico de movimentos na Web expõe prateleira/zona de destino e distingue captura contemporânea de backfill histórico.

Evidência no SHA `7bf95468320fc1dd4ab992b520e855d463b6e1f6`: API CI **1725 passed, 1 skipped**; Quality Gates, Security Scans e Docker Compose concluídos com sucesso. A validação PostgreSQL exercitou as guardas de retenção, auditoria e imutabilidade.

- [ ] Se a operação necessitar de ocultar zonas/prateleiras descontinuadas, desenhar arquivamento/soft-delete com autorização, auditoria e preservação de histórico. Não disponibilizar eliminação física como substituto.


## P0 — Concorrência e auditoria das transições de estado das tarefas

- [x] Confirmar bloqueio da linha da tarefa com autorização por loja antes e depois do lock (`SELECT ... FOR UPDATE` em PostgreSQL).
- [x] Cobrir duas atribuições concorrentes: exactamente uma transição e um evento `STATUS_CHANGED`.
- [x] Cobrir concorrência entre `COMPLETED` e `CANCELLED`: exactamente um pedido vence; o outro recebe HTTP 409; o ledger contém apenas a transição terminal vencedora.
- [x] Verificar que a transição terminal preserva quantidade/motivo correctos e que uma tarefa terminal não pode ser reaberta.
- [x] Injectar falha depois do flush do evento e confirmar rollback atómico do estado e da auditoria.
- [x] API CI PostgreSQL 16: **1725 passed, 1 skipped** no SHA `cfeeab3f4e092709de9eccb0dfc54397f72f12af`; Quality Gates, Security Scans e Docker Compose aprovados no mesmo SHA.
- [ ] Manter pendente o arquivamento/soft-delete de prateleiras e zonas até existir requisito operacional; não enfraquecer as guardas de retenção.

A transição usa lock pessimista da tarefa e valida o estado já actualizado após adquirir o lock. A prova concorrente é executada com pedidos HTTP concorrentes em PostgreSQL e não é inferida dos testes SQLite.


## P0 — Autorização explícita do histórico de eventos de tarefas

- [x] Confirmar política de rota `SUPERVISOR_OR_ADMIN` para `GET /api/v1/tasks/{task_id}/events`.
- [x] Reforçar a autorização no handler: EMPLOYEE recebe HTTP 403, incluindo quando consulta tarefa atribuída a si próprio; a auditoria detalhada fica reservada a supervisores e administradores.
- [x] Manter SUPERVISOR limitado à loja e ADMIN com leitura global.
- [x] Testar negação uniforme para tarefa própria, tarefa de colega, tarefa não atribuída e ID inexistente quando o actor é EMPLOYEE.
- [x] API CI `45716057516`, Quality Gates `45716057563`, Security Scans `45716057667` e Docker Compose `45716057580`: todos concluídos com sucesso no SHA `f925b875f871964ce80805c4927af15616f58774`.



## P0 — Defesa em profundidade nas operações de eventos de paletes

- [x] Reforçar no handler de leitura de eventos de palete a autorização `SUPERVISOR_OR_ADMIN` definida na política central.
- [x] Reforçar a mesma autorização no handler de registo de transições/alterações de palete, antes de bloquear ou alterar o registo.
- [x] Testar que EMPLOYEE recebe 403 tanto na leitura como na escrita, sem alteração de estado nem criação de evento.
- [x] Testar que SUPERVISOR consegue ler o histórico e registar uma transição válida.
- [x] API CI `45716912538`, Quality Gates `45716912911`, Security Scans `45716912543` e Docker Compose `45716912421`: sucesso no SHA `50df52e59eca47aa2dfc868fc16621cf2f636586`.


## P0 — RBAC explícito no catálogo de lojas e snapshots de inventário

- [x] Reforçar GET `/api/v1/stores`: apenas ADMIN/SUPERVISOR, coerente com a política central.
- [x] Exigir ADMIN/SUPERVISOR para criar snapshots de qualquer origem (ERP/WMS/POS/MANUAL/IMPORT), não apenas para contagens MANUAL.
- [x] Exigir ADMIN/SUPERVISOR na listagem de snapshots e na consulta do snapshot mais recente.
- [x] Testar que EMPLOYEE recebe 403 nos quatro endpoints e que a tentativa de ingestão não persiste snapshot.
- [x] Corrigir regressão encontrada na primeira execução: o handler de listagem ainda permitia leitura em contexto de teste/direct-call; a guarda foi adicionada e a suite repetida.
- [x] API CI `45718367981`: **1728 passed, 1 skipped**; Quality Gates `45718367943`, Security Scans `45718367972` e Docker Compose `45718367912` — sucesso no SHA `19bf8dd2bf2b6990faff261effc0752523f59a5b`.


## P0/P1 — RBAC explícito na ingestão POS de vendas e tráfego

- [x] Exigir ADMIN/SUPERVISOR nos endpoints de registo horário de vendas e tráfego.
- [x] Exigir ADMIN/SUPERVISOR nos endpoints batch de vendas e tráfego.
- [x] Exigir ADMIN/SUPERVISOR nos imports CSV horário de vendas e tráfego, antes de ler/processar o ficheiro.
- [x] Testar os seis endpoints com actor EMPLOYEE: todos devolvem 403 e não persistem linhas.
- [x] API CI `45719344000`: **1729 passed, 1 skipped**; Quality Gates `45719344142`, Security Scans `45719343998` e Docker Compose `45719344004` — sucesso no SHA `d36af7332544204fc14b6764a3faf99c24aa4741`.


## P0/P1 — RBAC explícito na persistência de evidência OCR e fusão visual/textual

- [x] Exigir ADMIN/SUPERVISOR para criar execuções OCR persistidas.
- [x] Exigir ADMIN/SUPERVISOR para gerar/actualizar correspondências OCR com o catálogo.
- [x] Exigir ADMIN/SUPERVISOR para persistir fusão de evidência visual + OCR.
- [x] Testar actor EMPLOYEE nos três endpoints: todos devolvem 403 antes de bloquear/alterar a captura e nenhuma execução, correspondência ou fusão é persistida.
- [x] API CI `45720266566`: **1730 passed, 1 skipped**; Quality Gates `45720266628`, Security Scans `45720266508` e Docker Compose `45720266578` — sucesso no SHA `a9271dd595c7d913a93cd969cf73d58b5e49438d`.


## P0/P1 — RBAC explícito nas mutações de warehouse e rotação de paletes

- [x] Exigir ADMIN/SUPERVISOR para criar localizações de armazém e colocações de produto.
- [x] Exigir ADMIN/SUPERVISOR para registar paletes físicas.
- [x] Exigir ADMIN/SUPERVISOR para criar/alterar políticas de rotação e executar simulações.
- [x] Testar seis operações com actor EMPLOYEE: todas devolvem 403 antes da leitura/mutação e não criam localizações, colocações, paletes ou políticas.
- [x] API CI `45721215742`: **1731 passed, 1 skipped**; Quality Gates `45721215822`, Security Scans `45721215637` e Docker Compose `45721215724` — sucesso no SHA `3f63efd0da73070cc1654e76ea58ecfe0e79ca93`.



## P0 — Integridade referencial de alertas e reconciliações (migration 0099)

- [x] Criar migration 0099 com preflight fail-closed para alertas e reconciliações históricas; não há backfill nem alteração automática de evidência.
- [x] Validar alertas contra a loja efectiva da prateleira e a associação SKU–prateleira em `shelf_products`.
- [x] Validar reconciliações contra loja/prateleira, associação SKU–prateleira, observação (mesma prateleira e SKU) e cada snapshot opcional (mesma loja e SKU).
- [x] Impedir que alterações posteriores à associação SKU–prateleira, observação ou hierarquia invalidem evidência já retida.
- [x] Implementar variantes PostgreSQL com locks `FOR SHARE` sobre as linhas de origem e SQLite com triggers equivalentes.
- [x] Publicar teste SQLite para associações incompatíveis, snapshots cruzados, preservação sem persistência parcial, alterações a relações de origem e rejeição do preflight.
- [x] Validar upgrade, integridade/concorrência PostgreSQL 16 e gates globais no commit `024b76241b8a116d9930ea448dd6668f434926c2`: API CI `45794895213`, Quality Gates `45794895243`, Security Scans `45794895272` e Demo Docker Compose `45794895899` terminaram com sucesso. O smoke 0099 confirmou lock wait real em `pg_stat_activity` para transferência cross-store da zona e remoção de associação SKU; ambas foram rejeitadas após a transacção de evidência confirmar. Os quatro testes antigos foram alinhados com a política ADMIN_ONLY nos fixtures, sem alterar autorização de produção.
- [x] Validar no API CI `45795924709` o smoke `postgres_shelf_reconciliation_lineage_migration_cycle_smoke.py`: numa base PostgreSQL 16 isolada, upgrade para 0099, downgrade para 0098 com remoção dos seis triggers/cinco funções e reaplicação de 0099 com recriação dos objectos — sucesso. A base partilhada de CI e produção nunca são sujeitas a downgrade.
- [x] Adicionar smoke PostgreSQL dedicado e ligá-lo ao API CI para competir inserção de alerta com transferência de zona e remoção da associação SKU; execução aprovada no API CI `45795924709`.
- [x] Validar concorrência específica de `InventoryReconciliation` contra alteração da observação de origem: API CI `45797706450` confirmou lock wait real em `pg_stat_activity`, rejeição da alteração concorrente e preservação da linhagem; suite completa **1739 passed, 1 skipped**.
- [x] Tornar determinística e específica a observação do bloqueio: capturar os PIDs PostgreSQL do contender e da transacção de evidência; exigir `wait_event_type = 'Lock'` e que o PID esperado esteja em `pg_blocking_pids(pid)`. Validado no commit `9a78d2f185ba2bcdf5ff043097f4895639125a09`: API CI `45812501875`, Quality Gates `45812501507`, Security Scans `45812501427` e Docker Compose `45812501364` passaram; suite API **1740 passed, 1 skipped**.

A migration não altera snapshots, não enfraquece a retenção 0098 e não modifica a semântica das FKs existentes. O downgrade remove apenas as guardas introduzidas em 0099. A validação de dados históricos é deliberadamente bloqueante.



## Edge AI — associação operacional dispositivo-tarefa

- [x] Implementar serviço transaccional para criar associações explícitas dispositivo-tarefa, capturando `task_version` e actor humano.
- [x] Implementar revogação única com motivo obrigatório e evento append-only.
- [x] Aplicar ordem de locks `Store → Task → Device → Assignment` nos fluxos de criação e revogação.
- [x] Expor endpoints ADMIN/SUPERVISOR e registar as rotas na política central.
- [x] Validar validade temporal timezone-aware, loja, estado do dispositivo/tarefa e duplicados activos.
- [x] Acrescentar testes de serviço para criação/revogação, duplicação, actor inválido, datas sem fuso e dispositivo de outra loja.
- [x] Acrescentar smoke PostgreSQL 16 para criação concorrente e revogação concorrente; execução CI ainda pendente.
- [ ] Confirmar API CI, Quality Gates, Security Scans e Docker Compose no SHA final.
- [ ] Adicionar testes HTTP dedicados de autorização ADMIN/SUPERVISOR/EMPLOYEE e isolamento de loja.
- [ ] Não activar `TASK_ACKNOWLEDGED` até a persistência do acknowledgement e a conclusão do inbox estarem na mesma transacção sob fencing.
- [ ] Não retomar auditoria BOLA/IDOR sem instrução explícita.


## Edge worker — fronteira transaccional para handlers (2026-11-27)

- Criada a via explícita `transactional_handlers`: o handler recebe a mesma sessão SQLAlchemy usada para finalizar o processamento.
- A função `complete_edge_event_transactionally` bloqueia a linha de processamento, valida estado, owner, fencing token e expiração, executa operações de base de dados e confirma `PROCESSED` na mesma transacção.
- Qualquer excepção faz rollback dos efeitos do handler e da conclusão. O worker tenta aplicar retry/dead-letter separadamente, sempre sob fencing; se o lease já não for válido, não altera o estado.
- Os handlers legados mantêm-se separados. `TASK_ACKNOWLEDGED` continua desactivado; falta implementar ledger de acknowledgements, validar associação/versão e criar smoke PostgreSQL concorrente.
- Foram adicionados testes para commit conjunto, rollback e worker transaccional. Validados no SHA `5072f05c9ffb5dc2576e5eb8a6e4be7b033263ae`: API CI/PostgreSQL 16 **1755 passed, 1 skipped**; Quality Gates (API e Web), Security Scans (Python, Web, Gitleaks e OWASP ZAP) e Docker Compose — sucesso.
- Correcção de relógio: `complete_edge_event_transactionally` aceita `now` opcional para testes determinísticos; em produção usa UTC real. Os testes injectam o instante posterior ao claim sem falsear a duração do lease.
- Próximo: ledger append-only de acknowledgements, ligação ao evento da inbox, validação de associação activa e `task_version`, idempotência/conflitos de `event_id`, e smoke PostgreSQL 16 dedicado a fencing/concorrência/leases obsoletos. `TASK_ACKNOWLEDGED` permanece desactivado.


## Edge AI — Ledger de acknowledgements (2026-11-27)

- [x] Criar migration 0103 com ledger append-only separado do histórico operacional da tarefa.
- [x] Impor unicidade por inbox e por dispositivo/event_id; ligar por FKs compostas a identidade do evento e da associação versionada.
- [x] Acrescentar serviço transaccional que valida loja, dispositivo activo, associação vigente, timestamps e task_version.
- [x] Garantir que COMPLETED fica como REVIEW_REQUIRED e não altera tarefa nem inventário.
- [ ] Ligar o serviço à fronteira transaccional do worker sem activar TASK_ACKNOWLEDGED até aos testes e smoke PostgreSQL 16.
- [ ] Acrescentar testes de atomicidade/fencing, replay e concorrência; executar CI completa.


### 2026-11-27 — Validação defensiva adicional do Edge ACK

A validação de `action` rejeita agora explicitamente valores que não sejam texto, incluindo listas, objectos, booleanos e números. Foram acrescentados cinco casos parametrizados para garantir `INVALID_ACK_ACTION` sem persistência. A execução dos testes e os workflows CI continuam pendentes; não activar a registry por omissão. A revisão também confirmou que o smoke PostgreSQL existente ainda não cobre concorrência entre revogação e ACK nem isolamento adversarial cross-store — estas provas permanecem em falta.


## 2026-11-27 — Regressão CI do worker Edge ACK identificada e corrigida

- A API CI `45994745435` no commit `09fc570e7032aa66fa6f8c16f4a998f988509bed` executou PostgreSQL 16 e os smokes anteriores com sucesso, mas a suite terminou com `1 failed, 1764 passed, 1 skipped`. A falha foi `test_worker_routes_task_acknowledgement_through_fenced_transaction`: `occurred_at` foi lido da inbox SQLite sem `tzinfo`, levando o serviço a rejeitar um timestamp já normalizado na ingestão.
- Corrigido em `6c4379ecc85bbe4e43d276ac97af01cce5a81520`: o timestamp persistido da inbox é normalizado com `_database_utc`, tal como os timestamps persistidos da associação. O timestamp externo continua sujeito à validação estrita no ponto de ingestão.
- Acrescentados quatro cenários parametrizados de identidade cross-store em `test_edge_task_acknowledgement_service.py` (tarefa estrangeira, dispositivo estrangeiro, loja estrangeira com tarefa local e conjunto de identidades estrangeiras sem associação). Commit dos testes: `a840fac4b12d6f324c29c6a6b0b441a58aba85a5`.
- A API CI/Quality Gates/Security Scans/Docker Compose do commit `a840fac4b12d6f324c29c6a6b0b441a58aba85a5` foi observada em execução; a validação do commit corretivo `6c4379e` ainda tem de ser confirmada. Não declarar suite aprovada.
- A prova PostgreSQL de concorrência entre revogação e processamento ainda não foi acrescentada; manter este ponto explicitamente aberto. A registry permanece opt-in e `COMPLETED` continua apenas `REVIEW_REQUIRED`.


## P0 — Edge ACK vs revogação: concorrência validada (2026-11-27)

- [x] Provar em PostgreSQL 16 o cenário revogação-primeiro: o ACK fica bloqueado por lock PostgreSQL, a revogação confirma e o ACK é rejeitado como `UNASSIGNED_DEVICE`, sem acknowledgement persistido.
- [x] Provar em PostgreSQL 16 o cenário ACK-primeiro: a revogação fica bloqueada, o ACK confirma primeiro e permanece no ledger com timestamp anterior à revogação.
- [x] A prova de bloqueio exige `pg_stat_activity.wait_event_type = 'Lock'` e confirmação do PID bloqueador por `pg_blocking_pids()`; temporizações são apenas polling com timeout.
- [x] Corrigir a preparação do segundo cenário para usar dispositivo independente, respeitando a unicidade histórica de associação dispositivo/tarefa.
- [x] Validar no SHA `cd28865c03abaf4ccde959e098e1dcf462943299`: API CI `45998882415`, incluindo o smoke PostgreSQL 16 de ACK atomicity/concurrency/fencing/immutability; Quality Gates `45998882598`, Security Scans `45998882484` e Docker Compose `45998882648` — todos com sucesso.
- [ ] Manter `TASK_ACKNOWLEDGED` opt-in/desactivado até revisão operacional explícita e decisão separada de activação.

**Limite da prova:** no cenário revogação-primeiro, o smoke constrói manualmente a transacção de revogação com a ordem canónica Store → Task → Device → Assignment; no cenário ACK-primeiro, invoca `revoke_edge_task_assignment`. A evidência demonstra a serialização das duas ordens, mas não deve ser descrita como chamada do serviço real nos dois cenários.


## 2026-11-27 — Correcção crítica do entrypoint Edge Event Worker

- Revisão pós-publicação detectou que `edge_event_worker.py` ainda continha um `main()` antigo a importar o módulo removido `app.edge_event_worker_runtime`, seguido de um bloco `if __name__ == "__main__"` antes da definição do runtime integrado. Ao executar `python -m app.edge_event_worker`, esse bloco era executado primeiro e falhava com importação do módulo inexistente; o entrypoint publicado não arrancava.
- Removido o bloco obsoleto; o único `main()` e o bloco de execução ficam agora depois de `run_worker`, no próprio módulo.
- Acrescentado teste de regressão que executa `python -m app.edge_event_worker --help` num subprocesso e valida as opções CLI.
- Commits publicados na `main`: correcção `0a150b20f9971f6c714acd8949f3422a409b4c39`; teste `986043f946ec053a8f03b1ee7f32b63a7bed3605`.
- **Validação ainda pendente:** pytest/API CI, PostgreSQL 16, concorrência multi-worker, crash/lease/takeover/fencing e Docker Compose. Não afirmar o arranque validado até a CI executar o teste de subprocesso.
- A registry transaccional continua sem injecção automática; `TASK_ACKNOWLEDGED` não foi activado; `COMPLETED` continua `REVIEW_REQUIRED`.
