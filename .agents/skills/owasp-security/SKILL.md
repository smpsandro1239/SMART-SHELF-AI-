---
name: owasp-security
description: Use when reviewing API authorization, tenant isolation, source code security, dependency vulnerabilities, or exposed secrets.
license: CC-BY-4.0
---

# OWASP Secure Agent Playbook

Fonte upstream: `vendor/owasp-secure-agent-playbook`. Licença CC-BY-4.0; preservar atribuição.

Selecciona e lê integralmente a skill e o playbook apropriados:
- API: `plugins/code-security-skills/skills/api-security-review/SKILL.md` e `plugins/code-security-skills/plays/api-security-review.md`.
- Código: `plugins/code-security-skills/skills/code-review-security/SKILL.md` e `plugins/code-security-skills/plays/code-review-security.md`.
- Dependências: `plugins/code-security-skills/skills/sca-audit/SKILL.md` e play correspondente.
- Segredos: `plugins/code-security-skills/skills/secrets-scan/SKILL.md` e play correspondente.

Para o SMART SHELF AI, dar prioridade a BOLA/IDOR, BFLA, isolamento ADMIN/SUPERVISOR/EMPLOYEE, acesso a imagens/artefactos, retenção/legal hold, JWT, mass assignment e exposição de dados. Mapear findings para CWE/OWASP e incluir ficheiro/linha, pré-condições, impacto, evidência e remediação. Não executar testes em sistemas externos; limitar a revisão ao repositório e ambientes autorizados.

SCA só é considerada executada quando um scanner real está disponível e foi corrido. Nunca imprimir valores secretos; redigir evidência.
