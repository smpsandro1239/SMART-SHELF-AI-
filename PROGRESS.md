# PROGRESS — SMART SHELF AI

## EDGE-OBSERVABILITY-HISTORY-01 — schema validado e agregador em implementação

- HEAD da main confirmado no início desta fase: 9bac2589727c9fe75d8a077736f9d29e616e8cea.
- Política aprovada: 90 dias para agregados de 15 minutos, agregados diários e eventos operacionais do supervisor.
- Inbox, processing, ACK, revisões humanas, auditoria de dispositivos e telemetria actual permanecem fora desta política.
- Agregador independente do Edge Worker; agregação idempotente e tenant-scoped; sem endpoint público.
- Não se pretende guardar cada transição/tentativa individual nem inferir contadores de rejeições/duplicados sem fonte durável.
- Migration 0105 publicada no SHA 8966ffdf91bf6d81437cc504f337b15cfce4db13; API CI, Quality Gates, Security Scans e Docker Compose Smoke concluíram SUCCESS. Suite API: 1803 passed, 1 skipped.
- Incremento seguinte em preparação: agregador independente, UPSERT, checkpoints, retenção em lotes e serviço Docker. Persistência assíncrona de eventos do supervisor permanece pendente.
- Não declarar a fase concluída até CI e smoke PostgreSQL 16 aprovados.


## Estado actual
- Branch: main
- SHA validado: f9ff01b477575b8f1ebc8534a940ffac25d1f637
- Última actualização: 2026-11-27

## EDGE-INGEST-OBSERVABILITY-01
- A instrumentação da ingestão HTTP foi validada no SHA 5f4a9a2a944ca7b41ae1206653d3e77c4211b4c8: API CI 46030149210, Quality Gates 46030149206, Security Scans 46030149185 e Docker Compose Smoke 46030149183 — todos SUCCESS.
- Os contadores são process-local; não constituem retenção histórica.

## EDGE-HUMAN-ACK-REVIEW-01 — IMPLEMENTADO E VALIDADO
- Ledger edge_task_acknowledgement_reviews append-only, com FKs compostas para loja/tarefa/ACK, actor autenticado, decisão, motivo, referência de evidência, idempotency key e timestamp UTC.
- Serviço transaccional e endpoints POST/GET autenticados.
- ADMIN/SUPERVISOR activos; supervisor limitado à própria loja. Utilizadores EMPLOYEE e contas inactivas são recusados.
- Idempotência por store/ACK/actor; replay idêntico devolve o registo (HTTP 200), reutilização com conteúdo diferente gera conflito.
- Locks PostgreSQL da tarefa e ACK serializam pedidos concorrentes. Triggers PostgreSQL e SQLite impedem UPDATE/DELETE.
- O ledger é o próprio registo de auditoria atómico. A revisão não altera tarefa, ACK, snapshots, movimentos ou inventário.
- Testes de serviço, API e migration: 1802 passed, 1 skipped.
- Smoke PostgreSQL 16: dois POST concorrentes com a mesma chave aguardaram o lock da mesma tarefa; foi persistida uma única revisão, com respostas HTTP 201 e 200. Confirmada a ausência de mutação de tarefa, ACK e inventário.

## Validação final no SHA f9ff01b477575b8f1ebc8534a940ffac25d1f637

| Workflow | Run | Resultado |
|---|---:|---|
| API CI / PostgreSQL 16 | 46033847401 | **SUCCESS** |
| Quality Gates | 46033847516 | **SUCCESS** |
| Security Scans / OWASP ZAP | 46033847557 | **SUCCESS** |
| Docker Compose Smoke | 46033847475 | **SUCCESS** |

A API CI confirmou a migration 0104 em PostgreSQL 16, o smoke de concorrência/idempotência da revisão humana e a suite completa de testes.

## Próximas tarefas
- [ ] Avaliar agregação durável e retenção histórica das métricas operacionais Edge.
- [ ] Manter TASK_ACKNOWLEDGED desactivado por omissão e sem autorização de produção até existir aprovação operacional explícita.
- [ ] Definir eventual fluxo de reconciliação posterior, separado da revisão humana, sem efeitos automáticos de inventário.

## Limites de validação
- Não foram executados testes localmente nesta sessão; a validação foi efectuada pelos workflows GitHub Actions indicados.
- A revisão humana aprova ou rejeita a declaração do dispositivo; não comprova fisicamente a reposição.

## EDGE-OBSERVABILITY-HISTORY-01 — incremento 1

- Migration `0105_edge_observability_history` encadeada depois de 0104; cria agregados por loja/janela, checkpoints e eventos do supervisor com campos allowlisted.
- Modelos SQLAlchemy adicionados sem alterar inbox, processing, ACK, revisões humanas ou telemetria actual.
- Teste SQLite cobre unicidade, constraints de granularidade/métrica, FK de loja, allowlist de eventos e chave idempotente.
- Validação pendente: execução da suite e PostgreSQL 16 pela CI.
