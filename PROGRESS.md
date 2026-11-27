# PROGRESS — SMART SHELF AI

## Estado atual
- Branch: main
- HEAD anterior confirmado: 460bf6c4f3b472b6fed1251bbbca559d1f272cb2
- Última atualização: 2026-11-27

## Validação EDGE-OBSERVABILITY-02
- API CI: SUCCESS — run 46029148954.
- Quality Gates: SUCCESS — run 46029148883.
- Security Scans: SUCCESS — run 46029148963.
- Docker Compose Smoke: SUCCESS — run 46029149013.
- Os quatro workflows foram concluídos com sucesso no SHA 460bf6c4f3b472b6fed1251bbbca559d1f272cb2.

## Tarefa actual — EDGE-INGEST-OBSERVABILITY-01
- Implementados contadores na fronteira HTTP da API: received, accepted, duplicate, rejected e categorias de rejeição.
- Os contadores são process-local, protegidos por lock e registados em logs estruturados sem payload/segredos.
- Acrescentado teste HTTP que cobre aceite, duplicado, conflito de sequência e autenticação inválida.
- Não existe endpoint público nem retenção histórica; estes limites estão documentados.
- Validação desta alteração: pendente de GitHub Actions.

## Próximas tarefas
- [ ] Definir agregação durável e retenção histórica sem transformar métricas em ledger.
- [ ] Implementar revisão humana append-only das declarações COMPLETED (actor autenticado, decisão, motivo obrigatório, timestamp e referência de evidência), sem mutação automática de tarefa/inventário.
- [ ] Manter TASK_ACKNOWLEDGED desactivado por omissão.

## Limites de validação
- Não foram executados testes localmente nesta sessão.
- Os resultados de CI acima referem-se exclusivamente ao commit anterior, não à alteração de ingestão agora preparada.
