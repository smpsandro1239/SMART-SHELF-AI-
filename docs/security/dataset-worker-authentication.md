# Autenticação e autorização de workers de datasets

## Objetivo e fronteira de confiança

Workers de execução de datasets são identidades de serviço, não utilizadores humanos. Não reutilizam JWT de ADMIN/SUPERVISOR/EMPLOYEE nem confiam em `worker_id` enviado livremente pelo cliente.

A migration `0060_dataset_worker_credentials` introduz três registos:

- `dataset_workers`: identidade estável e estado ACTIVE/DISABLED;
- `dataset_worker_credentials`: credenciais individuais, scopes, validade, revogação, rotação e último uso;
- `dataset_worker_events`: auditoria append-only de registo, emissão, rotação, revogação e desativação.

## Formato e armazenamento do segredo

A credencial emitida tem o formato `ssw1.<credential_id>.<secret>`. O identificador público permite localizar o registo; o segredo aleatório tem 256 bits de entropia. A base de dados guarda apenas SHA-256 do segredo. A comparação do digest usa `hmac.compare_digest`; uma credencial inexistente usa um digest fictício para evitar uma comparação trivialmente mais curta.

O valor em texto simples é apresentado uma única vez pelo comando de provisionamento. Não é escrito em eventos, logs, tabelas ou documentação. Deve ser guardado num secret manager e transportado exclusivamente por TLS.

## Scopes

A allow-list inicial é explícita e não aceita wildcard:

| Scope | Estado |
|---|---|
| `jobs:claim` | Wrapper autenticado implementado |
| `jobs:heartbeat` | Wrapper autenticado implementado |
| `jobs:complete` | Wrapper autenticado implementado |
| `jobs:fail` | Wrapper autenticado implementado |
| `artifacts:read` | Reservado; serviço de leitura ainda não implementado |
| `outputs:publish` | Reservado; promotor fenced ainda não implementado |

Os wrappers de claim/heartbeat/conclusão/falha recebem um `DatasetWorkerPrincipal` obtido após autenticação e retiram o `worker_id` desse principal. Não aceitam um identificador de worker fornecido separadamente pelo chamador.

## Provisionamento local confiável

Executar dentro do ambiente da API, com acesso administrativo à base de dados:

```bash
cd apps/api
python -m app.dataset_worker_admin issue \
  --worker-id training-node-01 \
  --scope jobs:claim \
  --scope jobs:heartbeat \
  --scope jobs:complete \
  --scope jobs:fail
```

A saída JSON inclui a credencial completa uma única vez. Não copiar essa saída para tickets, commits, histórico de shell partilhado ou logs.

Rotação atómica (revoga as credenciais ainda válidas do worker e emite uma nova):

```bash
python -m app.dataset_worker_admin rotate \
  --worker-id training-node-01 \
  --scope jobs:claim \
  --scope jobs:heartbeat \
  --scope jobs:complete \
  --scope jobs:fail
```

Revogação individual e desativação integral:

```bash
python -m app.dataset_worker_admin revoke --credential-id <credential_id>
python -m app.dataset_worker_admin disable --worker-id training-node-01
```

A validade predefinida é 30 dias; o serviço limita a validade a 90 dias e rejeita valores inferiores a 60 segundos. Um worker desativado não pode receber novas credenciais. A rotação e a revogação são transacionais.

## Limites e controlos ainda necessários

- A credencial é um bearer token reutilizável até expirar ou ser revogado. Ainda não existe assinatura por pedido, nonce ou proteção anti-replay; não alegar resistência a replay. O transporte tem de usar TLS e os tokens devem ter scopes mínimos e validade curta.
- `last_used_at` é telemetria, não mecanismo anti-replay.
- A emissão só está disponível através de CLI local confiável; não existe endpoint HTTP público de emissão.
- A API de jobs/claim/heartbeat ainda não está exposta. A autenticação tem de ser integrada no middleware/handlers antes de disponibilizar qualquer rota.
- Os wrappers existentes cobrem operações de lease. A leitura de bytes por chamada e a publicação/promoção de outputs com verificação do fencing token actual continuam por implementar.
- Os eventos de segurança são append-only na base de dados PostgreSQL e SQLite. Os detalhes auditados não incluem segredos.
- A desativação de um worker revoga todas as credenciais que ainda não estavam revogadas.

## Validação exigida

Os testes unitários cobrem credenciais malformadas/desconhecidas, segredo incorreto, expiração, revogação, rotação, desativação, scopes inválidos/insuficientes e vinculação do claim à identidade autenticada. O smoke PostgreSQL valida o ciclo de vida e tenta UPDATE/DELETE directos aos eventos append-only. Só marcar a migration e o serviço como validados depois de API CI e Quality Gates passarem no commit correspondente.
