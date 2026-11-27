# PROGRESS — SMART SHELF AI

## Estado actual
- Branch de trabalho: main
- SHA inicial desta ronda: 5f4a9a2a944ca7b41ae1206653d3e77c4211b4c8
- Último commit de implementação: 12d252bff69b36cc96858cf2a044e6fe678da998
- Última actualização: 2026-11-27

## EDGE-INGEST-OBSERVABILITY-01
- A instrumentação da ingestão HTTP foi validada no SHA inicial desta ronda: API CI 46030149210, Quality Gates 46030149206, Security Scans 46030149185 e Docker Compose Smoke 46030149183 — todos SUCCESS.
- Os contadores continuam process-local e não constituem retenção histórica.

## EDGE-HUMAN-ACK-REVIEW-01
- Adicionado ledger append-only para decisões humanas sobre ACK COMPLETED/REVIEW_REQUIRED.
- Implementados serviço transaccional, idempotência por store/ACK/actor, autorização ADMIN/SUPERVISOR, isolamento multi-loja e endpoints POST/GET.
- O registo de revisão é também o registo de auditoria atómico; nenhuma tarefa, ACK ou entidade de inventário é actualizada.
- Adicionados testes de serviço, API e migration SQLite.
- A primeira execução Quality Gates revelou 7 falhas colaterais em `test_observations.py`: o novo fixture API removia um override de dependência definido ao nível do módulo por outro ficheiro de testes. Corrigido para restaurar o override anterior. A repetição da suite está pendente no SHA final.
- Não foram executados testes localmente nesta sessão.
- Acrescentado smoke PostgreSQL 16 que mantém a linha da tarefa bloqueada, envia dois POST HTTP concorrentes com a mesma chave e exige bloqueio real em `pg_stat_activity`, uma revisão persistida e respostas 201/200.
- A primeira execução do smoke PostgreSQL falhou apenas na selecção do ACK: o script consultava `.one()` sem filtrar a inbox, mas o banco partilhado já continha ACKs de smokes anteriores. Corrigido para filtrar pelo `inbox_id` criado pelo próprio ensaio; repetir API CI pendente.

## Próximas tarefas
- [ ] Confirmar API CI/PostgreSQL 16, Quality Gates, Security Scans e Docker Compose no SHA final.
- [ ] Acrescentar smoke concorrente PostgreSQL dedicado a duas revisões simultâneas do mesmo ACK.
- [ ] Manter `TASK_ACKNOWLEDGED` desactivado por omissão e sem autorização de produção.
- [ ] Definir agregação durável e retenção histórica das métricas operacionais.

## Limites de validação
- Sem execução local; a validação depende dos workflows GitHub Actions.
- A revisão humana não confirma fisicamente reposição nem altera inventário.
