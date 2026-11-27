## 2026-11-27 — Edge ACK: concorrência validada e fronteira operacional em revisão

### Evidência de validação
O código do Edge ACK foi validado no SHA `cd28865c03abaf4ccde959e098e1dcf462943299`:
- API CI / PostgreSQL 16: `45998882415` — sucesso, incluindo o smoke de atomicidade, concorrência, fencing e imutabilidade.
- Quality Gates: `45998882598` — sucesso.
- Security Scans: `45998882484` — sucesso.
- Docker Compose: `45998882648` — sucesso.

As alterações documentais posteriores foram também verificadas:
- Quality Gates `45999727222` — todos os jobs concluídos com sucesso.
- Security Scans `45999727282` — todos os jobs concluídos com sucesso, incluindo OWASP ZAP passive baseline.

A prova de concorrência cobre ambas as ordens. No cenário revogação-primeiro, o smoke constrói manualmente a transacção com a ordem canónica Store → Task → Device → Assignment; no cenário ACK-primeiro, chama o serviço real `revoke_edge_task_assignment`. A documentação não atribui falsamente o serviço real aos dois cenários.

### Revisão da fronteira operacional
- **Autorização/tenant:** o handler confirma loja, dispositivo ACTIVE, associação vigente e `task_version`; testes de serviço cobrem identidades cross-store. Continua por definir uma matriz de permissões por acção do dispositivo.
- **Opt-in:** a registry transaccional está disponível, mas não é injectada por omissão no worker. Não foi encontrada uma feature flag/configuração de deployment específica para activar o ACK; a registry explícita não deve ser apresentada como feature flag operacional.
- **Observabilidade:** o worker emite logs de sucesso/falha e códigos de erro. Não foram identificadas métricas específicas para ACK, rejeições, retries, dead-letter, lease loss ou latência; não declarar observabilidade operacional completa.
- **Retry/recuperação:** existem leases, heartbeat, fencing, retries limitados com backoff exponencial e DEAD_LETTER. É necessário ensaio end-to-end de crash/takeover e reconciliação dos estados terminais antes do piloto.
- **Auditoria/revisão humana:** o ledger é append-only; `COMPLETED` resulta em `REVIEW_REQUIRED`. Falta formalizar o fluxo de revisão humana, actor, decisão e motivo.
- **Segurança/E2E:** os testes de serviço cobrem cross-store; o smoke PostgreSQL prova concorrência ACK/revogação. Falta a matriz operacional por acção, feature flag fail-closed, métricas e ensaio completo de recuperação/revisão.

### Estado e decisão
`TASK_ACKNOWLEDGED` continua desactivado por omissão. `COMPLETED` não conclui a tarefa nem altera inventário. A validação CI não equivale a autorização para produção. Próximo marco: fechar os gaps operacionais acima e obter aprovação explícita antes de qualquer activação.

---

## 2026-11-26 — Edge AI: estado real da ingestão e acknowledgements de tarefas

A ingestão Edge não está apenas em contrato: o repositório já contém provisionamento controlado de dispositivos, credenciais revogáveis armazenadas como digest, autenticação HMAC com nonce/timestamp, endpoint de ingestão, inbox imutável, cursor sequencial transaccional e worker com lease/fencing/retry/dead-letter. O ACK HTTP confirma aceitação durável na inbox, não execução de domínio.

O worker mantém `DEVICE_HEARTBEAT` como único handler built-in. `SHELF_CAPTURED`, `SHELF_OBSERVATION` e `TASK_ACKNOWLEDGED` não devem produzir efeitos operacionais enquanto não existirem handlers e contratos específicos. Foi criado [edge-task-acknowledgement-contract.md](architecture/edge-task-acknowledgement-contract.md), que exige associação explícita dispositivo-tarefa, versão, idempotência, fencing e revisão humana; uma declaração Edge de conclusão não conclui a tarefa nem movimenta stock.

O schema da associação já foi criado na migration 0102: ligação à mesma loja por FKs compostas, validade temporal, revogação única, actor, ledger append-only e `task_version` gerida pela base de dados. A migration PostgreSQL 16 e a suite API passaram: API CI `45876761643` (**1747 passed, 1 skipped**), Quality Gates `45876761651`, Security Scans `45876761497` e Docker Compose `45876761707`, todos no SHA `6ae449d883c845072127f188861be44e57dd2193`. Falta o serviço/API ADMIN/SUPERVISOR, a prova de concorrência PostgreSQL e a integração atómica do handler. A implementação do handler exige primeiro resolver a fronteira actual do worker, que executa o handler e confirma o inbox em transacções separadas. A auditoria BOLA/IDOR fica fora do âmbito desta fase por indicação do utilizador.

## 2026-11-26 — Ledger de reconciliações: serialização em lote e contexto histórico do actor

A listagem do ledger passou a executar três consultas SQL para uma página não vazia, independentemente do número de reconciliações: registos paginados, utilizadores criadores/revisores e eventos associados. Os eventos são agrupados por reconciliation_id e ordenados por created_at/id, preservando a paginação e o contrato da API. Novos eventos guardam o snapshot mínimo de contexto do actor (user_id, role, store_id e full_name). Sem backfill retroactivo. Testes e workflows aguardam validação no SHA final.

---

## 2026-11-26 — Histórico de retenção de imagens tenant-atomic

O GET /api/v1/shelf-images/{image_id}/retention/events deixou de consultar eventos e imagem em duas fases. A imagem e a sua loja são agora verificadas na mesma instrução SQL que junta por OUTER JOIN uma subquery de eventos paginada. Histórico vazio e páginas posteriores ao último evento permanecem válidos; IDs estrangeiros/inexistentes mantêm 404. Regressão adicionada. Commits `8c9eb1aa` e `6ee7d565`. CI pendente.

## 2026-11-26 — Leituras atómicas de histórico de movimentos e alertas

Os endpoints de histórico de movimentos e alertas foram consolidados numa query pai + OUTER JOIN a eventos. O tenant é aplicado na mesma instrução; um pai autorizado sem eventos permanece distinguível de um ID estrangeiro/inexistente sem uma segunda query. Regressão de movimentos cobre same-store e cross-store; a cobertura existente de alertas mantém-se. Commits `cb9cb3fe` e `d0782203`. CI pendente.

## 2026-11-26 — Isolamento do histórico de mapeamentos ERP/WMS

Foi eliminada a separação entre o preflight do mapping e a leitura dos eventos em GET /api/v1/stores/{store_id}/inventory/external-mappings/{mapping_id}/events. A query usa o mapping como tabela-pai, OUTER JOIN aos eventos e filtra simultaneamente por mapping_id e store_id, preservando histórico vazio e ocultando IDs estrangeiros/inexistentes. Regressão API acrescentada; commits 3a95f8a1 e 41bfe0a6. Validação CI pendente.

## 2026-11-26 — Validação da migration 0101 e dos smokes PostgreSQL

No SHA 3bc6963176d7c142b223dbca82537691542a6aff, API CI/PostgreSQL 16, Docker Compose, Quality Gates e Security Scans concluíram com sucesso. A API CI aplicou 0101_inventory_sync_job_store_immutable, executou o smoke concorrente dos sync jobs e o smoke de capture-session, e terminou a suite API sem falhas.

## 2026-11-26 — Imutabilidade do tenant nos jobs ERP/WMS

`InventorySyncJob.store_id` é definido no enqueue e não é alterado pelos handlers nem pelo worker. Como os eventos são ligados ao job por `job_id`, a loja do job é a fronteira de visibilidade do histórico e integra também a chave idempotente. Foi criada a migration `0101_inventory_sync_job_store_immutable`, com triggers PostgreSQL/SQLite que rejeitam alterações reais de `store_id`, preservando actualizações de lifecycle, lease e fencing. Foram adicionados teste SQLite da migration e smoke PostgreSQL concorrente que verifica espera por row lock, rejeição da reassociação e manutenção da loja original. Commits de implementação/testes: `50988b43`, `999fa077`, `319d6f67`, `fba79f53`. A execução de CI e validação PostgreSQL 16 no HEAD final permanecem pendentes.

## 2026-11-26 — Correcção do smoke de serialização da propriedade da prateleira

A API CI identificou uma expectativa incorrecta no smoke PostgreSQL: depois de provar que o UPDATE concorrente de `zones.store_id` aguardava pelo lock da escrita da prateleira, o teste esperava que a transferência fosse concluída. A base de dados rejeita-a correctamente porque a sessão de captura acabada de persistir é evidência operacional retida. O smoke foi corrigido para exigir o bloqueio, a rejeição por `IntegrityError` com a razão esperada e a permanência da sessão/zona na loja original. A alteração está publicada no commit `5f7867bb67c2d2334d8afe85da7c8838ba87db5b`; a validação CI no novo HEAD permanece pendente.

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


## 2026-11-25 — Autoridade WMS por localização: validada

**SHA:** `c8efb82b64d4aed9fcc81fdb4a0571695fdd23cf`.

A autoridade do stock físico de retaguarda está formalizada e implementada por loja/localização. O WMS só é elegível quando a localização exacta está configurada e o snapshot mais recente dessa localização indica AVAILABLE. UNAVAILABLE/UNKNOWN bloqueia snapshots disponíveis anteriores. Reservas são descontadas; ERP nunca é fallback. ERP mantém-se como fonte administrativa independente para reconciliação.

Novos snapshots WMS exigem localização e disponibilidade explícitas ao nível da API e da base de dados (triggers PostgreSQL/SQLite). Os dados legados são preservados como UNKNOWN. A migration SQLite foi testada sem remover os guards append-only existentes. A reconciliação mantém quantidades ERP administrativas mesmo com disponibilidade WMS desconhecida.

**Evidência:** API CI `45574197186` — 1679 testes aprovados, 1 ignorado e 47 smokes PostgreSQL concluídos; Quality Gates `45574197259` — sucesso; Security Scans `45574197237` — sucesso; Docker Compose `45574197037` — sucesso.

**Ainda não homologado:** adapter WMS real, códigos/estados e mapeamento de unidades do fornecedor, factores logísticos externos e reservas multi-localização. A conversão interna por SKU entre unidade base, caixa e palete está implementada; não prova que os códigos/factores do fornecedor estejam correctos. O sucesso da CI não prova conectividade externa.

---

## 2026-11-25 — Autoridade WMS de stock físico por loja/localização

**Contrato aprovado:** WMS é a fonte de referência do stock físico da retaguarda. ERP permanece independente para reconciliação administrativa. POS é fonte de vendas/procura. MANUAL e IMPORT não são autoridades de stock físico por omissão.

**Implementado na main (validação CI pendente no HEAD final):**
- Snapshots passam a transportar localização WMS e estado de disponibilidade (AVAILABLE/UNAVAILABLE/UNKNOWN).
- A política de frescura WMS por loja pode declarar a localização exacta da retaguarda; configuração ausente significa stock físico desconhecido.
- Alterações da localização exigem motivo e criam evento append-only com actor e valores anterior/novo.
- Lotes WMS exigem localização e disponibilidade explícitas; replay idempotente compara também estes campos.
- Reconciliação e recomendações usam apenas o snapshot WMS mais recente da localização configurada. Um estado mais recente UNAVAILABLE/UNKNOWN bloqueia snapshots disponíveis antigos.
- Reservas são subtraídas ao stock físico. ERP não é fallback.
- Movimentos de reposição exigem WMS e localização configurada, preservando actor, motivo e snapshots de origem/resultante.

**Migrações:** `0084_wms_backroom_location_authority` e `0085_inventory_backroom_policy_audit`.

**Validação pendente:** migrations em SQLite/PostgreSQL 16, testes API, Quality Gates, Security Scans e Docker Compose no SHA final.

**Próximas lacunas:** homologar adapter WMS real; validar os códigos de localização com o fornecedor; normalizar unidade/caixa/palete; modelar reservas e disponibilidade em múltiplas localizações sem somar domínios incompatíveis.

**Limite de produto:** o contrato e os testes não demonstram conectividade real com ERP/WMS. Não apresentar o histórico de sincronização como integração homologada.

---

## 2026-11-24 — Contrato técnico para adapters ERP/WMS

- Protocolo assíncrono e read-only para fornecedores ERP/WMS.
- DTO normalizado com SKU, ID externo, quantidades decimais, referência idempotente e timestamp timezone-aware.
- Validação de limites compatíveis com o schema de snapshots e rejeição de duplicados dentro do lote.
- Loader de factories confiáveis, sem adapter de fallback ou mock apresentado como integração.
- Próxima etapa: orquestrador/worker com identidade de serviço, gestão de segredos, timeouts, paginação, retries limitados, idempotência persistente e homologação de conectores reais.
- Estado: contrato e testes publicados; sem conectividade externa ou escrita de snapshots nesta fase.

## 2026-11-24 — Observabilidade de sincronizações ERP/WMS

- Ledger persistente de tentativas ERP/WMS com lifecycle STARTED/SUCCESS/PARTIAL/FAILED, contagens, duração, erros e referência externa.
- Eventos de auditoria append-only; a base de dados permite apenas uma transição STARTED → terminal e bloqueia eliminações.
- Histórico e health endpoints por loja, com alertas calculados para fontes sem sucesso registado ou além da janela de frescura.
- UI React para estado das fontes e histórico recente.
- Limite: não existe ainda conectividade ERP/WMS real, scheduler, retries nem notificações. Adapters dependem de contratos, credenciais e homologação.

## 2026-11-24 — Integridade semântica da reconciliação de inventário

- Acrescentada regressão para produto associado a prateleira sem observação nem snapshot de retaguarda.
- A API deve preservar `NO_OBSERVATION` e valores quantitativos `null`; ausência de evidência nunca é convertida em stock zero nem numa divergência contabilística.
- O teste verifica que a consulta não cria movimentos ou snapshots.
- Commit de teste: `3f5c0b012fd4104edc1cf55c24d308668a99a1d1`. CI ainda pendente.

## 2026-11-23 — Visibilidade operacional do ledger de inventário

- O produto passa a expor o histórico read-only de movimentos de inventário reconciliados, filtrável por loja, produto e tarefa.
- A consulta mantém o princípio de aprovação humana e registos imutáveis; não cria movimentos nem altera snapshots.
- Acesso limitado a ADMIN/SUPERVISOR com validação de âmbito da loja. Testes de filtros, autorização e ausência de mutação adicionados; CI pendente.

## 2026-11-23 — Dashboard operacional: métricas accionáveis

- O resumo operacional inclui distribuição de tarefas por prioridade, tarefas urgentes activas, tarefas activas sem atribuição e taxa de conclusão.
- A métrica de prateleiras com necessidade de atenção passou a contar IDs de prateleira distintos, não o número de observações. `attention_observations` mantém a contagem de evidências.
- O cálculo respeita a visibilidade por papel e loja; EMPLOYEE só agrega tarefas atribuídas ao próprio utilizador.
- Testes unitários dedicados cobrem os três papéis e dados duplicados. CI do novo HEAD pendente.

## 2026-11-23 — Paridade de respostas BOLA em deteções e exemplares

- Reforçado o smoke PostgreSQL pré-lock para comparar corpo JSON e status entre IDs estrangeiros reais e IDs inexistentes em três operações direct-ID: revisão de deteção, histórico de revisão e revisão de exemplar.
- Os pedidos são executados enquanto locks PostgreSQL reais da imagem e do produto permanecem retidos; o smoke exige HTTP 404 equivalente e ausência de mutações.
- Commit `1cdc4f67` publicado. API CI/PostgreSQL 16 e restantes workflows ainda pendentes.

## 2026-11-23 — Validação de isolamento de IDs em planogramas e Warehouse

- O contrato de ocultação de prateleiras em planogramas foi alinhado nos testes HTTP e no smoke PostgreSQL: IDs estrangeiros e inexistentes devolvem HTTP 404 equivalente.
- O smoke Warehouse passou a validar IDs directos de paletes e políticas de rotação, incluindo leitura/escrita, comparação com IDs inexistentes, ausência de mutações estrangeiras e controlo positivo same-store.
- API CI [45268275419](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275419): PostgreSQL 16, migrations e smokes aprovados; **1599 passed, 1 skipped**.
- Quality Gates [45268275423](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275423): **1599 passed, 1 skipped**, compilação Python e build Web.
- Security Scans [45268275427](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275427) e Docker Compose [45268275477](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45268275477) passaram.
- Limite: a matriz BOLA/IDOR global permanece aberta; esta ronda não demonstra cobertura de todos os endpoints e relações indirectas.

## 2026-11-23 — Segurança de planogramas: ocultação de IDs cross-store

- Implementado: a resolução da prateleira aplica o tenant na query para SUPERVISOR; ADMIN mantém visibilidade global.
- Contrato: IDs estrangeiros/inexistentes devolvem HTTP 404 `Shelf not found`.
- Teste: regressão em `apps/api/tests/test_capture_sessions.py`.
- Estado: código e teste publicados; execução de CI e smoke PostgreSQL no HEAD final pendentes.


## Segurança P0 — histórico de eventos de paletes sem oráculo BOLA (2026-11-23; CI pendente)

O endpoint GET /api/v1/warehouse/pallets/{pallet_id}/events resolve primeiro a palete com id e store_id, só depois consulta os eventos. O smoke PostgreSQL multi-loja foi reforçado para comparar uma palete estrangeira real com um ID inexistente, exigindo HTTP 404 e corpo idêntico. O controlo positivo same-store continua a exigir HTTP 200. Falta validar o novo smoke no API CI/PostgreSQL 16 e nos restantes workflows.

## Segurança P0 — histórico de alertas com predicado SQL multi-tenant (2026-11-23; CI pendente)

A rota `GET /api/v1/observation-alerts/{alert_id}/events` filtra `alert_id` e `store_id` na mesma query para SUPERVISOR, evitando carregar alertas estrangeiros antes de aplicar a autorização. ADMIN conserva visibilidade global e EMPLOYEE continua proibido. Regressão HTTP compara alerta estrangeiro com ID inexistente (404 e corpo idêntico). CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose pendentes.

## Segurança P0 — ocultação de IDs directos de deteções em observação e histórico (2026-11-23; validação pendente)

A criação de observações a partir de deteções e a consulta do histórico de revisões por `detection_id` passam a usar ocultação cross-store (`hide_foreign=True`), devolvendo HTTP 404 idêntico ao ID inexistente. A autorização é verificada antes do lock da imagem e novamente depois do lock. Testes autenticados cobrem os dois endpoints e o caminho same-store. API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose pendentes.

## Segurança P0 — IDs de prateleira em criação e consenso (2026-11-23; validação pendente)

As rotas de criação de observações/sessões e a consulta de consenso autenticam o actor antes de resolver shelf_id. Para SUPERVISOR, IDs estrangeiros e inexistentes devolvem HTTP 404 equivalente; a avaliação de alertas herda o mesmo bloqueio antes de persistir. Regressões verificam ausência de novos registos. Commits: 9288459, cce1afd (código); d5d6243 (testes). CI/PostgreSQL 16 pendente.

## Segurança P0 — IDs de consenso de prateleira (2026-11-23; validação pendente)

O endpoint read-only de consenso por shelf_id oculta agora a existência de prateleiras estrangeiras com HTTP 404, igual ao caso inexistente. A avaliação/persistência de alertas usa o mesmo contrato, sem criar alertas para pedidos negados. Foram acrescentadas regressões HTTP para ambos os caminhos. Commits: 2f4470e (código), 5feffba (teste). CI/PostgreSQL 16 pendente.

## Segurança P0 — IDs de sessões de captura e alertas (2026-11-23; validação pendente)

As operações directas por ID de sessão de captura e alerta foram alinhadas com a política de ocultação cross-store: escrita com autorização pré-lock e revalidação pós-lock; leitura de eventos sem lock mas com verificação de tenant antes da consulta dos eventos. IDs estrangeiros e inexistentes devolvem HTTP 404 equivalente. Regressões verificam ausência de efeitos persistidos. Commits: b627107 (código), 1a2e776 (testes reforçados). API CI/PostgreSQL 16 ainda não confirmado.

## Segurança P0 — IDs de localizações de armazém (2026-11-23; CI pendente)

A criação de colocações valida agora a localização através do helper multi-tenant com autorização antes do lock e revalidação depois do lock. IDs estrangeiros e inexistentes produzem o mesmo HTTP 404. Foi adicionada regressão HTTP autenticada e verificação de não persistência. Commits: a77c679 (código) e 68e907f (teste). A validação CI/PostgreSQL 16 ainda está pendente; a matriz de IDs de prateleira e relações indirectas permanece aberta.

## Segurança P0 — IDs directos de deteção e exemplar: autorização antes de locks (2026-11-23; CI pendente)

- A revisão humana de deteções, o histórico por detection_id e a revisão de exemplares foram auditados quanto à ordem imagem → produto → exemplar e à validação de tenant antes dos locks.
- Criado smoke PostgreSQL 16 com supervisor de outra loja, IDs reais estrangeiros e locks simultâneos sobre imagem e produto; as três operações têm de responder HTTP 403 sem esperar.
- O smoke confirma também ausência de persistência de revisão e manutenção do exemplar em PENDING.
- Novo passo API CI: `Verify PostgreSQL direct-ID detection and exemplar tenant pre-lock authorization`.
- API CI [45194763822](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45194763822) passou no SHA `fefb56f`, com o smoke PostgreSQL 16 e **1588 passed, 1 skipped**. Quality Gates [45194764768](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45194764768), Security Scans [45194765202](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45194765202) e Docker Compose [45194764844](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45194764844) também passaram.
- A matriz global de endpoints/papéis/tenants, relações indirectas e volume persistente continuam pendentes.

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

## 2026-11-23 — Matriz PostgreSQL de leituras cross-store (código publicado; CI pendente)

- O smoke de autorização de inventário passou a testar 23 rotas GET com `store_id` explícito, cobrindo vendas, tráfego, forecasting, reposição, decisões e warehouse.
- Um SUPERVISOR da loja A tenta consultar a loja B; cada resposta esperada é HTTP 403 antes da leitura dos registos. As negações de escrita e verificações de não persistência existentes foram preservadas.
- Commit: `40f9456a`.
- API CI [45131503709](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503709), Docker Compose [45131503757](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503757), Quality Gates [45131503760](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503760) e Security Scans [45131503689](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503689) estão em execução/pendentes. Não marcar ainda como validado.
- A cobertura ainda não constitui a matriz completa endpoint × perfil × loja; permanecem IDs aninhados, fluxos indirectos, testes positivos same-store e volume persistente.

---

## 2026-11-23 — Nove rotas HTTP cobertas pelo smoke PostgreSQL pré-lock

- Expandido `postgres_retention_legal_hold_concurrency_smoke.py`: supervisor externo tenta aceder a nove rotas (conteúdo, deteções, evidence fusion, OCR evidence/matches/runs, eventos de retenção, retry e restrict) enquanto outra transacção mantém a linha da imagem bloqueada.
- As nove rotas responderam HTTP 403 antes da libertação do lock; o passo PostgreSQL passou no API CI [45130818413](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818413), SHA `d319d1a4`.
- Docker Compose [45130818319](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818319), Quality Gates [45130818392](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818392) e Security Scans [45130818374](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818374) passaram.
- API CI concluiu com sucesso: **1555 passed, 1 skipped** no [run 45130818413](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818413).
- Os endpoints ADMIN-only de artefactos, legal hold e purge seguem a política de administrador global. A próxima cobertura de autorização multi-loja deve focar os restantes handlers que permitem SUPERVISOR, em especial operações de escrita/revisão.

---

## 2026-11-23 — Validação CI da autorização PostgreSQL pré-lock

- Smoke PostgreSQL de retenção e autorização multi-loja passou no API CI [45129975394](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975394), SHA de código `926abcf1`. A chamada de supervisor de outra loja foi rejeitada com HTTP 403 enquanto a linha da imagem permanecia bloqueada.
- Docker Compose [45129975482](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975482) passou.
- A falha anterior do Compose smoke por falta de `MIGRATION_DB_USER` foi corrigida em `b4995042`; regressão estática em `edf879a2`. O workflow Compose voltou a passar no SHA `926abcf1`.
- Quality Gates [45130013285](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013285) passou: suite API, compilação Python e build Web.
- API CI [45129975394](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975394) concluiu com sucesso no SHA de código `926abcf1`, incluindo migrações PostgreSQL 16, todos os smokes e **1555 passed, 1 skipped**.
- Quality Gates [45130013285](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013285), Security Scans [45130013260](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013260) e Docker Compose [45129975482](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975482) também passaram.
- A prova cobre o helper pré-lock através de um handler representativo; a cobertura HTTP/PG dos restantes handlers e o ensaio de volume persistente permanecem em aberto.

---

## 2026-11-23 — Prova PostgreSQL de autorização pré-lock entre lojas (CI validada; cobertura adicional pendente)

- O smoke de retenção usa duas lojas e um supervisor da loja externa à imagem.
- A linha da imagem fica bloqueada numa sessão PostgreSQL; o pedido externo de restrição tem de responder HTTP 403 antes da libertação do lock. Isto verifica o comportamento em PostgreSQL real e não apenas a ordem estática do código.
- Os ensaios concorrentes de legal hold/purge e restore/purge continuam incluídos.
- O smoke é executado pelo passo já existente no API CI.
- Commits: `25a34b8f`, `926abcf1`.
- Validação confirmada: API CI [45129975394](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975394) passou (1555 passed, 1 skipped), Docker Compose [45129975482](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975482), Quality Gates [45130013285](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013285) e Security Scans [45130013260](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013260) passaram. A cobertura dos restantes endpoints multi-loja de retenção/artefactos continua pendente.

---

## 2026-11-23 — Autorização de tenant antes de locks em retenção e artefactos (código publicado; CI em execução)

- A auditoria da ordem de locks encontrou dez handlers que adquiriam `FOR UPDATE` na imagem antes de validar a loja. Embora alguns validassem o tenant mais tarde, um pedido sem autorização podia adquirir locks de recursos de outra loja antes da rejeição.
- Corrigidos os cinco fluxos de retenção (restauro, legal hold apply/release e agendamento/cancelamento de purga), a consulta de elegibilidade de purga e quatro fluxos de artefactos externos (registo, snapshot de inventário, diagnóstico de acesso e evento de disposição).
- Os nove handlers que operam sobre a imagem usam agora `_lock_authorized_shelf_image`, que verifica a loja antes do lock e volta a verificar a linhagem depois. A elegibilidade mantém o erro específico de linhagem inválida e faz o preflight antes do lock.
- `test_security.py` passou a exigir a ordem autorização → lock nos dez handlers. Uma verificação estática adicional no código publicado confirmou os dez casos. Um teste unitário também confirma que um supervisor de outra loja é rejeitado antes de qualquer query de lock.
- Corrigida também a duplicação de duas tarefas pendentes em `TODO.md`.
- Commits de código/testes: `f6e2156e`, `659586be`, `7f372fbc`, `cbc6a1a6`, `70b1b351`; TODO: `fcb685bf`.
- CI actual no SHA de código/testes `70b1b351`: API CI [45127205680](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45127205680), Quality Gates [45127205615](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45127205615), Security Scans [45127205627](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45127205627) e Docker Compose [45127205559](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45127205559) foram iniciados; resultados ainda não confirmados.
- Validação anterior da correcção PostgreSQL default ACL: API CI/PostgreSQL 16 run [45084795278](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45084795278) passou; Quality Gates [45084849142](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45084849142) e Security Scans [45084849107](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45084849107) passaram no SHA documental `00d6ef51`.
- **Ainda em aberto:** testes de integração PostgreSQL com duas lojas para estes dez fluxos, ensaio de volume persistente e operações reais API com principal runtime. A auditoria estática não substitui estes ensaios.

---
### Segurança P0 — precisão do smoke de default ACLs (2026-11-22; correcção publicada, CI pendente)

- O smoke filtra agora `pg_default_acl.defaclrole` pelo principal de migrations configurado em `MIGRATION_DB_USER`; já não agrega ACLs de owners diferentes.
- O grantee continua a ser o principal runtime autenticado, com verificação de privilégios esperados e rejeição de GRANT OPTION.
- API CI PostgreSQL 16 fornece `MIGRATION_DB_USER=postgres`; regressão estática acrescentada.
- Commits: `bb3766fc`, `491ae99f`, `8e5a6810`.
- A API CI [45083455380](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083455380), Docker Compose [45083455389](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083455389), Quality Gates [45083489901](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083489901) e Security Scans [45083489889](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083489889) passaram em SHAs anteriores à correcção. A reexecução no novo SHA está pendente.

---

### Segurança P0 — smoke do principal PostgreSQL runtime (2026-11-22; código publicado, validação pendente)

- O smoke agora valida LOGIN/NOINHERIT e todos os atributos de privilégio do papel, ausência de memberships e ownership via `pg_shdepend`.
- Verifica CONNECT, USAGE sem CREATE, DML nas tabelas operacionais e ACLs por defeito para futuras tabelas/sequências, sem grant option.
- Mantém validação negativa de escrita nas tabelas de confiança ONNX e da sequência associada.
- Teste estático actualizado em `apps/api/tests/test_database_role_separation.py`.
- Commits `2d7bce2f`, `afda3ee6`, `ee609372`, `72d4034d`.
- **Não marcar como validado:** API CI, PostgreSQL 16 smoke, Quality Gates e ensaio de volume persistente aguardam execução/confirmação.

---

### Computer Vision — avaliador COCO v1 (implementação publicada; CI validada; dataset real pendente)

- Avaliador AP101/mAP50/mAP50_95 e operating point precision/recall/F1, por classe e global.
- Runner executa apenas test split de release aprovado para inferência, valida hashes das anotações, manifest e imagens contra o release fingerprint e usa provider ONNX assinado.
- O pipeline de release liga os hashes dos três splits à aprovação e detecta alterações durante o gate.
- Não treina nem escreve em inventário; não foram produzidas métricas reais.
- [Protocolo de avaliação](vision-model-evaluation.md).

### Edge AI — contrato de eventos v1 (implementação de domínio publicada; CI validada em 2026-11-22)

- Envelope versionado e payloads específicos para heartbeat, captura, observação visual e confirmação de tarefa.
- Fingerprint canónico, chave de idempotência por dispositivo e classificação de sequência NEXT/GAP/STALE.
- Contrato não autentica dispositivos nem persiste/acknowledges eventos; inbox/outbox duráveis, credenciais e ingestão multi-loja são fase seguinte.
- API CI/Quality Gates no código `91ea51e0`: 1545 passed, 1 skipped. A validação do contrato não equivale a ingestão persistente.
- [Especificação do protocolo Edge](edge-device-event-contract.md).

### Computer Vision — manifesto ONNX Ed25519 v2 e confiança persistente (implementação publicada; CI validada em 2026-11-22)

- Payload Ed25519 schema v2 assina `model_id`, `release_version`, `key_id` e SHA-256 do detector/embedder; schema v1 é rejeitado no provider real.
- Migration `0069_vision_model_release_trust_state`: high-water mark por deployment, eventos append-only, monotonicidade e protecção contra remoção/alteração do estado.
- Registo transaccional serializa releases concorrentes, aceita retries exactos e rejeita rollback, colisão de versão e mudança de identidade.
- Provider verifica a versão antes/depois da inferência; worker bloqueia o release actual durante a publicação e termina se ficar obsoleto.
- Rotação/revogação configurável por keyring e `VISION_MODEL_REVOKED_KEY_IDS_JSON`; procedimento em [docs/vision-model-manifest.md](vision-model-manifest.md).
- Testes: `test_vision_model_manifest.py`, `test_vision_model_release.py`, `test_vision_model_release_migration.py` e smoke PostgreSQL `postgres_vision_model_release_smoke.py`, integrado no API CI.
- API CI [45065013302](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065013302) e Docker Compose [45065013291](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065013291) passaram no commit de código `91ea51e0`; Quality Gates [45065079666](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065079666) e Security Scans [45065079730](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065079730) passaram no descendente documental `1566b8ea`; 1545 testes aprovados, 1 ignorado. Smoke PostgreSQL confirmou concorrência, rollback, imutabilidade e bloqueio de TRUNCATE.

### Deploy — digests e política de confiança ONNX nos serviços Docker Compose (2026-11-22, CI validada)

- `api` e `vision-worker` recebem agora `VISION_DETECTOR_MODEL_SHA256` e `VISION_EMBEDDING_MODEL_SHA256` do ambiente do deployment.
- Os valores não são inventados nem preenchidos por defeito: ficam vazios quando não configurados e o provider ONNX real continua a rejeitar a configuração incompleta.
- Foi acrescentado teste de contrato para os dois serviços e as duas variáveis.
- Implementação: commits `2d810e8a`, `263de3e8`; teste e registo de progresso: commits subsequentes na branch `main`.
- O encaminhamento de digests é uma segunda confirmação ao manifesto Ed25519 v2; não substitui a aprovação de pesos nem a avaliação do detector.
- Docker Compose smoke [45065013291](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065013291) passou no commit de código `91ea51e0`; `VISION_MODEL_DEPLOYMENT_ID` fica vazio por omissão e é obrigatório/não-default em produção.

### IA e catálogo — integridade dos exemplares de embeddings (2026-11-21, validado)

- ProductExemplar exige agora ID inteiro positivo, versão de modelo e proveniência textual não vazia e SHA-256 hexadecimal com 64 caracteres.
- Testes paramétricos cobrem IDs booleanos/floats/strings, valores nulos/vazios e digests inválidos.
- API CI [44902878547](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878547), Quality Gates [44902878553](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878553), Docker Compose [44902878594](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878594) e Security Scans [44902878703](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878703) passaram; **1461 testes aprovados, 1 ignorado**.
- Limite: integridade de metadados não demonstra precisão de matching; continua necessária avaliação independente por SKU, loja e cenário.

### Gitleaks — scan do histórico Git completo (2026-11-21, validado)

- O workflow agora executa Gitleaks sobre todos os commits alcançáveis (--log-opts=--all), além do scan do commit actual.
- A primeira análise encontrou 7 ocorrências generic-api-key em exemplos de documentação, fixtures HMAC de testes e um hash de commit. Foram classificadas como falsas positivas; valores de exemplo actuais foram substituídos e as fingerprints históricas exactas foram registadas em .gitleaksignore.
- Reexecução: 2741 commits analisados, zero ocorrências não autorizadas. Não houve reescrita do histórico nem exclusões genéricas.
- Security Scans, API CI, Quality Gates e Docker Compose passaram; 1432 testes aprovados, 1 ignorado.

### Integridade do provider ONNX — digests aprovados e pré-processamento (2026-11-21, validado)

- O provider real exige digest SHA-256 aprovado para o detetor e, quando configurado, para o extrator de embeddings.
- Os hashes são comparados antes da criação das sessões ONNX e revalidados após o carregamento; digest divergente ou ausente impede o arranque.
- Os fingerprints separam o pré-processamento letterbox do detetor e o resize stretch dos crops do extrator.
- API CI e Quality Gates: 1432 passed, 1 skipped; PostgreSQL 16, compilação Python e build Web aprovados. Docker Compose e Security Scans passaram.
- Limite: não existem pesos reais autorizados, dataset anotado ou avaliação independente por SKU/cenário. A separação owner/runtime, trust state read-only e provisionamento recorrente foram validados no SHA `fcd19a3a` (API CI, Quality Gates, Security Scans e Compose; 1552 passed, 1 skipped). O Compose smoke simulou ownership e membership legados e confirmou reconciliação; falta ensaio com volume persistente real preservado entre reinícios.

### Isolamento multi-loja do histórico de alertas — 2026-11-21 (validado)

- Revisão estática: o endpoint valida o alerta pai com `_require_alert_supervisor` antes de consultar os eventos.
- Adicionada regressão HTTP cross-store e removida uma definição de teste duplicada.
- API CI [44893270814](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893270814) e Quality Gates [44893270837](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893270837): **1423 passed, 1 skipped**. Docker Compose [44893271027](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893271027) e Security Scans [44893270848](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893270848) passaram. A matriz completa BOLA/IDOR continua aberta.

### RBAC centralizado (2026-11-20)

- Política extraída para `apps/api/app/api_security_policy.py` com categorias por grupo e fail-closed para papel desconhecido.
- API CI, Quality Gates e Docker Compose passaram no commit `afd2a38`; **1389 passed, 1 skipped, 1 warning**.
- A matriz completa endpoint × ADMIN/SUPERVISOR/EMPLOYEE × loja permanece em aberto; a centralização não substitui testes de isolamento handler-a-handler.

### CORS preflight e Bearer — validado (2026-11-20)

- Preflight OPTIONS com Origin/Access-Control-Request-Method passa para CORSMiddleware validar origem, método e headers; API continua a exigir Bearer em pedidos reais.
- `allow_credentials=False`, pois não há autenticação por cookie.
- RED observado no commit `831c1026`; GREEN no commit `a63d646`.
- API CI, Quality Gates e Docker Compose passaram; **1388 passed, 1 skipped, 1 warning**.

### CORS preflight e autenticação Bearer (2026-11-20)

- O teste de preflight revelou 401 porque o middleware Bearer interceptava OPTIONS antes do CORSMiddleware.
- Corrigir com bypass estrito apenas para requests OPTIONS que contenham Origin e Access-Control-Request-Method; o CORSMiddleware continua a validar origem/método/headers.
- Desactivar CORS credentials porque a autenticação usa Bearer, não cookies.
- RED observado no commit `831c1026`; GREEN pendente.

### Estado consolidado P0 — 2026-11-20

- Inventário de outputs finais sem publicação auditável: implementado e validado; sempre report-only, mesmo com `--apply`.
- CORS de produção: origens explícitas HTTPS e fail-closed para wildcard/localhost/HTTP; API CI, Quality Gates e Docker Compose aprovados, 1387 passed.
- OWASP: primeira revisão estática de 130 rotas documentada. Não foi confirmado bypass nos fluxos revistos; a política RBAC distribuída é risco residual e a auditoria completa permanece aberta.
- Próximo: política declarativa por rota + matriz endpoint × papel × loja; depois avançar para os restantes controlos de retenção/linhagem.

### Primeira ronda OWASP API Security (2026-11-20)

- Revisão estática de 130 rotas, autenticação JWT, RBAC, store scope, planogramas e testes existentes.
- Finding CORS de produção corrigido e validado em CI.
- Risco residual: políticas RBAC distribuídas em path/method allowlists e handlers; centralizar metadata e testar cobertura de todas as rotas.
- Auditoria não equivale a pentest; SCA/secret scan/DAST ainda não executados.

### Hardening CORS em produção (2026-11-20)

- Validação fail-closed de origens explícitas HTTPS; rejeita wildcard, userinfo, path, query, fragmentos, localhost e loopback.
- A primeira execução detectou falso rejeitamento de DNS e fixtures de produção incompletos; ambos foram corrigidos.
- Revalidação GREEN pendente.

### Hardening CORS em produção (2026-11-20)

- A configuração anterior aceitava origens wildcard, HTTP, localhost e paths em produção com credenciais CORS activadas.
- Implementada validação fail-closed de origens explícitas HTTPS; rejeita wildcard, userinfo, path, query, fragmentos e loopback.
- RED observado no commit `e8c9935`; GREEN/CI pendente.

### Inventário de outputs finais sem publicação auditável (2026-11-20)

- Detecta ficheiros finais canónicos antigos em `published/` sem linha SQL de publicação.
- Reporta digest, tamanho, estado do job e timestamp; não segue symlinks.
- É sempre report-only, mesmo com `--apply`, porque a ausência de auditoria não prova que os bytes são descartáveis.
- RED observado no commit `cc7dc70b`; implementação adicionada, GREEN/CI pendente.

### Metodologia de engenharia e skills (2026-11-20)

- Superpowers fixado como submódulo Git para TDD, debugging, planeamento e revisão; Frontend Design para direcção visual; Impeccable para auditoria e polish.
- Entradas de skills em `.agents/skills/`; instruções de prioridade em `AGENTS.md`.
- Sem dependências runtime.
- Worktrees/subagentes apenas quando o runtime os suporta; não simular capacidades.
- Próximo passo: validar clone/submódulos e usar TDD com revisão numa correção P0.

### Impeccable — governança de qualidade de frontend (2026-11-20)

- Skill upstream integrada e fixada em `vendor/impeccable`; ponto de entrada dos agentes em `.agents/skills/impeccable/SKILL.md`.
- Contexto durável de produto e design em `PRODUCT.md` e `DESIGN.md`.
- Detector v4.10.0 integrado no Quality Gates com relatório baseline não bloqueante para findings preexistentes; erro de execução continua a falhar o job.
- Estado: integração documental e CI configurada; auditoria visual efectiva e correções de findings ainda pendentes. Não afirmar conformidade WCAG nem aprovação visual sem inspeção renderizada e testes.
- Próximo passo: recolher o primeiro artefacto de auditoria, priorizar findings, corrigir P0/P1 e fazer verificação visual desktop/mobile.

### Hardening do container vision-worker — 2026-11-20

- O worker executa como UID/GID `65532:65532`, sem privilégios Linux adicionais.
- Root filesystem read-only, `cap_drop: ALL`, `no-new-privileges:true` e tmpfs limitado a `/tmp`; HOME/cache/TMPDIR usam essa área temporária.
- Imagens e pesos de modelos permanecem em mounts read-only.
- O smoke Compose valida configuração Docker efectiva e permissões de escrita do processo.
- Esta alteração não hardena a API, não separa o armazenamento de outputs de datasets e não prova quiescência de workers antigos.
- Validação CI pendente no commit desta ronda.

### Isolamento filesystem da captura — primeira barreira read-only (2026-11-20)

- O serviço `vision-worker` monta agora o volume persistente `shelf_images` em modo só de leitura; a API permanece responsável por escrever uploads e gerir retenção.
- A inspecção do worker confirmou que o fluxo de inferência resolve e lê a imagem, sem escrever no volume de capturas.
- O smoke Docker Compose passa a inspeccionar o mount do container e exige `RW=false`.
- Limite: isto não separa UID/GID, não isola `DATASET_OUTPUT_STORAGE_PATH` e não prova quiescência de processos antigos. A limpeza de staging órfão continua report-only.
- Validação CI pendente no commit desta alteração.

### Inventário seguro de staging órfão — 2026-11-20

- O reconciliador identifica ficheiros antigos em staging sem publicação correspondente e classifica job desconhecido, job concluído sem publicação, token obsoleto, job terminal e worker potencialmente activo.
- A nova classe é sempre report-only, mesmo com `--apply`: lease/fencing na base de dados não prova que um processo antigo deixou de escrever no filesystem.
- Teste de regressão cobre job terminal e job desconhecido, confirmando que os bytes são preservados.
- Limitação: isolamento por permissões/identidade de sistema operativo e prova de quiescência continuam por implementar; não existe limpeza automática nem scheduler.

### Regressão negativa da publicação derivada — 2026-11-20

- Callback de autorização recusado: rollback da publicação e da relação, ausência do ficheiro final e staging preservado.
- Validado no commit `9d65bff677128bf2d0e7a81f04ca7d0aceb52b36`: API CI [44731813064](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44731813064), Quality Gates [44731812997](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44731812997) e Docker Compose [44731812973](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44731812973) passaram; PostgreSQL 16 e **1375 passed, 1 skipped, 1 warning**.
- O aviso é a depreciação externa `anyio.abc.BlockingPortal` do Starlette TestClient.

### Publicação atómica de outputs derivados — 2026-11-20

- `promote_dataset_job_output` aceita uma relação pai → derivado opcional, com actor, motivo e callback obrigatório.
- Bloqueia a cadeia ancestral antes dos locks do job/fontes e confirma publicação + aresta append-only na mesma transacção SQL.
- Retry exacto mantém idempotência; metadados divergentes são rejeitados.
- Validado no commit `41c2bb6e4b02e6744ea428403213452800ad8214`: API CI [44731054620](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44731054620), Quality Gates [44731054475](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44731054475) e Docker Compose [44731054522](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44731054522) passaram; 1374 passed, 1 skipped e 1 warning.
- Limite: ainda não existe worker de transformação real nem integração externa.

### Linhagem de outputs derivados — smoke PostgreSQL acrescentado (2026-11-20)

- O smoke de publicação cria agora dois outputs independentes, regista a aresta pai → derivado com autorização explícita e verifica leitura do descendente.
- Acrescentadas verificações PostgreSQL de rejeição de ciclos e de UPDATE/DELETE à linhagem append-only.
- Restrição e legal hold no pai bloqueiam o descendente; libertar a restrição não liberta o legal hold herdado.
- A validação do novo smoke e da migration 0066 aguarda API CI/PostgreSQL 16, Quality Gates e Docker Compose. Não foram executados testes localmente.
- Limitações preservadas: sem integração de transformação real, endpoint, broker, inventário de cópias externas ou autorização de governação por perfil. Purga física continua desactivada.

### Validação da idempotência estrita da observação após revisão SKU — 2026-11-20

- API CI [44648427709](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44648427709) passou: migrations PostgreSQL 16, todos os smokes operacionais e suite API concluídos.
- Quality Gates [44648427667](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44648427667) passou: **1343 passed, 1 skipped, 1 warning**, compilação Python e build TypeScript/produção Web.
- Docker Compose [44648427581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44648427581) passou: build, readiness, seed, worker e perfis demo.
- A validação é automatizada; não houve teste manual com câmaras ou datasets reais. O aviso é a depreciação externa `anyio.abc.BlockingPortal` do Starlette TestClient.

### Idempotência estrita da confirmação de observações — 2026-11-19

- Corrigida a deduplicação por deteção para não devolver uma observação de SKU A quando uma revisão humana posterior já selecionou SKU B.
- O replay só é idempotente quando o produto e o estado coincidem; pedidos com identidade diferente recebem HTTP 409, preservando a observação original.
- Foi acrescentado teste HTTP de regressão para revisão SKU posterior e tentativa de reutilização da deteção com outro produto.
- A validação do commit `c854e948b5664870942b9302dee4913e0349755b` está concluída: API CI [44648427709](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44648427709), Quality Gates [44648427667](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44648427667) e Docker Compose [44648427581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44648427581) passaram. A suite API reportou 1343 passed, 1 skipped e 1 warning; os smokes PostgreSQL 16, compilação Python e build Web passaram.

### Confirmação humana explícita de observações demo — validação concluída (2026-11-19)

- API CI [44596254264](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44596254264) passou com PostgreSQL 16, smokes operacionais e **1343 testes aprovados, 1 ignorado e 1 aviso**.
- Quality Gates [44596254489](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44596254489) passou com compilação Python, suite API e build TypeScript/produção Web.
- Docker Compose [44596254260](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44596254260) passou com arranque, readiness, seed, worker e perfis de demonstração.
- A correção do smoke PostgreSQL de retenção foi validada. A nova regra de confirmação humana está coberta por testes API e pelo smoke de concorrência.
- A evidência é CI automatizado; não houve validação manual com imagens reais.

### Confirmação humana explícita de observações demo — 2026-11-19

- O endpoint de criação de observação a partir de deteção demo exige agora `confirmed_status`, separado da revisão de SKU.
- A API rejeita estados em falta ou incompatíveis com a classe da deteção; a proveniência regista o estado, o utilizador confirmador e o timestamp UTC.
- O comportamento continua restrito ao provider mock/demo e não constitui validação de visão computacional real.
- Testes de regressão HTTP acrescentados. A primeira API CI identificou um smoke PostgreSQL com payload desactualizado; o script foi alinhado para enviar `confirmed_status=EMPTY`, mantendo a prova de serialização com o lock da imagem. Aguarda nova execução CI.

### Contrato de evidência de comparação de planogramas — 2026-11-19

- A validação do fingerprint foi concluída no commit db7f8b423d14b0011609ff154874014cd122dfac: API CI [44589714790](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44589714790), Quality Gates [44589714764](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44589714764) e Docker Compose [44589714845](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44589714845) passaram.
- Criado contrato técnico proposto para identidade, snapshot, idempotência, revisão append-only, retenção/linhagem e ordem de locks: [planogram-comparison-evidence-contract.md](architecture/planogram-comparison-evidence-contract.md).
- Não foi criada migration nem persistência: a captura pode ser purgada e as deteções podem desaparecer em cascata; a precedência de revisões SKU e o manifesto completo de inferência ainda não estão definidos.
- Próximos passos bloqueados por decisão de produto/privacidade: aprovar sobrevivência de derivados após purga/legal hold; definir manifesto imutável do pipeline e regra de revisão; depois implementar schema append-only e smoke PostgreSQL concorrente.

### Comparação read-only de captura com planograma ativo — 2026-11-19

- Implementado serviço puro de comparação entre deteções persistidas e células do planograma ACTIVE.
- Endpoint `GET /api/v1/shelves/{shelf_id}/planograms/comparison/{image_id}` para ADMIN/SUPERVISOR, com isolamento multi-loja, imagem ACTIVE/COMPLETED, validação da calibração e SKU esperado.
- A resposta liga os resultados ao SHA-256 da captura, à versão do modelo e à versão do planograma; inclui estados e contagens por célula, sem modificar inventário.
- Sem calibração de visibilidade por captura, o comparador nunca afirma EMPTY por ausência de deteções ou por `empty_facing`; usa UNKNOWN.
- Testes API acrescentados para facings, proveniência, vazio conservador, estado pendente e autorização.
- Validação CI concluída: API CI [44563920216](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44563920216) com **1337 passed, 1 skipped, 1 warning** e PostgreSQL 16; Quality Gates [44564178983](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44564178983) com o mesmo resultado, compilação Python e build Web; Docker Compose [44563920224](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44563920224) aprovado.
- Próximos passos: persistir resultados imutáveis por imagem/modelo/versão; ligar worker respeitando retenção e ordem de locks; criar UI de revisão; validar NMS/facings/visibilidade com dataset anotado.

### 2026-11-19 — Linhagem e propagação de governação de outputs

- CI anterior confirmado: API CI 44538123392, Quality Gates 44538123460 e Docker Compose 44538123417 passaram no SHA inicial.
- Migration 0066 e modelo append-only de arestas pai → derivado; ciclos rejeitados por serviço e trigger; callback explícito e actor activo.
- Consumo governado percorre ancestrais, adquire locks de publicações em ordem crescente, detecta alterações concorrentes da cadeia, autoriza todos os nós e herda restrições/legal holds e elegibilidade de todas as fontes.
- Matriz de autorização específica de outputs permanece deny-by-default; não há endpoints de gestão nem scopes de governação para workers.
- Proposta de aprovação independente documentada, sem activar fluxo até decisões do responsável do produto/jurídico.
- Contrato de propagação para caches, exports, object storage, réplicas e backups documentado. Nenhum adapter ou inventário externo foi presumido.
- Validação da migration 0066, smoke PostgreSQL de linhagem/ciclo/hold herdado e suite API concluída no commit `4153625226c6b08b9e09d491986a1415e3fbc847`: API CI [44730129439](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44730129439), Quality Gates [44730129686](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44730129686) e Docker Compose [44730129490](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44730129490) passaram; 1374 passed, 1 skipped e 1 warning.

### Consumo concorrente e restrição de outputs — 2026-11-19

- Confirmados como aprovados no commit anterior: API CI 44536740007, Quality Gates 44536740024 e Docker Compose 44536739957.
- O smoke PostgreSQL passa a testar a serialização real entre leitura verificada e aplicação concorrente de restrição, usando sessões independentes e observação de locks em pg_stat_activity.
- A validação da alteração aguarda API CI, Quality Gates e Docker Compose.
- Próximas dependências: matriz de autorização por perfil/loja, política de aprovação independente para libertação de legal hold, linhagem/catálogo de derivados e inventário explícito de cópias externas, caches e backups. Não presumir regras comerciais ou legais.

### Reconciliação conservadora de outputs (2026-11-19)

- Implementado CLI manual com simulação por defeito e `--apply` explícito, período de segurança configurável (7 dias por omissão).
- Temporários privados antigos só são removidos se forem ficheiros regulares com nome interno esperado. Staging só é removido quando publicação append-only, job, token, digest e tamanho coincidem e o destino publicado foi revalidado.
- Jobs `SUCCEEDED` sem publicação, symlinks, caminhos desconhecidos, ficheiros recentes e conteúdos divergentes são preservados. Sem scheduler e sem suporte a object storage.
- Quality Gates [44484598129](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44484598129) e Docker Compose [44484598370](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44484598370) passaram; API CI [44484598295](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44484598295) passou, incluindo smokes PostgreSQL e suite API.
- Procedimento: [dataset-output-reconciliation.md](operations/dataset-output-reconciliation.md).

### Publicação de outputs — redução de locks (2026-11-19)

- A preparação/cópia/hash do output foi retirada da transacção com locks PostgreSQL; a autorização é revalidada sob locks imediatamente antes da publicação final.
- A secção crítica contém apenas o hard link no-clobber e o registo append-only. O staging é limpo após commit e a reconciliação de um destino criado antes de um crash verifica o digest fora dos locks.
- Teste de regressão cobre revogação durante a preparação e exige recusa sem publicação.
- Código integrado na `main`: `5767468ad8058a593474695b2cb0dee9ef3118e7`; documentação: `5e84a0cec8cc15ca829aa6eda1694d8013819858`.
- Validação concluída: API CI [44483199562](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44483199562), Quality Gates [44483436546](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44483436546) e Docker Compose [44483199541](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44483199541) passaram. A evidência é CI; não foram executados testes localmente.
- O smoke PostgreSQL dedicado confirma que a revogação faz commit numa segunda sessão enquanto a preparação está pausada e que a publicação é recusada na revalidação final. API CI [44485569053](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44485569053) passou.
- Próxima prioridade: reconciliador de temporários e staging órfãos; depois catálogo de outputs com herança de retenção/legal hold.

### Auditoria HTTP de integrações externas — percurso ADMIN (2026-11-18)

- Acrescentado teste JWT positivo para criação, listagem, consulta de cobertura e revogação de integrações externas por ADMIN.
- Verificado o isolamento entre lojas e a resposta 404 para tentativa de actualizar uma integração através do caminho de outra loja.
- Confirmado que a resposta não inclui campos de credenciais e que a alteração regista o utilizador ADMIN responsável.
- O teste usa SQLite isolado; validação CI pendente no commit desta ronda. A auditoria global de autorização permanece aberta.

# SMART SHELF AI — Roadmap

## Prioridade atual: preparar um piloto controlado com validação operacional e evidência

### Ronda em curso — 2026-11-18

- Reforçado o protocolo para leitura integral do README antes de cada ronda de desenvolvimento.
- Corrigida uma expectativa demasiado restritiva no smoke PostgreSQL do diretório de funcionários: a listagem global ADMIN pode incluir funcionários activos criados por outros smokes na base de CI partilhada.
- Aguardar API CI/PostgreSQL para validar a correcção. O run anterior `44308942806` falhou apenas na asserção de igualdade global do smoke; o Docker Compose smoke `44308942877` passou.
- A auditoria global de autorização por handler continua pendente.

### Estado de validação — 2026-11-18

- API CI [44271596288](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44271596288), commit `30f3b4e`: suite API e smokes PostgreSQL concluídos com sucesso, incluindo os novos testes de picking.
- Quality Gates [44271717562](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44271717562), commit `93abecc`: testes API/compilação Python e build TypeScript/produção Web concluídos com sucesso.
- Docker Compose smoke [44271596168](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44271596168), commit `30f3b4e`: build, arranque, readiness, seed e validação dos perfis aprovados.
- A ronda de picking está validada por CI; a auditoria de desempenho abaixo está preparada, mas ainda carece de planos obtidos em dados representativos. A preparação da auditoria de desempenho passou no API CI [44291136290](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291136290) (**1148 passed, 1 skipped, 1 warning**), Quality Gates [44291194461](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291194461) e Docker Compose [44291133419](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291133419).

### Ronda adicional — integridade do picking (2026-11-18)

- O planeador exclui todas as linhas quando a entrada contém duplicados para o mesmo SKU/localização, impedindo dupla contagem de stock. A mesma localização para SKUs diferentes continua válida.
- Testes de regressão e validação CI concluídos: API CI `44271596288`, Quality Gates `44271717562` e Docker Compose smoke `44271596168` passaram.

### Preparação da auditoria de desempenho — 2026-11-18

- [x] Criar script read-only para planos das consultas de imagens, deteções, OCR, retenção e fila de revisão SKU, com timeout e validação de loja/imagem.
- [x] Acrescentar testes unitários aos SELECTs limitados e à validação de IDs.
- [x] Documentar execução, segurança e critérios de interpretação em [PERFORMANCE-QUERY-AUDIT.md](PERFORMANCE-QUERY-AUDIT.md).
- [ ] Executar em staging/réplica com volume representativo; nenhuma decisão de índice deve ser tomada antes dessa evidência.

- [x] Usar botão HTML nativo nos cartões de resumo de zona e anunciar o carregamento da avaliação operacional através de uma região de estado acessível.
- [x] Web CI [44296222519](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44296222519) passou; Quality Gates [44296524262](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44296524262) passou com testes API/compilação Python e build Web/TypeScript aprovados no commit `897d6946d0641ee8201cd14c7df8549c60c55a9b`.
### Acessibilidade e navegação responsiva — 2026-11-18

- [x] Corrigir semântica dos cartões de zona com botão nativo e anunciar o carregamento da avaliação operacional; Quality Gates [44296524262](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44296524262) passou no commit `897d6946d0641ee8201cd14c7df8549c60c55a9b`.

- [x] Adicionar skip link para o conteúdo principal e landmark de navegação com nome acessível.
- [x] Disponibilizar navegação equivalente em ecrãs pequenos, onde a barra lateral deixa de estar visível.
- [x] Reforçar indicadores de foco visível e anúncio do estado inicial de carregamento.
- [x] Validar Web CI [44292103581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44292103581) e Quality Gates [44292103676](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44292103676), ambos aprovados no commit `5ca7babcd3529f4459a50eaf5542aa289db91d05`.
- [ ] Validar manualmente teclado, leitor de ecrã, contraste de todos os estados e comportamento real em browser; não declarar conformidade WCAG 2.2 AA apenas com o build.

### Auditoria de autorização HTTP — actualização de evidência (2026-11-18)

- [x] Confirmar os testes JWT de upload na suite API: [API CI 44291136290](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291136290), 1148 aprovados, 1 ignorado, 1 aviso.
- [x] Confirmar o smoke PostgreSQL de autorização multi-loja das sessões de captura no mesmo workflow.
- [ ] Continuar auditoria por rota/handler; não inferir cobertura exaustiva a partir dos cenários já aprovados.

### Validação directa e contrato de output ONNX — 2026-11-20

- O commit `1bd2e361` passou API CI e Quality Gates com **1358 testes aprovados, 1 ignorado e 1 aviso**, além de migrations/smokes PostgreSQL 16 e Docker Compose smoke.
- O construtor rejeita limites numéricos inválidos; o contrato do output foi adicionalmente endurecido para rejeitar batch estático diferente de 1, coerente com o decoder.
- A regressão do batch estático foi acrescentada nesta ronda e aguarda CI do novo commit. Não foram executados testes localmente.
- O fingerprint SHA-256 não equivale a assinatura/autorização de modelo; continuam pendentes manifesto assinado, dataset autorizado e avaliação reproduzível.

### Falhas de entrada e timeout do provider ONNX — 2026-11-20

- Acrescentados testes para imagem corrompida e timeout do runtime: o provider propaga ambas as falhas e não devolve uma análise vazia enganadora.
- A integração do worker deve continuar a ser validada para garantir estado FAILED, sem deteções persistidas, em falhas de inferência.
- CI pendente para os novos testes; não foram executados localmente.

### Prioridades ainda abertas

1. **P1 — desempenho:** executar `apps/api/scripts/postgres_image_query_plan_audit.py` numa réplica/staging com volume representativo; analisar planos `EXPLAIN (ANALYZE, BUFFERS)` e medir paginação profunda antes de acrescentar índices ou alterar contratos. Procedimento em [PERFORMANCE-QUERY-AUDIT.md](PERFORMANCE-QUERY-AUDIT.md).
2. **P1 — aceitação manual:** percorrer o demo completo no browser com ADMIN, SUPERVISOR e EMPLOYEE, sem alterar directamente a base de dados; guardar evidência real em `docs/screenshots/demo/`.
3. **P1 — acessibilidade:** verificar navegação por teclado, foco, leitores de ecrã e contraste de todos os estados; não declarar conformidade WCAG 2.2 AA apenas com base no build.
4. **P1 — dados existentes:** executar o preflight da migração 0054 sobre uma cópia representativa dos dados de cada ambiente antes de qualquer aplicação com histórico real.
5. **P2 — armazém:** definir com o responsável operacional as regras de transferência palete↔colocação e reconciliação com stock agregado; manter os domínios separados até existir decisão aprovada.
6. **P2 — capacidade:** validar a política de capacidade/peso/temperatura com perfis físicos completos e regras reais de negócio; dados desconhecidos continuam a bloquear recomendações em vez de serem assumidos como zero.
7. **P2 — IA e integrações:** provider de visão production-grade treinado/avaliado e conectores POS/ERP/WMS reais continuam fora da validação actual.

### Implementado nesta fase

- [x] Criar provider mock determinístico compatível com `VisionProvider`, selecionável por `VISION_PROVIDER_FACTORY`.
- [x] Configurar API e worker no Docker Compose para usar o provider mock por omissão no ambiente local.
- [x] Criar seed idempotente com loja Demo Store Braga, três prateleiras, quinze produtos, três perfis, snapshots e política de frescura.
- [x] Gerar imagem sintética local sem dados pessoais ou fotografia de terceiros; persistir o ficheiro gerado na pasta do repositório através de bind mount.
- [x] Ligar o upload do frontend à criação de sessão e ao registo de imagem, hash e proveniência.
- [x] Ligar deteções mock à revisão humana de SKU e à criação idempotente de observação.
- [x] Corrigir o motor de decisões para associar a observação ao SKU correto, sem propagar evidência de um produto a todos os produtos da prateleira.
- [x] Ligar recomendação, aprovação humana, validação de stock, atribuição a EMPLOYEE e criação de tarefa.
- [x] Incluir referência da imagem, deteção, observação e SHA-256 na tarefa e mostrar a miniatura protegida pela autorização da imagem.
- [x] Suportar execução da tarefa, registo de quantidade efetiva, motivo para reposição parcial e reconciliação explícita.
- [x] Disponibilizar cronologia auditável da tarefa a ADMIN/SUPERVISOR.
- [x] Aplicar a política de frescura configurada também na avaliação operacional; o seed fornece 24 horas e limita o SKU principal a 4 unidades.
- [x] Disponibilizar listagem de funcionários ativos com isolamento por loja para atribuição por SUPERVISOR.
- [x] Acrescentar testes do provider, seed, worker, revisão/observação idempotente e isolamento da listagem de funcionários.
- [x] Criar um pré-validador local read-only para Docker Compose, serviços, readiness da API, frontend e imagem sintética.
- [x] Criar workflow dedicado para validar a sintaxe Bash do pré-validador.
- [x] Documentar checklist de aceitação ponta-a-ponta por perfil, proveniência, reconciliação e dashboard.

### Validação

- [x] Suite API completa: 1 097 testes aprovados, 1 ignorado; compilação Python aprovada.
- [x] Build TypeScript/produção do frontend aprovado.
- [x] CI PostgreSQL: migrações e smokes de integridade, isolamento, concorrência, ciclo de tarefa e reconciliação aprovados.
- [x] Confirmar execução bem-sucedida do workflow Docker Compose smoke: build e arranque de PostgreSQL/API/worker, readiness após migrações, seed, imagem sintética, worker ativo e autenticação/autorização dos três perfis (PR #4, commit `452583eaec108a176190d19cb097cf3a8a872ede`). Esta validação corre num runner efémero; não equivale a ensaio manual local.
- [ ] Executar localmente a interface e percorrer manualmente o cenário integral com os três perfis, confirmando movimento/snapshot/auditoria finais (checklist em [DEMO.md](DEMO.md)).
- [ ] Capturar screenshots reais do percurso; as instruções de captura estão em [DEMO.md](DEMO.md).

## Limitações e fronteiras actuais

- O provider do demo é mock determinístico; não é um modelo treinado nem valida semanticamente a imagem.
- Não existe integração POS/ERP/WMS real configurada.
- Não existe executor de purga física; os endpoints de retenção são de governação/preview e falham fechados.
- O ensaio manual ponta-a-ponta, capturas reais e auditoria formal de acessibilidade continuam pendentes.
- Slotting físico e picking existem como recomendações consultivas; não reservam stock nem executam movimentos.
- Registos de paletes e inventário agregado permanecem separados para evitar dupla contabilização.

## Regras de conclusão

Só marcar uma tarefa de validação como concluída quando existir implementação e evidência de teste/build. Um provider mock não é um modelo de IA treinado; um seed não é inventário real; uma reconciliação local não equivale a integração com um sistema externo.


## Pré-validação local reforçada — 2026-11-17

- [x] O preflight continua read-only e verifica a configuração Docker Compose e a presença dos três serviços.
- [x] A readiness da API é agora validada semanticamente: exige `status=ready`, `database=connected` e `migrations=current`; um HTTP 200 com payload incompleto/malformado não é considerado sucesso.
- [x] A imagem sintética é validada dentro do container API através do Pillow: ficheiro regular (não symlink), PNG íntegro e dimensões esperadas de 1200×700.
- [x] A verificação da sintaxe Bash já tinha workflow dedicado; a nova versão do script aguarda a execução CI deste commit.
- [x] O workflow Docker Compose smoke confirmou no commit `b618c0ac` a subida de PostgreSQL/API/worker, seed e autenticação dos três perfis, incluindo a restrição de acesso do EMPLOYEE.
- [ ] Executar a nova versão do preflight num ambiente local com Docker Compose e frontend iniciado.
- [ ] Percorrer manualmente o fluxo completo de captura, revisão, tarefa, execução, reconciliação e dashboard com os três perfis.
- [ ] Guardar capturas reais do percurso e preencher `docs/DEMO-ACCEPTANCE.md`.

**Limite:** o CI de Docker Compose prova o arranque, seed e autenticação/permissões básicas; não prova ainda o percurso operacional completo na interface web. O preflight valida a integridade do asset e a readiness, mas não substitui a aceitação manual.


## Critérios de prontidão para piloto

O demo só deve ser anunciado como aceite ponta-a-ponta depois da checklist manual de [DEMO-ACCEPTANCE.md](DEMO-ACCEPTANCE.md) estar preenchida com evidência real. CI verde valida código e testes automatizados, mas não substitui ensaio de browser, acessibilidade, dados representativos, backups/restauro ou integrações externas.

## Auditoria de autorização — integrações externas (2026-11-18)

- [x] Confirmar controlo ADMIN nos handlers de criação, listagem, alteração e cobertura de integrações externas por loja.
- [x] Acrescentar teste de integração HTTP com JWT para SUPERVISOR e EMPLOYEE nas quatro operações, incluindo verificação de ausência de efeitos laterais.
- [x] API CI `44299045159`: 1149 passed, 1 skipped, 1 warning; Quality Gates `44299324366` aprovou testes API, compilação Python e build Web.
- [x] Reconciliar `docs/security/http-route-inventory.md`: 16 rotas integradas na tabela principal; total 123 declarações, sem entradas obsoletas (commit `a60ac242`).
- [ ] Continuar a auditoria handler-a-handler dos restantes endpoints e caminhos indirectos.

**Limite:** o teste acrescentado usa SQLite isolado. Não prova concorrência PostgreSQL nem fecha a auditoria global de autorização.

### Inventário de rotas HTTP — reconciliação (2026-11-18)

- [x] Comparar o inventário com as declarações literais do módulo FastAPI principal.
- [x] Acrescentar 16 rotas omitidas e actualizar o total documentado para 123; nenhuma entrada anterior ficou obsoleta.
- [ ] Concluir a revisão de autorização por handler, incluindo caminhos indirectos e isolamento multi-loja.

A reconciliação estática não constitui uma auditoria de segurança concluída. O Docker Compose `44299045038` também passou (build, readiness, seed, worker e perfis).

## Diretório de funcionários — autorização (2026-11-18)

- [x] Confirmar a política no handler: ADMIN global, SUPERVISOR limitado à loja atribuída e apenas funcionários activos.
- [x] Adicionar teste HTTP JWT para isolamento cross-store, papéis e estado activo.
- [x] Validar no API CI/Quality Gates (runs 44337777007 e 44337776819).
- [ ] Decidir, com base no risco operacional, se é necessário smoke PostgreSQL específico.

A cobertura usa SQLite isolado e não deve ser apresentada como prova de concorrência ou isolamento PostgreSQL.



### Diretório de funcionários — validação PostgreSQL (2026-11-18)

- [x] Acrescentar smoke HTTP/JWT em PostgreSQL 16 para `GET /api/v1/store-employees`, cobrindo isolamento do SUPERVISOR, exclusão de inactivos, filtro cross-store, acesso ADMIN e recusa EMPLOYEE.
- [x] Integrar o smoke no workflow API CI.
- [x] Confirmar a execução do smoke PostgreSQL no API CI (run 44337777007).


### Reforço do smoke de funcionários — 2026-11-18

- [x] Cobrir 401 para ausência de Bearer, JWT inválido e conta SUPERVISOR inactiva.
- [x] Verificar que a listagem global de ADMIN exclui funcionários inactivos.
- [x] Preservar cobertura de isolamento por loja, filtro ADMIN e recusa EMPLOYEE.
- [x] Confirmar execução no API CI/PostgreSQL (run 44337777007).


### Governação de artefactos externos — autorização (18-11-2026)

- [x] Rever os seis handlers de governação de artefactos externos e confirmar a exigência de ADMIN no início de cada operação.
- [x] Acrescentar teste HTTP/JWT para SUPERVISOR e EMPLOYEE em registo, listagem, snapshot de inventário, decisão de acesso e eventos de disposição.
- [x] Confirmar no teste que as recusas não criam registos de artefactos, snapshots ou eventos.
- [x] Validar no API CI e Quality Gates (runs 44337777007 e 44337776819).
- [ ] Continuar auditoria global de autorização; não inferir cobertura total a partir deste conjunto.


### Validação integrada — commit 4b45ae4 (2026-11-18)

- [x] API CI: smoke PostgreSQL e suite `pytest -q` aprovados — [run 44337777007](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44337777007).
- [x] Quality Gates: build Web de produção aprovado — [run 44337776819](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44337776819).
- [x] Docker Compose: API, PostgreSQL, worker e perfis de demonstração aprovados — [run 44337776893](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44337776893).


### Gestão de integrações externas — autorização HTTP (2026-11-18)

- [x] Rever os quatro handlers de criação, listagem, cobertura e actualização de integrações externas.
- [x] Acrescentar teste JWT para SUPERVISOR e EMPLOYEE nos quatro métodos.
- [x] Confirmar no teste a recusa HTTP 403 e a ausência de efeitos laterais sobre registos e política.
- [x] Validar a nova cobertura no API CI e Quality Gates (runs 44338653668 e 44338651433); Docker Compose smoke também passou (run 44338651406).


### Validação CI — gestão de integrações externas (18-11-2026)

- [x] API CI e suite API aprovados — [run 44338653668](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44338653668).
- [x] Quality Gates e build de produção aprovados — [run 44338651433](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44338651433).
- [x] Docker Compose smoke aprovado — [run 44338651406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44338651406).


### Fluxo ADMIN de integrações externas por HTTP (18-11-2026)

- [x] Cobrir criação, listagem, cobertura e revogação com JWT ADMIN.
- [x] Confirmar ausência de campo de segredo nas respostas e estado de cobertura coerente.
- [ ] Validar no API CI e Quality Gates.

### Fluxos de revisão humana — controlo de perfil (18-11-2026)
- [x] Identificar as rotas de fila/resumo de revisão, avaliação de SKU e candidatos de treino como operações reservadas a ADMIN/SUPERVISOR.
- [x] Acrescentar teste JWT HTTP que exige 403 para EMPLOYEE nas cinco operações, incluindo criação de revisão de deteção.
- [x] Confirmar no teste que a operação de escrita recusada não cria registos.
- [ ] Validar o teste no API CI e Quality Gates.
- [ ] Prosseguir a auditoria de autorização por handler e isolamento multi-loja.

**Limite:** teste HTTP com SQLite isolado; não equivale a validação PostgreSQL nem a conclusão da auditoria global.

### Isolamento multi-loja — armazém (18-11-2026)
- [x] Cobrir leitura de localizações de outra loja por supervisor.
- [x] Cobrir criação de localização noutra loja por supervisor.
- [x] Cobrir criação de colocação numa localização de outra loja.
- [x] Verificar 403 e ausência de efeitos laterais.
- [ ] Validar no CI e continuar a cobertura dos recursos de armazém.

**Limite:** evidência HTTP SQLite; a auditoria multi-loja permanece aberta.

### Isolamento multi-loja — paletes e rotação (18-11-2026)
- [x] Cobrir listagem e registo de paletes da loja B por supervisor da loja A.
- [x] Cobrir alteração de política de rotação da loja B por identificador.
- [x] Cobrir leitura e escrita de eventos de ciclo de vida de palete da loja B.
- [x] Confirmar 403 e ausência de efeitos laterais em estado, política e eventos.
- [ ] Validar no API CI e Quality Gates.
- [ ] Continuar a revisão de simulação, portefólio e histórico de rotação.

**Limite:** teste HTTP com SQLite isolado; não prova concorrência PostgreSQL nem conclui a auditoria global.

### Isolamento multi-loja — vendas e forecasting (2026-11-18)
- [x] Cobrir ingestão diária/horária, tráfego e batches.
- [x] Cobrir histórico, previsão de procura, risco de rutura, portefólio e perfil horário.
- [x] Verificar 403 e ausência de efeitos laterais.
- [ ] Validar no CI e continuar auditoria dos restantes fluxos.

**Limite:** teste HTTP/JWT com SQLite isolado; não prova isolamento PostgreSQL nem conclui a auditoria global.


### Importações CSV horárias — isolamento multi-loja (18-11-2026)

- [x] Rever a ordem de autorização dos handlers de importação CSV de vendas e tráfego: a verificação de loja ocorre antes da leitura/parsing do ficheiro.
- [x] Acrescentar teste HTTP/JWT multipart para SUPERVISOR da loja A a tentar importar dados para a loja B.
- [x] Verificar HTTP 403 e ausência de efeitos laterais nas tabelas de vendas e tráfego.
- [ ] Validar o teste no API CI e Quality Gates.
- [ ] Criar/confirmar smoke PostgreSQL específico para isolamento multi-loja nas importações CSV.

**Limite:** a cobertura HTTP adicionada usa SQLite isolado. A revisão estática da ordem de execução não substitui um teste PostgreSQL nem encerra a auditoria global.


### Autorização das importações CSV horárias em PostgreSQL — 18-11-2026

- [x] Smoke PostgreSQL com JWT real para importação de vendas horárias e tráfego.
- [x] Rejeição cross-store antes de parsing e verificação de ausência de efeitos laterais.
- [x] Caminho positivo: SUPERVISOR importa ambos os ficheiros na própria loja.
- [x] Validar API CI, Quality Gates e Docker Compose smoke no commit `1e3499c8c80ef75494a29d06807469898471e4e1`; todos passaram.


### Cobertura completa das importações CSV — 18-11-2026

A auditoria foi alargada para incluir a importação diária `POST /api/v1/sales/import-csv`, além das importações horárias. O teste HTTP/JWT e o smoke PostgreSQL agora cobrem os três endpoints. A evidência PostgreSQL da ronda horária anterior passou no API CI; a extensão diária aguarda validação no novo commit.


**Evidência de validação (18-11-2026):** commit `1e3499c8c80ef75494a29d06807469898471e4e1`; API CI [44404814359](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44404814359), Quality Gates [44404814406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44404814406) e Docker Compose smoke [44404813670](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44404813670) passaram. A prova PostgreSQL cobre os três endpoints CSV com JWT real, isolamento cross-store, ausência de efeitos laterais e caminho positivo na loja autorizada.


### Hierarquia de zonas e prateleiras — autorização (18-11-2026)

- [x] Rever as regras ADMIN-only de criação de zonas/prateleiras.
- [x] Cobrir listagens SUPERVISOR por loja, filtro cross-store e recusa de EMPLOYEE.
- [x] Verificar ausência de efeitos laterais em escritas recusadas e caminho positivo ADMIN.
- [ ] Validar API CI e Quality Gates.
- [ ] Confirmar no smoke PostgreSQL as constraints/triggers de linhagem da hierarquia, sem inferir essa validação a partir de SQLite.


### Batches e consultas de forecasting — isolamento multi-loja (18-11-2026)

- [x] Confirmar validator de loja única nos schemas dos batches de vendas horárias e tráfego.
- [x] Testar payloads com duas lojas: HTTP 422 e ausência de efeitos laterais nas duas lojas.
- [x] Alargar cobertura HTTP/JWT a vendas diárias, traffic peaks, hourly demand e slotting recommendations.
- [ ] Validar os testes no API CI e Quality Gates.
- [ ] Prosseguir auditoria handler-a-handler; a cobertura actual não fecha a matriz global.


### Linhagem de registos associados a prateleiras — PostgreSQL (18-11-2026)

- [x] Rever triggers da migration 0050 para alerts, capture sessions e replenishment tasks.
- [x] Acrescentar smoke PostgreSQL para INSERT/UPDATE cross-store e movimentos da hierarquia.
- [ ] Validar API CI e registar resultado.


### Linhagem multi-loja shelf → zone → store — validada (18-11-2026)

- A migration `0050_shelf_record_store_lineage_guard` e o smoke PostgreSQL foram validados no API CI [44408063719](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44408063719): PostgreSQL 16, migrações, smokes operacionais e suite API passaram.
- O smoke confirmou a rejeição de INSERT/UPDATE divergentes em alertas, sessões de captura e tarefas, bem como movimentos de prateleiras/zonas com dependências existentes.
- Quality Gates [44408063767](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44408063767) passou no mesmo SHA `04c542320ad892a06c81c2295f518f5583428bc4`.
- A auditoria global de autorização e isolamento multi-loja permanece aberta; a validação não deve ser generalizada para rotas não cobertas.


### Linhagem pai/filho de artefactos externos — reforço de contrato e HTTP (18-11-2026)

- O endpoint existente valida o pai no mesmo recurso de imagem e loja e mantém a ordem de bloqueios imagem → integração → referência.
- O schema de criação passa a rejeitar booleanos em `parent_reference_id`, evitando a coerção Python `True == 1`.
- Foi acrescentado teste HTTP/JWT para raiz, descendente, repetição idempotente, conflito de linhagem, pai inexistente, pai de outra imagem e pai de outra loja.
- A validação CI ainda está pendente; a cobertura de integração usa SQLite isolado e não fecha a validação PostgreSQL nem a auditoria global.


### Elegibilidade operacional de datasets — locks da linhagem multi-loja (18-11-2026)

A validação de proveniência interna passa a bloquear explicitamente imagem, prateleira e zona, pois as três linhas determinam a loja efectiva e a retenção aplicável ao artefacto. A query usa ordenação determinística e o teste de contrato compila SQL PostgreSQL para confirmar `FOR UPDATE OF shelf_images, shelves, zones`. Falta smoke de concorrência PostgreSQL com alteração hierárquica em transação concorrente e auditoria dos consumidores que possam contornar o release gate.


### Smoke concorrente PostgreSQL — elegibilidade de datasets (18-11-2026)

Foi criado e integrado no API CI o smoke `postgres_dataset_eligibility_concurrency_smoke.py`. Duas sessões PostgreSQL independentes exercitam actualizações a `shelves.zone_id` e `zones.store_id` enquanto o gate mantém os locks de imagem/prateleira/zona. O smoke exige evidência de bloqueio real através de `pg_stat_activity` e `pg_blocking_pids`, e confirma que as alterações só terminam depois do commit do gate. A validação de runtime permanece pendente até o workflow concluir.


## 2026-11-18 — Elegibilidade de datasets: concorrência PostgreSQL validada

- [x] Confirmar no API CI [44410444406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444406) o smoke `postgres_dataset_eligibility_concurrency_smoke.py`: PostgreSQL 16 observou bloqueios reais a alterações concorrentes de `shelves.zone_id` e `zones.store_id` enquanto o gate mantinha locks de imagem/prateleira/zona.
- [x] Confirmar no mesmo API CI a suite API completa, incluindo o teste HTTP/JWT de registo de linhagem pai/filho.
- [x] Confirmar Quality Gates [44410444404](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444404) e Docker Compose [44410444721](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444721).
- [ ] Auditar consumidores COCO, galeria, revisão offline, aprovação, exportação e treino para identificar caminhos que não passam pelo release gate.
- [ ] Definir linhagem operacional e propagação de retenção para derivados, exports, relatórios, caches e backups; não activar purge físico sem política aprovada.
- [ ] Desenhar coordenação durável com lease/claim e fencing para consumidores remotos ou destacados, porque locks da sessão síncrona não cobrem trabalho assíncrono.

**Limites:** a prova HTTP/JWT da linhagem usa SQLite isolado; o smoke PostgreSQL prova os locks do gate, não o uso universal do gate por todos os consumidores. A suite verde não demonstra integração com fornecedores externos nem execução de treino real.


## 2026-11-18 — Gate de aprovação obrigatório no consumidor síncrono

- [x] Ligar `dataset_execution` ao gate completo de aprovação antes de iniciar o consumidor.
- [x] Exigir release record e os três splits COCO; aceitar os três registos de revisão visual em conjunto e exigir aprovação visual quando configurado.
- [x] Incluir hashes do registo e do relatório do gate na fingerprint imutável da release.
- [x] Manter os locks de elegibilidade operacional durante a criação da release e o consumidor síncrono, adquirindo-os apenas depois das verificações de ficheiros.
- [ ] Validar suite API e Quality Gates no CI.
- [ ] Desenhar leases/claims duráveis com fencing para filas e consumidores remotos/destacados.
- [ ] Auditar exports, caches, backups e artefactos derivados quanto a herança de retenção.

**Limites:** a garantia é local e síncrona. Não autoriza jobs remotos nem substitui política formal de retenção/purge.


### Gate de aprovação no consumidor síncrono — validado (18-11-2026)

- [x] API CI [44412024791](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44412024791): **1168 passed, 1 skipped, 1 warning**; migrações PostgreSQL 16 e smokes operacionais passaram.
- [x] Quality Gates [44412024893](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44412024893): compilação Python e build Web passaram.
- [x] Docker Compose [44412025214](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44412025214): stack de demonstração passou.
- [x] Gate de aprovação, evidência SHA-256 vinculada à release e execução síncrona com locks mantidos validados pela suite API.
- [ ] Criar lease/claim durável com fencing para consumidores remotos ou destacados.
- [ ] Propagar linhagem e retenção aos derivados, exports, relatórios, caches e backups; manter purge físico desactivado.

**Limites:** a evidência é CI automatizado; não comprova treino real nem integração externa. O lock transaccional não protege trabalho que sobreviva ao processo consumidor.


### Auditoria das fronteiras dos consumidores de datasets — 18-11-2026

- [x] Classificar validação COCO, galeria offline, diff, qualidade, revisão, aprovação, release e execução.
- [x] Identificar `dataset_execution` como a única fronteira inspeccionada que inicia um processo externo; está ligada ao gate de aprovação.
- [x] Documentar que relatórios/galeria/releases candidatas não são autorização operacional nem autenticam revisores.
- [ ] Implementar catálogo persistente de artefactos derivados e herança de retenção para relatórios, exports, caches e backups.
- [ ] Implementar lease/claim/fencing durável para consumidores assíncronos e condicionar a publicação ao token actual.
- [ ] Substituir revisão por ficheiro declarativo por aprovação autenticada quando existir contrato de utilizadores/revisores.


### Execução assíncrona de datasets — contrato de lease/fencing definido (18-11-2026)

- [x] Definir identidade imutável do job, idempotência, estados e transições.
- [x] Definir claim `FOR UPDATE SKIP LOCKED`, expiração, takeover e fencing token monotónico.
- [x] Definir revalidação de retenção/legal hold em enqueue, claim, heartbeat e conclusão.
- [x] Definir staging e promoção condicionada ao token actual.
- [x] Implementar persistência, serviço de lease e auditoria append-only.
- [x] Validar concorrência, takeover, token obsoleto e retenção em PostgreSQL 16 no API CI [44416138879](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138879); suite API: 1177 passed, 1 skipped, 1 warning.
- [ ] Integrar worker/fila apenas depois da validação do serviço.


### Persistência de jobs de datasets e fencing — implementação inicial (18-11-2026)

- [x] Criar migration/modelos para jobs, fontes internas e eventos append-only.
- [x] Implementar enqueue idempotente, claim `SKIP LOCKED`, lease, heartbeat, falha, conclusão em staging e fencing monotónico.
- [x] Revalidar retenção/loja/hash das fontes em cada fronteira de autorização e revogar jobs inelegíveis.
- [x] Acrescentar testes unitários/SQLite e smoke PostgreSQL concorrente.
- [x] Validar migration PostgreSQL 16, suite API e smoke concorrente no API CI [44416138879](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138879), Quality Gates [44416138669](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138669) e Docker Compose [44416138628](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138628).
- [ ] Integrar broker/worker apenas depois da validação PostgreSQL.
- [ ] Implementar leitura de artefactos autorizada por chamada e promoção de outputs condicionada ao token actual.


### Fencing reforçado na base de dados — implementação preparada (2026-11-18)

- [x] Adicionar migration para incremento exacto de fencing token/attempt count em claims e takeovers.
- [x] Impedir heartbeat sobre lease expirado ou redução da expiração.
- [x] Exigir lease válido para sucesso/falha, timestamp terminal e output staged com digest.
- [x] Validar sequência de eventos na base de dados e bloquear eventos posteriores à transição terminal, preservando o evento terminal.
- [x] Adicionar testes SQLite e ampliar o smoke PostgreSQL com tentativas SQL directas.
- [x] Validar API CI [44419928230](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928230), Quality Gates [44419928281](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928281) e Docker Compose [44419928382](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928382): migration PostgreSQL 16, smokes e 1179 testes aprovados, 1 ignorado, 1 aviso.
- [ ] Implementar autenticação de workers e serviço de leitura/promoção com fencing.


### Máquina de estados e identidade dos jobs assíncronos — 2026-11-18

- [x] Especificar transições válidas: `QUEUED → LEASED/REVOKED/CANCELLED`; `LEASED → LEASED/SUCCEEDED/FAILED/REVOKED/CANCELLED`.
- [x] Bloquear actualizações a jobs terminais e alterações à identidade imutável depois do enqueue.
- [x] Acrescentar guards equivalentes para PostgreSQL e SQLite, testes de migration e smoke SQL directo.
- [ ] Confirmar a migration 0058 e os workflows de CI antes de marcar a garantia como validada.
- [ ] Implementar autenticação de workers, consumo de bytes autorizado por chamada e promoção de outputs com fencing.


### Validação da migration 0058 — 18-11-2026

- [x] API CI [44421831066](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44421831066): migration PostgreSQL 16, smoke de execução assíncrona e 1179 testes aprovados, 1 ignorado, 1 aviso.
- [x] Quality Gates [44421831076](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44421831076) e Docker Compose [44421831148](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44421831148) passaram.
- [x] A migration 0059 de estado inicial obrigatório foi validada no API CI [44428496117](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496117), com PostgreSQL 16, smoke de leases/fencing e 1179 testes aprovados, 1 ignorado e 1 aviso; Quality Gates [44428496156](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496156) e Docker Compose [44428496204](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496204) passaram.


### Guard de estado inicial dos jobs assíncronos — 19-11-2026

- [x] Acrescentar cobertura SQLite para os oito campos que não podem ser definidos num INSERT inicial de job.
- [x] Acrescentar tentativas equivalentes no smoke PostgreSQL 16, com transacções independentes e rejeição esperada pela base de dados.
- [x] Corrigir os INSERTs de teste sem colunas duplicadas e validar PostgreSQL 16, smoke de leases/fencing e suite API (**1179 passed, 1 skipped, 1 warning**) no API CI [44428496117](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496117); Quality Gates [44428496156](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496156) e Docker Compose [44428496204](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496204) passaram.
- [ ] Implementar autenticação/identidade de workers antes de disponibilizar endpoints de claim/heartbeat; manter a API de jobs não exposta enquanto essa fronteira não existir.


### Autenticação de workers de datasets — estado atualizado (19-11-2026)

- [x] Definir credenciais individuais, emissão segura, expiração, rotação e revogação de workers.
- [x] Vincular `worker_id` à identidade autenticada e autorizar scopes por operação.
- [x] Testar tokens inválidos/expirados/revogados, scopes insuficientes e vínculo de identidade entre worker e credencial.
- [ ] Implementar assinatura por pedido/nonce e testes anti-replay.
- [x] Manter endpoints de jobs não expostos enquanto a autenticação HTTP não estiver integrada.


## 2026-11-19 — Autenticação individual de workers (implementação inicial validada)

**Implementado no código:**
- Migration `0060_dataset_worker_credentials`: identidades de workers, credenciais individuais e eventos de segurança append-only.
- Credencial bearer com segredo aleatório de 256 bits, hash SHA-256 persistido, comparação em tempo constante, validade máxima de 90 dias, rotação, revogação e desativação.
- Scopes explícitos sem wildcard; wrappers de claim/heartbeat/complete/fail derivam a identidade exclusivamente do principal autenticado.
- CLI de provisionamento local; nenhuma rota HTTP pública de emissão foi criada.
- Testes SQLite e smoke PostgreSQL de ciclo de vida e imutabilidade integrados no workflow API CI.

**Validação concluída no commit de código `d7c84125d35a5fff5d2254a3ee33a08cd41edcc7`:** API CI [44431378398](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378398) passou (PostgreSQL 16, smoke de credenciais e **1202 passed, 1 skipped, 1 warning**), Quality Gates [44431378324](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378324) e Docker Compose [44431378349](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378349) também passaram.

**Riscos e trabalho restante:**
1. A autenticação bearer não é anti-replay; falta assinatura por pedido/nonce ou protocolo equivalente.
2. O middleware/handlers HTTP ainda não autenticam workers e os endpoints de jobs permanecem não expostos.
3. Os scopes `artifacts:read` e `outputs:publish` são apenas reservados; faltam leitura de bytes por chamada e promoção com fencing.
4. Não existe broker nem worker remoto de treino; a persistência de leases não equivale a execução operacional.
5. A credencial só pode ser emitida pelo CLI local confiável; a operação em produção precisa de secret manager, TLS e procedimento de provisionamento controlado.

Referência de implementação: [Autenticação e autorização de workers](security/dataset-worker-authentication.md).


## 2026-11-19 — Autenticação HTTP assinada e proteção contra replay

A migration `0061_dataset_worker_request_nonces` e o módulo `app.dataset_worker_http` implementam uma fronteira reutilizável para pedidos de workers. A dependência `require_dataset_worker(scope)` exige bearer individual, timestamp com tolerância de 60 segundos, nonce aleatório, assinatura HMAC-SHA-256 e scope específico. A assinatura cobre a identidade da credencial, método, caminho/query exactos e SHA-256 do corpo. O servidor persiste apenas o digest do nonce, com unicidade por credencial, e confirma-o antes de entregar o principal ao handler.

**Validação concluída no commit `7bb67412cdb6b63b8221a2a29a12d7347005a451`:** API CI [44471171581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171581) passou em PostgreSQL 16, incluindo duas sessões concorrentes que reutilizam o mesmo nonce (**uma aceite, uma rejeitada**) e **1211 testes aprovados, 1 ignorado e 1 aviso**. Quality Gates [44471171526](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171526) e Docker Compose [44471171533](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171533) também passaram.

**Decisão:** as futuras rotas de workers devem usar um prefixo separado da API humana, por exemplo `/internal/v1/dataset-jobs`, e aplicar a dependência em todos os handlers. Não expor rotas enquanto leitura autorizada de artefactos, publicação fenced e worker remoto não estiverem implementados. A tabela de nonces retém os digests durante 121 segundos; pedidos assinados posteriores limpam os expirados.

**Próximas tarefas P0:** leitura de bytes autorizada por chamada (`artifacts:read`), promotor de outputs condicionado ao fencing token actual (`outputs:publish`), e só depois integração de broker/worker remoto.


## 2026-11-19 — Leitura de fontes de treino com fencing e auditoria

A migration `0062_dataset_job_artifact_reads` e o serviço `read_dataset_job_source_bytes` fecham a operação de leitura interna para jobs. O worker necessita do scope `artifacts:read`, lease não expirado, identidade autenticada e fencing token actual. O serviço valida a fonte imutável do job, revalida credencial/scope, bloqueia imagem/prateleira/zona, verifica loja, retenção, legal hold, caminho sem symlinks, tamanho e SHA-256, e só devolve bytes em memória.

A tabela `dataset_execution_job_artifact_reads` regista cada leitura bem-sucedida e é append-only. Triggers SQL rejeitam inserções sem lease/fonte/loja/retention/worker/credencial/scope válidos e impedem UPDATE/DELETE. O smoke PostgreSQL confirmou que uma restrição de retenção concorrente espera pelos locks da leitura e que a leitura posterior é recusada sem criar auditoria de sucesso.

**Validação concluída no commit `c6b00478514812e094b960f5fefe4b6380b0fb9a`:** API CI [44473560217](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560217), Quality Gates [44473560287](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560287) e Docker Compose [44473560252](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560252) passaram; suite API com **1223 testes aprovados, 1 ignorado e 1 aviso**.

**Próxima fronteira P0:** implementar `outputs:publish` com validação do estado `SUCCEEDED`, digest e fencing token actual, protocolo de staging/publicação recuperável e compensação de ficheiros órfãos. Só depois integrar broker e worker remoto. O serviço de leitura existe, mas não está ainda exposto por endpoint HTTP; a execução assíncrona continua não operacional.


## 2026-11-19 — Promoção de outputs de datasets com fencing

A migration `0063_dataset_job_output_publications` e o serviço `app.dataset_job_output_publications.promote_dataset_job_output` implementam a promoção interna de outputs concluídos. A operação valida o estado `SUCCEEDED`, o fencing token actual, o evento terminal do worker, o digest do output e a credencial activa com `outputs:publish`. A referência de staging é limitada ao job/token, os caminhos são abertos sem seguir symlinks, o conteúdo é copiado para temporário privado e verificado por tamanho/SHA-256, e o destino é publicado com hard link atómico sem sobrescrita.

A tabela de publicação é append-only e as triggers PostgreSQL/SQLite impedem inserções que não correspondam ao evento terminal e à autorização persistida. A referência final é determinística e content-addressed. Uma repetição após a promoção filesystem mas antes do commit SQL valida o destino existente e reconcilia a auditoria.

**Validação concluída no commit `46006afcc5167e04f77037f985e65981a78248e3`:** API CI [44480661837](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661837) passou com PostgreSQL 16, smoke concorrente e **1231 testes aprovados, 1 ignorado e 1 aviso**; Quality Gates [44480661851](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661851) e Docker Compose [44480661813](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661813) também passaram.

**Riscos e próximas prioridades P0/P1:** automatizar limpeza/reconciliação de temporários órfãos após crash; integrar outputs no catálogo de artefactos derivados e propagar retenção/legal hold; separar permissões filesystem entre staging e publicação para o futuro worker; só depois criar handlers HTTP internos, broker e worker remoto. Não expor endpoints nem declarar execução assíncrona operacional enquanto estes elementos não estiverem concluídos.

## Reconciliador: preservação perante destino adulterado — 2026-11-19

Foi acrescentada cobertura para a divergência entre o destino publicado e a auditoria imutável. O staging só pode ser removido quando o destino publicado e o próprio staging correspondem simultaneamente ao digest e tamanho registados. A nova regressão verifica que um destino adulterado impede a limpeza, mesmo quando o staging ainda contém os bytes esperados. A execução CI desta cobertura está pendente.


### Governação de outputs assíncronos — decisão arquitectural (19-11-2026)

- [x] Auditar os registos existentes de publicação, linhagem de fontes e catálogo externo por imagem.
- [x] Decidir que `dataset_execution_job_output_publications` é a raiz canónica do output; evitar catálogo duplicado e associação artificial a uma única imagem.
- [x] Documentar a herança de restrições de todas as fontes e a necessidade de eventos de governação append-only separados.
- [ ] Implementar eventos de retenção/legal hold associados à publicação, sem mutação da auditoria de publicação.
- [ ] Implementar avaliação fail-closed e locks de todas as imagens de origem em ordem crescente.
- [ ] Validar concorrência e migration em PostgreSQL 16 e SQLite.
- [ ] Manter purga física desactivada até existir política de retenção e cobertura externa aprovadas.

Ver [decisão de governação de retenção dos outputs](architecture/dataset-output-artifact-governance.md).


### Revalidação de fontes na promoção de outputs — 19-11-2026

- [x] Revalidar as fontes imutáveis do job na transacção final de promoção, depois da preparação do ficheiro.
- [x] Manter locks de imagem/prateleira/zona até ao commit da publicação, com ordem por ID crescente.
- [x] Impedir INSERT SQL directo se qualquer fonte estiver ausente, com loja/hash divergente, RESTRICTED ou sob legal hold (PostgreSQL e SQLite).
- [x] Acrescentar testes SQLite para restrição/legal hold e smoke PostgreSQL para a corrida entre hold e promoção.
- [ ] Validar migration 0064, suite API e workflows de CI.


### Promoção de outputs — cobertura multi-origem (2026-11-19)

- Regressões SQLite/serviço acrescentadas para duas fontes, entrada fora da ordem dos IDs e inelegibilidade da segunda origem por restrição ou legal hold.
- Migration 0064 coberta com trigger a rejeitar publicação quando apenas uma das fontes está inelegível.
- Smoke PostgreSQL 16 alargado para job multi-origem e corrida de legal hold sobre a segunda imagem durante a preparação.
- Validação CI pendente no commit desta ronda; não declarar a cobertura PostgreSQL concluída antes do API CI.


### Validação final — publicação multi-origem e retenção (2026-11-19)

- API CI [44516774051](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774051): **1241 passed, 1 skipped, 1 warning**, incluindo migration 0064 e smoke PostgreSQL 16 com duas fontes e hold concorrente sobre a segunda.
- Quality Gates [44516774058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774058): compilação Python, suite API e build Web aprovados.
- Docker Compose [44516774048](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774048): aprovado.
- O aviso Starlette/AnyIO é uma depreciação externa; sem falhas associadas.


### Governação append-only dos outputs publicados — 2026-11-19

- Implementada migration 0065 e modelo para eventos separados da publicação canónica.
- Implementados eventos de restrição/restauro e legal hold/libertação, actor activo, motivo, evidência e detalhes JSON limitados.
- Triggers PostgreSQL/SQLite impõem sequência consecutiva, máquina de estados por tipo de evento e imutabilidade UPDATE/DELETE.
- Serviço interno exige callback de autorização positivo; a projecção de estado deriva a situação efectiva da cronologia.
- Testes SQLite e smoke concorrente PostgreSQL acrescentados; aguarda CI do commit.
- Permanecem em aberto a matriz de permissões, integração com consumidores de bytes, endpoints/worker remoto, política de retenção e disposição física.


### Validação final da migration 0065 — 19-11-2026

- API CI [44519805058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44519805058): migration PostgreSQL 16 e smoke de governação concorrente aprovados; **1244 passed, 1 skipped, 1 warning**.
- Quality Gates [44519805055](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44519805055): compilação Python, suite API e build Web aprovados.
- Docker Compose [44519805067](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44519805067): aprovado.
- O aviso Starlette/AnyIO é uma depreciação externa, sem falhas associadas.


### Consumo governado de outputs publicados — 2026-11-19

- [x] Centralizar a leitura integral de outputs publicados num serviço fail-closed.
- [x] Consultar restrição/legal hold append-only e herdar elegibilidade de todas as fontes do job.
- [x] Verificar identidade content-addressed, tipo regular, ausência de symlinks, tamanho e SHA-256.
- [ ] Ligar cada endpoint/export/worker/cache/backup futuro a esta fronteira; manter interfaces externas desactivadas até existir autorização definida.
- [ ] Definir propagação para derivados e armazenamento externo, matriz de permissões e política de retenção.


## 2026-11-19 — Primeira sequência de visão computacional

Foi concluída a primeira fatia técnica para tornar o contrato ONNX mais seguro e preparar a análise geométrica de prateleiras:

1. O provider preserva `class_id`, resolve-o através de `VISION_CLASS_LABELS_JSON` e falha perante IDs desconhecidos; as etiquetas não são tratadas como SKU.
2. Os metadados ONNX são verificados antes da inferência: dtype float32, input NCHW RGB, dimensões, batch e output pós-NMS de seis colunas. Os valores de saída são validados quanto a finitude e intervalos.
3. O worker exige modo explícito `disabled`, `mock` ou `real`; mock só aceita a factory de demonstração e é bloqueado em produção.
4. `app.shelf_layout` introduz células geométricas fornecidas por calibração/planograma. `EMPTY` exige deteção positiva `empty_facing` acima do threshold, geometria compatível e célula visível/não ocluída; ausência de deteções é `UNKNOWN`. Conflitos produto/vazio são devolvidos como `CONFLICT`.
5. Os testes cobrem classes, outputs inválidos, contratos de tensor, isolamento dos providers, células sobrepostas, SKU mistos, ocupação, vazio e incerteza.

**Limites ainda activos:** não há pesos ONNX aprovados nem dataset comercial anotado; a validação do modelo ainda não verifica digest/assinatura/proveniência do artefacto. As células não estão persistidas, versionadas, expostas por API nem integradas no worker ou frontend. `EMPTY` é uma observação visual de uma célula calibrada, não uma contagem de inventário nem prova de stock contabilístico zero.

A validação mais recente está registada em [API CI](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44553140735) (**1311 passed, 1 skipped, 1 warning**), [Docker Compose smoke](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44553140813) e [Quality Gates](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44553235687); os três workflows passaram.

## 2026-11-19 — Quarta sequência: semântica conservadora de espaços vazios

O comparador de células foi endurecido para não inferir vazio apenas porque o detector não encontrou um produto. A etiqueta semântica `empty_facing` é tratada separadamente de objetos de produto.

- O estado `EMPTY` exige uma deteção `empty_facing` acima do threshold configurável (0,80 por omissão), intersecção geométrica suficiente e célula explicitamente visível/não ocluída.
- Ausência de deteções, confiança insuficiente, célula não calibrada ou oclusão resultam em `UNKNOWN`.
- Deteções simultâneas de produto e espaço vazio na mesma célula resultam em `CONFLICT`.
- O comparador preserva índices de deteção, SKU observados e sobreposição para revisão.
- API CI [44553140735](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44553140735): **1311 passed, 1 skipped, 1 warning**; Quality Gates [44553235687](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44553235687) e Docker Compose [44553140813](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44553140813) aprovados.

**Pendente:** persistir/versionar planogramas e calibração, ligar o comparador ao worker e UI, validar o threshold com imagens reais anotadas. A evidência `EMPTY` continua a não alterar inventário.
## 2026-11-19 — Quinta sequência: conformidade de facings

As células calibradas suportam agora um número esperado de facings por SKU. O comparador calcula quantas deteções de produto frontais se associam a cada célula e devolve `UNDER_FACED`, `OVER_FACED` ou `OCCUPIED` quando a contagem é inferior, superior ou exacta. `MISPLACED`, `OCCUPIED_UNIDENTIFIED` e `CONFLICT` mantêm precedência para preservar a incerteza.

`observed_facings` conta caixas pós-NMS associadas à célula; não representa unidades em profundidade nem stock disponível. A deduplicação e calibração de caixas com imagens reais são necessárias antes de usar esta contagem operacionalmente. Persistência de planogramas, API e interface continuam pendentes.

## 2026-11-19 — API de planogramas versionados

Foi concluída a primeira fronteira HTTP do ciclo de vida dos planogramas: criar DRAFT com células, consultar histórico, ler versão ativa, ativar e retirar. A autorização é restrita a ADMIN/SUPERVISOR e o isolamento de loja é repetido no serviço de domínio. A ativação substitui a versão ativa anterior de forma transacional; as versões ativadas/retiradas mantêm o histórico.

Validação final no commit `dd262068bdf8178a8eddff0f103317aec8a3558b`: API CI [44559057802](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44559057802) com PostgreSQL 16 e **1330 testes aprovados, 1 ignorado e 1 aviso**; Quality Gates [44559057575](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44559057575) e Docker Compose [44559057828](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44559057828) aprovados.

**Próximas prioridades:** edição atómica de células em DRAFT, persistência de `expected_facings`, UI de planogramas, integração do comparador com o worker e validação por dataset real. Até lá, os planogramas são dados de configuração e não alteram stock.


## 2026-11-19 — Facing targets persistidos e edição de DRAFT

A migration 0068 persiste `expected_facings` opcional por célula, com constraint PostgreSQL e triggers SQLite que exigem valor positivo e SKU esperado. O serviço de planogramas valida o campo e o endpoint PUT substitui atomicamente as células de uma versão DRAFT. A operação partilha a ordem de locks de ativação; ACTIVE/RETIRED permanecem imutáveis.

Validação no commit `3d9f338e5bdf50a9674f53d05da1ad99e23faa01`: API CI [44560333697](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44560333697) e Quality Gates [44560333600](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44560333600) com **1334 testes aprovados, 1 ignorado e 1 aviso**; Docker Compose [44560333624](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44560333624) aprovado.

**Próximas prioridades:** smoke PostgreSQL dedicado à constraint e corrida edição/ativação; integrar comparação no worker e UI; calibrar a contagem com dataset real. `observed_facings` continua a contar caixas frontais detetadas, não unidades em profundidade.


## 2026-11-19 — Smoke PostgreSQL de planogramas e concorrência

O API CI inclui agora um smoke PostgreSQL 16 dedicado à migration 0068 e ao ciclo de vida dos planogramas. São verificadas as constraints de `expected_facings`, a imutabilidade de células ACTIVE, a unicidade da versão ativa e uma corrida entre substituição de células DRAFT e ativação em sessões distintas. A ativação tem de esperar pelo commit da edição e usar a geometria substituída.

Validação no commit `46eb9bbc19a039d2e68183655fb07501a0c12ef8`: API CI [44561359774](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44561359774) e Quality Gates [44561359524](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44561359524) com **1334 testes aprovados, 1 ignorado e 1 aviso**; Docker Compose [44561359723](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44561359723) aprovado.

**Próxima fronteira:** ligar a versão ativa ao worker, persistir resultados de comparação rastreáveis por imagem/planograma/modelo e apresentar revisão humana. Não alterar inventário automaticamente.


### Interface React de comparação de planogramas — 2026-11-19

- Criado componente dedicado no frontend para selecionar prateleira e captura concluída e consultar o endpoint de comparação read-only.
- A interface apresenta a versão ativa, proveniência da captura/calibração, versão do modelo, resultados por célula, facings e deteções associadas.
- O acesso visual é exposto apenas a ADMIN/SUPERVISOR; a API mantém a validação JWT e o isolamento por loja.
- A interface não cria observações/tarefas nem altera inventário. Sem calibração de visibilidade continua a apresentar UNKNOWN.
- Build/CI e validação manual ainda pendentes. Próxima sequência: validar build; acrescentar testes de componente; depois avaliar persistência append-only das comparações com retenção/proveniência explícitas.


## 2026-11-19 — Comparação de planogramas: serialização com retenção

A comparação passou a bloquear a captura e a imagem de calibração em ordem crescente de ID, seguidas da prateleira e do planograma ativo. A versão ativa é recarregada após os locks; uma mudança concorrente resulta em HTTP 409. A captura é revalidada como ACTIVE/COMPLETED sob lock e a restrição de retenção fica serializada com a leitura. O smoke PostgreSQL dedicado foi alargado para testar a concorrência real entre comparação e restrição da captura. A validação desta alteração está pendente dos workflows disparados pelo commit. A comparação continua on-demand, read-only e não altera inventário.


### Validação CI — comparação e retenção serializadas (19-11-2026)

A alteração foi validada no API CI [44588809660](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44588809660), Quality Gates [44589016727](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44589016727) e Docker Compose [44588809507](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44588809507). O API CI executou o smoke PostgreSQL 16 de planogramas, incluindo a corrida comparação/retenção, e a suite terminou com **1342 testes aprovados, 1 ignorado e 1 aviso**. O Quality Gates confirmou também compilação Python e build TypeScript/produção Web. A comparação continua read-only e não persistida.


### Correção do isolamento do teste de idempotência SKU — 2026-11-19

- A primeira execução do CI após a alteração identificou uma falha no teste integrado: a revisão SKU B usada para testar a colisão de idempotência era aplicada à mesma deteção que alimentava o fluxo operacional de tarefas.
- O endpoint comportou-se de forma conservadora; a alteração da revisão fez com que a decisão operacional deixasse de reconhecer a evidência do SKU A, pelo que o teste não podia continuar a esperar a criação da tarefa.
- O teste foi corrigido para usar uma segunda deteção independente na mesma captura para o cenário SKU A → SKU B. Assim, a revisão de regressão não altera a evidência do fluxo de tarefas principal.
- A validação da correção aguarda nova execução dos workflows API CI e Quality Gates; não declarar a suite aprovada até essa execução terminar.


### Isolamento total do cenário de idempotência — 2026-11-19

- A execução CI do commit `6e9a3147e33076316bef9feb72c4cf212e63d87b` confirmou que separar apenas a deteção não era suficiente: a deteção de regressão continuava na mesma prateleira e a observação adicional alterava a avaliação operacional usada pelo teste de criação de tarefas.
- O cenário SKU A → SKU B foi movido para uma segunda prateleira, com imagem e deteção próprias, mantendo os mesmos produtos atribuídos. O fluxo operacional original passa a usar exclusivamente a prateleira e a evidência originais.
- A correção aguarda nova execução integral do CI. A falha anterior foi **1 failed, 1342 passed, 1 skipped, 1 warning**; não considerar a suite aprovada.


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
- A alteração está publicada na branch principal, mas aguarda API CI, Quality Gates e Docker Compose; não considerar a proteção validada até os workflows terminarem.


### Proteção contra falsificação de metadados de evidência — 2026-11-19

- A observação manual genérica aceita texto livre; sem uma fronteira explícita, um utilizador autenticado poderia tentar introduzir os marcadores internos usados pelo fluxo de demonstração.
- O endpoint genérico rejeita agora os campos reservados de proveniência (`demo_detection_id`, imagem, revisão e confirmação humana), reservando-os para a rota de deteção revista.
- A avaliação de evidência exige também estado humano confirmado igual ao estado da observação, timestamp de confirmação e utilizador confirmador ativo ADMIN/SUPERVISOR com âmbito de loja válido.
- O teste integrado tenta criar metadados de demonstração através do endpoint genérico e espera HTTP 422, além de verificar que uma referência cruzada de prateleira não produz evidência elegível.
- Validação CI pendente no commit seguinte.


### 2026-11-20 — Matriz geométrica do provider ONNX

- Foram adicionados testes de regressão para a transformação inversa do letterbox e clipping às dimensões da imagem original.
- O decoder rejeita coordenadas normalizadas fora de [0,1] e valores não finitos; caixas degeneradas são descartadas e resultados são ordenados por confiança antes de aplicar o limite máximo de deteções.
- Os testes sintéticos cobrem o contrato geométrico, mas não substituem validação com modelo ONNX real e dataset autorizado.
- Próximo passo: testar a fronteira integrada do worker em falhas de inferência, incluindo estado FAILED, fencing/lease e ausência de efeitos em inventário/observações.


### 2026-11-20 — Falhas de inferência no worker

- Acrescentado teste integrado para timeout e falha de runtime durante inferência.
- O teste verifica FAILED e ausência de efeitos derivados em deteções, observações e inventário.
- O cenário usa SQLite isolado; a cobertura de lease/fencing PostgreSQL permanece nos smokes dedicados.
- Validado no commit `4212aeab21bfe9182a485e10cfbd8a209d1d28ac`: API CI [44652277501](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44652277501), Quality Gates [44652277455](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44652277455) e Docker Compose [44652278042](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44652278042) passaram; 1374 passed, 1 skipped e 1 warning na suite API.


### 2026-11-20 — Fencing do resultado após takeover de lease

- Adicionado teste integrado para a corrida em que a lease muda durante a inferência e o provider antigo devolve resultados válidos.
- O resultado obsoleto deve ser descartado sem publicar deteções nem alterar observações/inventário.
- A cobertura verifica a fronteira de claim do worker em SQLite; a serialização concorrente real continua dependente dos smokes PostgreSQL dedicados.
- Validado no commit `4212aeab21bfe9182a485e10cfbd8a209d1d28ac`: API CI [44652277501](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44652277501), Quality Gates [44652277455](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44652277455) e Docker Compose [44652278042](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44652278042) passaram. O smoke PostgreSQL cobre o takeover com resultado válido obsoleto e falha de provider após takeover; a suite API terminou com 1374 passed, 1 skipped e 1 warning.

## 2026-11-20 — Teste dos locks da proveniência de outputs

A primeira validação da alteração de locks falhou apenas no novo teste SQL: este executava uma query em SQLite sem criar o esquema e, por isso, não conseguia compilar a instrução PostgreSQL. A implementação foi separada em construtor de query e executor, permitindo inspeccionar o SQL PostgreSQL sem executar `FOR UPDATE` em SQLite. Commits de correcção: `d82ec0a` e `a2fbc1a`. A nova execução API CI/Quality Gates/Docker Compose permanece pendente.

## 2026-11-20 — Robustez de publicação e recuperação de outputs

A promoção de outputs locais passa a sincronizar cada componente da árvore de armazenamento, verificar e sincronizar ficheiros/destinos existentes antes de reutilização, e emitir avisos quando a limpeza de staging pós-commit não consegue confirmar durabilidade. Os erros anteriores ao commit mantêm o staging e não criam publicação SQL parcial. A reconciliação permanece conservadora e report-only para ficheiros sem publicação.

Validação no commit `4beb3f002b809de8ef50f9990a377db2f7f7c36d`: API CI, Quality Gates e Docker Compose aprovados; 1404 testes aprovados, 1 ignorado e 1 aviso. Os limites de durabilidade do filesystem/volume físico estão documentados em `docs/operations/dataset-output-reconciliation.md`.
## 2026-11-21 — Governação explícita das rotas API

A autorização HTTP foi convertida de grupos/fallback genérico para um registo método × template com 128 entradas. Novas rotas e métodos não declarados são recusados para todos os perfis até receberem uma política. O teste de cobertura percorre as rotas FastAPI registadas; o auditor `--strict` passou a integrar o API CI.

Também foi fechada uma janela de revogação de perfil em dez handlers de administração/catálogo, que agora recarregam o actor na sessão de execução. O teste integrado simula ADMIN → SUPERVISOR entre middleware e handler e confirma ausência de escrita.

Validação no commit `311fecc9e13641e6d5eb55465fda646fb2909601`: Quality Gates e Docker Compose passaram; **1407 testes aprovados, 1 ignorado e 1 aviso**. O API CI [44881182965](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44881182965), commit `8775aaff`, confirmou o gate estrito com 128 métodos, 0 rotas não classificadas e 0 fallbacks legados, além dos smokes PostgreSQL e da mesma suite API. A matriz endpoint × perfil × loja continua como trabalho aberto; classificação explícita não prova isoladamente o isolamento de tenant.

### 2026-11-21 — Cobertura completa das decisões RBAC por perfil

- Adicionado teste que percorre todas as entradas explícitas de método/template e verifica as decisões para ADMIN, SUPERVISOR e EMPLOYEE.
- O teste também rejeita políticas duplicadas, categorias não suportadas e confirma que uma rota não registada é negada a todos os perfis.
- Quality Gates [44882467613](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44882467613) passou: compilação Python, build Web e **1408 testes aprovados, 1 ignorado e 1 aviso**.
- Docker Compose demo smoke [44882467596](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44882467596) passou.
- API CI [44882467564](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44882467564) concluiu com sucesso: migrations PostgreSQL 16, smokes de concorrência/isolamento/retention e **1408 passed, 1 skipped, 1 warning**.
- Limite: esta cobertura verifica a política central por método/rota/perfil; não substitui a auditoria handler × perfil × loja e dos caminhos indirectos.

### 2026-11-21 — SCA, secret scanning e DAST configurados

- Criado .github/workflows/security-scans.yml com pip-audit para dependências API/OCR, npm audit --audit-level=high, Gitleaks e OWASP ZAP Baseline contra Docker Compose efémero.
- As Actions externas são fixadas a SHA completo e as permissões são limitadas por job.
- ZAP corre inicialmente em modo baseline passivo/report-only; não executa operações activas nem prova a segurança de rotas autenticadas.
- Primeira execução: Gitleaks e npm audit passaram; pip-audit identificou 158 ocorrências em 5 pacotes Python. As versões directas vulneráveis foram actualizadas e a FastAPI foi elevada para 0.165.0 para resolver a dependência Starlette sem pin isolado. A validação da segunda execução e a triagem ZAP continuam pendentes.

### Segurança — remediação SCA, lock ordering e headers HTTP (2026-11-21)

- SCA inicial detectou 158 ocorrências em cinco pacotes Python; dependências actualizadas. Revalidação pip-audit e npm audit sem vulnerabilidades conhecidas; Gitleaks passou.
- 22 handlers multi-loja passaram a verificar o tenant antes do lock e novamente após refresh; teste estático de regressão e testes de helper adicionados.
- Headers HTTP de segurança, CSP, HSTS em produção, no-store em APIs e Swagger UI desactivado em produção.
- API CI e Quality Gates: **1413 passed, 1 skipped**; PostgreSQL 16 e Docker Compose smoke passaram.
- ZAP Baseline e API safe-mode: 0 alertas High/Medium/Low; apenas alertas informativos. Scan não autenticado; DAST autenticado/activo continua aberto.

### Computer Vision — contrato ONNX e recuperação de falhas (2026-11-21)

- Matriz de testes de boxes ONNX ampliada para coordenadas invertidas, área nula, padding letterbox e clipping parcial.
- Worker testado para RuntimeError/TimeoutError: FAILED, erro sanitizado, deteções anteriores preservadas e nenhum snapshot de inventário.
- API CI e Quality Gates: **1422 passed, 1 skipped**; PostgreSQL 16 e Docker Compose smoke aprovados.
- A precisão do detector real continua por validar: falta modelo aprovado, dataset autorizado e métricas reproduzíveis por SKU/cenário.


### Isolamento multi-loja — listagem de sessões de captura (2026-11-21)

- Confirmado no handler `list_capture_sessions` o filtro por `CaptureSession.store_id` para utilizadores não ADMIN.
- Acrescentado teste com duas lojas: a sessão da loja estrangeira não aparece na listagem do supervisor, incluindo quando este manipula o filtro `shelf_id` para apontar à prateleira estrangeira.
- A validação local não foi executada neste ambiente; a suite CI será usada para confirmar o novo teste. A cobertura desta rota não fecha a matriz global handler × perfil × loja.


### Segurança PostgreSQL — owner/runtime e estado de confiança ONNX (implementação publicada; CI validada em 2026-11-22)

- Serviço one-shot `migrate` aplica Alembic como owner; API/vision-worker usam `APP_DB_USER` sem privilégios DDL.
- Migration 0070 e bootstrap revogam INSERT/UPDATE/DELETE/TRUNCATE e privilégios da sequência nas tabelas ONNX; runtime conserva apenas SELECT.
- O provider não regista releases no arranque. O perfil one-shot `register-model-release` valida assinatura/digests e exige o owner das tabelas.
- Verificações e registos partilham advisory transaction lock por deployment; o runtime não necessita de UPDATE/SELECT FOR UPDATE.
- Smoke `postgres_runtime_role_smoke.py` verifica leitura, ausência de privilégios de escrita e recusa efectiva de mutações; integrado no API CI e Docker Compose.
- ADR: [ADR-009 — Isolar o estado de confiança de releases ONNX](architecture/adr-009-onnx-trust-state-privileges.md).
- API CI [45076219787](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219787), Quality Gates [45076219801](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219801), Security Scans [45076219740](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219740) e Docker Compose [45076219751](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219751) passaram no HEAD `aeff4a3b`; suite API 1552 passed, 1 skipped.
- O serviço `provision-runtime-role` reconcilia volumes existentes antes de migrations; API CI, Quality Gates, Security Scans e Compose passaram no SHA `fcd19a3a` (1552 passed, 1 skipped). O Compose smoke simulou uma tabela pertencente ao runtime e uma membership herdada, confirmando a reparação. Continua pendente um ensaio com volume persistente real entre reinícios e uma validação mais ampla dos fluxos operacionais com o runtime.

### Segurança PostgreSQL — trust state ONNX read-only para runtime (22-11-2026; CI validada)

- Migration `0070_vision_model_trust_runtime_readonly` revoga privilégios de escrita nas tabelas de confiança ao principal runtime; o bootstrap executado pelo serviço `provision-runtime-role` aplica a mesma regra em volumes novos e existentes.
- `register_vision_model_release.py` regista apenas releases Ed25519 válidas, com digests verificados, através do owner das tabelas; Compose disponibiliza a operação num perfil one-shot.
- API/worker apenas lêem o trust state. Advisory transaction lock serializa inferência/publicação com registo de releases sem UPDATE.
- Testes estáticos, migration SQLite dialect-safe e smoke PostgreSQL com tentativa real de DML directo adicionados.
- A camada foi validada no HEAD `aeff4a3b`: API CI, Quality Gates, Security Scans e Docker Compose passaram; suite API 1552 passed, 1 skipped.
- Não existem ainda pesos ONNX ou dataset autorizado; o provider real permanece desligado.


### Provisionamento recorrente do principal runtime (22-11-2026; CI validada)

- Novo serviço one-shot `provision-runtime-role` executa o script idempotente via TCP depois de a base de dados ficar saudável e antes de Alembic.
- O serviço reconcilia utilizador, senha, memberships, ownership, privilégios DML operacionais e revoga escrita no trust state; não depende de `initdb.d` nem de volumes vazios.
- Runtime passa a `NOINHERIT`; smoke PostgreSQL verifica `rolinherit=false`.
- API/worker dependem do sucesso de provisioning e migrations; falha de provisionamento impede o arranque.
- CI API/Quality/Security/Compose passou no HEAD `aeff4a3b`. O smoke Compose simulou ownership e membership legados e confirmou a reconciliação; continua pendente um ensaio operacional com volume persistente real preservado entre reinícios, fora do runner efémero.


### 2026-11-23 — Controlos positivos same-store com IDs logísticos reais

- O smoke PostgreSQL multi-loja passou a criar packaging CASE e paletes válidas nas duas lojas.
- As 23 leituras same-store passaram a incluir cálculo de unidades, plano de rotação de palete e eventos de palete, anteriormente excluídos por falta de dados válidos.
- As leituras cross-store usam o ID real da palete da loja estrangeira; os controlos positivos usam o ID da palete própria. Isto evita falsos positivos por HTTP 404 causado por IDs inexistentes.
- Commit de implementação: `3af7a02b`.
- Validação CI/PostgreSQL 16 pendente; não considerar a ampliação validada até o workflow terminar com sucesso.
- A matriz endpoint × perfil × loja, a auditoria de IDs aninhados e o ensaio de volume PostgreSQL persistente continuam em aberto.


### Evidência CI — smoke inicial de leituras multi-loja (2026-11-23)

- API CI [45131503709](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503709) passou no SHA `40f9456a`, com PostgreSQL 16, todos os smokes e **1555 passed, 1 skipped**.
- Docker Compose [45131503757](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503757) passou.
- No Quality Gates [45131503760](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503760), Web build passou, mas o job API foi cancelado durante instalação. Em Security Scans [45131503689](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503689), Gitleaks/npm audit passaram e pip-audit/ZAP foram cancelados.
- O commit posterior `3af7a02b` acrescentou controlos same-store para paletes/embalagem; necessita de validação CI própria.


### 2026-11-23 — BOLA: IDs aninhados de paletes entre lojas

- O smoke PostgreSQL multi-loja inclui agora dois ataques em que o supervisor da loja A fornece um `store_id` autorizado, mas referencia uma palete real da loja B.
- Foram cobertos o planeamento de rotação e a consulta de eventos de ciclo de vida; ambos têm de responder HTTP 404.
- Commit: `db177bce`.
- A alteração está publicada em `main`; API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose ainda não foram confirmados para este SHA.
- Próxima expansão: IDs de localização, shelf, tarefa, packaging e relações indirectas. Não considerar a auditoria BOLA/IDOR global concluída.


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


## 2026-11-23 — Regressão do worker Edge após perda de lease (validação pendente)

- Acrescentados testes para os caminhos de sucesso, erro transitório e erro permanente quando o heartbeat perde a lease durante a execução do handler.
- O worker deve abandonar o resultado local; não pode confirmar, reprogramar retry nem enviar para dead-letter sem lease válida.
- Commit de teste: aec6f2b1701e2fcb92e51ba981c9819d8347c683.
- Os quatro workflows foram iniciados; aguarda-se conclusão de API CI, Quality Gates, Security Scans e Docker Compose.
- A cobertura actual de erro usa SQLite e não substitui um teste PostgreSQL com takeover concorrente e fencing.


## 2026-11-23 — BOLA: recursos aninhados de prateleira (validação pendente)

- Ampliado postgres_inventory_authorization_smoke.py com observações, sessões de captura, alertas e eventos reais de loja estrangeira.
- Testadas tentativas cross-store de criar observações/sessões/planogramas, ler consenso/planogramas/eventos e filtrar listagens por shelf_id estrangeiro.
- Controlos same-store para observação e sessão de captura mantêm HTTP 201.
- Commits: d4429b0fa1ab3d2c729d6c5b8b29f38dc5cdf731 e 99a69a7415bc552b0cf104861d93881dac6259e1.
- CI/PostgreSQL 16 do SHA final ainda pendentes.
- A cobertura actual continua centrada no actor SUPERVISOR e nos recursos escolhidos; não representa a matriz completa de todos os papéis e endpoints.


## 2026-11-23 — Extensão da matriz de papéis no smoke multi-loja

- ADMIN confirma visibilidade das fixtures reais estrangeiras (observação, sessão e alerta).
- EMPLOYEE é recusado em observações, sessões de captura, alertas e planogramas, inclusive na própria loja, de acordo com a política explícita RBAC.
- Commit: 26a97f7136eace2bc0b4f428731db3990163aa93.
- CI/PostgreSQL 16 pendentes; a matriz integral por endpoint e papel continua em aberto.


## Evidência de execução — smoke BOLA/RBAC (2026-11-23)

- O passo PostgreSQL 16 **Verify PostgreSQL inventory and warehouse cross-store authorization** passou no API CI [45177953932](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45177953932), para o commit de código `26a97f7136eace2bc0b4f428731db3990163aa93`.
- Docker Compose Smoke [45177953980](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45177953980) passou.
- A suite pytest completa ainda estava em execução; Quality Gates e Security Scans foram cancelados e permanecem por repetir.


## 2026-11-23 — Ocultação de IDs directos de ciclo de vida de paletes

- Reposto o modo `hide_foreign=True` na rota de escrita de eventos de ciclo de vida de paletes.
- Regressão coberta por pedido autenticado contra uma palete estrangeira real e contra um ID inexistente; ambos devem devolver 404 sem persistir eventos nem alterar estado.
- A decisão segue o contrato de não divulgação já aplicado à alteração de políticas de rotação e mantém a autorização antes dos locks PostgreSQL.
- Commits: `4873087c` e `ecc652e5`.
- Validação CI do novo HEAD pendente; não considerar a tarefa concluída até os workflows relevantes terminarem.


## 2026-11-23 — BOLA: criação de prateleiras por zona (validação pendente)

A rota POST /api/v1/shelves passa a validar o store_id da zona antes de criar a prateleira. SUPERVISOR não pode usar um zone_id estrangeiro; zonas estrangeiras e IDs inexistentes devolvem HTTP 404 equivalente. O teste autenticado cobre tentativa cross-store, controlo positivo same-store e ausência de persistência. Commits: aa46a255 (código), 716c359 (teste). CI/PostgreSQL 16 pendente.


## 2026-11-23 — BOLA: associação de produtos a prateleiras (validação pendente)

POST /api/v1/shelf-products valida agora o actor antes de resolver shelf_id e oculta prateleiras estrangeiras com HTTP 404, igual ao caso inexistente, antes de bloquear o produto. A regressão autenticada verifica ausência de associação cross-store e criação same-store válida. Commits: 6a4b783 (código), 78d07d3 (teste). CI/PostgreSQL 16 pendente.


## 2026-11-23 — BOLA: IDs directos de tarefas e eventos (validação pendente)

A leitura de eventos de tarefa autentica o actor antes de resolver task_id e oculta IDs estrangeiros com HTTP 404 igual ao caso inexistente, sem row lock na rota GET. A alteração de estado e a reconciliação usam _lock_store_scoped_record com hide_foreign=True. Testes cobrem igualdade das respostas cross-store/inexistente, ausência de eventos/alterações e ausência de movimentos de inventário em reconciliação negada. Commits: 954f973 (GET), ee40b88 (PATCH/reconciliação), f12ed7b e cc3dc3a (testes). CI/PostgreSQL 16 pendente.


## 2026-11-23 — BOLA: IDs de evidência de visão computacional (validação pendente)

Os endpoints de eventos de retenção, revisão de deteções e revisão de exemplares autenticam o actor antes de resolver IDs diretos. Recursos de outra loja são ocultados com HTTP 404 equivalente ao ID pai inexistente; a rota GET não adquire row lock e a ordem de locks imagem → produto → exemplar permanece inalterada. Testes cobrem IDs estrangeiros/inexistentes e controlos de operação same-store. Commits: e402eda, 956431e, 11305cc, 1420ed4 e 57cdab3. A expectativa do smoke PostgreSQL para warehouse placement foi alinhada em 9f5ebe0. CI atual ainda em execução.


## 2026-11-23 — BOLA: IDs de upload e sessão de captura (validação pendente)

O upload de imagens valida o actor antes de resolver shelf_id e oculta prateleiras estrangeiras como inexistentes. O capture_session_id opcional usa preflight tenant, lock e revalidação, com HTTP 404 uniforme para sessão estrangeira/inexistente. Testes verificam a equivalência das respostas e ausência de efeitos laterais em ficheiros e registos. Commits: 90bd84f, 91da9f1, fdcbd55, 30f0dda, 0d7a079 e 3e1ac0a. CI do HEAD final pendente.


### Validação PostgreSQL — deteções e exemplares

O smoke postgres_detection_exemplar_prelock_smoke.py foi atualizado após a alteração deliberada do contrato cross-store de HTTP 403 para HTTP 404 uniforme. O teste continua a manter as locks da imagem e do produto ocupadas e exige que os três pedidos sejam recusados antes de aguardar por elas, sem persistir revisões. Commit de correção: 31e6c9f. Nova execução CI pendente.


## 2026-11-23 — Validação P0 concluída

O commit `1ffe4d3a7567c486f68de5e26051f7bcc0a2c110` concluiu com sucesso a validação da ronda de isolamento multi-tenant: API CI com 1595 testes aprovados e 1 ignorado; smoke tests PostgreSQL 16; Quality Gates; Security Scans (secret scan, dependências Python/Web e OWASP ZAP passive baseline); e Docker Compose demo stack. A primeira execução revelou expectativas 403 obsoletas e uma fixture duplicada; ambas foram corrigidas e a execução final passou. A próxima ronda continua a auditoria de IDs aninhados em OCR, matching, artefactos e warehouse.

## Segurança P0 — histórico de tarefas com predicado SQL multi-tenant (2026-11-23; validação pendente)

A rota `GET /api/v1/tasks/{task_id}/events` filtra `task_id` e `store_id` na query para SUPERVISOR, evitando materializar uma tarefa estrangeira antes da autorização. ADMIN conserva visibilidade global. A regressão verifica 404 indistinguível para tarefa estrangeira/inexistente e acesso ADMIN. API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose do SHA final pendentes.


## Segurança P0 — preflight SQL multi-tenant para detection_id (2026-11-23; CI pendente)

Os endpoints de revisão humana, histórico e criação de observação resolvem agora a imagem de origem através de JOIN Detection → ShelfImage → Shelf → Zone. Para actores não ADMIN, o predicado de loja é aplicado no SELECT, evitando materializar uma detecção estrangeira antes da autorização. Mantém-se a autorização pré-lock e a revalidação pós-lock da imagem. Testes cobrem IDs estrangeiros/inexistentes e os contratos HTTP. API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose pendentes.



## Inventário — histórico operacional e reconciliação

O histórico de movimentos tem agora uma interface integrada no dashboard, com filtros por produto/tarefa, indicadores e detalhe da linhagem dos snapshots. A consulta é read-only e respeita RBAC e âmbito de loja. A rota foi adicionada à matriz explícita de políticas, depois de a execução anterior de API CI ter identificado a ausência dessa classificação.

Próxima fatia funcional: modelar divergências entre observações visuais e inventário de referência, mantendo a observação como evidência independente e exigindo revisão humana antes de qualquer ajuste contabilístico. A modelação deverá preservar a distinção entre stock de retaguarda, reservado, disponível, transferido para a prateleira e observado visualmente.


## Dashboard — precisão do KPI de urgência

O contador de tarefas urgentes foi alinhado com a taxonomia de prioridades: apenas tarefas `URGENT` activas entram no KPI. Prioridade `HIGH` permanece distinta e visível na distribuição por prioridade.


## 2026-11-23 — Histórico operacional de inventário

O dashboard inclui agora a consulta do histórico de movimentos, com filtros, métricas e detalhe da linhagem dos snapshots. O painel é read-only e visível a ADMIN/SUPERVISOR. A política RBAC explícita inclui a rota de movimentos. A execução TypeScript/build passou; a suite API revelou um KPI de urgências que incluía HIGH indevidamente. A query foi corrigida para contar apenas URGENT, ficando a validação final do novo SHA pendente.

Próxima entrega: divergências auditáveis entre observação visual e stock de referência, sem ajustes contabilísticos automáticos; em paralelo, definir a semântica dos diferentes estados/localizações do stock com base nos modelos existentes.


## Inventário — reconciliação operacional integrada
O dashboard passa a apresentar, em separado, o objetivo de exposição, a última quantidade observada na prateleira e o snapshot autoritativo da retaguarda (on-hand, reservado e disponível). A diferença é uma métrica de exposição e não uma divergência contabilística. A interface expõe idade/fonte dos dados e ausência de evidência; não altera inventário. Próxima evolução: workflow de divergências formais com revisão humana, estados e trilho de auditoria, sem reconciliação automática de quantidades contabilísticas.

## 2026-11-24 — Frescura temporal das observações na reconciliação

A resposta de reconciliação inclui agora `observation_age_minutes`, permitindo avaliar a idade da evidência visual sem confundir dados antigos com medições actuais. Não é imposto um limite de obsolescência até existir uma política operacional configurada. A ausência de observação continua representada por `null`. Teste com relógio controlado: 90 minutos; CI pendente.



### Integridade da criação de tarefas — revalidação sob lock

A criação a partir de recomendação recalcula agora a recomendação depois de adquirir o lock estável da loja. Isto evita usar uma decisão calculada antes da secção crítica quando os dados de stock ou evidência podem ter mudado. A garantia depende de os escritores concorrentes de inventário respeitarem o mesmo lock; validar em PostgreSQL 16 e com teste concorrente dedicado.


### Validade temporal do inventário de retaguarda

O motor de recomendações aplica agora a política de frescura por loja e origem aos snapshots de retaguarda. Evidência antiga ou futura deixa de suportar recomendações accionáveis e impede a criação de tarefas derivadas. Estados novos: `STALE_INVENTORY` e `INVALID_INVENTORY_TIMESTAMP`. A validação automatizada está publicada, mas aguarda execução em CI/PostgreSQL.


### Distribuição operacional de tarefas

A API disponibiliza agora uma primeira distribuição automática de tarefas pendentes por funcionário, usando carga activa, prioridade e continuidade de zona. A atribuição fica registada no histórico da tarefa. A evolução seguinte deverá incorporar turnos, competências, disponibilidade e capacidade horária, sem inferir esses dados a partir do histórico.


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


## 2026-11-24 — Reconciliação multi-fonte ERP/WMS (implementação publicada; validação pendente)

- API: últimos snapshots ERP e WMS independentes por loja/produto, com on-hand, reservado, disponível, timestamp, idade e estado de frescura.
- A diferença WMS−ERP só é calculada quando ambas as fontes estão presentes e dentro da política de frescura; caso contrário, a resposta identifica `MISSING_ERP`, `MISSING_WMS`, `STALE_SOURCE` ou `INVALID_TIMESTAMP`.
- Dashboard: domínios ERP e WMS apresentados separadamente e divergência operacional evidenciada sem qualquer mutação de stock.
- Teste dedicado cobre divergência de quantidades disponíveis e garante que a leitura não cria movimentos nem snapshots.
- Corrigidas três falhas da suite API detectadas no workflow anterior, relacionadas com import de HTTPException, fixture de observação sem associação SKU/prateleira e fixture que tentava repetir a transição para ASSIGNED.
- API CI, Quality Gates, Web CI, Security Scans e Docker Compose do HEAD final ainda pendentes.
- Não existe ainda adapter ERP/WMS real; a comparação depende de snapshots previamente ingeridos e não constitui ajuste contabilístico.


## Ledger auditável — P0 implementado; CI pendente

- Ledger persistente por loja, prateleira e produto.
- Snapshot imutável de contagem de prateleira, WMS, ERP, IDs, timestamps e diferenças.
- Workflow de revisão humana maker-checker com decisão justificada e eventos append-only.
- Triggers protegem a evidência e o histórico de auditoria.
- Interface React para criar registos e rever pendentes.
- Separação explícita face a `inventory_movements` e aos saldos contabilísticos.
- Próximos passos: dashboard agregado, adapters reais ERP/WMS e histórico de sincronizações.


### ERP/WMS — orquestração inicial
A camada de serviço já liga adapters configurados no deployment ao ledger e aos snapshots. A migração 0078 cria mappings explícitos por loja/fonte; a 0079 permite registar o external_run_id na única transição STARTED → SUCCESS/PARTIAL/FAILED, sem reabrir ou alterar execuções concluídas. O orquestrador executa páginas em transacções independentes e deixa evidência das páginas confirmadas se uma página posterior falhar.

Continua pendente: API de gestão de mappings, worker durável/scheduler, secret manager e adapter real homologado. O serviço não cria reconciliações nem aprova divergências.


### Administração segura dos mappings externos
A gestão de SKU externos passa a estar disponível por API autenticada e limitada à loja do utilizador (ADMIN pode gerir todas as lojas; SUPERVISOR apenas a sua). Criação requer integração activa e produto interno activo. Alterações exigem motivo, são auditadas e não alteram a identidade externa do mapping. Desactivação substitui eliminação; histórico append-only protegido por triggers.

Próximo marco operacional: worker durável com leases/fencing e recuperação segura, seguido de secret manager e adapter real homologado.


## 2026-11-25 — Concorrência e recuperação de workers ERP/WMS

O API CI passa a executar um smoke dedicado em PostgreSQL 16 com dois claims concorrentes, takeover de lease, rejeição do worker antigo e interrupção real de um processo com SIGKILL após a confirmação da tentativa STARTED. A recuperação deve finalizar o ledger como PARTIAL, com evento COMPLETED e contagens desconhecidas.

Limite da evidência: este smoke não mata o processo depois de confirmar uma página de inventário nem verifica o replay idempotente dos snapshots. Esse cenário continua como próximo teste de integração do orquestrador.


## 2026-11-25 — Prova de crash após commit de página ERP/WMS

O smoke PostgreSQL 16 passa a executar o orquestrador de sincronização com um adapter determinístico. O worker confirma a primeira página, bloqueia na obtenção da segunda e é terminado com SIGKILL. Um novo worker recupera o lease, confirma o ledger anterior como PARTIAL e repete a primeira página. A prova verifica que o snapshot mantém o mesmo ID e conteúdo e que não é duplicado, enquanto uma referência da página seguinte é persistida normalmente.

A validação depende do resultado verde do API CI no SHA final; a existência do passo no workflow não constitui, por si só, evidência de execução bem-sucedida.


## 2026-11-25 — Regressão multi-loja da reconciliação com SKU global partilhado

- Adicionado teste HTTP em apps/api/tests/test_inventory.py para o mesmo produto global associado a prateleiras em duas lojas.
- Snapshots ERP/WMS com quantidades e IDs diferentes são criados por loja; o teste verifica que a reconciliação e o ledger da loja A só devolvem evidência da loja A.
- A revisão directa de uma reconciliação da loja B por SUPERVISOR da loja A tem de devolver 404 sem alterar o estado PENDING.
- Commit de teste: 07b141b91d2d76a6ff6e1cefe0e721cf42978e8b. API CI, Quality Gates, Security Scans e Docker Compose ainda pendentes neste SHA.
- Em aberto: definir a semântica de fonte/localização para o snapshot genérico apresentado como retaguarda. A enumeração actual ERP/WMS/POS/MANUAL/IMPORT não prova, por si só, que uma fonte represente stock físico de retaguarda; não assumir equivalências.


## 2026-11-25 — Ledger de eventos dos movimentos: fase 1 implementada, CI pendente

A migration 0087 cria um ledger append-only com identidade de operação, movimento, loja, actor, motivo, timestamp e evidência. A reconciliação regista MOVEMENT_RECORDED na mesma transacção que o movimento e o snapshot resultante. A leitura é read-only e limitada por RBAC/tenant. Os testes cobrem rollback se o evento falhar, isolamento cross-store e imutabilidade SQLite. A validação dos quatro workflows no novo SHA é obrigatória antes de declarar a fase concluída.

A confirmação WMS, compensações e divergências permanecem pendentes; não há adapter WMS homologado nem evidência externa. A unidade base e as conversões unidade/caixa/palete continuam por definir.


## 2026-11-25 — Concorrência da reconciliação de movimentos

- [x] Adicionar smoke PostgreSQL 16 com duas tarefas do mesmo SKU a disputar simultaneamente o mesmo snapshot WMS.
- [x] Incluir uma unidade reservada e confirmar que a disponibilidade efectiva é seis, não sete.
- [x] Exigir exactamente uma reconciliação aprovada, um movimento, um snapshot resultante e um evento de auditoria; a segunda operação deve falhar por stock insuficiente.
- [x] Verificar retry idempotente da tarefa vencedora, sem criar novo movimento.
- [ ] Confirmar execução do novo smoke e os quatro workflows no SHA final.
- [x] Acrescentar prova PostgreSQL de rollback integral quando a inserção do evento de movimento falha (execução CI pendente).

A serialização depende dos locks de produto e snapshot no endpoint de reconciliação. O smoke exercita pedidos HTTP concorrentes com sessões de base de dados independentes; testes SQLite não substituem esta prova PostgreSQL.


## 2026-11-25 — Migration 0088: disponibilidade WMS na fronteira de movimentos

- [x] Reforçar trigger PostgreSQL e SQLite para exigir `availability_status=AVAILABLE` no snapshot WMS de origem de qualquer novo movimento.
- [x] Preservar snapshots e movimentos históricos sem backfill ou mutação.
- [x] Testar AVAILABLE/UNAVAILABLE/UNKNOWN e downgrade em SQLite.
- [x] Acrescentar prova PostgreSQL por INSERT directo com tarefa, quantidade e snapshot resultante coerentes.
- [ ] Validar migration 0088, smoke e workflows no SHA final.

A frescura continua dependente da política por loja e é validada pelo serviço; a migration não introduz um limite temporal global.


## 2026-11-25 — Unidade base congelada nos movimentos (0089)

- [x] Persistir `unit_code` copiado de `Product.unit` em movimentos novos.
- [x] Rejeitar INSERT directo com unidade vazia ou diferente da unidade base do SKU em PostgreSQL/SQLite.
- [x] Não preencher unidade nos movimentos históricos sem prova temporal.
- [x] Expor `quantity_exact` e unidade na API e evidência de auditoria.
- [x] Rejeitar precisão superior a três casas decimais na conclusão da tarefa, antes de persistir, com validação defensiva na reconciliação.
- [x] Corrigir a interface para não somar quantidades de unidades incompatíveis.
- [ ] Validar migration 0089, suite API, PostgreSQL smoke e workflows no SHA final.

O contrato actual usa a escala persistida `NUMERIC(12,3)`. A conversão de embalagens continua explícita através dos níveis de embalagem do produto.


## 2026-11-25 — Planeamento de embalagens com Decimal exacto

- [x] Preservar valores Decimal exactos no resultado do cálculo UNIT/CASE/PALLET.
- [x] Manter compatibilidade dos campos numéricos e acrescentar campos `*_exact` textuais.
- [x] Validar quantidades fraccionárias, caixa aberta/fechada, unidade e palete.
- [x] Garantir que o cálculo não executa movimentos de stock.


## 2026-11-25 — Skew temporal ERP/WMS (migration 0093)

A reconciliação mede e expõe o skew absoluto de captura. A política ERP por loja pode definir tolerância opcional de 0–10080 minutos; NULL significa não configurada. Sem tolerância, timestamps diferentes não produzem delta nem DIVERGENCE. Acima do limite configurado, a comparação quantitativa também é suspensa. Só dentro do limite se comparam quantidades. A configuração exige motivo e fica auditada no ledger append-only. Não existe valor operacional por defeito.

A migration 0093 e os testes SQLite/API foram preparados; validação PostgreSQL 16 e workflows GitHub no SHA final ainda pendentes.


## 2026-11-25 — Retenção da hierarquia e imutabilidade da auditoria de tarefas (0096–0098)

- [x] Bloquear eliminação de prateleiras/zonas com histórico de tarefas.
- [x] Proteger eventos de tarefa contra UPDATE/DELETE e congelar a identidade da tarefa após o primeiro evento.
- [x] Bloquear cascades sobre imagens, sessões, observações, alertas, associações, planogramas, reconciliações e inbox Edge.
- [x] Validar retenção de imagem ACTIVE com legal hold sem tarefa associada em PostgreSQL 16.
- [x] Expor a proveniência física do destino no histórico Web de movimentos.
- [x] API CI **1725 passed, 1 skipped**, Quality Gates, Security Scans e Docker Compose aprovados no SHA `7bf95468320fc1dd4ab992b520e855d463b6e1f6`.

Arquivamento/soft-delete continua condicionado a requisito operacional; a eliminação física não é alternativa à retenção.


## 2026-11-25 — Transições concorrentes do ciclo de vida das tarefas validadas

O endpoint de transição usa lock pessimista da linha da tarefa e revalida o estado após o lock. O smoke PostgreSQL 16 prova que duas atribuições concorrentes produzem apenas um evento; uma conclusão concorrente com cancelamento produz exactamente um vencedor e um HTTP 409; a auditoria reflecte o estado vencedor e não existe segunda transição terminal. A falha forçada após flush do evento reverte tanto a alteração do estado como o evento. A repetição de cancelamento é rejeitada e a tarefa terminal não pode ser reaberta.

**Evidência:** SHA `cfeeab3f4e092709de9eccb0dfc54397f72f12af`; API CI `45689904464` — **1725 passed, 1 skipped**; Quality Gates `45689904362`, Security Scans `45689904247` e Docker Compose `45689904380` — sucesso.

**Próxima revisão:** consistência temporal de `started_at`/`completed_at` e política de atribuição/reafectação. Não introduzir regras de negócio sem requisito operacional aprovado.


## 2026-11-25 — Autorização do histórico de eventos de tarefas

A política central classifica `GET /api/v1/tasks/{task_id}/events` como `SUPERVISOR_OR_ADMIN`. O handler reforça explicitamente esta fronteira: EMPLOYEE recebe HTTP 403 para qualquer tarefa, incluindo as que lhe estão atribuídas. SUPERVISOR consulta apenas a sua loja; ADMIN mantém acesso global. O teste exercita tarefa própria, tarefa de colega, tarefa não atribuída e ID inexistente para provar a negação consistente.

**Evidência:** SHA `f925b875f871964ce80805c4927af15616f58774`; API CI `45716057516`, Quality Gates `45716057563`, Security Scans `45716057667` e Docker Compose `45716057580` — todos com sucesso.


## 2026-11-25 — Defesa em profundidade do RBAC de eventos de paletes

Os handlers GET e POST do histórico/ciclo de vida de paletes agora repetem a autorização `SUPERVISOR_OR_ADMIN` já declarada na política central. Funcionários recebem 403 antes da leitura ou mutação. O teste confirma que a tentativa de escrita não altera o estado nem acrescenta evento e que um supervisor autorizado consegue ler e registar uma transição válida.

**Evidência:** SHA `50df52e59eca47aa2dfc868fc16621cf2f636586`; API CI `45716912538`, Quality Gates `45716912911`, Security Scans `45716912543` e Docker Compose `45716912421` — todos com sucesso.


## 2026-11-25 — RBAC explícito em snapshots de inventário e catálogo de lojas

Os handlers de criação de snapshots, listagem e consulta do snapshot mais recente agora exigem ADMIN/SUPERVISOR independentemente da origem do snapshot. A criação não permite que um perfil EMPLOYEE injete dados WMS/ERP/POS/IMPORT só porque a regra anterior de perfil estava condicionada a MANUAL. O GET `/api/v1/stores` também reforça no handler a política de leitura ADMIN/SUPERVISOR. A regressão inicial da listagem foi identificada pelo Quality Gates, corrigida e validada na execução seguinte.

**Evidência:** SHA `19bf8dd2bf2b6990faff261effc0752523f59a5b`; API CI **1728 passed, 1 skipped**; Quality Gates, Security Scans e Docker Compose — sucesso.


## 2026-11-25 — RBAC explícito nos writes POS de vendas e tráfego

Os endpoints de registo horário, batch e importação CSV de vendas/tráfego passaram a repetir no handler a exigência ADMIN/SUPERVISOR da política central. A verificação dos imports é feita antes da leitura do ficheiro. O teste usa actor EMPLOYEE e prova que os seis endpoints respondem 403 sem persistir linhas.

**Evidência:** SHA `d36af7332544204fc14b6764a3faf99c24aa4741`; API CI **1729 passed, 1 skipped**; Quality Gates, Security Scans e Docker Compose — sucesso.


## 2026-11-25 — Autorização da persistência OCR e fusão de evidência

Os handlers que persistem OCR runs, matches OCR→catálogo e fusão visual/textual repetem a política ADMIN/SUPERVISOR. A negação de EMPLOYEE ocorre antes do lock da imagem e antes de qualquer escrita; os testes confirmam ausência de registos após HTTP 403.

**Evidência:** SHA `a9271dd595c7d913a93cd969cf73d58b5e49438d`; API CI **1730 passed, 1 skipped**; Quality Gates, Security Scans e Docker Compose — sucesso.


## 2026-11-25 — RBAC das mutações de warehouse e paletes

Os handlers de criação de localizações e colocações, registo de paletes, políticas de rotação e simulação agora repetem a autorização ADMIN/SUPERVISOR da política central. A negação ocorre antes de ler ou bloquear recursos. Teste com EMPLOYEE confirma 403 nas seis operações e ausência de mutações.

**Evidência:** SHA `3f63efd0da73070cc1654e76ea58ecfe0e79ca93`; API CI **1731 passed, 1 skipped**; Quality Gates, Security Scans e Docker Compose — sucesso.

## Segurança multi-loja — revalidação da evidência de consenso (2026-11-26)

O endpoint de consenso aplica agora o tenant scope na própria query de observações e na validação da associação SKU/prateleira. A regressão determinística cobre a transferência da zona entre o preflight da prateleira e a leitura da evidência. A implementação e o teste foram publicados; a validação no API CI/PostgreSQL 16 e nos restantes workflows permanece pendente. Isto não encerra a matriz BOLA/IDOR.




## 2026-11-26 — API de associação operacional Edge dispositivo-tarefa

Foi implementado o primeiro fluxo operacional da associação Edge: serviço transaccional de criação/revogação, schemas, endpoints autenticados ADMIN/SUPERVISOR e política central explícita. A associação captura a versão da tarefa e regista CREATED/REVOKED no ledger append-only dentro da mesma transacção que altera a associação. A ordem de locks é Store → Task → Device → Assignment. A validade exige timestamps timezone-aware e o fim, quando definido, tem de ser posterior ao início.

**Validação pendente:** quatro testes de serviço e um smoke PostgreSQL 16 para corridas de criação/revogação foram adicionados; o smoke está ligado ao API CI. Aguardar resultados de todos os workflows no SHA final que inclui o smoke. A existência da API não autoriza ainda o handler `TASK_ACKNOWLEDGED`: a persistência do acknowledgement e a conclusão do inbox continuam a ter de ser atómicas sob fencing. A auditoria BOLA/IDOR permanece adiada.


## Edge worker — fronteira transaccional para handlers (2026-11-27)

- Criada a via explícita `transactional_handlers`: o handler recebe a mesma sessão SQLAlchemy usada para finalizar o processamento.
- A função `complete_edge_event_transactionally` bloqueia a linha de processamento, valida estado, owner, fencing token e expiração, executa operações de base de dados e confirma `PROCESSED` na mesma transacção.
- Qualquer excepção faz rollback dos efeitos do handler e da conclusão. O worker tenta aplicar retry/dead-letter separadamente, sempre sob fencing; se o lease já não for válido, não altera o estado.
- Os handlers legados mantêm-se separados. `TASK_ACKNOWLEDGED` continua desactivado; falta implementar ledger de acknowledgements, validar associação/versão e criar smoke PostgreSQL concorrente.
- Foram adicionados testes para commit conjunto, rollback e worker transaccional. Validados no SHA `5072f05c9ffb5dc2576e5eb8a6e4be7b033263ae`: API CI/PostgreSQL 16 **1755 passed, 1 skipped**; Quality Gates (API e Web), Security Scans (Python, Web, Gitleaks e OWASP ZAP) e Docker Compose — sucesso.
- Correcção de relógio: `complete_edge_event_transactionally` aceita `now` opcional para testes determinísticos; em produção usa UTC real. Os testes injectam o instante posterior ao claim sem falsear a duração do lease.
- Próximo: ledger append-only de acknowledgements, ligação ao evento da inbox, validação de associação activa e `task_version`, idempotência/conflitos de `event_id`, e smoke PostgreSQL 16 dedicado a fencing/concorrência/leases obsoletos. `TASK_ACKNOWLEDGED` permanece desactivado.


## 2026-11-27 — Edge Task Acknowledgement Ledger: primeira camada

A migration 0103 introduz um ledger append-only independente, ligado por chaves estrangeiras compostas ao evento autenticado da inbox e à associação dispositivo-tarefa versionada. O serviço de aplicação valida loja, dispositivo activo, associação não revogada, validade temporal e revisão da tarefa. As declarações COMPLETED são persistidas como REVIEW_REQUIRED e não alteram a tarefa nem o inventário.

A fronteira transaccional existente passa a fornecer o fingerprint do evento original ao handler. O handler continua desactivado: falta fechar cobertura de replay, fencing/rollback, concorrência PostgreSQL 16 e CI integral antes de qualquer registo de rota.


### 2026-11-27 — Validação defensiva adicional do Edge ACK

A validação de `action` rejeita agora explicitamente valores que não sejam texto, incluindo listas, objectos, booleanos e números. Foram acrescentados cinco casos parametrizados para garantir `INVALID_ACK_ACTION` sem persistência. A execução dos testes e os workflows CI continuam pendentes; não activar a registry por omissão. A revisão também confirmou que o smoke PostgreSQL existente ainda não cobre concorrência entre revogação e ACK nem isolamento adversarial cross-store — estas provas permanecem em falta.


## 2026-11-27 — Regressão CI do worker Edge ACK identificada e corrigida

- A API CI `45994745435` no commit `09fc570e7032aa66fa6f8c16f4a998f988509bed` executou PostgreSQL 16 e os smokes anteriores com sucesso, mas a suite terminou com `1 failed, 1764 passed, 1 skipped`. A falha foi `test_worker_routes_task_acknowledgement_through_fenced_transaction`: `occurred_at` foi lido da inbox SQLite sem `tzinfo`, levando o serviço a rejeitar um timestamp já normalizado na ingestão.
- Corrigido em `6c4379ecc85bbe4e43d276ac97af01cce5a81520`: o timestamp persistido da inbox é normalizado com `_database_utc`, tal como os timestamps persistidos da associação. O timestamp externo continua sujeito à validação estrita no ponto de ingestão.
- Acrescentados quatro cenários parametrizados de identidade cross-store em `test_edge_task_acknowledgement_service.py` (tarefa estrangeira, dispositivo estrangeiro, loja estrangeira com tarefa local e conjunto de identidades estrangeiras sem associação). Commit dos testes: `a840fac4b12d6f324c29c6a6b0b441a58aba85a5`.
- A API CI/Quality Gates/Security Scans/Docker Compose do commit `a840fac4b12d6f324c29c6a6b0b441a58aba85a5` foi observada em execução; a validação do commit corretivo `6c4379e` ainda tem de ser confirmada. Não declarar suite aprovada.
- A prova PostgreSQL de concorrência entre revogação e processamento ainda não foi acrescentada; manter este ponto explicitamente aberto. A registry permanece opt-in e `COMPLETED` continua apenas `REVIEW_REQUIRED`.


## 2026-11-27 — P0 Edge ACK vs revogação: concorrência PostgreSQL 16 validada

O smoke `apps/api/scripts/postgres_edge_task_acknowledgement_smoke.py` prova as duas ordens concorrentes. A prova de bloqueio não depende de sleeps como evidência: consulta `pg_stat_activity`, exige `wait_event_type='Lock'` e confirma o PID bloqueador através de `pg_blocking_pids()`.

**Revogação primeiro:** a transacção de revogação obtém os locks na ordem Store → Task → Device → Assignment. O ACK bloqueia efectivamente; após commit da revogação, retoma e é rejeitado como `UNASSIGNED_DEVICE`, sem registo no ledger.

**ACK primeiro:** o ACK obtém os locks e mantém a transacção aberta. A revogação fica bloqueada; após commit do ACK, a revogação retoma e confirma. O acknowledgement permanece no ledger com `received_at` anterior a `revoked_at`.

A primeira CI encontrou `DetachedInstanceError`, corrigido pela captura dos identificadores antes de fechar as sessões. A execução seguinte expôs a reutilização do mesmo par dispositivo/tarefa entre cenários; o cenário B passou a usar um dispositivo independente, respeitando a unicidade histórica das associações.

**Evidência:** SHA de código `cd28865c03abaf4ccde959e098e1dcf462943299`; API CI `45998882415` (incluindo o passo de smoke PostgreSQL 16), Quality Gates `45998882598`, Security Scans `45998882484` e Docker Compose `45998882648` — todos concluídos com sucesso.

**Precisão do teste:** o cenário revogação-primeiro constrói manualmente a transacção com a ordem canónica de locks; o cenário ACK-primeiro invoca `revoke_edge_task_assignment`. Assim, a prova não deve ser descrita como exercício do serviço real nos dois cenários.

O handler `TASK_ACKNOWLEDGED` continua desactivado/opt-in. `COMPLETED` permanece evidência `REVIEW_REQUIRED`, sem alteração automática da tarefa ou inventário. A validação desta garantia de concorrência não equivale a autorização para activar o handler em produção.
