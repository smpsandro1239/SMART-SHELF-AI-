# Ordem de autorização e locks por tenant

## Problema

Adquirir um row lock antes de verificar o store scope permite que um utilizador autenticado de outra loja cause contenção sobre recursos que não pode alterar. A resposta final 403 não elimina o impacto de disponibilidade.

## Contrato obrigatório

Para recursos multi-loja:
1. Fazer uma leitura não bloqueante para resolver o store_id.
2. Revalidar a identidade activa e as permissões do actor.
3. Aplicar store scope antes do lock.
4. Adquirir o row lock e refrescar o registo.
5. Revalidar o store scope sobre o estado bloqueado.
6. Executar a operação e auditoria na mesma transacção.

Não usar um lock global como substituto de autorização.

## Helpers

- _lock_authorized_shelf_image: valida a relação imagem → prateleira → zona antes e depois do lock.
- _lock_store_scoped_record: aplica o mesmo padrão a entidades com store_id directo.

## Cobertura

22 handlers são protegidos por estes helpers ou por autorização de recurso equivalente:
- Conteúdo, retenção, deteções, OCR, matching e fusão de evidências de imagens.
- Revisões de SKU e exemplares de embeddings.
- Sessões de captura e upload associado.
- Tarefas de reposição e reconciliação.
- Eventos de paletes.
- Actualização de alertas.

O teste test_store_scoped_lock_handlers_authorize_before_their_first_lock verifica que os handlers usam o helper antes de qualquer lock local. O teste test_store_scoped_record_lock_rejects_foreign_store_before_lock confirma que um actor de outra loja é recusado sem tentar adquirir lock.

## Evidência

No commit 1c0f591:
- API CI: 1413 passed, 1 skipped.
- Quality Gates: 1413 passed, 1 skipped.
- PostgreSQL 16 concurrency/retention smokes: PASS.
- ZAP baseline/API safe-mode: 0 High, 0 Medium, 0 Low.

## Limitações

Esta é uma correcção da ordem de locks e uma cobertura estática dos handlers identificados. Não substitui a auditoria completa BOLA/IDOR por recurso, nem a matriz autenticada endpoint × ADMIN/SUPERVISOR/EMPLOYEE × loja.

## Revalidação — 2026-11-21

No commit a345746, API CI e Quality Gates passaram com 1422 testes aprovados e 1 ignorado. Os 22 handlers abrangidos pela regra de autorização pré-lock continuam cobertos; PostgreSQL 16 smokes e o workflow de segurança também passaram.

## Evidência adicional — matriz de leituras multi-loja (2026-11-23)

- O smoke `postgres_inventory_authorization_smoke.py` cobre 23 rotas GET de vendas, tráfego, forecasting, replenishment, decisões e warehouse com `store_id` da loja estrangeira.
- O actor é um SUPERVISOR autenticado por JWT, associado à loja de origem; as respostas esperadas são HTTP 403. O mesmo script mantém as tentativas de escrita cross-store e verifica que não deixam alterações persistidas.
- A alteração está no commit `40f9456a`; API CI, Quality Gates, Security Scans e Docker Compose ainda aguardam conclusão no SHA.
- Esta evidência não substitui testes de IDs aninhados, todos os papéis/rotas, leitura positiva same-store ou ensaio de volume persistente.


## Cobertura adicional de IDs aninhados — 2026-11-23

O smoke PostgreSQL foi ampliado para testar isolamento por shelf_id em recursos indirectos:

- Observações, sessões de captura e alertas existentes na loja estrangeira não são devolvidos por listagens filtradas com o ID real da prateleira estrangeira.
- Criação de observações, sessões de captura e planogramas através de uma prateleira estrangeira é recusada.
- Leitura de consenso, planogramas e eventos de alertas estrangeiros é recusada.
- Os controlos positivos same-store para observação e sessão de captura confirmam que a autorização não bloqueia recursos próprios.

A implementação está publicada no commit 99a69a7415bc552b0cf104861d93881dac6259e1; a execução PostgreSQL 16/CI ainda está pendente. Esta cobertura não substitui a matriz integral endpoint x ADMIN/SUPERVISOR/EMPLOYEE.


## Matriz RBAC — ADMIN e EMPLOYEE (2026-11-23)

O smoke multi-loja também comprova:

- ADMIN consegue consultar os IDs concretos das observações, sessões e alertas seedados na loja B.
- EMPLOYEE recebe 403 nos endpoints de observações, sessões de captura, alertas e planogramas, mesmo quando consulta recursos da loja A.

Commit `26a97f7136eace2bc0b4f428731db3990163aa93`; validação PostgreSQL 16/CI pendente. Esta amostra não é a matriz completa de todos os endpoints.


## Evidência de execução PostgreSQL — 2026-11-23

O passo **Verify PostgreSQL inventory and warehouse cross-store authorization** passou no API CI [45177953932](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45177953932), em PostgreSQL 16, no commit de código `26a97f7136eace2bc0b4f428731db3990163aa93`. A evidência cobre as novas fixtures e tentativas BOLA/RBAC documentadas acima. A suite pytest completa ainda estava em execução, pelo que este resultado não equivale à conclusão integral do API CI.


## Planogramas — preflight de tenant e locks PostgreSQL (2026-11-23)

As operações do serviço app.shelf_planograms aplicam agora a sequência autorização → locks → revalidação:

- Criação: preflight da prateleira e da imagem de calibração, depois imagem → prateleira → planograma.
- Edição, activação e retirada por planogram_id: resolução não bloqueante da prateleira/imagem de origem, preflight do tenant e só depois aquisição dos locks.
- Comparação: preflight da prateleira, da captura e da imagem de calibração; as imagens são bloqueadas por ID crescente antes da prateleira/planograma.
- Leitura do planograma ACTIVE: valida o acesso à prateleira mesmo quando não existe versão activa.

O smoke postgres_planogram_lifecycle_smoke.py usa PostgreSQL 16 e mantém locks reais sobre uma prateleira ou imagem estrangeira enquanto um supervisor autorizado apenas na loja A tenta editar, activar, retirar, calibrar ou comparar recursos da loja B. As cinco operações têm de ser rejeitadas sem aguardar pela libertação dos locks. O passo passou no API CI [45185460992](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45185460992) e voltou a passar no HEAD [48859d1](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45186900075).

## Revisão de exemplares sem imagem de origem — pré-lock do catálogo (2026-11-23)

review_product_embedding_exemplar rejeita supervisores que tentem rever exemplares sem imagem de origem antes de adquirir o lock do produto global. Para exemplares com imagem, o serviço valida primeiro o tenant e a retenção; uma auto-revisão é recusada depois dessa validação e antes do lock do produto. A verificação pós-lock continua presente para detectar alterações concorrentes à autoria/origem.

O teste test_image_less_exemplar_non_admin_is_rejected_before_product_lock confirma a ausência de query ao catálogo e a preservação do estado PENDING. O smoke postgres_embedding_review_smoke.py mantém o produto bloqueado numa sessão PostgreSQL e exige HTTP 403 sem espera para o pedido não autorizado. O passo passou no API CI [45186900075](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45186900075).

## Evidência consolidada — 2026-11-23

No HEAD 48859d1e1e0cc0581c5cdf69b14db6a5cfed6794:
- API CI [45186900075](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45186900075): PostgreSQL 16, todos os smokes, **1588 passed, 1 skipped**.
- Quality Gates [45186899975](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45186899975): compilação Python, suite API (**1588 passed, 1 skipped**) e build Web.
- Security Scans [45186899976](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45186899976): Gitleaks, pip-audit, npm audit e OWASP ZAP passive baseline.
- Docker Compose [45186899968](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45186899968): stack demonstrativa aprovada.

A validação é automatizada. Não substitui a matriz integral BOLA/IDOR, ensaio de volume persistente preexistente, revisão manual da interface ou avaliação com modelos/imagens reais.


## Ocultação de IDs directos de sessões e alertas — 2026-11-23

- O fecho de sessões de captura usa _lock_store_scoped_record com hide_foreign=True: o tenant é verificado antes do lock e revalidado depois.
- A actualização de alertas usa o mesmo helper; a leitura de eventos não adquire lock, mas valida o store_id antes de consultar eventos.
- Para SUPERVISOR, IDs estrangeiros e inexistentes devolvem HTTP 404 equivalente. ADMIN mantém acesso global e EMPLOYEE continua bloqueado pelo RBAC.
- Regressões HTTP verificam igualdade das respostas 404 e ausência de alterações na sessão/alerta estrangeiro. Código b627107; testes 1a2e776. CI/PostgreSQL 16 ainda pendente.


## Ocultação de IDs directos de consenso de prateleira — 2026-11-23

O endpoint GET /api/v1/shelves/{shelf_id}/observation-consensus compara o tenant da prateleira antes de consultar evidência. Para SUPERVISOR, uma prateleira estrangeira e um ID inexistente devolvem o mesmo HTTP 404. A rota POST /api/v1/shelves/{shelf_id}/observation-alerts/evaluate herda o contrato e não persiste alertas quando a prateleira não é autorizada. Testes autenticados cobrem ambos os percursos. Código 2f4470e; teste 5feffba. CI/PostgreSQL 16 pendente.


## IDs de prateleira — criação e consenso (2026-11-23)

As rotas create_observation, create_capture_session e get_shelf_observation_consensus executam a autenticação/validação de papel antes da consulta do ID de prateleira. Para SUPERVISOR, IDs de outra loja e IDs inexistentes devolvem HTTP 404 equivalente. A avaliação de alertas usa o mesmo caminho de consenso e não persiste quando a prateleira não é autorizada. Testes HTTP cobrem os cenários negativos e ausência de efeitos. Commits de código 9288459/cce1afd; testes 739a574/d5d6243. CI/PostgreSQL 16 pendente.


## IDs directos de tarefas — ocultação e leitura sem lock (2026-11-23)

- GET /api/v1/tasks/{task_id}/events autentica/responde primeiro com actor, resolve a tarefa sem row lock e oculta tarefas estrangeiras com HTTP 404 igual ao ID inexistente antes de consultar eventos.
- PATCH /api/v1/tasks/{task_id}/status e POST /api/v1/tasks/{task_id}/reconcile-inventory executam preflight tenant, lock e revalidação através de _lock_store_scoped_record(hide_foreign=True).
- Testes de regressão comparam respostas estrangeira/inexistente para os três endpoints; verificam ausência de transição/eventos e ausência de InventoryMovement quando a reconciliação é negada.
- Commits: GET 954f973; mutations ee40b88; testes f12ed7b e cc3dc3a. Validação CI/PostgreSQL 16 pendente.
