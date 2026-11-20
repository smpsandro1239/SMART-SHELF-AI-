# Revisão inicial de segurança da API — 2026-11-20

## Estado e âmbito

Revisão estática inicial guiada pelo OWASP Secure Agent Playbook, commit de aplicação `1b1e4eafecf17a93eb4e588f6e6416ae79e49488`.

Ficheiros analisados:
- `apps/api/app/main.py`: middleware HTTP, enumeração de rotas e handlers.
- `apps/api/app/security.py`: criação/validação JWT e hashing de passwords.
- `apps/api/app/config.py`: validação de configuração de produção.
- `apps/api/app/shelf_planograms.py`: autorização de operações de planogramas.
- `apps/api/tests/test_auth_middleware_jwt.py`, `test_security.py`, `test_config.py`: testes de autenticação, autorização e configuração.

O parser estático identificou 130 declarações de rotas na API. Esta revisão é uma triagem documentada, não um pentest nem uma certificação de segurança.

## Controlos confirmados no código

1. **Autenticação por defeito:** o middleware exige Bearer token em todas as rotas `/api/v1/`, excepto `/api/v1/auth/bootstrap` e `/api/v1/auth/login`.
2. **Identidade e papel autoritativos:** o middleware carrega o utilizador da base de dados e usa o papel persistido; não confia no claim `role` do JWT.
3. **JWT:** algoritmo HS256 fixo e claims `sub`, `iat` e `exp` obrigatórios na descodificação.
4. **RBAC:** gates para ADMIN e SUPERVISOR/ADMIN; EMPLOYEE tem allowlist de operações de leitura/escrita.
5. **Isolamento de loja:** handlers e serviços aplicam `_enforce_store_scope`, `_planogram_shelf_scope` e filtros de tenant; planogramas voltam a validar o store no serviço de domínio.
6. **Retenção:** testes existentes verificam que conteúdo e derivados de imagens de outra loja ou com retenção restrita não são expostos.
7. **CORS de produção:** a configuração agora exige origens explícitas HTTPS e rejeita wildcard, HTTP, userinfo, path, query, fragmentos, localhost e loopback.

## Evidência de testes

- `test_every_versioned_api_route_requires_bearer_except_public_auth_routes` percorre as rotas versionadas registadas e exige 401 sem token.
- `test_auth_middleware_uses_database_role_not_untrusted_jwt_role_claim` verifica que o papel do token não substitui o papel na base de dados.
- Testes dedicados verificam gates ADMIN, restrições EMPLOYEE, isolamento SUPERVISOR, imagens/OCR, inventário, vendas, forecasting, warehouse, capture sessions e SKU evaluation.
- `test_production_rejects_ambiguous_or_insecure_cors_origins` cobre wildcard, wildcard subdomain, HTTP, localhost, loopback e path.
- No commit `1b1e4ea`: API CI, Quality Gates e Docker Compose passaram; suite API **1387 passed, 1 skipped, 1 warning**. Smokes PostgreSQL 16 incluíram autorização de inventário, sessões de captura, SKU evaluation, retenção/legal hold e governação de outputs.

## Finding corrigido

| ID | Severidade | Finding | Estado |
|---|---|---|---|
| API-CORS-001 | Alta configuração | Produção aceitava origens CORS wildcard/HTTP/localhost com `allow_credentials=True` | Corrigido em `1b1e4ea` |

O RED foi observado no commit `e8c9935`: seis novos casos falharam porque a configuração aceitava origens inseguras. O GREEN foi confirmado no commit `1b1e4ea`.

## Risco residual / trabalho em aberto

- **Política de autorização distribuída:** parte do RBAC está em listas de paths/métodos no middleware e parte em handlers/serviços. Não foi encontrado bypass confirmado nos fluxos revistos, mas esta dispersão facilita regressões quando forem adicionadas novas rotas.
- Criar um registo declarativo de políticas por rota (autenticação, papéis, tenant scope) e um teste que falhe quando uma rota nova não tem classificação explícita.
- Completar a matriz endpoint × papel × tenant para os 130 endpoints, incluindo endpoints menos usados e combinações de métodos.
- Rever limites de taxa, abuso de fluxos de negócio, exposição de schemas/erros e configuração TLS no reverse proxy/ambiente real.
- Não foi executado scanner SCA, secret scanner, DAST ou pentest externo nesta ronda. Não declarar esses controlos concluídos.

## Conclusão

Não foi confirmado um bypass de autenticação ou isolamento multi-loja nesta triagem. Foi corrigida uma configuração CORS de produção. A auditoria de autorização continua aberta até existir uma matriz completa e testes de política declarativa para todas as rotas.

## Finding adicional — CORS preflight interceptado por autenticação

| ID | Severidade | Finding | Estado |
|---|---|---|---|
| API-CORS-002 | Alta funcionalidade | Middleware Bearer respondia 401 a OPTIONS preflight antes de CORSMiddleware; browsers não conseguiam completar chamadas cross-origin | Corrigido em `a63d646` |

O teste HTTP envia `Origin`, `Access-Control-Request-Method` e `Access-Control-Request-Headers: authorization`. O comportamento correcto é deixar CORSMiddleware validar a origem/método/headers, responder 200 para uma origem permitida e não emitir `Access-Control-Allow-Credentials`, dado que a autenticação da API usa Bearer e não cookies. Requests reais continuam a exigir token.

A correcção foi validada pelo teste `test_bearer_api_cors_preflight_does_not_enable_cookie_credentials`: HTTP 200 para a origem permitida, `Authorization` presente nos headers permitidos e ausência de `Access-Control-Allow-Credentials`. O middleware só deixa passar preflight OPTIONS com `Origin` e `Access-Control-Request-Method`; pedidos API reais continuam a exigir Bearer. API CI [44785894943](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44785894943), Quality Gates [44785894965](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44785894965) e Docker Compose [44785894960](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44785894960) passaram; **1388 passed, 1 skipped, 1 warning**.
