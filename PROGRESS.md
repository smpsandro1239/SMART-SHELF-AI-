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
- Quality Gates [44880841658](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44880841658) e Docker Compose [44880841671](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44880841671) passaram no commit de código/testes `311fecc9`. A execução Quality Gates do head documental anterior está em curso; não há execução local.
