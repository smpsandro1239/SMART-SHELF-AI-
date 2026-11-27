# PROGRESS — SMART SHELF AI

## Estado atual
- Branch: `main`
- Último commit de código validado: `4ea755b6a110bb6766748cb970db0458583444b8`
- Último commit publicado: `e45015296ad2221828af6a94f53178abc822c9e2` (documentação)
- Última atualização: 2026-11-27

## Tarefa atual
- Identificador: EDGE-ACK-REVIEW-01
- Descrição: formalizar o fluxo auditável de revisão humana para ACK COMPLETED.
- Estado: PENDING — manter COMPLETED em REVIEW_REQUIRED e sem efeitos no inventário até existir revisão autenticada e auditável.

## Tarefas concluídas
- [x] Supervisor independente com subprocesso, heartbeat, PID e estado operacional.
- [x] Watchdog para crash, SIGKILL e heartbeat obsoleto; backoff exponencial limitado.
- [x] Lock exclusivo para impedir supervisores duplicados no mesmo runtime.
- [x] Shutdown SIGTERM/SIGINT gracioso, timeout e SIGKILL de último recurso.
- [x] Healthcheck do supervisor e do processo filho.
- [x] Docker Compose smoke de recuperação SIGKILL, heartbeat obsoleto, shutdown SIGTERM e reinício limpo.
- [x] Métricas do polling no heartbeat e propagação do snapshot ao estado do supervisor.
- [x] Logs de outcomes correlacionados por IDs internos, tentativa, duração e resultado; sem payload ou texto de excepção.
- [x] Scopes de acção por associação dispositivo-tarefa; lista vazia e associações antigas são deny-by-default.
- [x] Configuração ACK fail-closed com flag false por omissão e selector explícito de registry.
- [x] Injecção explícita do mapa transaccional; flag isolada não activa handlers.
- [x] Erro de configuração do filho deixa supervisor em FAILED sem restart loop.
- [x] Testes de ACK_RECORDED, ACK_REJECTED, RETRY, DEAD_LETTER, LEASE_LOST, scopes e configuração fail-closed.

## Tarefas pendentes
- [ ] Implementar revisão humana auditável de COMPLETED (actor, decisão, motivo, timestamp, evidência).
- [ ] Decidir mecanismo de exportação/consumo das métricas sem adicionar infraestrutura desnecessária.
- [ ] Manter ACK desactivado até aprovação operacional explícita.

## Tarefas bloqueadas
- A activação de ACK em produção exige aprovação operacional; não está autorizada nesta fase.

## Testes
- Compilação Python e suite API: SUCCESS.
- PostgreSQL 16 ACK smoke: SUCCESS, incluindo scope deny-by-default e DEAD_LETTER.
- Docker Compose smoke: SUCCESS.
- Quality Gates: SUCCESS.
- Security Scans: SUCCESS.
- Testes locais: não executados; esta execução não dispõe de terminal ligado ao repositório.

## CI/CD
- SHA integralmente validado: `4ea755b6a110bb6766748cb970db0458583444b8`.
- API CI: SUCCESS — run 46023483063.
- Docker Compose smoke: SUCCESS — run 46023483209.
- Quality Gates: SUCCESS — run 46023483050.
- Security Scans: SUCCESS — run 46023483060.

## Decisões técnicas
- O supervisor é processo independente, não uma thread no worker.
- Heartbeats e estado são ficheiros JSON atómicos em `/tmp`.
- O timeout do heartbeat do filho é configurável; o valor por omissão é 120 s.
- O lock `flock` evita duplicação de supervisores no mesmo volume.
- Os contadores são snapshots voláteis por processo, não um ledger histórico.
- `EDGE_TASK_ACKNOWLEDGEMENT_ENABLED` é false por omissão; true exige `EDGE_TASK_ACKNOWLEDGEMENT_HANDLER_REGISTRY=builtin-v1`.
- O mapa transaccional é injectado explicitamente; flag isolada não activa ACK.
- O supervisor mantém-se FAILED em erro de configuração, sem reinícios repetidos.
- `COMPLETED` continua apenas `REVIEW_REQUIRED`; nenhum acknowledgement altera tarefa, versão, stock ou movimentos.
- Nenhuma migration foi necessária para scopes: a allowlist é guardada no evento CREATED append-only.

## Próxima ação obrigatória
- Desenhar e implementar revisão humana append-only para declarações COMPLETED, sem concluir tarefas nem alterar inventário automaticamente.

---

