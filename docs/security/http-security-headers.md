# Headers HTTP e política de documentação

## Headers

A middleware apply_security_headers aplica:
- X-Content-Type-Options: nosniff.
- X-Frame-Options: DENY.
- Referrer-Policy: strict-origin-when-cross-origin.
- Permissions-Policy: camera=(self), microphone=(), geolocation=().
- Cross-Origin-Resource-Policy: same-origin.
- Content-Security-Policy restritiva para respostas API/JSON.
- Cache-Control: no-store nas rotas /api/v1/.
- Strict-Transport-Security em produção.

A documentação Swagger UI fica desactivada em produção. Fora de produção, /docs usa CSP específica que permite os assets jsdelivr e o código inline necessário à página gerada pelo FastAPI. Redoc permanece desactivado.

## Verificação

Os testes cobrem respostas 401, headers de segurança e política de documentação. O workflow OWASP ZAP Baseline e API safe-mode no commit 1c0f591 reportou:
- Baseline: 0 High, 0 Medium, 0 Low; 3 informativos.
- API OpenAPI safe-mode: 0 High, 0 Medium, 0 Low; 4 informativos.

O scan não autenticado recebeu 401 nos endpoints protegidos. Os resultados não certificam a autorização após login nem substituem DAST autenticado/activo.

## Limitação da documentação de desenvolvimento

Em ambientes não produtivos, o Swagger UI continua a usar assets jsdelivr e inline scripts/styles, permitidos pela CSP específica. A documentação interactiva não é publicada em produção. A revisão de SRI dos assets de desenvolvimento continua a ser uma melhoria possível.
