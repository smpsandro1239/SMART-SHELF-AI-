# PROGRESS — SMART SHELF AI

## Estado atual
- Branch: `main`
- HEAD inicial confirmado nesta sessão: `0b0bc58874a9b3c3bf29276c6a867a206de4a959`
- Última atualização: 2026-11-27

## Tarefa atual
- Identificador: EDGE-OBSERVABILITY-02
- Descrição: completar contadores operacionais Edge no heartbeat privado e definir fronteira segura de exportação.
- Estado: IMPLEMENTADO — validação CI pendente no novo SHA.

## Tarefas concluídas
- [x] Supervisor independente com subprocesso, heartbeat, watchdog, backoff, singleton lock e shutdown gracioso.
- [x] Heartbeat de polling e propagação do snapshot para o estado do supervisor.
- [x] Logs de outcomes correlacionados sem payload nem texto de excepção.
- [x] Contadores de PROCESSED, RETRY, DEAD_LETTER, LEASE_LOST, ACK_CLAIMED, ACK_RECORDED e ACK_REJECTED.
- [x] Contadores de falhas de handler, duplicados rejeitados e renovações/falhas de lease.
- [x] Observadores best-effort: falha da telemetria não interrompe nem altera a operação transaccional.
- [x] Decisão de exportação: ficheiros privados em /tmp e logs; sem endpoint HTTP/porta adicional nesta fase.
- [x] Testes de observação de outcomes e rejeição de ACK duplicado.

## Tarefas pendentes
- [ ] Contabilizar eventos recebidos no ponto de ingestão HTTP, separadamente de eventos reclamados pelo worker.
- [ ] Definir agregação durável e retenção de métricas históricas antes de analytics.
- [ ] Implementar revisão humana append-only de declarações COMPLETED (actor, decisão, motivo, timestamp e evidência), sem mutação automática de tarefa/inventário.
- [ ] Validar API CI/PostgreSQL 16, Docker Compose, Quality Gates e Security Scans no SHA desta alteração.

## Tarefas bloqueadas
- Activação de ACK em produção: exige aprovação operacional explícita; permanece desactivada por omissão.

## Testes
- Adicionados: observação dos outcomes PROCESSED/CLAIMED e ACK_CLAIMED/ACK_REJECTED por duplicado.
- Execução local: não disponível nesta sessão; aguardar GitHub Actions.
- Regressões a confirmar: suite Edge worker, suite API e PostgreSQL 16.

## CI/CD
- Último SHA observado antes da alteração: `0b0bc58874a9b3c3bf29276c6a867a206de4a959`.
- Quality Gates e Security Scans: SUCCESS nesse SHA.
- API CI e Docker Compose: SUCCESS no SHA validado anteriormente `4ea755b6a110bb6766748cb970db0458583444b8`.
- Resultado da nova alteração: pendente.

## Decisões técnicas
- Heartbeat JSON continua privado no filesystem efémero do container.
- Não expor endpoint Prometheus/HTTP sem autenticação, isolamento multi-loja e consumidor definido.
- Snapshots de métricas são operacionais e voláteis; não substituem ledger append-only nem analytics históricos.
- Métricas nunca alteram inventário, tarefa, ACK ou estado transaccional.
- `TASK_ACKNOWLEDGED` continua fail-closed e `COMPLETED` continua `REVIEW_REQUIRED`.

## Próxima ação obrigatória
- Adicionar contagem de eventos recebidos no ponto de ingestão, sem confundir recepção com claim/processamento; depois retomar o desenho da revisão humana auditável.
