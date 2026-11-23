## 2026-11-23 — Controlos positivos same-store para recursos logísticos reais

- O smoke `postgres_inventory_authorization_smoke.py` cria agora um nível de embalagem CASE e uma palete válida em cada loja.
- Os pedidos de leitura cross-store usam o ID real da palete estrangeira; os controlos positivos substituem-no pelo ID da palete da loja do supervisor.
- Foram removidas as três exclusões anteriores: cálculo de unidades de reposição, plano de rotação de palete e eventos de ciclo de vida. A expectativa passa a ser HTTP 200 para todos os 23 controlos same-store e HTTP 403 para as 23 leituras cross-store.
- Commit de código: `3af7a02b`.
- API CI, Quality Gates, Security Scans e Docker Compose deste novo SHA ainda não foram confirmados. A alteração foi publicada no GitHub; não foi executada localmente nesta sessão.
- Próximo passo: validar o smoke em PostgreSQL 16 e expandir a matriz para IDs aninhados/relacionais.

---

## 2026-11-23 — Expansão da matriz PostgreSQL de leituras cross-store

- Actualizado `apps/api/scripts/postgres_inventory_authorization_smoke.py` para exercitar 23 endpoints GET que recebem `store_id` em vendas, tráfego, forecasting, replenishment, decisões operacionais e warehouse.
- Cada pedido usa um JWT real de SUPERVISOR da loja A e identifica a loja B. A expectativa é HTTP 403 antes de consultar dados da loja estrangeira.
- Mantidos os testes existentes de escrita cruzada e as verificações de estado persistido (inventário, policies, placements, tarefas, movimentos e eventos).
- O script já está integrado no job API CI através do passo `Verify PostgreSQL inventory and warehouse cross-store authorization`.
- Commit: `40f9456a`.
- API CI [45131503709](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503709), Docker Compose [45131503757](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503757), Quality Gates [45131503760](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503760) e Security Scans [45131503689](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45131503689) foram iniciados; ainda não existe resultado confirmado para este SHA.
- A matriz não cobre todas as combinações endpoint × role × tenant. Permanecem pendentes a matriz positiva same-store, IDs aninhados/relacionais e volume PostgreSQL persistente.

---

## 2026-11-23 — Expansão da prova PostgreSQL pré-lock para nove rotas HTTP

- O smoke `postgres_retention_legal_hold_concurrency_smoke.py` testa agora nove rotas de imagem com um supervisor de outra loja: conteúdo, deteções, evidence fusion, OCR evidence/matches/runs, eventos de retenção, retry e restrict.
- A transacção concorrente mantém a linha `shelf_images` bloqueada. Todas as rotas têm de responder HTTP 403 antes da libertação do lock; qualquer handler que tente bloquear a imagem antes de autorizar provoca timeout e falha o smoke.
- O passo `Verify PostgreSQL legal hold and purge schedule concurrency` passou no API CI [45130818413](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818413), SHA `d319d1a4`.
- Docker Compose [45130818319](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818319), Quality Gates [45130818392](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818392) e Security Scans [45130818374](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818374) passaram.
- API CI terminou com sucesso: **1555 passed, 1 skipped** no [run 45130818413](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130818413).
- Os endpoints de artefactos, legal hold e purge que exigem ADMIN seguem a política de administrador global; não são casos de negação cross-store para SUPERVISOR. A revisão dos restantes handlers de escrita/revisão continua pendente.

---

## 2026-11-23 — Resultados CI da prova PostgreSQL multi-loja pré-lock

- O smoke PostgreSQL `Verify PostgreSQL legal hold and purge schedule concurrency` concluiu com sucesso no API CI [45129975394](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975394), commit de código `926abcf1`. O teste executou o pedido de supervisor estrangeiro enquanto a imagem estava bloqueada e confirmou rejeição HTTP 403 sem aguardar pelo lock.
- Docker Compose demo smoke passou em [45129975482](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975482), no mesmo SHA de código.
- A falha anterior do Compose smoke foi causada pela ausência de `MIGRATION_DB_USER` nas invocações inline do runtime-role smoke. Corrigido em `b4995042`, com regressão estática em `edf879a2`; a execução Compose acima passou no SHA `926abcf1`.
- Quality Gates passou em [45130013285](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013285), SHA documental `7b10c5c1`: compilação Python, suite API e build Web concluídos com sucesso.
- API CI terminou com sucesso em [45129975394](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975394), SHA de código `926abcf1`: migrações PostgreSQL 16, todos os smokes, provisionamento/verificação da role runtime e **1555 testes aprovados, 1 ignorado**.
- Security Scans terminou com sucesso em [45130013260](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013260), SHA documental `7b10c5c1`: Gitleaks, pip-audit, npm audit e OWASP ZAP passive baseline passaram.
- Quality Gates [45130013285](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013285) e Docker Compose [45129975482](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975482) também passaram.
- **Ainda pendente:** integração multi-loja HTTP/PG dos restantes handlers, ensaio de volume persistente preexistente e operações reais com principal runtime.

---

## 2026-11-23 — Prova PostgreSQL de autorização multi-loja antes de lock (CI validada; cobertura adicional pendente)

- O smoke de retenção PostgreSQL cria agora uma segunda loja e um supervisor pertencente a essa loja.
- Enquanto outra sessão mantém a linha de uma imagem bloqueada com `FOR UPDATE`, o supervisor externo tenta restringir a imagem através da API.
- O teste exige HTTP 403 antes da libertação do lock; se o handler tentar adquirir o lock antes da autorização, a chamada excede o timeout e o smoke falha.
- Os ensaios anteriores de concorrência entre legal hold, agendamento de purga e restauro foram preservados.
- O smoke já está ligado ao job PostgreSQL da API CI através do passo existente `Verify PostgreSQL legal hold and purge schedule concurrency`.
- Commits: `25a34b8f` e `926abcf1`.
- **Validação concluída:** API CI [45129975394](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975394) passou com 1555 testes aprovados e 1 ignorado; Quality Gates [45130013285](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013285), Security Scans [45130013260](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45130013260) e Docker Compose [45129975482](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45129975482) passaram. Não foi executado localmente nesta sessão.

---

## 2026-11-23 — Autorização de tenant antes de locks em retenção e artefactos (código publicado; CI em execução)

- A auditoria da ordem de locks encontrou dez handlers que adquiriam `FOR UPDATE` na imagem antes de validar a loja. Embora alguns validassem o tenant mais tarde, um pedido sem autorização podia adquirir locks de recursos de outra loja antes da rejeição.
- Corrigidos os cinco fluxos de retenção (restauro, legal hold apply/release e agendamento/cancelamento de purga), a consulta de elegibilidade de purga e quatro fluxos de artefactos externos (registo, snapshot de inventário, diagnóstico de acesso e evento de disposição).
- Os nove handlers que operam sobre a imagem usam agora `_lock_authorized_shelf_image`, que verifica a loja antes do lock e volta a verificar a linhagem depois. A elegibilidade mantém o erro específico de linhagem inválida e faz o preflight antes do lock.
- `test_security.py` passou a exigir a ordem autorização → lock nos dez handlers. Uma verificação estática adicional no código publicado confirmou os dez casos. Foi acrescentado um teste unitário que prova que um supervisor de outra loja é rejeitado antes de qualquer query de lock.
- Corrigida também a duplicação de duas tarefas pendentes em `TODO.md`.
- Commits de código/testes: `f6e2156e`, `659586be`, `7f372fbc`, `cbc6a1a6`, `70b1b351`; TODO: `fcb685bf`.
- CI actual no SHA de código/testes `70b1b351`: API CI [45127205680](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45127205680), Quality Gates [45127205615](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45127205615), Security Scans [45127205627](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45127205627) e Docker Compose [45127205559](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45127205559) foram iniciados; resultados ainda não confirmados.
- Validação anterior da correcção PostgreSQL default ACL: API CI/PostgreSQL 16 run [45084795278](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45084795278) passou; Quality Gates [45084849142](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45084849142) e Security Scans [45084849107](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45084849107) passaram no SHA documental `00d6ef51`.
- **Ainda em aberto:** testes de integração PostgreSQL com duas lojas para estes dez fluxos, ensaio de volume persistente e operações reais API com principal runtime. A auditoria estática não substitui estes ensaios.

---
## 2026-11-22 — Correcção do âmbito dos default ACLs PostgreSQL (código publicado; CI pendente)

- A revisão do smoke identificou que a query de `pg_default_acl` agregava permissões concedidas ao runtime por qualquer owner, em vez de verificar especificamente os objectos futuros criados pelo principal de migrations.
- A query passa a filtrar `pg_default_acl.defaclrole` pelo papel explícito `MIGRATION_DB_USER`, e continua a verificar o grantee como `current_user`, privilégios exactos e ausência de GRANT OPTION.
- O job PostgreSQL 16 da API CI fornece `MIGRATION_DB_USER=postgres`; o teste estático verifica o contrato e a ligação da configuração.
- Commits desta correcção: `bb3766fc`, `491ae99f`, `8e5a6810`.
- Evidência anterior à correcção: API CI [45083455380](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083455380) e Docker Compose [45083455389](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083455389) passaram no SHA `72d4034d`; Quality Gates [45083489901](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083489901) e Security Scans [45083489889](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45083489889) passaram no SHA `9bad015c`.
- **Ainda não validado:** os workflows têm de ser reexecutados no novo SHA; continua pendente o ensaio com volume persistente real e operações API com o principal runtime.

---

## 2026-11-22 — Expansão do smoke de segurança PostgreSQL runtime (implementação publicada; CI pendente)

- O smoke `apps/api/scripts/postgres_runtime_role_smoke.py` verifica agora o atributo LOGIN e todos os atributos privilegiados, incluindo NOINHERIT.
- A verificação de ownership foi generalizada para `pg_shdepend`, em vez de se limitar a relações, schemas e bases de dados.
- São verificados CONNECT, USAGE no schema público e ausência de CREATE.
- O smoke inspeciona os default ACLs de tabelas e sequências futuras, exige apenas os privilégios operacionais previstos e rejeita GRANT OPTION.
- Todas as tabelas operacionais existentes têm de conceder SELECT/INSERT/UPDATE/DELETE; as duas tabelas de confiança ONNX permanecem SELECT-only e sem acesso à sequência de auditoria.
- Foi acrescentado teste estático para impedir regressões na cobertura do smoke.
- Commits: `2d7bce2f`, `afda3ee6`, `ee609372`, `72d4034d`.
- **Validação pendente:** não foi possível executar localmente Python/PostgreSQL nesta sessão; os workflows do SHA final ainda não foram confirmados. Continua pendente o ensaio com volume persistente real e operações API sob o principal runtime.

---

## 2026-11-21 — Avaliação de Computer Vision com COCO (implementação publicada; CI/dataset pendentes)

- Criado `apps/api/app/vision_evaluation.py`: avaliação determinística de caixas COCO com AP101, mAP50, mAP50_95 e métricas TP/FP/FN, precision, recall e F1 por classe e globalmente.
- O evaluator rejeita IDs ambíguos, classes desconhecidas, caixas fora da imagem, scores não finitos e crowd annotations ainda não suportadas.
- Criado `apps/api/scripts/evaluate_vision_model.py`: executa o provider ONNX real apenas num test split pertencente a um release aprovado para inferência; exige manifesto Ed25519, keyring, hashes e SHA-256 das imagens.
- O runner exige confidence floor 0.0 para AP, mede separadamente o operating threshold, e escreve relatório com release fingerprint, versão do modelo, pesos e pré-processamento. Não treina nem altera inventário.
- Testes sintéticos em `apps/api/tests/test_vision_evaluation.py`; protocolo em `docs/vision-model-evaluation.md`.
- Limite: não foi executado com dataset autorizado nem pesos reais; nenhuma métrica de precisão foi produzida. CI ainda por confirmar.

## 2026-11-21 — Contrato Edge AI v1 (implementação de domínio publicada; CI pendente)

- Criado `apps/api/app/edge_event_contract.py` com envelope v1, payloads tipados por evento, limites de tamanho/profundidade, timestamps timezone-aware, IDs e hashes validados.
- Tipos: DEVICE_HEARTBEAT, SHELF_CAPTURED, SHELF_OBSERVATION e TASK_ACKNOWLEDGED.
- Acrescentados fingerprint SHA-256 canónico, chave idempotente por dispositivo/evento, comparação de replay exacto e classificação de sequência NEXT/GAP/STALE.
- Criados testes em `apps/api/tests/test_edge_event_contract.py` para payloads válidos/inválidos, tenant IDs, bounding boxes, tamanho, idempotência e lacunas de sequência.
- Documentação do protocolo: `docs/edge-device-event-contract.md`.
- Limite explícito: não existe ainda autenticação/registo de dispositivos, endpoint, inbox/outbox persistente, cursor durável nem ACK de entrega. O módulo não faz persistência nem mutações de inventário. CI pendente.

## 2026-11-21 — Manifesto ONNX assinado com Ed25519 (implementação publicada; Quality Gates e Security Scans validados)

- O provider ONNX real passou a exigir um manifesto autenticado por Ed25519 e um keyring explícito de chaves públicas confiáveis.
- A assinatura cobre o payload JSON canónico com schema versionado, key ID e SHA-256 do detector e, opcionalmente, do embedder. Os hashes são comparados com os ficheiros reais e com as variáveis SHA-256 já configuradas.
- A validação rejeita assinatura inválida, key ID desconhecido, chave pública com tamanho incorrecto, digest divergente, ficheiro alterado, symlink, JSON ambíguo/malformado e campos extra ou em falta.
- A API e o vision-worker recebem `VISION_MODEL_MANIFEST_PATH` e `VISION_MODEL_TRUSTED_KEYS_JSON` através do Docker Compose. Foi fixada `cryptography==50.0.2` para Ed25519.
- Foi criado `apps/api/scripts/create_vision_model_manifest.py` para assinar offline com PEM Ed25519; o utilitário imprime apenas a chave pública Base64. A chave privada nunca é distribuída para os containers.
- Testes adicionados em `apps/api/tests/test_vision_model_manifest.py`. No HEAD `e9145ac7cb89409e80259f52967f7fccda3de478`, Quality Gates passou (compilação Python, suite pytest API e build Web) no run [44918245867](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44918245867); Security Scans passou no run [44918245858](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44918245858). API CI e Docker Compose smoke tiveram sucesso em SHA anterior e não são aqui apresentados como validação deste HEAD.
- Limitações conhecidas: não há prevenção persistente de rollback nem política automática de revogação/rotação. A assinatura autentica a origem dos pesos, não a precisão do modelo.
- Especificação operacional: `docs/vision-model-manifest.md`.

## 2026-11-21 — Encaminhamento de digests ONNX no Docker Compose (validação pendente)

- A revisão da configuração detectou que o provider ONNX real exige `VISION_DETECTOR_MODEL_SHA256` e, quando existe embedder, `VISION_EMBEDDING_MODEL_SHA256`, mas os serviços API e worker não recebiam essas variáveis através do Compose.
- O `docker-compose.yml` foi alterado para encaminhar ambos os valores aos dois processos. Os valores por omissão permanecem vazios, pelo que a configuração continua a falhar fechada se o operador activar o provider real sem fornecer digests aprovados.
- Foi acrescentado `apps/api/tests/test_vision_compose_configuration.py` para fixar a passagem das duas variáveis nos serviços API e vision-worker.
- Commits: Compose `2d810e8a`; teste inicial `d00278b2`; correcção do teste `b417490a` e `263de3e8`; documentação em curso.
- Estado: implementação publicada; testes e workflows ainda não executados/confirmados nesta ronda. Não declarar a alteração validada até CI verde.
- Limite: isto não implementa manifesto assinado nem fornece pesos ONNX; apenas torna configuráveis no container os digests que já eram obrigatórios no provider real.

## 2026-11-21 — Integridade dos exemplares de embeddings (validado)

- A validação de ProductExemplar aceitava alguns valores com tipos inadequados: booleanos/floats como IDs e metadados não textuais podiam atravessar a fronteira de domínio.
- A implementação passou a exigir ID de produto inteiro positivo; versão do modelo, revisor, timestamp de revisão e licença como strings não vazias; e digest SHA-256 com exactamente 64 caracteres hexadecimais.
- Foram adicionados testes paramétricos para booleanos, floats, strings, valores nulos, hashes de comprimento incorrecto e caracteres não hexadecimais.
- Commits: implementação 762d3344dbcb72c39d223bdd2a97a7f8e8333421; testes a1e056c3a49eebd1b7ac36903cc1453b6d570338.
- Validação no SHA a1e056c3: API CI [44902878547](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878547) passou com PostgreSQL 16, smokes de concorrência/isolamento e **1461 passed, 1 skipped**. Quality Gates [44902878553](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878553) confirmou compilação Python, build Web e a mesma suite; Docker Compose [44902878594](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878594) e Security Scans [44902878703](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44902878703) passaram.
- Limite: esta alteração melhora a integridade dos registos de referência; não valida qualidade visual dos embeddings, precisão por SKU nem adequação de thresholds para uma loja real.

## 2026-11-21 — Gitleaks sobre o histórico Git completo (validado)

- A ação oficial Gitleaks estava a usar --log-opts=-1 no evento push; o checkout tinha histórico completo, mas a acção só verificava o commit actual. Foi acrescentado um passo explícito com --log-opts=--all.
- A primeira execução percorreu 2740 commits e encontrou 7 ocorrências da regra generic-api-key. A análise dos contextos confirmou exemplos de bootstrap na documentação, chaves HMAC de testes e um hash de commit; não foram identificadas credenciais activas.
- Os exemplos de credenciais e a chave de teste actual foram substituídos por placeholders/valores de teste explícitos. As 7 ocorrências históricas foram adicionadas a .gitleaksignore através das fingerprints exactas, sem exclusões por caminho, regra ou regex. O histórico Git não foi reescrito.
- Reexecução: 2741 commits analisados, no leaks found. Artefacto SARIF full-history disponível no workflow Security Scans [44895863007](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44895863007).
- Segurança: pip-audit sem vulnerabilidades conhecidas; npm audit 0 vulnerabilidades; ZAP baseline/API safe-mode 0 FAIL, 0 WARN, 0 INFO e 120 PASS. Docker Compose passou.
- API CI [44895863058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44895863058) e Quality Gates [44895863008](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44895863008) passaram, com 1432 passed, 1 skipped; PostgreSQL 16, compilação Python e build Web aprovados.
- Commit de correcção e cobertura: 1097e53a4bfae31f66e4a6c434a37caa1a40e233. Limite: as impressões digitais antigas permanecem no histórico por não se ter reescrito a história; a supressão é específica a cada ocorrência classificada como falsa positiva.

## 2026-11-21 — Pinning de integridade dos modelos ONNX (validado em CI)

- A auditoria confirmou que o provider calculava SHA-256 dos pesos e incorporava o digest no fingerprint, mas não comparava o ficheiro com um digest previamente aprovado. O comportamento anterior permitia que um modelo substituído antes do arranque fosse simplesmente identificado como uma nova versão.
- Primeiro foram publicados testes de regressão. O Quality Gates observou RED: 9 falhas, 1423 aprovados e 1 ignorado. As falhas demonstraram a ausência de suporte aos digests no provider e a ausência de exigência dos digests no factory real.
- ONNXShelfVisionProvider passou a validar o formato dos digests esperados e a comparar os hashes do detetor e do embedder antes de criar sessões ONNX. O factory create_provider() falha fechado quando falta o digest do detetor ou, havendo embedder, o digest do embedder. A verificação pós-carregamento existente foi preservada para detectar substituição durante a abertura da sessão.
- O fingerprint do detetor usa rgb-letterbox-bilinear-114-v1; o fingerprint do extrator usa rgb-crop-stretch-bilinear-v1. Assim, os identificadores não confundem pipelines de pré-processamento distintos.
- Commits: implementação 1b03b66cd24c9efed2b16c41a71cbfd2f5c2c2ea; testes e asserção do fingerprint 663bf495f6d15a4bcc92aa6fedc87d18e47e4e71.
- GREEN: API CI [44894912840](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44894912840) e Quality Gates [44894912818](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44894912818) passaram, com 1432 passed, 1 skipped. Os smokes PostgreSQL 16, compilação Python e build Web passaram. Docker Compose [44894912826](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44894912826) e Security Scans [44894912752](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44894912752) também passaram.
- Limites: nenhum peso ONNX real foi fornecido ou avaliado. Os hashes aprovados são âncoras de confiança da configuração de deployment; ainda não existe manifesto assinado com verificação de assinatura. Não activar provider real em piloto sem pesos, licenças, dataset e métricas autorizados.

## 2026-11-21 — Isolamento multi-loja do histórico de alertas (validado)

- A revisão handler-a-handler confirmou que `GET /api/v1/observation-alerts/{alert_id}/events` carrega o alerta pai e chama `_require_alert_supervisor`, que verifica o papel e a loja antes de devolver eventos.
- Acrescentado teste HTTP de regressão: um supervisor da loja A tenta ler a cronologia de um alerta da loja B e deve receber HTTP 403.
- Removida uma segunda definição duplicada de `test_cross_store_alert_update_checks_scope_before_acquiring_row_lock`; a definição repetida não criava um cenário adicional, mas ocultava a duplicação na suite.
- A implementação do endpoint não foi alterada: a cobertura passa a provar explicitamente o controlo já existente.
- Validação GREEN no commit `1a53a9f1`: API CI [44893270814](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893270814) e Quality Gates [44893270837](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893270837) passaram, com **1423 passed, 1 skipped**. Docker Compose [44893271027](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893271027) e Security Scans [44893270848](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44893270848) também passaram.

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
- Quality Gates [44880841658](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44880841658) e Docker Compose [44880841671](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44880841671) passaram no commit de código/testes `311fecc9`. A sincronização documental `5cdcf4b` também passou Quality Gates [44881922766](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44881922766). Não há execução local.

## 2026-11-21 — Matriz exaustiva de decisões RBAC

Foi acrescentado um teste parametrizado por todas as entradas de API_ROUTE_POLICIES. Para cada método/template, o teste verifica a decisão de ADMIN, SUPERVISOR e EMPLOYEE segundo a categoria declarada, além de detectar chaves duplicadas e categorias fora do conjunto permitido. Rotas não registadas continuam a ser negadas a todos os perfis.

O commit b1c60246938befa86233b49f6d8a4841617fbfdc passou Quality Gates [44882467613](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44882467613): compilação Python, build Web e **1408 passed, 1 skipped, 1 warning**. O aviso é a depreciação externa anyio.abc.BlockingPortal emitida pelo Starlette TestClient.

Docker Compose demo smoke [44882467596](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44882467596) passou. API CI [44882467564](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44882467564) concluiu com sucesso: auditoria estrita de rotas, migrations PostgreSQL 16, smokes de concorrência/isolamento/retention e **1408 passed, 1 skipped, 1 warning**.

A auditoria handler × perfil × loja permanece aberta: a matriz centralizada não prova isolamento de cada recurso nem caminhos indirectos. SCA, secret scan e DAST não foram executados.

## 2026-11-21 — Scanners de segurança automatizados adicionados

Foi criado .github/workflows/security-scans.yml com quatro jobs independentes: pip-audit para requirements.txt e requirements-ocr.txt, npm audit --audit-level=high para o lockfile Web, Gitleaks para histórico Git e OWASP ZAP Baseline para a API num Docker Compose efémero. As Actions de terceiros foram fixadas a commits completos; os jobs usam contents: read e o job Gitleaks recebe apenas a permissão adicional de comentários PR necessária à integração.

A primeira execução confirmou Gitleaks PASS e npm audit PASS. O pip-audit falhou com 158 ocorrências em cinco pacotes Python (pytest 8.3.5, PyJWT 2.10.1, python-multipart 0.0.20, Pillow 11.2.1 e Starlette 0.46.2). Foram actualizadas as dependências directas para versões corrigidas; FastAPI 0.165.0 passa a seleccionar Starlette compatível, sem pin directo de Starlette. A segunda execução SCA e a regressão completa continuam pendentes.

O ZAP está inicialmente em modo baseline passivo e report-only (fail_action: false), sem autenticação nem mutações. Isto estabelece recolha de evidência, não uma certificação DAST nem uma aprovação de segurança.

## 2026-11-21 — Remediação SCA, isolamento de locks e headers HTTP

### Dependências e qualidade
A primeira execução SCA detectou 158 ocorrências em cinco pacotes Python. Foram actualizados FastAPI 0.165.0, Pillow 13.0.0, PyJWT 2.15.1, python-multipart 0.0.34 e pytest 9.2.0; FastAPI selecciona a versão compatível de Starlette sem pin directo. Foi adicionado httpx2 2.16.2 para substituir o caminho deprecated do Starlette TestClient. O uso de Pillow foi migrado de Image.getdata para get_flattened_data.

No commit 1c0f59136af8364aab868b60f477c169679c4f3f:
- API CI [44884714292](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714292): sucesso; 1413 passed, 1 skipped; migrations e smokes PostgreSQL 16 passaram.
- Quality Gates [44884714318](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714318): sucesso; 1413 passed, 1 skipped; build Python/Web passou sem o aviso anterior do TestClient.
- Docker Compose [44884714261](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714261): sucesso.
- Security Scans [44884714393](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714393): pip-audit sem vulnerabilidades conhecidas, npm audit passou e Gitleaks passou.

### Isolamento multi-loja e concorrência
A auditoria encontrou endpoints que adquiriam locks antes de verificar o store scope. Foram criados _lock_authorized_shelf_image e _lock_store_scoped_record. O padrão é: leitura não bloqueante para obter store_id, validação de actor/tenant, lock com populate_existing, nova validação do tenant e só depois a operação. O padrão foi aplicado a 22 handlers de imagens, OCR, deteções, exemplares, sessões, paletes, tarefas e alertas. O teste estático impede regressões na ordem de autorização e locks.

O endpoint PATCH de alertas foi também corrigido para autorizar antes do lock. Os smokes PostgreSQL continuam a validar concorrência e retenção.

### Headers HTTP e DAST
Foram acrescentados headers HTTP de segurança, CSP, HSTS em produção e Cache-Control no-store para APIs. Swagger UI é desactivado em produção; a documentação interactiva fica disponível apenas fora de produção com CSP específica.

ZAP Baseline e API safe-mode [44884714393](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714393) analisaram 134 endpoints no baseline e 131 operações importadas via OpenAPI. Ambos os relatórios apresentaram 0 alertas High, 0 Medium e 0 Low; os alertas restantes são informativos. O scan não é autenticado: 128 operações protegidas responderam 401. Não é uma certificação de segurança nem substitui DAST autenticado/activo.

## 2026-11-21 — Matriz ONNX e falhas do worker

Foi ampliada a cobertura do contrato de saída do detector ONNX:
- Caixas com coordenadas invertidas ou área nula são descartadas.
- Caixas totalmente contidas no padding de letterbox são descartadas.
- Caixas que intersectam parcialmente o padding são recortadas correctamente à geometria da imagem original.

Foi acrescentado teste de integração do worker para RuntimeError e TimeoutError. Em ambos os casos, o worker marca a imagem como FAILED, guarda uma mensagem sanitizada, preserva deteções anteriores e não cria snapshots de inventário.

Validação no commit a345746200eb6ea8b0035bd2cdba7c188de87ef9:
- API CI [44885522283](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44885522283): sucesso, **1422 passed, 1 skipped**; migrations e smokes PostgreSQL 16 passaram.
- Quality Gates [44885522309](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44885522309): sucesso, **1422 passed, 1 skipped**.
- Docker Compose [44885522318](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44885522318): sucesso.
- Security Scans [44885522256](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44885522256): sucesso; SCA e secret scan passaram; ZAP sem alertas High/Medium/Low.

A cobertura é de contrato e tratamento de falhas. Não representa avaliação de precisão de um modelo real; a integração ONNX continua dependente de modelo e dataset autorizados.


## 2026-11-21 — Isolamento multi-loja na listagem de sessões de captura

- A auditoria handler-a-handler confirmou que `GET /api/v1/capture-sessions` restringe as sessões à `store_id` do actor não administrador.
- Acrescentado teste de regressão com duas lojas, duas prateleiras e sessões independentes. O supervisor da loja A só recebe a sua sessão e não consegue obter a sessão da loja B através de `shelf_id` estrangeiro.
- O teste chama o handler com actor de teste controlado e base SQLite isolada; a validação da execução CI e dos smokes PostgreSQL continua necessária para fechar esta unidade.
- A matriz global endpoint × perfil × loja continua aberta; este teste cobre apenas a listagem de sessões de captura.


## 2026-11-22 — Confiança persistente e anti-rollback de modelos ONNX

Foi implementado o schema v2 do manifesto Ed25519: o payload assinado inclui `model_id` e `release_version` monotónica, além de `key_id` e hashes do detector/embedder. Manifestos v1 deixam de ser aceites no provider real. O utilitário offline exige agora `--model-id` e `--release-version`.

A migration `0069_vision_model_release_trust_state` cria o high-water mark persistente por `VISION_MODEL_DEPLOYMENT_ID` e um trilho append-only de decisões. O serviço `app.vision_model_release` serializa upgrades, aceita retries exactos, rejeita rollback, colisão de versão e alteração da identidade do modelo. Triggers PostgreSQL/SQLite protegem a monotonicidade, impedem apagar o estado e tornam os eventos imutáveis; downgrade recusa remover high-water marks existentes.

O provider real regista o release depois de construir/validar as sessões ONNX, verifica a versão antes/depois da inferência e o worker bloqueia a linha do release na transacção de publicação. Um worker obsoleto não persiste resultados, reencaminha a captura para PENDING e termina para reiniciar com a configuração actual.

A rotação normal está documentada em `docs/vision-model-manifest.md`: adicionar chave nova, assinar release superior, confirmar todas as instâncias no novo release e só depois remover/revogar a chave antiga. A revogação explícita usa `VISION_MODEL_REVOKED_KEY_IDS_JSON`; o `VISION_MODEL_DEPLOYMENT_ID` tem de permanecer estável.

Testes acrescentados: `test_vision_model_release.py`, `test_vision_model_release_migration.py`, testes de configuração de deployment e smoke PostgreSQL `postgres_vision_model_release_smoke.py`, integrado em API CI. Em `APP_ENV=production`, `VISION_MODEL_DEPLOYMENT_ID` é obrigatório e não pode ser `default`; Compose deixa o valor vazio quando não configurado.

Validação confirmada:
- API CI [45065013302](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065013302): sucesso; PostgreSQL 16, migration 0069, smoke de concorrência/rollback/append-only/TRUNCATE e **1545 passed, 1 skipped**.
- Quality Gates [45065079666](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065079666): sucesso; **1545 passed, 1 skipped**, compilação Python e build Web.
- Docker Compose [45065013291](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065013291): sucesso; readiness, seed e worker.
- Security Scans [45065079730](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45065079730): sucesso; SCA, Gitleaks do histórico e ZAP baseline.

Limitação de segurança resolvida em camadas: owner de migrations separado do runtime, tabelas de confiança ONNX read-only para API/worker e registo explícito de releases pelo owner. O owner continua privilegiado e deve permanecer restrito ao serviço de migrations e ao perfil one-shot. Não existem pesos/dataset autorizados, pelo que nenhuma inferência real foi activada.


## 2026-11-22 — Separação PostgreSQL owner/runtime e trust state ONNX (CI validada no HEAD aeff4a3b)

- O Compose executa Alembic no serviço one-shot `migrate` com o principal owner; API e vision-worker usam `APP_DB_USER`/`APP_DB_PASSWORD` separados. A API já não executa migrations no arranque.
- O bootstrap `infra/postgres/10-create-runtime-role.sh` cria um papel NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/NOBYPASSRLS/NOINHERIT, remove memberships/ownership anteriores, concede DML operacional e revoga CREATE no schema.
- A validação CI anterior confirmou a instalação limpa e o smoke de permissões geral no HEAD `bbf5ad80`: API CI, Quality Gates, Security Scans e Docker Compose passaram; suite API **1549 passed, 1 skipped**. O smoke runtime-role passou, mas a auditoria adicional detectou que o runtime ainda tinha DML sobre as tabelas de confiança ONNX.
- Nova análise P0: triggers monotónicos não impediam o runtime de inserir eventos falsos ou elevar arbitrariamente o high-water mark para uma versão futura, bloqueando releases legítimas.
- Implementada migration `0070_vision_model_trust_runtime_readonly` e actualização do bootstrap: runtime passa a ter apenas SELECT em `vision_model_release_states`/`vision_model_release_events`, sem DML/TRUNCATE nem acesso à sequência de eventos.
- O provider deixou de registar releases no arranque. Criado `apps/api/scripts/register_vision_model_release.py` e perfil one-shot `register-model-release`, que verifica manifesto Ed25519, digests e exige o owner das tabelas.
- `app.vision_model_release` usa advisory transaction lock por deployment para serializar verificações read-only e registos privilegiados; evita SELECT FOR UPDATE e mantém o runtime sem UPDATE.
- A migration 0070 falha fechada em produção se `APP_DB_USER` faltar, não existir, coincidir com o owner ou for owner das tabelas de confiança.
- O smoke PostgreSQL foi alargado para provar SELECT autorizado, DML/sequence privileges ausentes, recusa efectiva de INSERT/UPDATE/DELETE/TRUNCATE e validação do release pelo runtime. Foram acrescentados testes estáticos e teste de migração dialect-safe.
- Documentação actualizada: README, guia do manifesto, provider ONNX, segredos de produção, ADR-009 e TODO.
- **Validação da camada read-only ONNX:** concluída no SHA `5e16a9cb`: API CI, Quality Gates, Security Scans e Docker Compose passaram; suite API **1552 passed, 1 skipped**. O API CI confirmou o smoke PostgreSQL de permissões e o guard advisory com o principal runtime.


## 2026-11-22 — Provisionamento recorrente do principal runtime (CI validada no HEAD aeff4a3b)

- Foi removido o acoplamento do bootstrap ao directório `initdb.d`, que só corre em volumes novos.
- Adicionado o serviço one-shot `provision-runtime-role` (imagem PostgreSQL 16) entre `db` e `migrate`. Liga por TCP, autentica com o owner, reconcilia papel/senha/memberships/ownership/grants e termina antes de Alembic.
- A API e o worker só arrancam depois do provisionamento e das migrations; volumes persistentes antigos também passam pelo processo.
- O papel runtime passa a `NOINHERIT`; o smoke verifica `rolinherit=false` além de atributos, memberships, ownership, DML operacional e trust tables read-only.
- O API CI recebe explicitamente `POSTGRES_PASSWORD` para exercitar o mesmo script de provisionamento por TCP.
- README, guia do manifesto, DEMO, segredos de produção, ADR-009, TODO e instruções da API actualizados para remover comandos Alembic no container runtime.
- API CI [45076219787](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219787), Quality Gates [45076219801](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219801), Security Scans [45076219740](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219740) e Docker Compose [45076219751](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/45076219751) passaram no HEAD `aeff4a3b`; suite API **1552 passed, 1 skipped**. O Compose smoke simulou um volume legado ao atribuir ownership de uma tabela ao runtime e uma membership indevida, e confirmou a reconciliação automática.