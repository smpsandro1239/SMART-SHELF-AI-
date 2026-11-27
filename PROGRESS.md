# PROGRESS — SMART SHELF AI

## Estado atual
- Branch: `main`
- Último commit de código validado: `4024763c177dfad63179e3b3cb73648371a729dc`
- Último commit publicado: `8fa39d9d928456e86e7e4d46305be8f4fa375e8d` (documentação)
- Última atualização: 2026-11-27

## Tarefa atual
- Identificador: EDGE-ACK-AUTH-01
- Descrição: rever e fechar a autorização por acção dos acknowledgements Edge sem activar o handler.
- Estado: PENDING — a matriz de capacidades por acção ainda não está definida; manter ACK fail-closed.

## Tarefas concluídas
- [x] Supervisor independente com subprocesso, heartbeat, PID e estado operacional.
- [x] Watchdog para crash, SIGKILL e heartbeat obsoleto; backoff exponencial limitado.
- [x] Lock exclusivo para impedir supervisores duplicados no mesmo runtime.
- [x] Shutdown SIGTERM/SIGINT gracioso, timeout e SIGKILL de último recurso.
- [x] Healthcheck do supervisor e do processo filho.
- [x] Docker Compose smoke de recuperação SIGKILL, heartbeat obsoleto, shutdown SIGTERM e reinício limpo.
- [x] Métricas do polling no heartbeat e propagação do snapshot ao estado do supervisor.
- [x] Logs de outcomes correlacionados por IDs internos, tentativa, duração e resultado; sem payload ou texto de excepção.
- [x] Testes de ACK_RECORDED, ACK_REJECTED, RETRY, DEAD_LETTER e LEASE_LOST.

## Tarefas pendentes
- [ ] Decidir mecanismo de exportação/consumo das métricas sem adicionar infraestrutura desnecessária.
- [ ] Auditar e definir autorização por acção para TASK_ACKNOWLEDGED; não activar a registry até existir política explícita.

## Tarefas bloqueadas
- Nenhuma dependência externa identificada. A autorização por acção permanece deny-by-default enquanto a matriz não for aprovada.

## Testes
- Compilação Python e suite API: SUCCESS.
- PostgreSQL 16 smokes incluídos no API CI: SUCCESS.
- Docker Compose smoke, incluindo SIGKILL, heartbeat stale e SIGTERM: SUCCESS.
- Testes de telemetria/outcomes: incluídos na suite API, SUCCESS.
- Testes locais: não executados; esta execução não dispõe de terminal ligado ao repositório.

## CI/CD
- SHA integralmente validado: `4024763c177dfad63179e3b3cb73648371a729dc`.
- API CI: SUCCESS — run 46019666164.
- Docker Compose smoke: SUCCESS — run 46019666111.
- Quality Gates: SUCCESS — run 46019666195.
- Security Scans: SUCCESS — run 46019666137.

## Decisões técnicas
- O supervisor é processo independente, não uma thread no worker.
- Heartbeats e estado são ficheiros JSON atómicos em `/tmp`.
- O timeout do heartbeat do filho é configurável; o valor por omissão é 120 s.
- O lock `flock` evita duplicação de supervisores no mesmo volume.
- Os contadores são snapshots voláteis por processo, não um ledger histórico.
- `TASK_ACKNOWLEDGED` continua opt-in e não é injectado no runtime.
- Nenhuma operação de inventário ou migration foi alterada nesta fase.

## Próxima ação obrigatória
- Auditar a autorização por acção de `TASK_ACKNOWLEDGED`; identificar os contratos existentes e implementar deny-by-default sem activar handlers.

---

