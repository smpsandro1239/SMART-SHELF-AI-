# SMART SHELF AI — Instruções para agentes

## Preparação obrigatória
Lê integralmente `README.md`, `TODO.md`, `PROGRESS.md`, `docs/ROADMAP.md`, `AUTONOMOUS-DEVELOPMENT-PROMPT.md` e a documentação da área alterada. Inicializa skills com `git submodule update --init --recursive`.

## Autonomia e prioridades
O pedido explícito do utilizador para avançar autonomamente e o protocolo do repositório autorizam a execução das prioridades já definidas. Não reabras decisões aprovadas nem peças aprovação por cada tarefa. Pára apenas quando faltar decisão comercial/operacional, credencial, acesso ou evidência externa indispensável.

## Skills
- Arranque/processo: `.agents/skills/using-superpowers/SKILL.md`; fonte upstream completa em `vendor/superpowers/skills/using-superpowers/SKILL.md`.
- TDD: `.agents/skills/test-driven-development/SKILL.md`.
- Debugging: `vendor/superpowers/skills/systematic-debugging/SKILL.md`.
- Verificação: `vendor/superpowers/skills/verification-before-completion/SKILL.md`.
- Planos: `vendor/superpowers/skills/writing-plans/SKILL.md`.
- Revisão: `vendor/superpowers/skills/requesting-code-review/SKILL.md`.
- Impeccable: `.agents/skills/impeccable/SKILL.md`.
- Frontend Design: `.agents/skills/frontend-design/SKILL.md`.
- OWASP Security: `.agents/skills/owasp-security/SKILL.md`.

Brainstorming só quando há decisão em aberto; requisitos aprovados no README/roadmap não precisam de nova aprovação. Usa subagentes/worktrees apenas se existirem ferramentas reais no runtime. Se a execução ocorrer via GitHub API, usa commits pequenos, CAS e CI; não afirmes que criaste worktrees.

## Limites do produto
API é a autoridade de permissões e regras. Observações de visão não alteram stock. `UNKNOWN`, falha de câmara e falha de análise não significam `OUT_OF_STOCK`. Mantém revisão humana explícita. Distingue mock, dados sintéticos, testes, CI, testes manuais e integrações reais. Não activar purga física nem apagar staging órfão sem política aprovada e prova de quiescência. Não introduzir dependências runtime ou telemetry sem revisão.

## Verificação
TDD RED/GREEN quando o ambiente o permitir; testes focados, suite API, PostgreSQL smoke, Python compile, Web build e Docker Compose conforme o impacto. Inspecciona o SHA exacto dos workflows. Actualiza TODO/PROGRESS/ROADMAP. Nunca declares sucesso sem evidência.
