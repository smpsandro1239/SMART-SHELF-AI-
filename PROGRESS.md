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
