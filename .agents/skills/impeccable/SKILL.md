---
name: impeccable
description: "Use when designing, critiquing, auditing, polishing, hardening, or improving the SMART SHELF AI frontend: dashboards, capture/review workflows, forms, navigation, accessibility, responsive behavior, UX copy, and design tokens."
metadata:
  upstream: https://github.com/pbakaus/impeccable
  pinned_commit: b49177d32788f2dc585c42831d845dacf1ebed2c
---

# Impeccable — SMART SHELF AI

This project entry point delegates to the upstream Impeccable skill, pinned as a Git submodule at `vendor/impeccable`. The upstream instructions, playbooks, reference files, agent definitions, and executable engine remain intact there.

## Mandatory loading

Before frontend design work, read:

1. `vendor/impeccable/.agents/skills/impeccable/SKILL.md` in full.
2. The relevant playbooks under `vendor/impeccable/.agents/skills/impeccable/reference/`.
3. `PRODUCT.md` and `DESIGN.md` at the repository root.
4. Read upstream `reference/craft-floor.md` immediately before editing UI code.

Keep the working directory at the repository root. Run the upstream context command once per session:

`vendor/impeccable/.agents/skills/impeccable/scripts/impeccable context`

On Windows without a POSIX shell, use `vendor/impeccable/.agents/skills/impeccable/scripts/impeccable.cmd`.

Use the upstream `critique`, `audit`, `document`, `polish`, `harden`, `adapt`, `typeset`, `layout`, and `extract` playbooks where appropriate. Do not run a broad redesign without explicit product direction. The current web app is an operational dashboard (Operate mode): clarity, scanability, task completion, consistency, accessibility, and responsive behavior take precedence over decorative novelty.

## Project-specific constraints

- Preserve business behavior, API contracts, role permissions, audit trails, and human approval boundaries.
- Do not imply that mock vision data or demo integrations are real.
- Never make UI claims about stock, detections, or camera health that the API cannot substantiate.
- Keep operational decisions and stock movements human-governed.
- Do not introduce new runtime dependencies, remote fonts/assets, analytics, or telemetry without review.
- Every changed screen must preserve loading, empty, error, disabled, and permission-denied states where applicable.
- Verify rendered output at desktop and mobile sizes when a browser/runtime is available. If unavailable, state that visual verification remains pending; a TypeScript build is not visual QA.

## Automated design detector

The quality workflow runs the upstream detector against `apps/web/src/` using the pinned CLI version. Findings are initially reported as a baseline and do not fail CI; inability to execute the detector does fail the job. Reduce findings incrementally and only add documented, narrowly scoped ignores when justified.
