# Matriz de autorização HTTP e testes JWT

## Objetivo e âmbito

Este documento regista a política de autorização aplicada pelo middleware HTTP em `apps/api/app/main.py` e a cobertura de integração com tokens JWT assinados. Não substitui a revisão de autorização de cada handler: o middleware decide se o perfil pode invocar uma família de rotas; os handlers continuam responsáveis por validar o âmbito da loja, atribuições e propriedade do recurso.

## Identidade e validação do token

1. As rotas fora de `/api/v1/` não passam pelo middleware de autenticação da API.
2. `POST /api/v1/auth/bootstrap` e `POST /api/v1/auth/login` são as rotas públicas declaradas.
3. As restantes rotas `/api/v1/` exigem `Authorization: Bearer <JWT>`.
4. O JWT é validado com a chave configurada e algoritmo HS256; o `sub` tem de identificar um utilizador existente e ativo.
5. O perfil e a loja efetivos são lidos da base de dados. O claim `role` do token não concede permissões por si só.
6. Tokens inválidos, expirados, sem identidade válida ou associados a utilizadores inativos recebem HTTP 401.
7. Em `APP_ENV=test`, o middleware é intencionalmente ignorado. Os testes deste documento alteram o ambiente para `production` durante o teste e usam uma base de dados SQLite isolada, exercitando o middleware HTTP e a validação de JWT sem monkeypatch de `_request_user`.

## Matriz do middleware

| Operação/família | ADMIN | SUPERVISOR | EMPLOYEE |
|---|---:|---:|---:|
| Endpoints públicos de bootstrap e login | Público | Público | Público |
| Rotas protegidas sem regra especial | Permitido pelo middleware | Permitido pelo middleware | Negado por omissão |
| Gestão de utilizadores em `/api/v1/auth/users...` | Permitido | Negado | Negado |
| Criação de lojas, zonas, prateleiras, produtos e associações SKU–prateleira | Permitido | Negado | Negado |
| Criação de perfis/embalagens de produto no armazém | Permitido | Negado | Negado |
| Criação de decisões operacionais aprovadas | Permitido | Permitido | Negado |
| Importação/registo de vendas e tráfego | Permitido | Permitido | Negado |
| Escrita de localizações, colocações e paletes | Permitido | Permitido | Negado |
| Políticas e simulações de rotação de paletes | Permitido | Permitido | Negado |
| Gestão de exemplares de embeddings | Permitido | Permitido | Negado |
| Fila de revisão, avaliação SKU e candidatos de treino (leitura) | Permitido | Permitido | Negado |
| Escrita de revisão de deteções | Permitido | Permitido | Negado |
| Criação de execuções OCR, matching OCR e fusão de evidência | Permitido | Permitido | Negado |
| EMPLOYEE: tarefas, perfil próprio e resumo do dashboard (GET) | — | — | Permitido |
| EMPLOYEE: listagem/upload de imagens e conteúdo/deteções/evidência associada (GET/POST conforme rota) | — | — | Permitido |
| EMPLOYEE: histórico de revisão da deteção (GET) | — | — | Permitido |
| EMPLOYEE: atualização de estado de tarefa (PATCH `/status`) | — | — | Permitido, sujeito ao handler e atribuição |
| Consulta de histórico de eventos de tarefa (GET `/api/v1/tasks/{id}/events`) | Permitido, sujeito ao âmbito | Permitido, sujeito ao âmbito da loja | Negado pelo middleware |
| Alertas de observação (listar, avaliar, alterar estado e consultar eventos) | Todas as lojas | Apenas loja própria | Negado pelo middleware |

**Importante:** a tabela representa as decisões do middleware, não garante por si só acesso ao recurso. ADMIN também pode ser limitado por validações de negócio; SUPERVISOR e EMPLOYEE têm de respeitar o `store_id` e as regras de atribuição implementadas nos handlers. O catálogo de produtos é global por decisão arquitetural; associações SKU–prateleira e dados derivados de imagens mantêm âmbito por loja.

## Cobertura de integração JWT

O ficheiro `apps/api/tests/test_auth_middleware_jwt.py` cobre:

- ausência de Bearer e token inválido (401);
- claim JWT adulterado quanto ao perfil: um token com claim ADMIN não eleva um EMPLOYEE;
- bloqueio de gestão de utilizadores para SUPERVISOR;
- bloqueio de criação de loja para EMPLOYEE, mesmo com claim ADMIN;
- acesso ADMIN à listagem de utilizadores;
- rejeição de token válido associado a utilizador inativo;
- listagem de lojas por SUPERVISOR limitada à loja atribuída na base de dados;
- listagem de tarefas de EMPLOYEE limitada às tarefas atribuídas ao próprio utilizador;
- início de tarefa atribuída permitido, mas tentativa de iniciar tarefa sem atribuição ou atribuída a outro funcionário da mesma loja rejeitada (403);
- cancelamento de tarefa por EMPLOYEE rejeitado (403);
- histórico de eventos reservado a ADMIN/SUPERVISOR: EMPLOYEE recebe 403 mesmo para tarefa própria, e SUPERVISOR só consulta eventos da sua loja;
- conclusão de tarefa atribuída por EMPLOYEE: a quantidade efetiva não pode exceder a pedida; conclusão parcial exige motivo; a quantidade e o motivo ficam registados no evento; EMPLOYEE não pode alterar a atribuição;
- tentativa de consulta e cancelamento de tarefa de outra loja por SUPERVISOR rejeitada (403).
- SUPERVISOR não cria tarefas de outra loja através dos fluxos manual, recomendação ou decisão operacional aprovada (403);
- EMPLOYEE não cria tarefas a partir de decisões operacionais (403);
- EMPLOYEE não reconcilia inventário, mesmo para tarefa da própria loja (403);
- SUPERVISOR não reconcilia tarefas de outra loja (403);
- resumo do dashboard limitado à loja do SUPERVISOR, com rejeição explícita de `store_id` estrangeiro (403);
- observações filtradas pela loja do SUPERVISOR; filtro de prateleira estrangeira não revela registos e criação de observação noutra loja recebe 403;
- sessões de captura listadas apenas para a loja do SUPERVISOR; criação/fecho de sessões estrangeiras recebe 403;
- EMPLOYEE não cria nem fecha sessões de captura (403);
- decisões operacionais limitadas à loja do SUPERVISOR, incluindo a rejeição de filtro estrangeiro (403);
- EMPLOYEE não acede às decisões operacionais nem aos indicadores de carga da equipa (403);
- alertas de observação: EMPLOYEE não lista, avalia, altera nem consulta eventos (403); SUPERVISOR avalia, altera estado e consulta eventos apenas na própria loja; ADMIN pode avaliar/listar e consultar eventos de ambas as lojas. A cobertura usa JWT real e dados SKU atribuídos a prateleiras das duas lojas; tentativas de PATCH e leitura de auditoria sobre alerta estrangeiro recebem 403;
- observações e sessões de captura: isolamento multi-loja e restrições de criação/fecho, cobertos pelos testes adicionados nesta ronda.

- validação JWT dos endpoints de importação em lote de vendas horárias e tráfego: SUPERVISOR recebe 422 quando tenta misturar lojas no mesmo lote, e EMPLOYEE recebe 403 para ambos os endpoints;

Os testes usam tokens criados pelo próprio módulo de segurança e o middleware HTTP real. A suite completa passou no API CI `43453794076` e Quality Gates `43453794115`, no commit `23155bce`, com PostgreSQL 16, migrações Alembic e smoke tests operacionais. A auditoria global permanece aberta: a passagem da suite existente não demonstra cobertura exaustiva de todos os métodos/rotas nem substitui revisão independente dos caminhos administrativos e indiretos.

## Cobertura JWT adicional — OCR e revisão humana

O teste `test_supervisor_jwt_cannot_access_foreign_ocr_or_retry_restricted_image` confirma que SUPERVISOR não consulta nem cria execuções OCR, não repete a análise e não revê deteções de imagens de outra loja. O fixture usa uma imagem estrangeira em estado RESTRICTED para confirmar que o âmbito da loja é verificado antes do estado de retenção (403, não 410). O teste `test_employee_jwt_cannot_start_ocr_or_submit_human_sku_reviews` confirma que EMPLOYEE não inicia OCR nem submete decisões humanas de SKU (403). A revisão de embeddings com JWT real confirma ainda autoaprovação bloqueada, aprovação por segundo SUPERVISOR da mesma loja e revisão por ADMIN.

## Separação de funções na curadoria de embeddings

A criação de um exemplar e a sua aprovação são operações distintas. Um utilizador SUPERVISOR não pode rever o próprio exemplar (HTTP 403); um segundo SUPERVISOR da mesma loja pode rever, e ADMIN mantém capacidade de supervisão global. Esta regra evita que uma única identidade introduza e aprove a mesma referência usada pelo matching SKU.

## Limitações e próximos critérios de fecho

- Expandir os testes JWT para cada método e rota administrativa, incluindo operações de retenção/legal hold, upload e leitura binária, OCR, embeddings e caminhos indiretos do worker. A cobertura de alertas foi ampliada para testar também PATCH e consulta de eventos em alerta estrangeiro (403), além de ACKNOWLEDGED e sequência de auditoria na própria loja; passou no API CI `43455507948` e Quality Gates `43455507915` (commit `8cb99a2`). A cobertura das três vias de criação de tarefas, reconciliação, dashboard, decisões operacionais, analytics, observações, sessões de captura, lotes de vendas/tráfego e fronteiras OCR/embeddings está incluída na suite anteriormente aprovada. A cobertura por endpoint continua incompleta e deve ser fechada de forma sistemática.
- Manter cobertura JWT de atribuição e transições de tarefas; os testes agora cobrem conclusão parcial, rejeição de quantidade acima do pedido, persistência da quantidade/motivo na auditoria e bloqueio de alteração de atribuição por EMPLOYEE. Continuar a cobrir transições e tarefas atribuídas a outro utilizador.
- Continuar a executar os testes de autorização HTTP e os smoke tests de integridade em CI com PostgreSQL 16; os testes JWT HTTP focados continuam a usar SQLite isolado, pelo que não devem ser descritos como cobertura PostgreSQL por endpoint. O gate dinâmico `test_every_versioned_api_route_requires_bearer_except_public_auth_routes` passou no API CI `43456601696` e Quality Gates `43456602071` (commit `4559365`); verifica que todos os métodos das rotas versionadas exigem Bearer, exceto bootstrap e login.
- Confirmar a política de acesso dos endpoints administrativos e a autorização no próprio worker antes de fechar a auditoria.
- Manter a purga física desativada até existir política formal de retenção e validação operacional.

A auditoria multi-loja permanece aberta até estes critérios serem verificados. Não se deve interpretar a presença deste documento ou a passagem dos testes focados como certificação de segurança global.


## Cobertura JWT — conclusão de tarefas e integridade da quantidade

A cobertura de autorização inclui agora a fronteira entre execução operacional e integridade da reposição. Um EMPLOYEE só pode iniciar/concluir a tarefa que lhe está atribuída; não pode reatribuir a tarefa. Ao concluir, a API rejeita quantidade superior à pedida (409), exige motivo para conclusão parcial (422) e persiste quantidade efetiva e motivo na cronologia. O teste confirma que um SUPERVISOR da mesma loja consegue consultar o evento e verificar os valores auditados.

Validação do estado anterior: API CI `43455507948` e Quality Gates `43455507915`, commit `8cb99a2`. Ambos os workflows passaram; API CI executou migrações e smoke tests PostgreSQL 16 e concluiu com 719 testes aprovados. A nova cobertura de conclusão JWT passou no API CI `43456168143` e no Quality Gates `43456168129`, no commit `9c06708`; a suite API terminou com 721 testes aprovados e o build web/compilação Python também passaram.


## Gate de cobertura global de autenticação das rotas

O teste `test_every_versioned_api_route_requires_bearer_except_public_auth_routes` percorre dinamicamente as rotas `/api/v1/` registadas na aplicação FastAPI, substitui parâmetros de caminho por valores de teste e invoca cada método sem credenciais. Todas as rotas protegidas têm de responder HTTP 401 antes de validação de payload ou execução do handler. Apenas `/api/v1/auth/bootstrap` e `/api/v1/auth/login` são excluídas, por serem os endpoints públicos definidos no middleware. Este gate deteta novas rotas versionadas que escapem inadvertidamente à autenticação; não substitui os testes de autorização por perfil nem os testes de isolamento de recursos.


## Estado de validação da autenticação global

O teste dinâmico de inventário das rotas protegidas passou no API CI `43456601696` e no Quality Gates `43456602071`, commit `4559365`. A suite de API, a compilação Python e o build de produção TypeScript/Vite passaram. Este gate cobre a ausência de credenciais; a autorização por perfil, o isolamento de loja e a propriedade de cada recurso continuam a ser verificados por testes específicos e permanecem sujeitos a auditoria contínua.


## Cobertura JWT — fronteira de criação administrativa

O teste parametrizado `test_admin_only_creation_routes_reject_non_admin_roles_before_handler` cobre por HTTP, com JWT real, os oito endpoints de criação protegidos pela regra ADMIN-only:

- `POST /api/v1/auth/users`;
- `POST /api/v1/stores`, `/api/v1/zones` e `/api/v1/shelves`;
- `POST /api/v1/products` e `/api/v1/shelf-products`;
- `POST /api/v1/warehouse/product-profiles` e `/api/v1/warehouse/product-packaging`.

Para cada endpoint, SUPERVISOR e EMPLOYEE têm de receber HTTP 403 antes de entrar no handler. ADMIN tem de ultrapassar o gate de perfil; é enviado um payload vazio e espera-se HTTP 422 da validação de entrada, evitando criar recursos de teste. Esta cobertura verifica a fronteira do middleware e não substitui testes de validação de dados ou isolamento de loja dentro dos handlers.


## Validação CI — cobertura administrativa e proteção de caminhos

O commit `007f5e6c15aa566a22a5703f87680568133c552f` passou no API CI `43458212830` e no Quality Gates `43458212870`. A suite API terminou com **731 testes aprovados e 1 ignorado**; a compilação Python, as migrações Alembic e os dois smoke tests PostgreSQL 16 passaram, assim como o build de produção TypeScript/Vite. A cobertura ADMIN-only descrita acima foi incluída nesta execução.

A regressão do worker para rejeitar symlinks no diretório da loja e em diretórios intermédios passou no API CI `43457363760` e no Quality Gates `43457363686`, no commit `f7fc3cc`. Estes resultados validam as regressões específicas; a auditoria global de autorização e isolamento multi-loja continua aberta.


## Cobertura JWT — leituras derivadas de imagem por EMPLOYEE

O teste `test_employee_jwt_cannot_read_foreign_image_derived_data_or_content` usa um token real de EMPLOYEE da loja A e uma imagem/deteção da loja B, com a imagem em estado `RESTRICTED`. Verifica HTTP 403 em sete caminhos de leitura permitidos pelo middleware para funcionários quando pertencem à própria loja: conteúdo binário, deteções, evidência OCR, execuções OCR, correspondências OCR, fusão de evidência e histórico de revisão humana. A resposta 403 demonstra que o handler aplica o isolamento multi-loja antes de revelar o estado de retenção ou conteúdo derivado.

Esta cobertura complementa os testes de SUPERVISOR em OCR/retry e os testes de isolamento por handler. Não valida o acesso cross-store em PostgreSQL: o fixture JWT HTTP usa SQLite isolado, enquanto os smoke tests PostgreSQL continuam a validar os fluxos operacionais e de concorrência.

## Cobertura JWT — operações de escrita reservadas a SUPERVISOR/ADMIN

O teste parametrizado `test_employee_cannot_use_supervisor_managed_write_endpoints` acrescenta 13 verificações HTTP com JWT real de EMPLOYEE para operações de importação/registo de vendas e tráfego, gestão de localizações/colocações/paletes, políticas e simulações de rotação e eventos de paletes. Todos os pedidos têm de receber HTTP 403 no middleware, antes de validação do payload ou execução do handler. A cobertura complementa os testes existentes para lotes horários, alertas, decisões operacionais, embeddings e criação ADMIN-only. Não substitui a validação de âmbito por loja efetuada nos handlers para SUPERVISOR.

## Cobertura JWT — isolamento multi-loja nas operações de armazém

O teste `test_supervisor_jwt_cannot_access_foreign_warehouse_resources` usa JWT real de SUPERVISOR da loja A e tenta consultar localizações, paletes e políticas de rotação da loja B, bem como criar uma localização, registar uma palete, criar uma política e simular rotação na loja B. Os sete pedidos têm de receber HTTP 403. Os pedidos de escrita usam payloads estruturalmente válidos para garantir que a rejeição decorre do âmbito da loja, antes de validações de entidades ou persistência. Esta cobertura valida os handlers de âmbito explícito para estes recursos; não certifica todos os endpoints de armazém nem substitui a auditoria por rota.

## Validação CI — isolamento de armazém por loja

O commit `4b0a023ca7996864c4dfc40dc3703a067785bc4f` passou no API CI `43468474493` e Quality Gates `43468474322`. A suite terminou com **746 testes aprovados e 1 ignorado**; migrações e smoke tests PostgreSQL 16, compilação Python e build TypeScript/Vite passaram. O novo teste JWT de SUPERVISOR acrescenta sete verificações cross-store no armazém. O fixture HTTP continua a usar SQLite; não se declara validação PostgreSQL individual desses sete handlers.
