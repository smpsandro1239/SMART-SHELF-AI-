## 2026-11-19 — Separação entre revisão SKU e confirmação do estado demo

- Identificada uma lacuna no endpoint `POST /api/v1/shelf-image-detections/{detection_id}/observation`: a revisão humana do SKU era suficiente para converter `empty_facing` em observação `EMPTY`, sem confirmação explícita do estado.
- O contrato exige agora `confirmed_status`; o estado tem de corresponder à classe de demonstração e ficam registados estado, ID do utilizador confirmador e timestamp UTC na proveniência.
- A ausência de confirmação é rejeitada pela validação HTTP (422); um estado incompatível é rejeitado com 409. A revisão SKU continua obrigatória e independente.
- Foram acrescentados testes para ausência, divergência, revisão obrigatória e idempotência.
- A primeira execução API CI revelou que o smoke PostgreSQL de retenção ainda enviava o contrato antigo (`product_id` sem `confirmed_status`), terminando antes de adquirir o lock da imagem. O payload do smoke foi alinhado com o contrato novo (`confirmed_status=EMPTY`), preservando a verificação concorrente.
- A validação CI da correção permanece pendente; não foram executados testes localmente nesta ronda.

## 2026-11-19 — Comparação read-only de captura com planograma ativo

- HEAD inicial da implementação: `b8865e1ff4d86577cfc51039c4f3092242911517`; commit da implementação do serviço/API: `c484074f6e84bfa231d3e202a2bbc39eccd027d7`; testes e correção da expectativa geométrica: `4f3c9a9083b5ab2187a918927b48770ce2813cbf`.
- Criado `app.shelf_planogram_comparison` para converter as células persistidas e comparar deteções guardadas, preservando os IDs de origem.
- Adicionado `GET /api/v1/shelves/{shelf_id}/planograms/comparison/{image_id}`. Só aceita imagem da mesma prateleira com retenção ACTIVE e análise COMPLETED, exige ADMIN/SUPERVISOR e revalida o planograma ACTIVE, a imagem de calibração e os SKUs através do serviço existente.
- A resposta inclui SHA-256 da captura, versão do modelo, versão do planograma e estados por célula com facings esperados/observados, produtos e IDs das deteções.
- A comparação é calculada on-demand, sem escrita, sem criação de tarefas/observações e sem efeitos sobre inventário.
- Segurança semântica: todas as células são tratadas como sem visibilidade calibrada nesta fase. Mesmo uma deteção `empty_facing` não gera `EMPTY`; a célula permanece `UNKNOWN` até existir evidência explícita de visibilidade para aquela captura.
- Testes API acrescentados para `UNDER_FACED`, proveniência, não inferência de vazio, análise pendente, EMPLOYEE e isolamento entre lojas. Não foram executados testes localmente.
- Validação concluída no código `4f3c9a9083b5ab2187a918927b48770ce2813cbf`: API CI [44563920216](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44563920216) passou com **1337 passed, 1 skipped, 1 warning**, incluindo migrações/smoke PostgreSQL 16; Quality Gates [44564178983](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44564178983) passou com os mesmos resultados, compilação Python e build TypeScript/produção Web; Docker Compose [44563920224](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44563920224) passou.
- Limites: resultado não é persistido, não está integrado no worker nem tem UI de revisão. Sem visibilidade calibrada, não existe conclusão de vazio. A contagem de facings continua dependente da qualidade das deteções/NMS e de validação com dataset real.

## 2026-11-19 — Linhagem de outputs, autorização e propagação

- SHA inicial: 9f6e871520a1d63b1f148bcc7578c546a41d090e.
- API CI 44538123392, Quality Gates 44538123460 e Docker Compose 44538123417 terminaram com sucesso no commit inicial. API CI concluiu migrações PostgreSQL 16, smokes operacionais e suite API.
- Definida a matriz deny-by-default para operações de outputs, sem presumir que ADMIN possui autoridade legal ou que SUPERVISOR tem âmbito sobre outputs multi-origem.
- Documentada a proposta de aprovação independente: pedido e aprovação distintos, identidades diferentes, hold activo até commit atómico de aprovação + evento de libertação. O fluxo não foi activado porque faltam decisões de produto/jurídico.
- Implementada migration 0066_dataset_output_lineage, modelo DatasetExecutionJobOutputLineage e serviço app.dataset_output_lineage. A relação é append-only, rejeita ciclos e exige actor activo e callback de autorização.
- O consumidor de outputs passa a bloquear a cadeia ancestral em ordem crescente, verificar estabilidade da linhagem, autorizar cada publicação, aplicar a governação de cada nó e revalidar as fontes de todos os jobs. Um hold/restrição num pai bloqueia os descendentes.
- Documentado o contrato para propagação em caches, exports, object storage, réplicas e backups; não existem ainda adapters externos nem inventário completo.
- Testes acrescentados para ciclos/imutabilidade da migration SQLite e para herança de legal hold no consumidor. Não foram executados testes localmente. A validação CI desta alteração está pendente.
- Riscos abertos: falta smoke PostgreSQL específico da linhagem; o registo de derivação não está ligado a worker real; a matriz de autorização e a aprovação legal continuam por aprovar; cópias externas não estão inventariadas; purga física permanece desactivada.

## 2026-11-19 — Verificação CI e corrida consumo/restrição de outputs

- HEAD inicial: e5a372d00199d441b6089254133f04dfd7f99e10.
- Confirmados como concluídos com sucesso os workflows API CI 44536740007, Quality Gates 44536740024 e Docker Compose 44536739957. API CI incluiu migrações PostgreSQL 16, smokes operacionais e suite API; Quality Gates executou API, compilação Python, TypeScript e build de produção Web; Docker Compose confirmou arranque, readiness, seed e worker.
- Acrescentado ao smoke PostgreSQL um cenário concorrente: a leitura de bytes mantém os locks da publicação enquanto outra sessão tenta aplicar uma restrição. A restrição só pode confirmar depois do commit da leitura; o evento é depois libertado para não contaminar os restantes cenários do smoke.
- Não foram executados testes localmente. A validação da alteração aguarda os workflows do novo commit.
- Limites: este cenário valida serialização PostgreSQL, não define quem pode restringir/libertar; a política de autorização HTTP, aprovação independente, catálogo de derivados e cobertura de backups/caches continuam por definir/integrar.

## 2026-11-19 — Reconciliação conservadora de outputs de datasets

- HEAD inicial: `e5545ffe3e6b620f143174488bc1f43b4eecd3a5`.
- Criado `app.dataset_job_output_reconciliation` e CLI `python -m app.dataset_job_output_reconciliation`. O modo predefinido é simulação; `--apply` é obrigatório para apagar e o período predefinido é sete dias.
- Temporários de promoção só são elegíveis se o nome interno corresponder ao padrão, forem ficheiros regulares e excederem a idade mínima. Staging só é removido com uma publicação append-only correspondente, job `SUCCEEDED`, fencing token actual, destino canónico e correspondência de SHA-256/tamanho entre staging, destino e auditoria.
- Jobs `SUCCEEDED` sem publicação, symlinks, referências desconhecidas, ficheiros recentes e conteúdos divergentes são preservados. Não existe scheduler; a limpeza é manual. Jobs falhados/revogados sem referência de publicação e object storage ficam fora do âmbito.
- Testes acrescentados para dry-run, aplicação, staging sem publicação e digest divergente.
- Commit de código: `8418fe44d927f6dec9768f4ca986c78fcd253eda`. Quality Gates `44484598129` passou (suite API, compilação Python, TypeScript e build Web); Docker Compose `44484598370` passou. API CI [44484598295](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44484598295) passou, incluindo smokes PostgreSQL e suite API.
- Não foram executados testes localmente. A validação até agora provém de GitHub Actions.
- Próxima tarefa: rever permissões/ownership separados entre API e worker; só depois expandir a limpeza a staging de jobs falhados/revogados, sem assumir que processos antigos deixaram de escrever.

## 2026-11-19 — Redução da janela de locks na publicação de outputs

- HEAD inicial: 223e6699f54e0e8de7ada29cbad3619645e236f6.
- O promotor anterior mantinha locks do job, worker e credencial durante a cópia e o cálculo SHA-256 do output. Para outputs próximos do limite de 2 GiB, isso podia atrasar revogação de credenciais e operações concorrentes.
- A promoção foi dividida em preflight sem locks, preparação de um temporário privado com verificação integral de tamanho/digest e transacção final curta. A fase final volta a bloquear e revalidar o job, evento terminal, worker, credencial, expiração, revogação, scope e fencing token antes do hard link sem sobrescrita e do INSERT append-only.
- O staging só é removido depois do commit SQL. Uma falha de limpeza deixa o staging recuperável; uma interrupção após o hard link mas antes do commit continua reconciliável pela verificação do destino, efectuada fora dos locks.
- Novo teste: a preparação confirma que a sessão DB não mantém transacção; revoga a credencial durante a cópia e confirma que a revalidação final recusa a publicação, sem artefacto publicado nem linha de auditoria.
- Commit de código: `5767468ad8058a593474695b2cb0dee9ef3118e7`; commit documental: `5e84a0cec8cc15ca829aa6eda1694d8013819858`.
- API CI [44483199562](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44483199562) passou, incluindo migration PostgreSQL, smoke de publicação concorrente e suite API. Docker Compose [44483199541](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44483199541) passou. Quality Gates [44483436546](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44483436546) passou com compilação Python, suite API, TypeScript e build Web.
- Não foram executados testes localmente; a evidência é exclusivamente GitHub Actions. O smoke PostgreSQL `postgres_dataset_job_output_publication_smoke.py` foi reforçado: pausa a preparação numa thread, revoga a credencial numa segunda sessão e exige que a revogação confirme antes de libertar a preparação; a publicação tem de ser recusada depois. API CI [44485569053](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44485569053) passou.
- Próxima tarefa: desenhar reconciliador idempotente de temporários/staging órfãos com período de segurança e provas de fencing/auditoria; depois integrar outputs no catálogo com herança de retenção/legal hold.

## 2026-11-18 — Gate de aprovação obrigatório na execução de datasets

- Base de trabalho: commit documental `39d90e7a75934037fab9c5281d13a19def6e2fb6`.
- Lacuna encontrada: `dataset_execution` criava uma release a partir de manifestos/auditorias e lançava o consumidor sem invocar `dataset_approval.run_release_gate`; assim, o fluxo de execução não exigia o registo de aprovação nem validava os três documentos COCO nessa fronteira.
- A execução passa a exigir `--release-record`, `--train`, `--val` e `--test`, e executa o gate de aprovação antes de criar a release ou iniciar o processo filho.
- A identidade da release passa a incluir os hashes do registo de aprovação e do relatório determinístico do gate. O processo filho recebe o estado, modo e hashes de aprovação através de `SMART_SHELF_DATASET_APPROVAL_*`.
- A validação operacional foi movida para o fim do trabalho de ficheiros/COCO/revisão. Para fontes internas, os locks são adquiridos apenas depois dessas verificações e mantidos através da criação da release e da execução síncrona.
- Foram acrescentados testes para a ordem transaccional, recusa sem aprovação, metadados de aprovação no ambiente do consumidor, fingerprint distinta e rejeição de evidência malformada.
- Validação pendente: ainda não foram executados pytest, compilação Python ou workflows para esta alteração. Não declarar a implementação certificada até API CI/Quality Gates terminarem.
- Limites: jobs remotos/destacados continuam fora da garantia; a ferramenta COCO offline continua sem autorização operacional própria. Próxima tarefa após CI: desenhar lease/claim com fencing para consumidores distribuídos e auditar exports/caches/backups.

## 2026-11-18 — Validação da elegibilidade de datasets e linhagem HTTP de artefactos

- SHA inicial e final da base validada: `33425007fc016b220c3f49f95078444189fd1ec9`.
- API CI [44410444406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444406) terminou com sucesso. O job `test` concluiu as migrações PostgreSQL 16, todos os smokes operacionais e `Run tests`; o passo `Verify PostgreSQL dataset eligibility hierarchy lock serialization` passou.
- O smoke `postgres_dataset_eligibility_concurrency_smoke.py` usou sessões PostgreSQL independentes e observou bloqueios reais via `pg_stat_activity`/`pg_blocking_pids` para alterações concorrentes a `shelves.zone_id` e `zones.store_id`. As alterações só terminaram depois do commit da transacção do gate.
- A suite API executou `test_admin_registers_artifact_parent_lineage_over_http`: criação de raiz/descendente, listagem, retry idempotente, conflito de linhagem, pai inexistente, pai de outra imagem e pai de outra loja. Esta integração HTTP/JWT usa SQLite isolado; não é uma validação PostgreSQL individual do endpoint.
- Quality Gates [44410444404](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444404) terminou com sucesso. Docker Compose [44410444721](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444721) terminou com sucesso.
- Actualizados README, TODO, roadmap e matriz de autorização para reflectir evidência e limitações.
- Não foram executados comandos localmente nesta ronda; a evidência apresentada provém exclusivamente dos workflows GitHub Actions indicados.
- Riscos em aberto: os caminhos COCO/galeria/revisão offline ainda precisam de auditoria de consumo do release gate; a propagação de retenção para derivados, exports, caches e backups não está demonstrada; locks de transacção não coordenam jobs remotos/destacados; purge físico continua desactivado.
- Próxima tarefa: inventariar cada consumidor e definir um mecanismo comum de autorização/linhagem com lease/fencing para operações assíncronas, sem assumir uma política de retenção não aprovada.

## 2026-11-18 — Percurso ADMIN e isolamento de integrações externas

- HEAD inicial: `038e7bcebda8bc02226f264ee3797772ac289a81`.
- Acrescentado teste JWT HTTP positivo para a gestão de integrações externas: ADMIN cria uma integração obrigatória para retenção, consulta a listagem e a cobertura, e revoga a integração.
- O cenário verifica isolamento entre lojas: a listagem da loja B não inclui a integração da loja A; um PATCH com o ID da integração A no caminho da loja B devolve 404 e mantém o estado ACTIVE.
- A resposta HTTP é verificada para não expor campos de credenciais/chaves; a alteração de política regista o ADMIN em `updated_by_user_id`.
- Actualizados TODO, matriz de autorização e roadmap.
- O teste é HTTP/JWT com SQLite isolado. Não constitui validação PostgreSQL individual dos handlers.
- Validação API CI e Quality Gates pendente após o push; não foram executados testes locais.

## 2026-11-18 — README obrigatório e robustez do smoke PostgreSQL de funcionários

- HEAD inicial: `fcbc65c408fc03b7a02f47159f96af2e4411cf36`.
- Foi reforçado `AUTONOMOUS-DEVELOPMENT-PROMPT.md` para exigir a leitura integral do `README.md` antes de qualquer análise ou alteração. A leitura pode ser dividida em blocos, mas não pode limitar-se ao índice, títulos ou resumo.
- O próprio README passou a declarar explicitamente essa regra junto do protocolo de desenvolvimento.
- A análise do API CI [44308942806](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44308942806) identificou uma falha no assert do smoke PostgreSQL do diretório de funcionários: a base de CI é partilhada por vários smokes e já continha outros funcionários activos. O handler ADMIN global estava a devolver os registos esperados, além dos registos criados por outros smokes; a igualdade exacta com apenas dois IDs era uma expectativa inválida do teste.
- O smoke foi corrigido para exigir a presença dos dois funcionários activos criados por este cenário, a ausência do funcionário inactivo e o estado activo de todas as linhas devolvidas, sem pressupor que a base de dados partilhada está vazia.
- O run API CI anterior falhou neste assert; o Docker Compose smoke [44308942877](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44308942877) passou. Não foram executados testes locais nesta ronda.
- A nova validação PostgreSQL fica pendente da execução CI do commit desta correcção. A auditoria global de autorização permanece aberta.

## 2026-11-18 — Actualização de evidência da auditoria de autorização

A revisão de `docs/security/http-authorization-matrix.md` encontrou dois estados de validação desactualizados. Os testes JWT de upload de imagens (PNG forjado/truncado, MIME SVG e sanitização do nome de ficheiro) estão incluídos na suite API; o API CI [44291136290](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291136290) passou com 1148 testes aprovados, 1 ignorado e 1 aviso. O smoke PostgreSQL `postgres_capture_session_authorization_smoke.py` também passou no passo dedicado do mesmo workflow.

A documentação foi corrigida sem encerrar a auditoria global: a suite e o smoke demonstram os cenários implementados, não uma prova de cobertura de todas as rotas e handlers. Não houve alterações de código nem de dados nesta ronda.

## 2026-11-18 — Fecho CI da ronda de acessibilidade semântica

- SHA final validado: `897d6946d0641ee8201cd14c7df8549c60c55a9b`.
- O cartão de resumo de zona usa agora `button type="button"` nativo em vez de `article[role=button]`, removendo gestão manual de Enter/Espaço e preservando o destino de navegação.
- O estado de carregamento da avaliação de evidência operacional usa `role="status"` e `aria-live="polite"`.
- Quality Gates [44296524262](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44296524262) passou: job de testes API e compilação Python concluído com sucesso; job Web TypeScript/build de produção concluído com sucesso. Os runs intermédios cancelados foram substituídos por esta execução final aprovada.
- Não foram executados testes locais nem ensaios manuais de browser nesta sessão. Permanecem pendentes teclado ponta-a-ponta, leitor de ecrã, zoom/reflow e medição de contraste; não declarar conformidade WCAG 2.2 AA.

## 2026-11-18 — Semântica e anúncios acessíveis nos estados operacionais

A revisão estática identificou um cartão de zona implementado como `article[role=button]`, com gestão manual de Enter/Espaço. Foi substituído por um `button type="button"` nativo, preservando o estilo e o destino de navegação. O cartão usa agora a semântica e o comportamento de teclado nativos do browser. O estado de carregamento da avaliação de evidência operacional passou também a usar `role="status"` e `aria-live="polite"`, tal como o carregamento inicial.

**Validação disponível:** Web CI [44296222519](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44296222519) passou no commit `49f137995cc4ffe34fc0354c0d7d1e267ea0b1a1`. Quality Gates [44296222533](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44296222533) estava em execução na última consulta; não é declarado aprovado. Não foram executados testes locais nem ensaios manuais de teclado/leitor de ecrã.

## Ronda 2026-11-18 — fecho da validação de navegação acessível

- HEAD inicial: `5ca7babcd3529f4459a50eaf5542aa289db91d05`.
- A execução Web CI [44292103581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44292103581) passou; Quality Gates [44292103676](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44292103676) terminou com sucesso no mesmo commit.
- A validação automatizada confirma o build Web e os gates configurados para a alteração de navegação acessível. Não foram executados testes locais nem ensaio manual de browser nesta sessão.
- Permanecem por executar: teclado ponta-a-ponta, leitor de ecrã, zoom/reflow, contraste medido dos estados e validação em browser móvel/desktop. Não declarar WCAG 2.2 AA.

## 2026-11-18 — Navegação acessível no frontend

A aplicação autenticada passou a ter um link de salto para o conteúdo principal, um landmark `nav` com nome acessível na navegação lateral e controlos de navegação equivalentes em ecrãs pequenos (a barra lateral é ocultada abaixo de 700 px). Foram reforçados os indicadores `:focus-visible` para controlos interactivos, incluindo o campo de filtro, e o estado inicial de carregamento passou a ser anunciado com `role="status"` e `aria-live="polite"`.

**Validação automatizada concluída:** Web CI [44292103581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44292103581) e Quality Gates [44292103676](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44292103676) passaram no commit `5ca7babcd3529f4459a50eaf5542aa289db91d05`. A validação confirma TypeScript/build e os gates automatizados configurados; não substitui testes manuais com teclado/leitor de ecrã nem medição sistemática de contraste. Não declarar conformidade WCAG 2.2 AA.

## 2026-11-18 — Auditoria de desempenho PostgreSQL (preparação)

Foi criado `apps/api/scripts/postgres_image_query_plan_audit.py` para recolher `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON, TIMING OFF)` das principais consultas de imagens/evidência e da fila de revisão SKU. O script exige PostgreSQL, usa transacção `READ ONLY`, timeout por consulta, valida que a imagem pertence à loja indicada e não executa DDL/DML. Foram acrescentados testes unitários para os seis SELECTs limitados e validação de IDs. A utilização está documentada em `docs/PERFORMANCE-QUERY-AUDIT.md` e ligada no README. A auditoria cobre primeiras páginas e offset profundo configurável (por omissão 5000), incluindo evidência fundida e a fila de revisão SKU.

**Validação automatizada concluída:** API CI [44291136290](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291136290) passou com **1148 testes aprovados, 1 ignorado e 1 aviso**; Quality Gates [44291194461](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291194461) passou com compilação Python e build Web; Docker Compose smoke [44291133419](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291133419) passou.

**Ainda não medido:** o script não foi executado contra staging/réplica com volume representativo nesta sessão. Não foram adicionados índices nem alterados contratos de paginação, porque ainda não existem planos reais que justifiquem essas mudanças.

## 2026-11-18 — Integridade do planeamento de picking

O planeador de picking passou a detetar duplicados na entrada para o par `(product_id, location_id)`, que é único no modelo de dados. Todas as linhas desse par são excluídas por ambiguidade, em vez de somar potencialmente duas vezes a mesma quantidade física. O resumo expõe `ambiguous_placement_rows_excluded`. Foram adicionados testes para a exclusão de duplicados e para confirmar que a mesma localização pode continuar a conter SKUs diferentes. **Validação concluída:** API CI [44271596288](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44271596288) passou no commit `30f3b4e`; Quality Gates [44271717562](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44271717562) passou no commit documental `93abecc`; Docker Compose smoke [44271596168](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44271596168) passou no commit `30f3b4e`. Não foram executados testes locais nesta sessão.

## Validação de concorrência de retenção — 2026-11-18

- [x] O smoke PostgreSQL cobre as duas ordens concorrentes entre restauro e agendamento de purga.
- [x] API CI run [44268766212](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44268766212), commit `ff59e475a6694985747b4b055aacd06c37aec053`: migrações PostgreSQL, todos os smokes operacionais (incluindo `postgres_retention_legal_hold_concurrency_smoke.py`) e suite API concluídos com sucesso.
- [x] Quality Gates run [44268807130](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44268807130), HEAD `0024f326bbe98ae09834c273163326809b28b5cd`, tentativa 2: API e Web concluídos com sucesso; **1 140 testes aprovados, 1 ignorado, 1 aviso**; compilação Python e build TypeScript/produção aprovados.
- [x] Docker Compose smoke run [44268766432](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44268766432), commit `ff59e475`: build, arranque, readiness, seed e validação dos perfis concluídos com sucesso.
- [x] Fechar a auditoria automatizada de concorrência legal hold/restauro/agendamento de purga.
- [ ] A execução de purga física continua deliberadamente indisponível; não existe executor operacional e a API mantém-se fail-closed.


## Concorrência entre restauro e agendamento de purga — 2026-11-18

O smoke apps/api/scripts/postgres_retention_legal_hold_concurrency_smoke.py foi alargado para testar também as duas ordens concorrentes entre o endpoint de restauro e o agendamento de purga. Se o restauro confirmar primeiro, o pedido de agendamento que aguardava o lock deve revalidar o estado ACTIVE e devolver HTTP 409. Se o agendamento confirmar primeiro, o restauro deve limpar a data e a versão da política e registar, por esta ordem, PURGE_CANCELLED e RESTORED. Tal como nos cenários de legal hold, o smoke confirma através de pg_stat_activity / pg_blocking_pids que o pedido HTTP está efetivamente bloqueado na linha da imagem. **Validado:** API CI run `44268766212` passou todos os passos, incluindo este smoke e a suite API. Quality Gates run `44268807130` (tentativa 2) passou API e Web no HEAD `0024f326`; Docker Compose smoke `44268766432` passou no commit de código `ff59e475`.

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

- **Retention restore/purge race — `ff59e475`:** API CI `44268766212` passed all PostgreSQL migration/smoke steps, including both restore-vs-schedule race orders, and the full API test suite. Quality Gates `44268807130` attempt 2 passed on HEAD `0024f326`: 1,140 passed, 1 skipped, 1 warning; Python compilation and Web TypeScript/production build passed. Docker Compose smoke `44268766432` passed on `ff59e475`.

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

## 2026-11-18 — Auditoria de autorização das integrações externas

- Confirmado por leitura dos handlers que `POST/GET /api/v1/stores/{store_id}/external-integrations`, `PATCH .../{integration_id}` e `GET .../coverage` exigem perfil ADMIN antes de executar a operação.
- A cobertura anterior em `test_store_external_integrations.py` chamava directamente um handler com EMPLOYEE; não exercitava o middleware HTTP nem os JWT.
- Acrescentado `test_external_integration_management_is_admin_only_over_http` em `test_auth_middleware_jwt.py`: quatro operações × dois perfis não administrativos, mais verificação de que os pedidos recusados não criam integrações.
- Commit de código/teste: `297f92453791331ab9788920f6a8e0b28367818f`.
- API CI run `44299045159`: **1149 passed, 1 skipped, 1 warning**; a nova cobertura JWT HTTP passou.
- Quality Gates run `44299324366`: suite API/compilação Python e build Web TypeScript/produção passaram.
- Docker Compose run `44299045038`: build, readiness, seed e verificação dos perfis/worker passaram.
- A auditoria global permanece aberta; a reconciliação do inventário é registada abaixo.

## 2026-11-18 — Reconciliação do inventário HTTP

- Comparação estática das declarações `@app.get/post/put/patch/delete` em `apps/api/app/main.py` com o inventário documentado encontrou 16 rotas em falta e nenhuma entrada obsoleta.
- Actualizado `docs/security/http-route-inventory.md` para 123 declarações únicas, com as 16 linhas integradas na tabela principal (commit documental `a60ac242`).
- O inventário foi reconciliado com o código `main.py` no commit `297f92453791331ab9788920f6a8e0b28367818f`; não foram encontradas entradas obsoletas.
- Limite: esta reconciliação é estática; não prova autorização efectiva, nem cobre routers montados dinamicamente. A auditoria handler-a-handler continua aberta.

## 2026-11-18 — Diretório de funcionários e isolamento multi-loja

- A revisão do inventário encontrou que `GET /api/v1/store-employees` não tinha cobertura explícita na suite JWT.
- O handler exige ADMIN/SUPERVISOR, restringe SUPERVISOR à própria loja e devolve apenas funcionários activos; ADMIN pode filtrar outra loja.
- Acrescentado `test_store_employee_directory_is_scoped_to_supervisor_store`: lista permitida na loja A, filtro cross-store 403, consulta ADMIN à loja B, EMPLOYEE 403 e exclusão de funcionário inactivo.
- Commit de teste: `16666ead622fcbdfea073e6f7fa5c178b93c4da3`.
- **CI pendente**; a auditoria de autorização por handler continua aberta.



## 2026-11-18 — Smoke PostgreSQL do diretório de funcionários

- A cobertura HTTP SQLite já existente foi complementada com `apps/api/scripts/postgres_store_employee_authorization_smoke.py`, que cria duas lojas, funcionários activos/inactivos e testa o endpoint com JWT assinados reais.
- O smoke verifica que SUPERVISOR só recebe funcionários activos da própria loja, que um filtro explícito para outra loja devolve 403, que ADMIN pode filtrar a segunda loja e que EMPLOYEE recebe 403.
- O passo foi integrado em `.github/workflows/api-ci.yml`, após as migrações e os smokes PostgreSQL de autorização relacionados.
- Commits: smoke `4094b2d1b5f5d2ce3bbc5bbf3ff372026c3f44d2`; workflow `2b9511c3212308cae5949f41360bbb431d070b70`.
- A execução CI ainda não foi confirmada nesta actualização. Não foram executados testes localmente nem se declara o cenário PostgreSQL aprovado.
- Próximo passo: confirmar o novo passo no API CI, corrigir eventuais falhas e só depois actualizar a matriz de autorização para evidência validada.


## 2026-11-18 — Reforço de autenticação do diretório de funcionários

- Expandido `apps/api/scripts/postgres_store_employee_authorization_smoke.py` para verificar também ausência de token (401), JWT inválido (401), identidade de SUPERVISOR inactiva (401) e listagem global de ADMIN sem funcionários inactivos.
- Mantidos os cenários de isolamento SUPERVISOR, filtro cross-store (403), filtro ADMIN por loja e recusa de EMPLOYEE (403).
- Commit do smoke: `e0ac4af806693cd203864ae92eb03e307fecafa6`.
- A execução do script contra PostgreSQL e o resultado do API CI continuam pendentes; não foi executado localmente.
- A revisão do middleware confirmou que `GET /api/v1/auth/users` exige autenticação e ADMIN. Não foi identificada exposição pública nessa rota.


## 2026-11-18 — Autorização dos artefactos externos de imagens

- A revisão dos handlers confirmou que as seis operações de governação de artefactos externos exigem ADMIN: registo, listagem, snapshot de inventário, decisão de acesso, criação e consulta de eventos de disposição.
- Foi acrescentado `test_shelf_image_external_artifact_governance_is_admin_only_over_http`, que usa JWT reais através do TestClient para SUPERVISOR e EMPLOYEE.
- O teste verifica 12 pedidos negados (seis operações por dois perfis) e compara contagens de artefactos, snapshots e eventos antes/depois para detectar efeitos laterais.
- O teste usa SQLite isolado; não prova concorrência nem comportamento de locks em PostgreSQL.
- Validação CI pendente. Não foram executados testes localmente nesta sessão.
- SHA inicial: `13af626c8237c8f5fa26d452a2d83d5342c4200b`.
- Próximo passo: executar API CI/Quality Gates, corrigir falhas e continuar a revisão dos restantes handlers.


## 2026-11-18 — Validação CI da autorização de artefactos externos

- API CI run [44337777007](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44337777007): **success**. As 28 etapas de smoke PostgreSQL terminaram com sucesso e a suite completa `pytest -q` também passou.
- Quality Gates run [44337776819](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44337776819): **success**; build Web de produção concluído.
- Docker Compose smoke run [44337776893](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44337776893): **success**; API, PostgreSQL, worker e perfis de demonstração verificados.
- A cobertura JWT de seis operações de governação de artefactos externos está agora validada pela suite API no CI. O teste HTTP usa SQLite isolado; os smoke PostgreSQL do workflow validam as respectivas invariantes de persistência/concurrency, mas não executam esse teste HTTP específico contra PostgreSQL.
- Não foram identificadas falhas de código nem regressões nesta ronda.
- Commit funcional: `4b45ae475b2059832c71ca447011fb9c34165c1d`.
- Próximo passo: continuar a auditoria dos restantes handlers e alinhar a política de acesso com os testes por perfil e loja.


## 2026-11-18 — Autorização da gestão de integrações externas por loja

- Revisão dos handlers `POST/GET /api/v1/stores/{store_id}/external-integrations`, `GET .../coverage` e `PATCH .../{integration_id}`: todos exigem ADMIN directamente no handler.
- Acrescentado `test_store_external_integration_governance_is_admin_only_over_http`: 8 pedidos (quatro operações por dois perfis JWT: SUPERVISOR e EMPLOYEE), todos esperados como HTTP 403.
- O teste compara a contagem e os campos de política da integração preexistente antes/depois, para detectar criação ou alteração por pedidos recusados.
- API CI run [44338653668](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44338653668): **success**; suite API e smoke PostgreSQL concluídos.
- Quality Gates run [44338651433](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44338651433): **success**; testes API, TypeScript e build de produção aprovados.
- Docker Compose smoke run [44338651406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44338651406): **success**.
- Teste HTTP/JWT validado na suite API; não foi executado localmente nesta sessão.
- Esta ronda alarga a cobertura de autorização administrativa; não encerra a auditoria global nem substitui testes PostgreSQL de concorrência.


## Validação CI — gestão de integrações externas (18-11-2026)

- Commit funcional: `038e7bcebda8bc02226f264ee3797772ac289a81`.
- API CI [44338653668](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44338653668): **success**.
- Quality Gates [44338651433](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44338651433): **success**.
- Docker Compose smoke [44338651406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44338651406): **success**.
- A suite de API passou com o novo teste de gestão de integrações externas. O teste HTTP específico usa SQLite isolado; os smokes PostgreSQL do workflow passaram, mas não executam esse teste HTTP contra PostgreSQL.
- Próximo foco: rever operações de integração externas para além dos quatro métodos já cobertos, incluindo eventuais callbacks/webhooks e fluxos de ingestão com credenciais ou segredos.


## 2026-11-18 — Fluxo ADMIN de integrações externas por HTTP

- Acrescentado `test_admin_can_manage_store_external_integrations_over_http`.
- O teste percorre criação (201), listagem (200), cobertura (200), revogação (200) e nova consulta de cobertura, usando JWT ADMIN real.
- Verifica que a resposta não expõe campo `secret`, que a integração começa como nunca observada e que a cobertura passa a indicar integração revogada.
- Execução CI pendente; o teste não foi executado localmente nesta sessão.

## 2026-11-18 — Autorização dos fluxos de revisão humana
- A revisão da matriz de middleware identificou um conjunto de operações de revisão acessíveis apenas a ADMIN/SUPERVISOR: fila de revisão, resumo, avaliação de SKU revista, candidatos de treino revistos e criação de revisão de uma deteção.
- Foi acrescentado test_employee_cannot_access_human_review_workflows_over_http, com JWT EMPLOYEE e middleware activo em modo production.
- O teste exige HTTP 403 nas cinco operações e compara a contagem de DetectionSkuReview antes/depois para garantir que a tentativa de submissão não cria uma revisão.
- A leitura de histórico de revisões de deteção continua a ser uma permissão separada; esta alteração não a alarga.
- O teste foi adicionado ao repositório, mas ainda não foi executado nesta sessão. A validação CI permanece pendente.
- Próximo passo: executar API CI/Quality Gates e continuar a auditoria dos restantes handlers, em especial operações de captura, catálogo partilhado e isolamento indirecto por loja.
- Correcção preventiva antes da validação: separar detection_id da expressão f-string para manter compatibilidade com o parser Python usado pelo projecto. A validação continua pendente.

## 2026-11-18 — Isolamento multi-loja no armazém
- Foi acrescentado test_supervisor_cannot_access_other_store_warehouse_resources_over_http.
- O teste usa um supervisor atribuído à loja A e tenta consultar localizações da loja B, criar uma localização na loja B e criar uma colocação numa localização da loja B.
- As três operações devem responder HTTP 403. O teste compara as contagens de WarehouseLocation e WarehouseProductPlacement antes/depois para verificar ausência de efeitos laterais.
- A alteração foi publicada na main; a validação CI ainda está pendente.
- Próximo passo: alargar a cobertura a paletes, eventos de rotação, políticas e leituras de inventário/forecasting com identificadores de outra loja.

## 2026-11-18 — Isolamento multi-loja em paletes e rotação
- A revisão dos handlers identificou operações de listagem/registo de paletes, actualização de políticas de rotação e leitura/escrita de eventos de ciclo de vida.
- Foi acrescentado test_supervisor_cannot_access_other_store_pallets_policies_or_events_over_http. O cenário cria uma palete, uma política e um evento na loja B e tenta aceder-lhes com JWT SUPERVISOR da loja A.
- O teste exige HTTP 403 em cinco operações e compara eventos, política e estado da palete antes/depois para detectar efeitos laterais.
- No commit anterior d39adb2, Quality Gates (incluindo build web) e Docker Compose smoke passaram. API CI run 44353746006 ainda estava em execução na última consulta.
- A nova cobertura foi publicada na main, mas ainda não foi executada; os workflows do novo commit são a validação pendente.
- A auditoria continua aberta; próximo foco: simulação, portefólio e histórico de rotação, além da confirmação PostgreSQL.

## 2026-11-18 — Isolamento multi-loja em vendas e previsões
- Revistos os handlers de ingestão diária/horária, tráfego, batches, consultas horárias, previsão de procura, risco de rutura e portefólios.
- Acrescentado test_supervisor_cannot_access_other_store_sales_and_forecasts_over_http, com 12 tentativas cross-store e JWT SUPERVISOR da loja A.
- O teste exige 403 e compara contagens de DailySalesRecord, HourlySalesRecord e HourlyStoreTrafficRecord antes/depois.
- A revisão estática confirma filtros store_id nas consultas de forecasting e nos perfis horários.
- Commit anterior 2fd6796 validado: API CI 44354437977, Quality Gates 44354438016 e Docker Compose smoke 44354437876 — todos success.
- Validação da nova cobertura pendente; auditoria multi-loja continua aberta.


## 2026-11-18 — Isolamento multi-loja nas importações CSV horárias

- Inspeccionados os handlers `POST /api/v1/sales/hourly/import-csv` e `POST /api/v1/sales/traffic/hourly/import-csv`.
- Ambos executam `_request_user` e `_enforce_store_scope` antes de validar a loja, ler o ficheiro ou analisar o CSV; a revisão estática confirma a ordem fail-fast.
- Acrescentado `test_supervisor_cannot_import_other_store_hourly_sales_or_traffic_csv_over_http` com uploads multipart reais na camada HTTP. As duas operações devem responder 403 e as contagens de `HourlySalesRecord` e `HourlyStoreTrafficRecord` da loja B devem permanecer inalteradas.
- O teste foi publicado na `main`; ainda não foi executado localmente nem validado por CI nesta ronda.
- Próximo passo: validar os workflows e acrescentar cobertura PostgreSQL de ingestão multi-loja, sem confundir o teste SQLite com prova de isolamento PostgreSQL.


## 2026-11-18 — Smoke PostgreSQL para autorização de importações CSV

- Corrigida a representação das quebras de linha nos payloads multipart do teste JWT SQLite.
- Criado `apps/api/scripts/postgres_sales_import_authorization_smoke.py`: duas lojas isoladas, JWT SUPERVISOR real, tentativas cross-store para os dois endpoints, contagens antes/depois e importações positivas na loja autorizada.
- Integrado o smoke no API CI após o smoke existente de idempotência concorrente CSV.
- O teste PostgreSQL ainda depende da execução do API CI deste commit; não foi executado localmente nesta sessão.


## 2026-11-18 — Cobertura CSV diária e horária completa

- A revisão da lista de rotas identificou também `POST /api/v1/sales/import-csv`, a importação diária que não estava incluída na primeira ronda horária.
- O teste JWT HTTP e o smoke PostgreSQL foram alargados para cobrir os três endpoints: vendas diárias, vendas horárias e tráfego horário.
- Para cada endpoint, a tentativa cross-store deve falhar com 403 antes do parsing; o smoke verifica contagens PostgreSQL antes/depois e confirma importação positiva na loja do supervisor.
- A validação desta extensão depende dos workflows do commit seguinte.


## Validação CI — importações CSV diárias e horárias (18-11-2026)

Commit validado: `1e3499c8c80ef75494a29d06807469898471e4e1`.

- API CI [44404814359](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44404814359): **sucesso**. Migrações PostgreSQL 16, smoke de idempotência CSV, smoke de autorização multi-loja dos três endpoints CSV e suite pytest passaram.
- Quality Gates [44404814406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44404814406): **sucesso**. Compilação Python, suite API, TypeScript e build de produção web passaram.
- Docker Compose smoke [44404813670](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44404813670): **sucesso**.
- O smoke PostgreSQL usou JWT real de SUPERVISOR, duas lojas, pedidos multipart e verificações directas das tabelas. Os três endpoints cross-store devolveram 403 sem novas linhas; as três importações na loja autorizada persistiram uma linha cada.
- Os checks externos Vercel continuam limitados por quota de deployment (build-rate-limit; retry indicado em 24 horas); não são falhas dos workflows de código acima.


## 2026-11-18 — Autorização da hierarquia de zonas e prateleiras

- Revisados os handlers `GET/POST /api/v1/zones` e `GET/POST /api/v1/shelves` e a classificação de perfil na middleware.
- Confirmado que as escritas são ADMIN-only; as leituras de SUPERVISOR filtram por loja e a consulta explícita de outra loja deve devolver 403. EMPLOYEE não tem permissão de leitura destes recursos.
- Acrescentado `test_zone_and_shelf_routes_enforce_admin_writes_and_store_scoped_reads`: verifica listagens próprias, tentativa cross-store, recusas sem efeitos laterais e criação positiva ADMIN.
- Teste publicado na `main`; a validação CI está pendente. A cobertura SQLite HTTP não substitui a validação PostgreSQL das triggers de linhagem hierárquica.


## 2026-11-18 — Reforço de batches multi-loja e forecasting

- Os schemas `HourlySalesBatchCreate` e `HourlyStoreTrafficBatchCreate` têm validator que exige um único `store_id` em todos os registos. Não foi identificada uma escrita cross-store por esta via.
- Acrescentado teste HTTP/JWT com batches contendo simultaneamente lojas A e B. A validação do schema deve rejeitar ambos com HTTP 422 antes da execução do handler; as contagens de vendas e tráfego nas duas lojas são comparadas antes/depois.
- A matriz de isolamento passa também a cobrir `GET /api/v1/sales/daily`, `GET /api/v1/forecasting/traffic-peaks`, `GET /api/v1/forecasting/hourly-demand` e `GET /api/v1/warehouse/slotting-recommendations`, cujos handlers aplicam `_enforce_store_scope` e filtram por `store_id`.
- Os testes foram publicados; aguardam validação CI. Não foi executado pytest localmente nesta ronda.


## 2026-11-18 — Linhagem de registos de prateleira em PostgreSQL

- Revisada a migration `0050_shelf_record_store_lineage_guard`: triggers protegem INSERT/UPDATE dos três registos operacionais e impedem mudanças de loja na hierarquia quando estas deixam referências inconsistentes.
- Criado `apps/api/scripts/postgres_shelf_record_lineage_smoke.py`, que usa PostgreSQL real e cria duas lojas, zonas, uma prateleira e registos válidos de alerta, captura e reposição.
- O smoke tenta INSERT e UPDATE com loja divergente nas três tabelas e movimentos cross-store de prateleira/zona; exige rejeição pela base de dados e confirma que os registos válidos permanecem intactos.
- Integrado no API CI. Ainda aguarda execução; não foi validado localmente nesta sessão.


## 2026-11-18 — Validação PostgreSQL da linhagem multi-loja de registos de prateleira

- SHA validado: `04c542320ad892a06c81c2295f518f5583428bc4`.
- O smoke `apps/api/scripts/postgres_shelf_record_lineage_smoke.py` foi executado no API CI com PostgreSQL 16.
- Passaram as migrações Alembic, os 28 passos de smoke PostgreSQL e a suite `pytest -q` (job completo com sucesso).
- O smoke confirmou que INSERT e UPDATE com `store_id` divergente são rejeitados em `observation_alerts`, `capture_sessions` e `replenishment_tasks`; também rejeitou a mudança de loja de prateleiras/zonas com registos dependentes.
- A validação confirmou que os três registos originais permanecem íntegros. A correcção anterior preservou os IDs após fechar a sessão SQLAlchemy, evitando acesso a atributos expirados/detached.
- API CI: [44408063719](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44408063719) — success. Quality Gates: [44408063767](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44408063767) — success.
- Não foram executados testes localmente nesta ronda. A evidência é de CI; não representa auditoria exaustiva de todos os handlers nem validação manual do produto.
- Próximo passo: continuar a auditoria de autorização e isolamento por loja nas rotas restantes, priorizando caminhos administrativos, operações indirectas e efeitos laterais.


## 2026-11-18 — Cobertura HTTP da linhagem pai/filho de artefactos externos

- Confirmado no handler existente que `POST /api/v1/shelf-images/{image_id}/artifacts` já valida o pai dentro do mesmo `shelf_image_id` e `store_id`, sob a ordem de locks imagem → integração externa → referência.
- Reforçado `ShelfImageArtifactReferenceCreate.parent_reference_id` com validação inteira estrita para impedir a coerção de booleanos para IDs.
- Acrescentado teste HTTP/JWT para criação de raiz e descendente, retry idempotente, conflito de linhagem, pai inexistente, pai de outra imagem na mesma loja e pai de outra loja; verifica ainda a listagem e a ausência de efeitos laterais.
- Testes e CI ainda não executados para este commit. A cobertura é SQLite HTTP, não evidência PostgreSQL.
- Próximo passo: validar API CI/Quality Gates e, se aprovado, atualizar a matriz de autorização com a evidência. Manter a auditoria multi-loja global aberta.


## 2026-11-18 — Locks da hierarquia na elegibilidade operacional de datasets

- A validação de imagens internas já bloqueava a linha de `shelf_images`, mas a loja efectiva também depende de `shelves.zone_id` e `zones.store_id`. O lock apenas da imagem deixava essas duas linhas fora da secção crítica.
- A consulta foi alterada para selecionar e bloquear imagem, prateleira e zona com `FOR UPDATE OF shelf_images, shelves, zones`, ordenando por `shelf_images.id, shelves.id, zones.id`.
- O relatório passou a expor os IDs de prateleiras e zonas bloqueados, além das imagens.
- Foi acrescentado teste de compilação com o dialecto PostgreSQL para verificar explicitamente as tabelas bloqueadas e a ordenação SQL.
- Ainda não foi executado o smoke de concorrência real PostgreSQL para este caminho. O teste de compilação não prova o comportamento de bloqueio em runtime.
- Próximo passo: adicionar smoke PostgreSQL com duas sessões, mantendo a validação aberta enquanto uma segunda transação tenta alterar a loja da zona/prateleira; depois validar o commit completo no API CI.


## 2026-11-18 — Smoke concorrente PostgreSQL para elegibilidade de datasets

- Criado `apps/api/scripts/postgres_dataset_eligibility_concurrency_smoke.py`.
- O smoke cria duas lojas e imagens internas com proveniência verificável; usa sessões SQLAlchemy independentes para manter o gate de elegibilidade aberto e tentar alterar, em paralelo, a zona da prateleira ou a loja da zona.
- A confirmação não depende apenas de temporização: consulta `pg_stat_activity` e `pg_blocking_pids(pid)` para exigir que cada UPDATE esteja realmente bloqueado pela transação de elegibilidade.
- Depois do commit do gate, o UPDATE deve concluir e o estado final é confirmado na base de dados.
- O smoke foi integrado no API CI após as migrações e o smoke de linhagem de registos de prateleira. A validação PostgreSQL 16 só será registada depois da execução do workflow deste commit.


## 2026-11-18 — Validação do gate de aprovação de datasets

- SHA validado: `107d2bda261685717d8601d2913b2a8beffcd7fa`.
- API CI [44412024791](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44412024791): sucesso; **1168 testes aprovados, 1 ignorado, 1 aviso**. Migrações PostgreSQL 16, smokes de concorrência/isolamento e suite API concluídos.
- Quality Gates [44412024893](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44412024893): sucesso; compilação Python e build TypeScript/produção Web aprovados.
- Docker Compose [44412025214](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44412025214): sucesso; stack de demonstração validada.
- A execução de consumidores síncronos passa a exigir gate de aprovação e a vincular a evidência à fingerprint da release. Os locks de elegibilidade interna permanecem durante o consumidor.
- Limite mantido: CI não valida treino real nem serviços externos; consumidores remotos/destacados continuam sem lease/fencing.
- Próxima prioridade: definir e testar uma autorização durável para consumidores assíncronos, sem permitir que um lease expirado valide resultados tardios.


## 2026-11-18 — Auditoria dos consumidores COCO e fronteiras de execução

- Inspeccionados `coco_dataset.py`, `coco_review.py`, `dataset_diff.py`, `dataset_audit.py`, `dataset_quality.py`, `dataset_review.py`, `dataset_approval.py`, `dataset_release.py` e `dataset_execution.py`.
- Conclusão: validação COCO, galeria e diff não iniciam treino; a galeria escreve HTML que referencia os originais, e o diff/qualidade escrevem relatórios. A revisão valida evidência declarada, mas não autentica o revisor. A release pode ser candidata. O wrapper síncrono `dataset_execution` é a fronteira inspeccionada que inicia o processo externo e já exige gate.
- Documentadas as operações, os efeitos laterais e os limites em `docs/architecture/dataset-consumer-boundaries.md`.
- A auditoria dos CLIs foi concluída para os ficheiros inspeccionados; não prova que um operador não execute manualmente um trainer fora do wrapper.
- Próximas lacunas: catálogo persistente de derivados e destinos; herança de retenção; revisão autenticada; claim/lease/fencing e publicação condicionada ao token actual.


## 2026-11-18 — Contrato técnico para execução assíncrona

- Definido o protocolo de lease/fencing para jobs de treino/inferência remotos: identidade imutável e idempotente, estados, claim com `SKIP LOCKED`, token monotónico, heartbeat, takeover e conclusão condicionada ao token.
- Definida revalidação de fontes internas em cada fronteira, lock order, auditoria append-only e publicação de outputs através de staging.
- Documentados os limites do heartbeat: não impede leituras de cópias locais após perda do lease; é necessário serviço de acesso controlado por leitura e inventário/revogação de caches.
- Documento: `docs/architecture/dataset-async-execution-lease.md`.
- Estado: desenho concluído; nenhuma tabela, serviço ou worker remoto foi implementado nesta etapa.
- Próximo passo: implementar serviço de leitura de artefactos por chamada e promotor de outputs condicionado ao fencing token actual; só depois integrar broker/worker.


## 2026-11-18 — Persistência de jobs assíncronos e serviço de fencing

- Base inicial: `24cd266ebcf2ea7719a18e3933d1d33e676416c1`; implementação preparada sobre a `main` após leitura integral do README e do protocolo autónomo.
- Criada migration `0056_dataset_execution_job_leases` com tabelas de jobs, fontes internas e eventos append-only; constraints para estados, modos, digests, lease e contadores; triggers para identidade imutável, linhagem/eligibilidade das fontes e eventos append-only.
- Criado `app.dataset_job_leases`: enqueue idempotente com evidência APPROVED, claim com `SKIP LOCKED`, lease, fencing monotónico, heartbeat, falha e conclusão em staging. As operações de vida do lease revalidam as fontes sob locks imagem/prateleira/zona.
- Adicionados testes SQLite de contrato e migration e smoke PostgreSQL com dois workers concorrentes, takeover, rejeição de heartbeat/conclusão obsoletos e sequência de eventos.
- O serviço não executa comandos nem publica outputs; não foi ligado a um broker ou worker. A primeira versão só aceita fontes internas; o acesso remoto aos bytes e a publicação fenced permanecem requisitos separados.
- Validação concluída: API CI [44416138879](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138879) passou com migration PostgreSQL 16, smoke de leases e **1177 testes aprovados, 1 ignorado, 1 aviso**; Quality Gates [44416138669](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138669) e Docker Compose [44416138628](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138628) também passaram. A primeira execução detectou dois defeitos nos fixtures/testes (dois jobs na fila inicial do smoke e comparação de uma entidade ORM mutável); ambos foram corrigidos antes da execução verde. Não foram executados testes localmente.


## 2026-11-18 — Fencing e sequências de eventos reforçados ao nível da base de dados

- HEAD inicial: `d84b836c566943e799ddb1ea6a23d1de5999b79f`.
- Criada migration `0057_dataset_execution_fencing_guards` com validação de claims, heartbeats, takeovers e transições terminais; acrescentadas constraints para outputs bem-sucedidos, estado terminal e leases activos.
- Acrescentados triggers SQLite equivalentes para testes de contrato; PostgreSQL usa constraints e triggers transaccionais.
- A sequência de eventos passa a ser validada na base de dados e os jobs terminais deixam de aceitar eventos adicionais, excepto o evento terminal correspondente à transição.
- O serviço de heartbeat preserva a expiração anterior quando a duração pedida é menor.
- Acrescentados testes de migration SQLite e verificações SQL directas ao smoke PostgreSQL.
- Validação: API CI [44419928230](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928230) passou com migration PostgreSQL 16, smoke SQL directo e **1179 testes aprovados, 1 ignorado, 1 aviso**; Quality Gates [44419928281](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928281) e Docker Compose [44419928382](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928382) passaram.


- Correcções durante a validação: o primeiro teste revelou que a lógica de heartbeat tinha sido aplicada por engano ao claim inicial; foi corrigida no commit `23a81cb`. O smoke PostgreSQL também foi adaptado para aguardar a expiração natural do lease, em vez de alterar directamente a expiração que a nova trigger protege. A execução final passou.


- Validação final do commit `93704d6b5f7262ec20befc6dc17ee4f1c80efb78`: API CI [44419928230](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928230) — migration PostgreSQL 16, smoke concorrente de leases/fencing e **1179 passed, 1 skipped, 1 warning**; Quality Gates [44419928281](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928281) — Python, suite API e build Web aprovados; Docker Compose [44419928382](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928382) aprovado.


## 2026-11-18 — Máquina de estados e identidade imutável dos jobs assíncronos

- HEAD de referência: `2e75c07ff31e6273f6905c84439df8efa8ea71d8`.
- Criada a migration `0058_dataset_execution_state_machine`, dependente de `0057_dataset_execution_fencing_guards`.
- PostgreSQL e SQLite passam a rejeitar transições fora do contrato, incluindo `QUEUED → SUCCEEDED`, reactivação terminal e alterações à identidade imutável do job.
- Mantidas as transições de revogação/cancelamento necessárias ao serviço, incluindo revogação de um lease expirado quando a fonte deixa de ser elegível.
- Acrescentados testes SQLite de migration e tentativas SQL directas no smoke PostgreSQL para identidade activa e reactivação terminal.
- Documentação de README, TODO, roadmap e contrato de execução actualizada.
- Estado: implementação preparada; ainda não declarar validada até concluir migration PostgreSQL 16, suite API, Quality Gates e Docker Compose.


### Validação da máquina de estados — migration 0058 (18-11-2026)

- API CI [44421831066](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44421831066): migration PostgreSQL 16 e smoke de execução assíncrona passaram; suite API **1179 passed, 1 skipped, 1 warning**.
- Quality Gates [44421831076](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44421831076): compilação Python, testes API e build Web passaram.
- Docker Compose [44421831148](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44421831148): stack de demonstração passou.
- A validação acima cobre o commit `8d63a1748ae2fa9608e110ef8f8220dc7be30c7e`. A migration 0059, acrescentada para impedir INSERT em estado terminal, permanece pendente de CI.


## 2026-11-19 — Cobertura negativa do estado inicial de jobs assíncronos

- HEAD de trabalho: commits `0d7592b12a98ee11f16730591c30368637b30c32` (teste SQLite) e `f07d9d2fbc194dacd05e38a100c6937cde9da9f2` (smoke PostgreSQL).
- A migration 0059 já impedia INSERT de jobs em estado diferente de `QUEUED` e metadados iniciais incompatíveis. A cobertura anterior testava sobretudo a inserção directamente em estado terminal.
- O teste SQLite e o smoke PostgreSQL foram expandidos para tentar, individualmente, inserir jobs `QUEUED` com proprietário/expiração de lease, fencing token, contador de tentativas, digest/output, referência staging, falha ou timestamp terminal forjados.
- A alteração acrescenta cobertura de regressão; não altera o contrato de produção nem relaxa as guards.
- Validação pendente: não foram executados testes localmente nesta ronda e ainda não foi confirmada uma execução CI verde para estes commits.
- Próximo passo: validar a migration 0059 e os oito casos negativos em PostgreSQL 16 e SQLite; depois avançar para autenticação de workers antes de expor operações de claim/heartbeat.


## 2026-11-19 — Correção e validação da migration 0059 (estado inicial de jobs)

- SHA inicial desta correção: `ef10bd76921b3868812c81611a1e313125c193a4`.
- A execução anterior revelou que os testes SQLite aceitavam silenciosamente INSERTs com colunas duplicadas para `fencing_token`/`attempt_count`; o smoke PostgreSQL terminava com `DuplicateColumn` antes de testar a trigger.
- Corrigidos `apps/api/tests/test_dataset_job_fencing_guards_migration.py` e `apps/api/scripts/postgres_dataset_job_lease_smoke.py`: a lista de colunas e os valores é agora construída sem duplicações, de modo que cada um dos oito metadados inválidos é realmente submetido à base de dados.
- API CI [44428496117](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496117) passou: migration PostgreSQL 16, todos os smokes operacionais (incluindo leases/fencing) e **1179 testes aprovados, 1 ignorado e 1 aviso**.
- Quality Gates [44428496156](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496156) passou com compilação Python, suite API e build TypeScript/produção Web. Docker Compose [44428496204](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496204) também passou.
- A migration de produção não foi alterada nesta correção; foi corrigida a cobertura de regressão que a exercita. Não foi executado pytest localmente nesta ronda.
- Próxima prioridade: implementar identidade/autenticação individual de workers antes de expor operações de claim/heartbeat; depois serviço de leitura controlada e promotor fenced.


## 2026-11-19 — Implementação de credenciais individuais para workers

- **Base inicial:** `709b48abef7106e99175f4a3b38b567279f9ca39`.
- **Migration/modelos:** `0060_dataset_worker_credentials`, `DatasetWorker`, `DatasetWorkerCredential`, `DatasetWorkerEvent`.
- **Serviço:** `app.dataset_worker_credentials` emite credenciais aleatórias, persiste apenas SHA-256, autentica principal de worker, verifica scopes e suporta rotação/revogação/desativação.
- **Identidade:** wrappers de claim, heartbeat, complete e fail obtêm `worker_id` do principal autenticado; não recebem identidade alternativa do chamador.
- **Provisionamento:** `python -m app.dataset_worker_admin` com operações issue/rotate/revoke/disable; emissão sem endpoint HTTP.
- **Testes:** `test_dataset_worker_credentials.py` cobre autenticação, segredo errado, token desconhecido/malformado, expiração, revogação, rotação, scopes, desativação e claim vinculado ao principal.
- **PostgreSQL:** `postgres_dataset_worker_credentials_smoke.py` foi integrado no API CI e testa o ciclo de vida e a imutabilidade dos eventos.
- **Documentação:** README, TODO, roadmap, contrato de leases e novo guia de segurança actualizados.

**Validação concluída no commit de código `d7c84125d35a5fff5d2254a3ee33a08cd41edcc7`:** API CI [44431378398](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378398) passou com PostgreSQL 16, smoke dedicado e **1202 passed, 1 skipped, 1 warning**; Quality Gates [44431378324](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378324) passou; Docker Compose [44431378349](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378349) passou. Não foi executado pytest local; a evidência é a execução CI.

**Limitações explícitas:** a credencial é bearer reutilizável e não previne replay; falta assinatura por pedido/nonce. Não há endpoints HTTP de jobs, broker/worker de treino, leitura de bytes por chamada ou promotor fenced. `artifacts:read` e `outputs:publish` são scopes reservados, sem handlers implementados.

- **Hardening SQL adicional:** migration 0060 impede UPDATE/DELETE de campos imutáveis de credenciais, bloqueia eliminação de credenciais, impede reativar workers desativados e mantém eventos append-only; teste SQLite e smoke PostgreSQL passaram no CI acima.


## 2026-11-19 — Pedidos assinados e anti-replay de workers

- **Base de implementação:** commit `d5e0a5b35d1dd2af1d46c4eaac60822155ac37dc`; correcção da tradução de nonce duplicado para erro de replay no commit `7bb67412cdb6b63b8221a2a29a12d7347005a451`.
- **Migration:** `0061_dataset_worker_request_nonces`, com digest do nonce, timestamp, expiração, FK para a credencial e restrição única por credencial/nonce.
- **Assinatura:** HMAC-SHA-256 sobre versão, credential ID, timestamp, nonce, método, request-target exacto e SHA-256 do corpo. O cliente deriva a chave do segredo da credencial; o servidor usa o hash persistido.
- **HTTP:** novo módulo `app.dataset_worker_http` com `require_dataset_worker(scope)`; autentica, verifica assinatura, aplica janela temporal de ±60 segundos e scope, e consome o nonce numa transacção própria antes do handler.
- **Replay:** o smoke PostgreSQL usa duas sessões concorrentes com o mesmo pedido; exactamente uma é aceite e a outra recebe `DatasetWorkerReplayError`. O primeiro CI detectou uma importação em falta de `IntegrityError`; a correcção foi aplicada e a nova execução passou.
- **Testes:** assinatura adulterada, método/caminho/query/corpo divergentes, timestamp expirado, scope insuficiente, repetição HTTP e constraints/downgrade da migration.
- **Validação:** API CI [44471171581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171581) passou com PostgreSQL 16, smoke de replay e **1211 passed, 1 skipped, 1 warning**; Quality Gates [44471171526](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171526) e Docker Compose [44471171533](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171533) passaram.
- **Fronteira não implementada:** não existem rotas de jobs montadas, broker nem worker remoto. A dependência está pronta para uso por futuros handlers, mas não deve ser apresentada como endpoint operacional. Leitura autorizada de artefactos e promoção fenced continuam pendentes.


## 2026-11-19 — Leitura segura e auditada de fontes de treino

- **Base validada:** commit `c6b00478514812e094b960f5fefe4b6380b0fb9a`.
- **Migration/modelo:** `0062_dataset_job_artifact_reads` e `DatasetExecutionJobArtifactRead`, com FKs, checks, índices e auditoria append-only.
- **Serviço:** `read_dataset_job_source_bytes` exige `artifacts:read`, lease actual e fencing token, valida pertença ao job, bloqueia a hierarquia de imagem, confirma loja/retention/legal hold e volta a validar worker/credencial no momento da leitura.
- **Filesystem:** leitura por descritores de directório e `O_NOFOLLOW`; traversal e symlinks rejeitados; tamanho e SHA-256 verificados; só os bytes em memória são devolvidos.
- **SQL:** triggers PostgreSQL/SQLite impedem registos de leitura sem lease/fonte/loja/retention/worker/credencial/scope válidos e proíbem UPDATE/DELETE da auditoria.
- **Corridas de revogação:** wrappers claim/heartbeat/complete/fail revalidam worker, credencial e scope no momento da operação; leitura repete a validação na transacção que segura os locks.
- **Smoke PostgreSQL:** confirmou leitura bem-sucedida e auditada; uma restrição concorrente ficou bloqueada pelo lock de origem e, após commit, a leitura seguinte foi recusada sem novo registo de sucesso. O smoke também confirmou que UPDATE/DELETE da auditoria são rejeitados.
- **Validação:** API CI [44473560217](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560217), Quality Gates [44473560287](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560287) e Docker Compose [44473560252](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560252) passaram; suite API: **1223 passed, 1 skipped, 1 warning**.
- **Limites:** serviço de leitura disponível internamente, mas sem endpoint HTTP montado; promoção de outputs, broker e worker remoto continuam pendentes.


## 2026-11-19 — Promoção de outputs com fencing e auditoria

- **Migration/modelo:** `0063_dataset_job_output_publications` e `DatasetExecutionJobOutputPublication`, com FKs, checks, unicidade por job/destino e auditoria append-only.
- **Autorização:** `promote_dataset_job_output` exige job `SUCCEEDED`, token actual, evento terminal do mesmo worker/token/digest e credencial activa com scope persistido `outputs:publish`.
- **Filesystem:** staging limitado a `staging/{job_id}/{fencing_token}/`; rejeita traversal e symlinks; copia para temporário privado, confirma tamanho/SHA-256 e publica por hard link atómico sem sobrescrita para destino determinístico.
- **Recuperação:** se o destino foi criado mas o commit SQL não ficou registado, uma nova chamada verifica o digest e completa a auditoria. A limpeza automática de temporários órfãos após crash abrupto continua pendente.
- **Auditoria SQL:** triggers PostgreSQL/SQLite validam o evento terminal, job, token, digest, worker, credencial e scope; UPDATE/DELETE são rejeitados.
- **Testes:** testes de serviço e migration SQLite; smoke PostgreSQL com duas sessões concorrentes, publicação idempotente, rejeição de token forjado e imutabilidade da auditoria.
- **Validação final:** commit `46006afcc5167e04f77037f985e65981a78248e3`; API CI [44480661837](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661837) — **1231 passed, 1 skipped, 1 warning** e smokes PostgreSQL 16 aprovados; Quality Gates [44480661851](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661851) e Docker Compose [44480661813](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661813) passaram.
- **Limites:** filesystem local apenas; sem object storage, catálogo de outputs/retention, endpoint HTTP de jobs, broker ou worker remoto. A execução assíncrona continua não operacional.

## 2026-11-19 — Regressão de destino publicado adulterado

Foi acrescentado um teste ao reconciliador de outputs para simular a adulteração do destino content-addressed depois de uma publicação auditada. Mesmo com o staging antigo e válido, o modo `apply` tem de preservar esse staging quando o SHA-256/tamanho do destino não correspondem à linha append-only. A regressão também verifica que o relatório identifica explicitamente a divergência. Validação CI pendente.


## 2026-11-19 — Regressão de symlinks no reconciliador

Adicionado teste de segurança para temporários de promoção cujo nome corresponde ao padrão interno mas cujo inode é um symlink. O teste executa o reconciliador em modo `apply` e verifica que o link é preservado, não aparece como candidato e o destino externo não é alterado. A validação CI deste commit está pendente.


## 2026-11-19 — Auditoria arquitectural da retenção de outputs

- Confirmado HEAD inicial `57ca70f29d51aa7c80fbd25a4ab9db13d9220658`.
- Lidos o protocolo autónomo, README integral por blocos, TODO, PROGRESS, roadmap e documentação de retenção relacionada.
- A publicação `dataset_execution_job_output_publications` já é um registo canónico append-only; as fontes imutáveis estão ligadas pelo job através de `dataset_execution_job_sources`.
- O catálogo `shelf_image_artifact_references` é por imagem/loja e as suas declarações não provam cobertura integral; não deve ser reutilizado directamente para um output que pode depender de várias imagens.
- Decisão: preservar a publicação como raiz, acrescentar eventos de governação separados e avaliar todas as fontes sob locks. Não duplicar hashes/caminhos numa segunda tabela nem activar purga por idade.
- Documento criado: `docs/architecture/dataset-output-artifact-governance.md`.
- Implementação de esquema/serviços permanece pendente porque a política de retenção, os poderes de legal hold e a cobertura externa ainda não estão aprovados. Nenhum comportamento destrutivo foi introduzido.
- Estado dos workflows do commit `57ca70f`: Docker Compose [44510497825](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44510497825) passou; Quality Gates [44510497768](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44510497768) passou; API CI [44510497835](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44510497835) ainda estava em execução na última consulta.


## 2026-11-19 — Fecho da corrida retenção/publicação de outputs

- Identificada uma janela de TOCTOU: a conclusão do job validava fontes, mas a promoção apenas revalidava job/worker/credencial depois da preparação dos bytes.
- Implementada revalidação de todas as fontes imutáveis através de `validate_internal_image_eligibility` na transacção final, com locks de imagem/prateleira/zona por ID crescente. Falha fechada se o job não tiver fontes ou se qualquer origem estiver ausente, mudar de loja/hash, ficar RESTRICTED ou receber legal hold.
- Criada migration `0064_dataset_output_source_eligibility` com trigger PostgreSQL que bloqueia as linhas de origem e trigger SQLite equivalente para impedir INSERT directo de publicação quando alguma fonte não é elegível.
- Acrescentados testes SQLite para RESTRICTED/legal hold e cenário concorrente PostgreSQL que aplica legal hold durante a fase lock-free de preparação.
- Código e documentação publicados; validação CI pendente.


## 2026-11-19 — Cobertura multi-origem na publicação de outputs

- Reforçada a regressão de serviço para jobs com duas imagens de origem. A lista é submetida deliberadamente fora da ordem dos IDs; a revalidação deve abranger ambas e manter a ordem estável de locks.
- A segunda origem é alterada durante a preparação do output: tanto `RESTRICTED` como `legal_hold` devem impedir a publicação. O teste verifica que não existe linha de publicação e que o staging original permanece intacto.
- A migration SQLite 0064 passa a ter um cenário com duas fontes, uma activa e outra restrita, para demonstrar que o trigger bloqueia a publicação completa.
- O smoke PostgreSQL foi alargado a jobs multi-origem e aplica o legal hold concorrente à segunda imagem, não à primeira.
- **Validação:** pendente dos workflows disparados pelo commit desta alteração. Nenhum teste local foi executado através desta sessão.
- **Limites:** não foram introduzidos eventos de governação de outputs, política de retenção nem purga física. A próxima decisão técnica é desenhar os eventos append-only sem alterar a publicação canónica.


### Validação final da cobertura multi-origem — commit `01abce944e7d883ea53aca17a09ac589701fdfc9`

- API CI [44516774051](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774051): **1241 passed, 1 skipped, 1 warning**; migration e smokes PostgreSQL 16 aprovados, incluindo promoção multi-origem e legal hold concorrente sobre a segunda fonte.
- Quality Gates [44516774058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774058): compilação Python, suite API e build TypeScript/produção aprovados.
- Docker Compose [44516774048](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774048): stack, readiness, seed e perfis demonstrativos aprovados.
- Aviso remanescente: depreciação de `anyio.abc.BlockingPortal` emitida pelo `starlette.testclient`; não provocou falhas.
- Nenhum teste foi executado localmente nesta sessão; a evidência é dos workflows GitHub Actions.


## 2026-11-19 — Eventos append-only de governação dos outputs (migration 0065)

- Criada a tabela `dataset_execution_job_output_governance_events`, separada da publicação canónica, com FK RESTRICT para publicação e actor humano.
- Eventos limitados a restrição aplicada/libertada e legal hold aplicado/libertado. A sequência é consecutiva por publicação; os triggers PostgreSQL bloqueiam a publicação para serializar escritores e SQLite aplica as mesmas regras de sequência/transição.
- UPDATE/DELETE dos eventos são recusados ao nível da base de dados. Actor inactivo, motivo vazio, evidência incompleta e transições repetidas/ilegais também são recusados.
- Criado `app.dataset_output_governance`: callback de autorização obrigatório, locks da publicação/actor, validação do motivo e da evidência, append de evento e leitura da projecção de estado.
- Testes acrescentados para migration SQLite, downgrade, autorização negativa, evidência e estados independentes de restrição/legal hold.
- O smoke PostgreSQL da publicação foi alargado para disputar duas restrições concorrentes na mesma publicação, observar o lock PostgreSQL, exigir um único evento aceite, aplicar legal hold e testar imutabilidade/sequence guard.
- **Validação:** pendente da execução dos workflows no commit desta alteração. Não foram executados testes localmente nesta sessão.
- **Decisão:** não foi escolhida uma matriz de permissões por perfil nem uma regra de dupla aprovação para libertar legal hold. O serviço exige callback de autorização obrigatório; não existe endpoint HTTP. Não foi criada purga física nem política de retenção temporal.


## 2026-11-19 — Validação final da governação append-only dos outputs

Commit validado: `b2247031a7d651a4efdc423f83bf7947723e27ff`.

- **API CI [44519805058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44519805058):** migration PostgreSQL 16, smoke de publicação e governação, concorrência de dois escritores na mesma publicação, transições, imutabilidade e suite API aprovados; **1244 passed, 1 skipped, 1 warning**.
- **Quality Gates [44519805055](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44519805055):** compilação Python, suite API e build TypeScript/produção Web aprovados; **1244 passed, 1 skipped, 1 warning**.
- **Docker Compose [44519805067](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44519805067):** stack demonstrativa aprovada.
- A primeira execução revelou um erro de teste na ordem dos eventos de legal hold e uma dependência de ordem do smoke de bootstrap. Ambos foram corrigidos; a execução final passou.
- O aviso restante é a depreciação `anyio.abc.BlockingPortal` no `starlette.testclient`; não está relacionado com esta alteração.
- Não foram executados testes localmente; a validação indicada é a dos workflows GitHub Actions.


## 2026-11-19 — Fronteira de consumo governado dos outputs publicados

- Criado `app.dataset_job_output_consumption` para leitura integral e verificada de outputs publicados.
- A operação bloqueia primeiro a publicação e o job, exige autorização explícita, consulta a projecção de eventos append-only e revalida a linhagem completa das fontes sob locks estáveis.
- O caminho tem de corresponder à referência content-addressed canónica. A leitura usa descritores de directório, `O_NOFOLLOW`, valida ficheiro regular, tamanho, estabilidade do inode/metadados e SHA-256.
- A função devolve bytes apenas depois de a leitura completa terminar; não suporta streams ou iteradores diferidos. O caller controla a transacção e deve mantê-la aberta até terminar o tratamento dos bytes.
- Testes acrescentados para caminho autorizado, autorização ausente, restrição, legal hold, restrições herdadas das fontes e adulteração.
- Não foram criados endpoints, downloads públicos, exports ou workers. Cópias externas, caches e backups ainda não são propagados.
- Validação: a executar por GitHub Actions após o commit; não foram executados testes locais nesta sessão.


### Validação PostgreSQL da fronteira de consumo — 2026-11-19

- O smoke PostgreSQL 16 passou a consumir o output publicado através do serviço, com autorização explícita, e comparar os bytes devolvidos.
- Depois de persistir uma restrição append-only, o mesmo caminho de consumo tem de lançar `DatasetJobOutputAccessDenied`.
- Foi acrescentado teste SQLite de symlink no destino publicado: o link é rejeitado e o ficheiro externo permanece intacto.
- A validação CI desta extensão fica pendente até à conclusão dos workflows do commit correspondente.


## Visão computacional — primeira sequência técnica concluída (2026-11-19)

HEAD validado: `69b9bba60a070933589d162ad9279ab4487c0a3b`.

- O provider ONNX deixou de descartar `class_id`: exige `VISION_CLASS_LABELS_JSON`, valida IDs/labels e rejeita classes devolvidas pelo modelo que não constem do catálogo configurado.
- Os contratos de input/output ONNX são verificados antes da inferência: float32, NCHW RGB, dimensão configurada, batch compatível, um input/output e seis valores por deteção pós-NMS.
- O worker usa `VISION_PROVIDER_MODE=disabled|mock|real`; o mock só aceita a factory determinística de demonstração e é recusado em produção. O Compose declara explicitamente o modo mock.
- `app.shelf_layout` ganhou `ShelfCell`, `ShelfCellObservation` e `compare_detections_to_cells`. Uma célula sem visibilidade calibrada começa em `UNKNOWN`; só uma célula explicitamente visível e não ocluída sem deteções pode ser `EMPTY`. O comparador não altera inventário.
- Testes adicionados para classes, confiança, metadados ONNX, provider modes, ocupação, célula vazia, oclusão, desconhecido, deslocamento e proveniência das deteções.
- API CI [44548878740](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44548878740): **1293 passed, 1 skipped, 1 warning**.
- Quality Gates [44548878678](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44548878678): build TypeScript/produção Web e compilação/testes API aprovados.
- Docker Compose [44548878709](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44548878709): stack de demonstração e verificações do worker aprovadas.
- O aviso remanescente é a depreciação Starlette/AnyIO; mensagens ERROR observadas nos logs PostgreSQL pertencem a testes de restrições negativas e o workflow terminou com sucesso.

**Limites:** não há pesos ONNX comerciais no repositório, dataset anotado nem benchmark de inferência real. As células são fornecidas por calibração/planograma revisto; ainda não há persistência, API nem integração no worker. O estado `EMPTY` é evidência visual local, nunca stock contabilístico.

**Próxima sequência proposta:** reforçar identidade/proveniência do modelo (SHA-256 do detector e embedder, fingerprint do mapa de classes e versão de pré-processamento), endurecer validação de imagens/outputs, e ligar a saída semântica à camada de matching sem transformar etiquetas genéricas em SKU.

## Visão computacional — identidade criptográfica do modelo (2026-11-19)

A segunda sequência reforçou a proveniência do provider ONNX sem alterar o schema da base de dados:

- SHA-256 dos pesos do detector e, quando configurado, do embedder, calculado por streaming em blocos de 1 MiB.
- Fingerprint efectivo do detector combina digest dos pesos, fingerprint do mapa de classes, tamanho de entrada, limiar de confiança, máximo de deteções e versão fixa do pré-processamento.
- Fingerprint do embedder é independente e combina os seus pesos, dimensão de entrada e versão de pré-processamento. A versão efectiva passa a ser `versão-configurada@SHA256`.
- O provider recusa caminhos de modelo simbólicos e repete o hash depois de criar cada sessão ONNX, rejeitando substituição do ficheiro durante o carregamento.
- Os fingerprints ficam dentro dos campos de versão já persistidos nas deteções; não se afirma que exista ainda um manifesto assinado nem colunas dedicadas de auditoria.
- **Compatibilidade deliberadamente fail-closed:** exemplares SKU aprovados com uma versão anterior do embedder não correspondem à nova versão fingerprintada. É necessário gerar e aprovar exemplares usando a nova versão efectiva antes de obter matches.
- Foram acrescentados testes de estabilidade, alteração de pesos/labels/configuração, symlink e substituição concorrente. Validação CI pendente para esta sequência.

## Visão computacional — whitelist semântica para matching SKU (2026-11-19)

- Foi adicionada a configuração `VISION_SKU_MATCH_LABELS` (por omissão `product`) para limitar as classes que podem gerar embeddings e consultar o catálogo.
- O provider ONNX não executa o embedder para classes não elegíveis, por exemplo `empty_facing`.
- `resolve_sku_match` repete a validação no worker, pelo que providers alternativos também não podem associar classes não elegíveis a SKU, mesmo que forneçam embeddings.
- A whitelist faz parte do fingerprint do detector; alterar as classes elegíveis altera a identidade efectiva da configuração.
- Foram acrescentados testes de provider e worker para provar que uma deteção `empty_facing` não é correspondida a exemplares de produto.
- Validação CI pendente; não existe ainda dataset real anotado nem ligação das classes de vazio ao comparador de células.
### Validação da terceira sequência — 2026-11-19

HEAD de código validado: `c43b420d2e836daab53f2db5db6a3ddb2dea98f8`.

- API CI [44551987378](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44551987378): PostgreSQL 16, migrations e testes de concorrência aprovados; **1307 passed, 1 skipped, 1 warning**.
- Quality Gates [44551987148](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44551987148): testes API/compilação Python e build TypeScript/produção Web aprovados.
- Docker Compose [44551987356](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44551987356): stack de demonstração aprovada.
- As falhas iniciais foram de fixtures: classe de catálogo não elegível, fixture de sessão do embedder a reutilizar contrato do detector e caixa de SKU esperado com sobreposição abaixo do limiar. Os fixtures foram corrigidos e a nova execução passou.
- Os dois checks Vercel continuam a reportar `build-rate-limit` (limite de builds da conta), não uma falha de compilação do frontend; o build Web do Quality Gates passou.

## Visão computacional — evidência positiva para espaços vazios (2026-11-19)

A quarta sequência corrige uma ambiguidade de negócio importante no comparador geométrico: ausência de deteções não prova que a célula está vazia.

- `compare_detections_to_cells` separa deteções `empty_facing` das deteções de produto.
- `EMPTY` exige uma deteção positiva `empty_facing`, confiança >= 0,80 (configurável), sobreposição geométrica mínima e célula marcada como visível e não ocluída.
- Sem deteções, com confiança insuficiente ou com a célula ocluída/fora de vista, o estado é `UNKNOWN`.
- Evidência simultânea de produto e vazio na mesma célula gera `CONFLICT`, sem resolução silenciosa.
- Os resultados preservam índices de deteção, IDs de produto e sobreposição máxima para auditoria/revisão.
- Testes acrescentados para vazio positivo, threshold, oclusão, ausência de deteção, conflito e scores inválidos.
- API CI [44553140735](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44553140735): PostgreSQL 16 e suite API aprovados; **1311 passed, 1 skipped, 1 warning**.
- Quality Gates [44553235687](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44553235687): testes API, compilação Python e build Web aprovados.
- Docker Compose [44553140813](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44553140813): stack de demonstração aprovada.

**Limites:** o comparador continua puro e não está ligado ao worker/API. As células têm de vir de calibração ou planograma externo; não há ainda persistência nem calibração real do threshold. O estado `EMPTY` é evidência visual da célula, não stock contabilístico.
## Visão computacional — comparação de facings com planograma (2026-11-19)

- `ShelfCell` suporta `expected_facings` opcional, positivo e associado a um SKU esperado.
- `ShelfCellObservation` expõe `expected_facings` e `observed_facings`; o contador considera apenas deteções de produto associadas à célula, nunca a classe `empty_facing`.
- Foram introduzidos `UNDER_FACED` e `OVER_FACED`; `OCCUPIED` significa contagem frontal exacta quando o esperado está configurado.
- Estados `MISPLACED`, `OCCUPIED_UNIDENTIFIED` e `CONFLICT` têm precedência sobre a comparação numérica para evitar mascarar SKU incorrecto/desconhecido ou evidência contraditória.
- Testes cobrem contagem inferior/excedente/exacta, prioridade de SKU errado, SKU desconhecido, validação de `expected_facings` e célula vazia com zero facings observados.
- Limite: a contagem é número de caixas pós-NMS associadas, não quantidade física em profundidade. Deduplicação/calibração com imagens reais e integração persistente continuam pendentes.
- Validação CI pendente para esta sequência.

## 2026-11-19 — API HTTP de planogramas versionados

A migration `0067_shelf_planograms` e o serviço de domínio passaram a ter uma fronteira HTTP autenticada:

- Criadas rotas para criar versões DRAFT com células, consultar histórico, obter versão ativa, ativar e retirar planogramas.
- Os motivos de ativação/retirada são obrigatórios; a ativação substitui a versão anterior na mesma transação.
- Middleware e handlers exigem ADMIN/SUPERVISOR; o serviço revalida actor ativo e âmbito da loja. Supervisores ficam limitados à sua loja; funcionários EMPLOYEE não acedem.
- A resposta inclui os metadados de ciclo de vida e as células normalizadas. O histórico é ordenado por versão descendente e tem paginação limitada.
- Corrigido o trigger SQLite de DELETE de células: a cascata de eliminação de um DRAFT não pode ser confundida com alteração de uma versão protegida.
- As primeiras execuções de CI identificaram um bloco mal formado no middleware e uma fixture que não fazia commit dos utilizadores de teste; ambos foram corrigidos antes da validação final.

**Validação final no commit `dd262068bdf8178a8eddff0f103317aec8a3558b`:**
- API CI [44559057802](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44559057802): PostgreSQL 16/migrações e **1330 passed, 1 skipped, 1 warning**.
- Quality Gates [44559057575](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44559057575): compilação Python, suite API e build Web aprovados.
- Docker Compose [44559057828](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44559057828): stack aprovada.

**Limites:** ainda não há endpoint de edição de rascunhos, persistência de `expected_facings`, UI React, integração do comparador no worker ou validação com dataset real. A API não altera inventário.


## 2026-11-19 — Facing targets persistidos e edição atómica de rascunhos

A migration `0068_shelf_planogram_expected_facings` acrescenta `expected_facings` às células. O campo é opcional; quando presente, tem de ser inteiro positivo e exige um SKU esperado. PostgreSQL usa CHECK constraint e SQLite usa triggers INSERT/UPDATE. O modelo, schemas e serviço de domínio validam a mesma regra.

O serviço `replace_draft_planogram_cells` substitui todas as células numa transação, apenas quando o planograma está em `DRAFT`. A ordem de locks mantém-se imagem → prateleira → planograma; a imagem de calibração e a elegibilidade dos SKUs são revalidadas antes da substituição. Depois de ativado, o planograma não pode ser editado. A rota HTTP `PUT /api/v1/planograms/{planogram_id}/cells` aplica a mesma política ADMIN/SUPERVISOR e isolamento multi-loja.

Foram acrescentados testes de serviço, migração SQLite e API para valores inválidos, associação obrigatória a SKU, round-trip de `expected_facings`, substituição de células e recusa de edição após ativação.

**Validação final no commit `3d9f338e5bdf50a9674f53d05da1ad99e23faa01`:**
- API CI [44560333697](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44560333697): PostgreSQL 16/migrações e **1334 passed, 1 skipped, 1 warning**.
- Quality Gates [44560333600](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44560333600): compilação Python, suite API e build Web aprovados.
- Docker Compose [44560333624](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44560333624): stack aprovada.

**Limites:** não existe ainda smoke PostgreSQL específico para a constraint de `expected_facings` nem teste concorrente entre edição e ativação. A comparação ainda não está integrada no worker/UI e não foi calibrada com imagens reais.


## 2026-11-19 — Smoke PostgreSQL dedicado a planogramas

Foi criado `apps/api/scripts/postgres_planogram_lifecycle_smoke.py` e integrado no workflow API CI. O smoke executa contra PostgreSQL 16 e verifica:

- CHECK constraint de `expected_facings`: rejeita zero e ausência de SKU esperado.
- Imutabilidade das células após ativação.
- Índice único parcial: não permite duas versões ACTIVE na mesma prateleira.
- Concorrência real em duas sessões: uma transação substitui as células de um DRAFT enquanto outra tenta ativá-lo. A ativação fica bloqueada no lock da prateleira até a edição fazer commit e ativa a nova geometria.

**Validação final no commit `46eb9bbc19a039d2e68183655fb07501a0c12ef8`:**
- Smoke PostgreSQL dedicado passou.
- API CI [44561359774](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44561359774): PostgreSQL 16/migrações e **1334 passed, 1 skipped, 1 warning**.
- Quality Gates [44561359524](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44561359524): compilação Python, suite API e build Web aprovados; **1334 passed, 1 skipped, 1 warning**.
- Docker Compose [44561359723](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44561359723): stack aprovada.

O teste de concorrência confirma a serialização edição/ativação no serviço e no PostgreSQL. A integração worker/UI continua por fazer.


## 2026-11-19 — Interface web de comparação de planogramas

- SHA inicial desta ronda: `5f08ef753f3ba0edba4708c1b72ecaf0d3b36c72`.
- Criado `apps/web/src/PlanogramComparison.tsx`, componente isolado que recebe as prateleiras/capturas carregadas pelo dashboard e usa o cliente HTTP autenticado existente.
- Integrado no dashboard para ADMIN/SUPERVISOR, com seleção de prateleira e capturas em estado COMPLETED.
- A interface mostra versão ativa, SHA-256 da imagem, modelo, origem de calibração, estado por célula, facings, IDs de deteções e sobreposição geométrica.
- A semântica do backend é preservada: sem calibração de visibilidade a interface apresenta UNKNOWN e informa que não se pode inferir vazio/rutura. Não há escrita nem alteração de inventário.
- Adicionados estilos responsivos e estados de erro/vazio/loading.
- Documentação actualizada no README, TODO e ROADMAP.
- Não foram executados testes locais nem CI nesta ronda; a validação de build/CI e a revisão manual permanecem pendentes.
- Próxima tarefa: obter execução dos Quality Gates/Web CI; corrigir quaisquer erros TypeScript e depois acrescentar testes de componente para filtros de loja/prateleira e erros HTTP.


## 2026-11-19 — Reforço de testes e reconciliação documental de planogramas

- Acrescentados testes HTTP para a resposta HTTP 409 quando não existe planograma ativo, mesmo que a captura esteja concluída e disponível.
- Acrescentado teste de proveniência de calibração por imagem: criação da captura de calibração, criação/ativação do planograma e verificação do ID e SHA-256 devolvidos pela comparação.
- Actualizada a documentação de arquitectura e o README para reflectir a interface React já integrada, eliminando a afirmação obsoleta de que não existe UI.
- Actualizado o TODO para distinguir a consulta visual já entregue da persistência append-only, integração worker e revisão humana ainda pendentes.
- A comparação mantém-se read-only e on-demand. A persistência fica deliberadamente bloqueada até existir política de retenção, identidade/versionamento do resultado e comportamento definido perante revogação da imagem/modelo/planograma.
- Os dois novos testes ainda necessitam de execução no CI; não declarar validação concluída antes dos workflows terminarem.


## 2026-11-19 — Reforço da proteção de retenção nas comparações

- Reconfirmado que o endpoint valida `retention_status == ACTIVE` em cada pedido e só depois consulta deteções.
- Acrescentado teste parametrizado para os estados RESTRICTED, PENDING_PURGE e PURGED, todos com resposta HTTP 404 e sem exposição do resultado.
- Documentada a distinção entre a captura de comparação e a referência histórica de calibração por imagem.
- Não foi criada persistência de resultados: continua dependente de um contrato de retenção, identidade/versionamento e auditoria append-only.
- Aguardam-se os workflows CI do commit desta alteração antes de declarar a cobertura validada.


## 2026-11-19 — Identidade determinística da comparação

- A resposta da comparação passou a expor `comparison_schema_version` e `comparison_sha256`.
- O digest SHA-256 é calculado sobre JSON canónico e inclui captura/digest, versão do modelo, identidade e versão do planograma, calibração e células comparadas.
- O teste HTTP de proveniência confirma que chamadas repetidas para a mesma evidência produzem o mesmo digest.
- O digest é um identificador reproduzível, não uma assinatura digital. A comparação continua on-demand e não persistida.
- A validação CI do novo contrato está pendente.


## 2026-11-19 — Serialização da comparação de planogramas com retenção

- Identificada uma janela de concorrência: o endpoint verificava a retenção da captura sem bloquear a linha da imagem e só depois carregava o planograma ativo.
- Criado `load_active_planogram_for_comparison`: bloqueia captura e calibração em ordem crescente de ID, valida ACTIVE/COMPLETED, bloqueia a prateleira e o planograma, e revalida a identidade da versão ativa.
- Alterações concorrentes de versão devolvem HTTP 409; capturas restringidas continuam a devolver HTTP 404.
- O smoke PostgreSQL mantém uma comparação aberta enquanto outra sessão tenta restringir a captura; a restrição deve esperar e a consulta posterior deve falhar.
- A comparação permanece read-only, não persistida e sem efeitos no inventário.
- Validação CI desta alteração pendente.


### Validação final da comparação serializada — 2026-11-19

- API CI [44588809660](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44588809660): passou; migration PostgreSQL 16, todos os smokes operacionais, incluindo o smoke de comparação/retenção, e **1342 testes aprovados, 1 ignorado e 1 aviso**.
- Quality Gates [44589016727](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44589016727): passou; compilação Python, suite API com o mesmo resultado e build TypeScript/produção Web aprovados.
- Docker Compose [44588809507](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44588809507): passou.
- A evidência confirma a serialização PostgreSQL entre comparação e restrição; não representa validação manual com imagens reais nem autoriza persistência/integração no worker.


## 2026-11-19 — Endurecimento do fingerprint de comparação

- O cálculo SHA-256 rejeita versões de esquema desconhecidas e força a versão suportada no payload canónico.
- O digest continua a excluir apenas o seu próprio campo; os resultados por célula fazem parte da identidade.
- Acrescentados testes para ordenação de chaves, alteração de estado de célula, digest próprio, versão não suportada e NaN.
- Validação CI pendente.
