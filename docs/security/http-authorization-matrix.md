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
- observações e sessões de captura: isolamento multi-loja e restrições de criação/fecho, cobertos pelos testes adicionados nesta ronda.

- validação JWT dos endpoints de importação em lote de vendas horárias e tráfego: SUPERVISOR recebe 422 quando tenta misturar lojas no mesmo lote, e EMPLOYEE recebe 403 para ambos os endpoints;

Os testes usam tokens criados pelo próprio módulo de segurança e o middleware HTTP real. Não substituem ainda uma suite completa de testes por endpoint nem a execução integral contra PostgreSQL.

## Cobertura JWT adicional — OCR e revisão humana

O teste `test_supervisor_jwt_cannot_access_foreign_ocr_or_retry_restricted_image` confirma que SUPERVISOR não consulta nem cria execuções OCR, não repete a análise e não revê deteções de imagens de outra loja. O fixture usa uma imagem estrangeira em estado RESTRICTED para confirmar que o âmbito da loja é verificado antes do estado de retenção (403, não 410). O teste `test_employee_jwt_cannot_start_ocr_or_submit_human_sku_reviews` confirma que EMPLOYEE não inicia OCR nem submete decisões humanas de SKU (403). A revisão de embeddings com JWT real confirma ainda autoaprovação bloqueada, aprovação por segundo SUPERVISOR da mesma loja e revisão por ADMIN.

## Separação de funções na curadoria de embeddings

A criação de um exemplar e a sua aprovação são operações distintas. Um utilizador SUPERVISOR não pode rever o próprio exemplar (HTTP 403); um segundo SUPERVISOR da mesma loja pode rever, e ADMIN mantém capacidade de supervisão global. Esta regra evita que uma única identidade introduza e aprove a mesma referência usada pelo matching SKU.

## Limitações e próximos critérios de fecho

- Expandir os testes JWT para cada método e rota administrativa, incluindo operações de retenção/legal hold, upload e leitura binária, OCR, embeddings e caminhos indiretos do worker. A cobertura das três vias de criação de tarefas e da reconciliação de inventário foi acrescentada e passou no API CI `43411781067` e Quality Gates `43411781094`. Nesta ronda foram acrescentados testes de isolamento do dashboard, decisões operacionais e bloqueio de analytics de equipa para EMPLOYEE; aguardar validação CI.
- Manter cobertura JWT de atribuição e transições de tarefas; acrescentar ainda casos de conclusão parcial, alteração de quantidades e tentativas de atualização de tarefa atribuída a outro utilizador.
- Executar a matriz contra PostgreSQL 16 no CI; SQLite serve apenas para testes HTTP rápidos.
- Confirmar a política de acesso dos endpoints administrativos e a autorização no próprio worker antes de fechar a auditoria.
- Manter a purga física desativada até existir política formal de retenção e validação operacional.

A auditoria multi-loja permanece aberta até estes critérios serem verificados. Não se deve interpretar a presença deste documento ou a passagem dos testes focados como certificação de segurança global.
