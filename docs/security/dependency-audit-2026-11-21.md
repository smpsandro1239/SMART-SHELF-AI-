# Auditoria de dependências — 2026-11-21

## Evidência inicial

Workflow: [Smart Shelf security scans — 44883407298](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44883407298), commit 5bebcec30d9224b35bf74c72192b0a355c6d6925.

- Python SCA: falhou, com 158 ocorrências em cinco pacotes.
- Web SCA: passou com npm audit --audit-level=high.
- Secret scanning: Gitleaks passou.
- DAST: a execução deste SHA foi cancelada por uma publicação subsequente; a execução do commit 607c290b ainda estava em curso no momento do registo.

As 158 ocorrências são achados do scanner OSV agregados nas dependências directas e transitivas; não equivalem a 158 CVEs únicos nem a 158 vulnerabilidades exploráveis na aplicação.

## Dependências afectadas e actualizações aplicadas

| Pacote | Versão anterior | Nova versão | Observação |
|---|---:|---:|---|
| FastAPI | 0.115.12 | 0.165.0 | Actualização do framework para permitir uma versão corrigida de Starlette |
| Starlette | 0.46.2 | Resolvida pelo FastAPI | Não fixar directamente; respeitar o intervalo declarado pelo FastAPI |
| Pillow | 11.2.1 | 13.0.0 | Corrige advisories de processamento de imagens |
| PyJWT | 2.10.1 | 2.15.1 | Corrige advisories de parsing/validação JWT |
| python-multipart | 0.0.20 | 0.0.34 | Corrige advisories de parsing multipart e DoS |
| pytest | 8.3.5 | 9.2.0 | Corrige PYSEC-2026-1845 |

Referências dos avisos observados:
- PyJWT: [PYSEC-2026-4140](https://osv.dev/vulnerability/PYSEC-2026-4140), [PYSEC-2026-4141](https://osv.dev/vulnerability/PYSEC-2026-4141).
- python-multipart: [PYSEC-2026-3036](https://osv.dev/vulnerability/PYSEC-2026-3036), [PYSEC-2026-3041](https://osv.dev/vulnerability/PYSEC-2026-3041).
- Pillow: [PYSEC-2026-4326](https://osv.dev/vulnerability/PYSEC-2026-4326), [CVE-2026-112393](https://osv.dev/vulnerability/CVE-2026-112393), entre outros.
- Starlette: [PYSEC-2026-1941](https://osv.dev/vulnerability/PYSEC-2026-1941), [PYSEC-2026-1942](https://osv.dev/vulnerability/PYSEC-2026-1942).
- pytest: [PYSEC-2026-1845](https://osv.dev/vulnerability/PYSEC-2026-1845).

## Alteração adicional de controlo de acesso

O handler PATCH de alertas de observação adquiria o lock da linha antes de validar o tenant do actor. Foi alterado para:
1. Ler inicialmente o alerta sem lock.
2. Revalidar identidade, papel e store scope.
3. Só depois adquirir o lock de escrita e recarregar a linha.
4. Revalidar o store scope sobre a linha bloqueada para cobrir alterações concorrentes.

Foi acrescentado um teste que confirma que um supervisor de outra loja é recusado antes de qualquer tentativa de lock. A validação final desta alteração aguarda os Quality Gates e API CI do commit correctivo.

## Estado

As actualizações de versões estão aplicadas no código, mas não são consideradas resolvidas até que:
- pip-audit volte a passar para os dois ficheiros de requirements;
- a suite API passe com FastAPI/Starlette/Pillow/PyJWT/pytest actualizados;
- os smokes PostgreSQL 16 passem;
- o ZAP baseline seja concluído e os alertas sejam triados.

Não foram adicionadas exclusões de advisories nem ignorados findings para forçar o sucesso.

## Revalidação após remediação — commit 1c0f591 (2026-11-21)

- pip-audit: sem vulnerabilidades conhecidas nas dependências API e OCR.
- npm audit: passou sem vulnerabilidades acima do limiar configurado.
- Gitleaks: passou, sem segredos detectados.
- ZAP Baseline: 0 High, 0 Medium, 0 Low; 3 informativos.
- ZAP API safe-mode com OpenAPI: 0 High, 0 Medium, 0 Low; 4 informativos; 131 operações importadas. 128 respostas 401 são esperadas no scan não autenticado e não provam autorização correcta para sessões autenticadas.

Workflows:
- [Security Scans 44884714393](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714393)
- [API CI 44884714292](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714292)
- [Quality Gates 44884714318](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714318)
- [Docker Compose 44884714261](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44884714261)

API CI e Quality Gates concluíram com **1413 passed, 1 skipped**. As migrations e os smokes PostgreSQL 16 passaram. O aviso de depreciação do Starlette TestClient foi removido com httpx2 2.16.2.

O baseline não é autenticado nem activo. Os alertas informativos dizem respeito a identificação de pedidos de autenticação, respostas 401 e política de cache; não foram identificados findings High/Medium/Low.

## Revalidação no commit a345746 — 2026-11-21

O workflow [Security Scans 44885522256](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44885522256) voltou a passar:
- pip-audit: sem vulnerabilidades conhecidas.
- npm audit: sucesso.
- Gitleaks: sucesso.
- ZAP Baseline: 0 High, 0 Medium, 0 Low; 3 informativos.
- ZAP API safe-mode: 0 High, 0 Medium, 0 Low; 4 informativos; 131 operações OpenAPI importadas.

Os alertas informativos incluem identificação de endpoints de autenticação, respostas 401 esperadas no scan não autenticado e directivas de cache. Não foi executado active scan nem teste com sessão autenticada.
