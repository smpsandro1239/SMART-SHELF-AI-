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

Os testes unitários cobrem credenciais malformadas/desconhecidas, segredo incorreto, expiração, revogação, rotação, desativação, scopes inválidos/insuficientes e vinculação do claim à identidade autenticada. O teste de migration SQLite cobre os guards de imutabilidade; o smoke PostgreSQL valida o ciclo de vida e tenta adulterar/eliminar credenciais e eventos. Validação concluída no commit de código `d7c84125d35a5fff5d2254a3ee33a08cd41edcc7`: API CI [44431378398](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378398) e Quality Gates [44431378324](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378324) passaram; suite API com 1202 testes aprovados, 1 ignorado e 1 aviso.

## Integridade imposta pela base de dados

A migration 0060 aplica guards equivalentes em PostgreSQL e SQLite:

- worker_id e created_at do worker são imutáveis; ACTIVE só pode transitar para DISABLED e nunca ser reativado;
- id, credential_id, worker_id, hash, scopes, created_at e expires_at da credencial são imutáveis;
- revoked_at e replaced_by_credential_id só podem transitar de NULL para um valor; last_used_at não pode recuar nem ser apagado;
- credenciais não podem ser eliminadas;
- eventos de segurança não aceitam UPDATE nem DELETE.

O teste SQLite `test_dataset_worker_credentials_migration.py` verifica estes guards e o smoke `postgres_dataset_worker_credentials_smoke.py` testa as proteções em PostgreSQL 16. Validação CI: [API CI 44431378398](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378398), [Quality Gates 44431378324](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378324) e [Docker Compose 44431378349](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378349); 1202 testes aprovados, 1 ignorado e 1 aviso.


## Assinatura de pedidos e proteção anti-replay (migration 0061)

A credencial bearer continua a identificar o worker, mas deixa de ser suficiente para autorizar um pedido protegido. A dependência FastAPI `require_dataset_worker(scope)` exige também:

- `X-Worker-Timestamp`: Unix time em segundos, dentro de ±60 segundos;
- `X-Worker-Nonce`: valor aleatório Base64URL, com pelo menos 128 bits de entropia;
- `X-Worker-Signature`: HMAC-SHA-256 em hexadecimal minúsculo.

A representação canónica assinada contém, por esta ordem, `SSW1`, credential ID, timestamp, nonce, método HTTP em maiúsculas, request-target exacto (caminho + query tal como recebido) e SHA-256 do corpo, separados por newline. O cliente deriva a chave HMAC como SHA-256 do segredo que recebeu uma única vez. O servidor usa o digest SHA-256 já persistido como chave de verificação; o segredo original não é armazenado.

Exemplo de integração futura num handler:

```python
from fastapi import APIRouter, Depends
from app.dataset_worker_http import require_dataset_worker

router = APIRouter(prefix="/internal/v1/dataset-jobs")

@router.post("/claim")
def claim_dataset_job(principal=Depends(require_dataset_worker("jobs:claim"))):
    ...
```

O exemplo ilustra apenas a aplicação da dependência; não existe ainda router/endpoint de jobs montado. A autenticação humana global protege `/api/v1`; por isso, as rotas de serviço futuras devem ficar num prefixo separado, com a dependência de worker em cada operação.

A migration `0061_dataset_worker_request_nonces` guarda somente o SHA-256 do nonce, credential ID, timestamp e expiração. Uma restrição única por credencial/nonce serializa repetições concorrentes. A janela do timestamp é ±60 segundos e o registo do nonce dura 121 segundos, tempo suficiente para cobrir todo o período em que o timestamp pode ser aceite. Nonces expirados são removidos no próximo pedido assinado. O nonce é consumido e confirmado numa transacção própria antes do handler; mesmo que a operação de negócio falhe, uma repetição tem de usar um nonce novo.

**Validação:** API CI [44471171581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171581) — migration PostgreSQL 16, smoke concorrente com duas sessões (**uma aceitação e uma rejeição**) e 1211 testes aprovados, 1 ignorado e 1 aviso; Quality Gates [44471171526](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171526); Docker Compose [44471171533](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171533).

**Limites:** esta camada autentica e autoriza pedidos assinados, mas não cria endpoints, broker nem worker remoto. Os scopes `artifacts:read` e `outputs:publish` continuam sem handlers; a leitura de bytes deve revalidar retenção no momento do consumo e a publicação deve validar o fencing token actual.


## Leitura de bytes de fontes de treino (`artifacts:read`) — migration 0062

O serviço `app.dataset_job_artifact_reads.read_dataset_job_source_bytes` implementa leitura interna por chamada, sem expor caminhos ou URLs. A operação exige principal autenticado com `artifacts:read`, job em `LEASED`, `worker_id` do principal e fencing token actual. A imagem tem de constar da tabela imutável de fontes do job.

A operação bloqueia job e hierarquia imagem/prateleira/zona até concluir a leitura; revalida loja, retenção e legal hold; revalida worker e credencial (estado, expiração, revogação e scope) na mesma transacção; abre o ficheiro com descritores de directório e `O_NOFOLLOW`; valida tamanho e SHA-256; devolve apenas os bytes em memória. Uma leitura bem-sucedida cria um registo em `dataset_execution_job_artifact_reads`.

A migration `0062_dataset_job_artifact_reads` inclui triggers PostgreSQL/SQLite que validam lease actual, owner, fencing token, fonte imutável, loja, retenção, legal hold, worker/credencial activos e scope `artifacts:read`. A auditoria é append-only. O smoke PostgreSQL confirmou que uma restrição de retenção concorrente espera pelo lock da leitura e impede a leitura seguinte, sem criar novo registo de sucesso.

As operações claim/heartbeat/complete/fail também revalidam o worker e a credencial no momento da operação, não confiando apenas no principal obtido alguns instantes antes pela dependência HTTP.

**Validação:** API CI [44473560217](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560217), Quality Gates [44473560287](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560287) e Docker Compose [44473560252](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560252); suite API: 1223 passed, 1 skipped, 1 warning.

**Limites:** o serviço ainda não está ligado a uma rota HTTP de jobs. A publicação de outputs com fencing (`outputs:publish`), broker e worker remoto permanecem pendentes.
