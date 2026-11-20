## 2026-11-20 — CORS preflight corrigido e validado

- O RED do commit `831c1026` mostrou que o middleware Bearer respondia 401 ao OPTIONS preflight antes de CORSMiddleware.
- O middleware agora encaminha apenas OPTIONS com `Origin` e `Access-Control-Request-Method` para CORSMiddleware; este continua a validar origem, método e headers.
- CORS `allow_credentials=False`: a API usa Bearer JWT, não cookies; Authorization continua permitido em preflight.
- GREEN no commit `a63d646`: teste confirma HTTP 200, origem permitida, header Authorization e ausência de `Access-Control-Allow-Credentials`.
- API CI [44785894943](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44785894943), Quality Gates [44785894965](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44785894965) e Docker Compose [44785894960](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44785894960) passaram. Suite API **1388 passed, 1 skipped, 1 warning**.

