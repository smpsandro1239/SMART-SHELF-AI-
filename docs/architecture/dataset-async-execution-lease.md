# Contrato de execução assíncrona de datasets: lease e fencing

## Estado

Contrato implementado até à promoção fenced de outputs nas migrations `0056`–`0063`: persistência de jobs, fencing, identidade de workers, pedidos assinados/anti-replay, leitura autorizada de fontes e serviço interno de publicação. **Ainda não existe broker, worker de treino/inferência remoto nem rotas HTTP de jobs.** O processo de treino suportado continua a ser o consumidor local síncrono de `app.dataset_execution`; a execução assíncrona não é operacional.

## Modelo de ameaça

O sistema tem de tolerar:
- dois workers a tentar reclamar o mesmo job;
- worker suspenso, crashado ou isolado da rede até o lease expirar;
- takeover por outro worker enquanto o primeiro ainda calcula;
- heartbeat/conclusão atrasados de um worker antigo;
- alteração de retenção, legal hold ou hierarquia da imagem durante a execução;
- retries de enqueue com a mesma chave idempotente;
- falha depois de o output ter sido produzido, mas antes de a conclusão ser persistida.

## Identidade imutável do job

Cada job deve fixar no momento de enqueue:
- idempotency key única;
- fingerprint da release;
- SHA-256 do registo de aprovação;
- SHA-256 do relatório determinístico do gate;
- modo aprovado (`training` ou `inference`);
- conjunto normalizado de fontes internas: `shelf_image_id`, `store_id` esperado e SHA-256 original.

O conjunto de fontes é imutável. Uma repetição da mesma idempotency key com payload idêntico devolve o job existente; a mesma chave com release, aprovação, modo ou fontes diferentes é conflito. Fontes externas não podem ser representadas como IDs internos: exigem integração com a fronteira de consumo de artefactos externos e inventários assinados.

## Estados

| Estado | Significado | Transições permitidas |
|---|---|---|
| `QUEUED` | Job aprovado e pronto para claim | `LEASED`, `REVOKED`, `CANCELLED` |
| `LEASED` | Worker detém lease ainda válido | `LEASED` (heartbeat/takeover), `SUCCEEDED`, `FAILED`, `REVOKED`, `CANCELLED` |
| `SUCCEEDED` | Resultado validado e registado | Terminal |
| `FAILED` | Execução terminou com falha | Terminal; retry deve ser um novo job/idempotency key |
| `REVOKED` | Fonte deixou de ser elegível ou aprovação foi revogada | Terminal |
| `CANCELLED` | Cancelamento explícito autorizado | Terminal |

Um lease expirado não é, por si só, um estado terminal. Um novo worker pode reclamar o job, incrementando o fencing token.

## Claim e fencing

1. O worker autentica-se por identidade de serviço e pede um job.
2. A transacção selecciona um job `QUEUED` ou com lease expirado através de `SELECT ... FOR UPDATE SKIP LOCKED`, ordenado por `created_at, id`.
3. O claim incrementa atomicamente `fencing_token`, incrementa `attempt_count`, define `lease_owner` e `lease_expires_at`, e regista evento append-only.
4. O token é monotónico por job. O worker recebe `job_id`, token, expiração e fingerprint; o token nunca é escolhido pelo worker.
5. Heartbeat, falha e conclusão exigem simultaneamente job, proprietário, token actual, estado `LEASED` e lease ainda válido. Qualquer mismatch é `LeaseLost`.
6. Um takeover incrementa o token. Um worker antigo pode terminar computação, mas não pode renovar, concluir ou publicar usando o token anterior.

## Retenção e autorização em cada fronteira

- O enqueue, claim, heartbeat e conclusão revalidam as fontes internas com `validate_internal_image_eligibility`, verificando loja efectiva, SHA-256, `ACTIVE` e ausência de legal hold.
- As linhas de imagem, prateleira e zona são bloqueadas por IDs crescentes, com a ordem de locks usada pelo gate actual.
- O lock do job é adquirido antes dos locks das fontes. Nenhum fluxo de retenção pode adquirir o lock do job depois de bloquear a imagem; se surgir essa necessidade, a ordem global tem de ser revista antes de implementar.
- Se uma fonte estiver restrita, sob legal hold, ausente ou com hash/loja divergente, o job passa para `REVOKED`; não pode iniciar ou publicar resultado.
- A conclusão valida novamente as fontes sob lock. O worker não pode assumir que uma autorização obtida no claim continua válida para sempre.

**Limite fundamental:** heartbeat não impede um worker de continuar a ler uma cópia local depois de perder o lease. Para garantir que a retenção corta novas leituras, o worker deve obter cada artefacto através de um serviço de consumo que revalida autorização no momento da leitura. Não materializar fontes em caches locais duradouros sem inventário, revogação e eliminação verificável.

## Publicação segura de outputs

- O worker escreve primeiro para uma localização de staging não publicada, identificada por `job_id + fencing_token`.
- A conclusão persiste o digest e a referência de staging apenas se o token continuar actual e as fontes continuarem elegíveis.
- Um passo separado promove/publica o output apenas após reler o job e verificar estado `SUCCEEDED`, digest e token actual.
- Um worker antigo nunca escreve para um alias estável ou caminho de produção.
- Se a promoção externa falhar, o job mantém evidência da conclusão e a promoção pode ser repetida idempotentemente; o artefacto não é anunciado como disponível antes da confirmação.

## Persistência e auditoria exigidas

A implementação deve usar:
- tabela de jobs com identidade imutável, estado, proprietário, expiração, token, tentativas e digest do output;
- tabela normalizada de fontes com FKs para job, imagem e loja, e triggers de imutabilidade;
- tabela de eventos append-only com sequência por job, evento, token, worker e detalhes sem segredos;
- constraints para estados, modos, hashes, token e contadores;
- índices para claim de jobs e lookup por imagem;
- transacções curtas; nunca manter locks PostgreSQL durante o treino remoto.

## Testes de aceitação obrigatórios

1. Dois workers concorrentes reclamam um único job: exactamente um recebe o claim.
2. Um job expirado é reclamado por outro worker e o token aumenta exactamente uma vez.
3. O worker antigo falha heartbeat, conclusão e publicação depois do takeover.
4. Um lease expirado não pode ser renovado retroactivamente.
5. Hash, loja, estado de retenção ou legal hold divergentes bloqueiam enqueue/claim/heartbeat/conclusão.
6. Restrição concorrente durante execução bloqueia a conclusão; a leitura de artefactos após a restrição é negada pelo serviço de consumo.
7. Retry idempotente com o mesmo payload devolve o mesmo job; payload diferente é conflito.
8. Eventos e fontes rejeitam UPDATE/DELETE directo em PostgreSQL e SQLite.
9. O smoke PostgreSQL usa sessões independentes, observa locks reais e confirma ausência de dupla atribuição e de publicação com token obsoleto.

## Sequência de implementação

1. Migration e modelos de job, fontes e eventos append-only.
2. Serviço transaccional de enqueue/claim/heartbeat/finish/cancel com fencing.
3. Testes unitários e de contrato SQLite.
4. Smoke PostgreSQL de concorrência, takeover e retenção.
5. Adaptador de fila/worker apenas depois de o contrato anterior passar CI.
6. Publicação/staging e catálogo de outputs ligados ao registo de artefactos e à retenção.

Não implementar um broker ou integração cloud antes dos passos 1–4. Não definir duração de retenção nem activar purge físico nesta fase.


## Implementação persistente inicial — migration 0056

Foi acrescentada a primeira camada executável do contrato:
- `dataset_execution_jobs`: identidade idempotente, hashes de release/aprovação/pedido, estado, proprietário/expiração, fencing token, tentativas e metadados de output em staging.
- `dataset_execution_job_sources`: lista imutável de imagens internas, loja esperada e SHA-256, com FKs RESTRICT e trigger que valida a linhagem e estado ACTIVE/no legal hold na inserção.
- `dataset_execution_job_events`: eventos com sequência por job, append-only.
- `app.dataset_job_leases`: enqueue, claim `SKIP LOCKED`, heartbeat, fail e complete. Claim/heartbeat/complete revalidam as fontes e mantêm locks apenas durante a transacção curta.

A implementação ainda não é um worker. O campo `staged_output_reference` regista a referência declarada pelo worker; não executa a promoção. Um consumidor que tenha perdido o lease pode continuar a calcular ou a ler cópias locais; este serviço apenas impede que o token obsoleto renove ou conclua o job. O serviço de leitura por artefacto e o promotor fenced continuam necessários.

**Compatibilidade e validação (commit `0d9140e`):** migration e triggers aplicadas com sucesso em PostgreSQL 16. O smoke `postgres_dataset_job_lease_smoke.py` passou no API CI [44416138879](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138879): dois workers concorrentes produziram exactamente um claim; takeover após expiração incrementou o fencing token; heartbeat e conclusão com token obsoleto foram rejeitados; fonte restringida foi revogada e a sequência append-only foi confirmada. A suite API passou com **1177 passed, 1 skipped, 1 warning**. Quality Gates [44416138669](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138669) e Docker Compose [44416138628](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138628) passaram. Esta evidência valida a persistência e o protocolo de lease, não um worker de treino remoto nem a publicação externa de outputs.


## Guards adicionais na base de dados — migration 0057

A migration `0057_dataset_execution_fencing_guards` reforça o contrato ao nível SQL:

- claim inicial: `fencing_token` e `attempt_count` incrementam exactamente uma unidade;
- heartbeat: só é permitido antes da expiração, com o mesmo proprietário/token, sem diminuir `lease_expires_at` e sem alterar o contador de tentativas;
- takeover: exige lease anterior expirado, novo proprietário e incremento exacto do token e tentativas;
- sucesso/falha: exigem lease anterior ainda válido e counters inalterados;
- estado terminal: exige `finished_at`; sucesso exige `output_sha256` e `staged_output_reference`;
- eventos: sequência consecutiva protegida por lock da linha do job; após terminalidade só é aceite o evento terminal correspondente, uma única vez.

O serviço de heartbeat preserva a expiração anterior se o pedido de renovação tiver duração inferior. O smoke PostgreSQL usa expiração natural para testar takeover e tenta, por SQL directo, encurtar o lease e inserir uma sequência descontínua; ambas as operações são rejeitadas.

**Validação:** commit `93704d6b5f7262ec20befc6dc17ee4f1c80efb78`; API CI [44419928230](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928230), Quality Gates [44419928281](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928281) e Docker Compose [44419928382](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928382) passaram. A suite API teve 1179 testes aprovados, 1 ignorado e 1 aviso.

Estes guards não autenticam o worker, não impedem que um processo obsoleto continue a ler bytes já copiados localmente e não promovem outputs do staging para um destino final. Essas garantias exigem, respectivamente, autenticação do worker, serviço de leitura controlada por chamada e promotor de outputs que valide o fencing token actual.


## Máquina de estados imposta pela base de dados — migration 0058

A migration `0058_dataset_execution_state_machine` materializa as transições já definidas na tabela de estados e impede que código SQL directo contorne o serviço:

- `QUEUED → LEASED`: claim inicial com owner, lease futuro e incremento exacto de token/tentativas.
- `QUEUED → REVOKED/CANCELLED`: terminação sem lease activo e sem alterar os counters.
- `LEASED → LEASED`: heartbeat do mesmo owner/token sem encurtar o lease, ou takeover após expiração com novo owner e incremento exacto.
- `LEASED → SUCCEEDED/FAILED/REVOKED/CANCELLED`: terminação com lease limpo, counters inalterados e `finished_at`; sucesso/falha exigem lease ainda válido, enquanto revogação pode ocorrer após expiração quando a elegibilidade da fonte falha.
- Estados terminais não aceitam UPDATE; a identidade do job (ID, idempotency key, hashes, modo e `created_at`) é imutável.

A trigger PostgreSQL e a trigger SQLite cobrem a mesma máquina de estados. Os testes de migration exercitam transições ilegais e alterações à identidade; o smoke PostgreSQL tenta mutar um job activo e reabrir um job concluído. A validação runtime da migration 0058 permanece pendente até os workflows CI desta revisão terminarem.


## Validação do estado inicial dos jobs — migration 0059 (19-11-2026)

A migration `0059_dataset_execution_initial_state` foi validada em PostgreSQL 16 pelo API CI [44428496117](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496117). A cobertura SQLite e o smoke PostgreSQL tentam individualmente inserir jobs `QUEUED` com proprietário/expiração de lease, fencing token, contador de tentativas, digest/output, referência staging, falha ou timestamp terminal. A primeira versão dos testes continha colunas duplicadas nas tentativas de alterar os counters; a correcção constrói dinamicamente a lista de colunas e valores e foi validada com **1179 testes aprovados, 1 ignorado e 1 aviso**. Quality Gates [44428496156](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496156) e Docker Compose [44428496204](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496204) também passaram.

A validação confirma o estado inicial dos registos e os guards de lease/fencing. **Não autentica workers**: `worker_id` continua a ser um identificador declarado pelo chamador do serviço interno. Não existem endpoints públicos de jobs, e devem continuar ausentes até existir identidade de serviço, credenciais individuais, autorização por scope, expiração/rotação/revogação e testes de replay.


## Autenticação individual dos workers — migration 0060

A migration `0060_dataset_worker_credentials` acrescenta identidades de serviço separadas das contas humanas. Cada worker recebe uma credencial bearer individual com identificador público, segredo aleatório de 256 bits, SHA-256 persistido, scopes explícitos, validade, revogação e ligação de rotação. A base de dados também mantém eventos de segurança append-only para registo, emissão, rotação, revogação e desativação.

O módulo `app.dataset_worker_credentials` autentica a credencial, valida o estado do worker e a expiração, compara hashes em tempo constante e devolve um principal cujo `worker_id` provém do registo autenticado. Wrappers para claim, heartbeat, complete e fail aplicam scopes e usam apenas a identidade do principal. O CLI `python -m app.dataset_worker_admin` permite provisionamento, rotação, revogação e desativação local; não foi criado endpoint público de emissão.

**Limites importantes:** a integração HTTP ainda não existe e os endpoints de jobs continuam fechados. A credencial é bearer reutilizável: ainda não existe assinatura por pedido, nonce ou prevenção de replay. `artifacts:read` e `outputs:publish` são scopes reservados até existirem o serviço de leitura por chamada e o promotor fenced. Ver [Autenticação de workers de datasets](../security/dataset-worker-authentication.md). A validação PostgreSQL/CI desta migration e do smoke de imutabilidade foi concluída no commit `d7c84125d35a5fff5d2254a3ee33a08cd41edcc7`; ver os resultados e limites na secção de guards SQL abaixo.

### Guards SQL de credenciais e identidade do worker — validados

Além dos hashes e scopes verificados pelo serviço, a migration 0060 impede alterações SQL directas à identidade, segredo, scopes e validade das credenciais; proíbe a eliminação de credenciais; torna a revogação unidireccional; mantém `last_used_at` monotónico; impede reativar workers desativados; e mantém eventos append-only em PostgreSQL e SQLite. A suite inclui um contrato de migration SQLite e o API CI inclui um smoke PostgreSQL de rotação, revogação, desativação e tentativas de adulteração.

**Validação no commit de código `d7c84125d35a5fff5d2254a3ee33a08cd41edcc7`:** [API CI 44431378398](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378398), [Quality Gates 44431378324](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378324) e [Docker Compose 44431378349](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378349) passaram; suite API com 1202 testes aprovados, 1 ignorado e 1 aviso.

A autenticação ainda não está ligada a endpoints HTTP, e o bearer token ainda não tem assinatura por pedido/nonce. Não expor rotas de jobs até essas duas lacunas e a autorização de leitura/publicação estarem resolvidas.


## Autenticação de pedidos de workers — migration 0061

A camada de credenciais individuais foi complementada por `app.dataset_worker_http.require_dataset_worker(scope)`. A dependência valida bearer, timestamp (±60 s), nonce, assinatura HMAC-SHA-256, método, request-target exacto e hash do corpo. A migration `0061_dataset_worker_request_nonces` persiste o digest do nonce com unicidade por credencial e expiração de 121 s. A transacção de consumo do nonce é confirmada antes da execução do handler.

O smoke PostgreSQL usa duas sessões independentes e a mesma assinatura/nonce; o resultado exigido é uma única aceitação e uma rejeição de replay. Validação concluída no API CI [44471171581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171581), juntamente com Quality Gates [44471171526](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171526) e Docker Compose [44471171533](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171533); a suite terminou com 1211 passed, 1 skipped e 1 warning.

A dependência ainda não está ligada a rotas de jobs reais. As futuras rotas devem ficar fora do prefixo `/api/v1` da autenticação humana e aplicar o scope correspondente em cada handler. A leitura autorizada de artefactos, promoção fenced e worker remoto continuam pendentes.


## Leitura de fontes de treino — migration 0062

O serviço `app.dataset_job_artifact_reads.read_dataset_job_source_bytes` implementa a operação de leitura interna autorizada. Exige `artifacts:read`, job lease actual, worker autenticado e fencing token. A origem tem de pertencer ao conjunto imutável do job. O serviço bloqueia job e hierarquia imagem/prateleira/zona, confirma loja/retention/legal hold, revalida credencial e scope, lê com descritores de directório/`O_NOFOLLOW`, confirma tamanho e SHA-256 e devolve apenas bytes em memória.

Cada leitura cria um registo append-only em `dataset_execution_job_artifact_reads`. Triggers PostgreSQL/SQLite validam lease, owner, fencing token, fonte, loja, hash, retenção, worker/credencial e scope; UPDATE/DELETE são proibidos. O smoke PostgreSQL confirmou serialização com uma restrição de retenção concorrente e ausência de auditoria de sucesso para a leitura recusada.

As operações de claim, heartbeat, complete e fail também voltam a validar worker, credencial e scopes na operação. Validação final no API CI [44473560217](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560217), Quality Gates [44473560287](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560287) e Docker Compose [44473560252](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560252); 1223 testes aprovados, 1 ignorado e 1 aviso.

O serviço não está ainda exposto por endpoint HTTP. Promoção de outputs com fencing, broker e worker remoto continuam por implementar.


## Promoção de outputs — migration 0063

A migration `0063_dataset_job_output_publications` cria uma tabela append-only por job, ligada ao worker e à credencial que publicam. O registo fixa fencing token, SHA-256, referência de staging, destino final, número de bytes e timestamp. Triggers PostgreSQL/SQLite validam o job `SUCCEEDED`, o digest e a referência persistidos, o fencing token actual, o evento terminal `SUCCEEDED` do mesmo worker/token e a credencial activa com `outputs:publish`. UPDATE e DELETE são rejeitados.

O serviço `app.dataset_job_output_publications.promote_dataset_job_output` não aceita `worker_id` separado: deriva a identidade do principal autenticado. Revalida a credencial e o scope persistido dentro da transacção. A referência de staging tem de começar por `staging/{job_id}/{fencing_token}/`; caminhos não canónicos, traversal e symlinks são recusados.

O ficheiro é aberto por descritores de directório com `O_NOFOLLOW`, copiado para um temporário privado e verificado por tamanho e SHA-256. A publicação usa hard link atómico sem sobrescrita para `published/{job_id}/{fencing_token}-{sha256}.artifact`. A referência final é determinística. Se o processo terminar depois da criação do destino mas antes do commit SQL, uma repetição verifica o digest do destino e conclui o registo de auditoria. A remoção do staging ocorre após a promoção bem-sucedida.

**Validação:** API CI [44480661837](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661837) — migration PostgreSQL 16, smoke de duas sessões concorrentes e **1231 passed, 1 skipped, 1 warning**; Quality Gates [44480661851](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661851) e Docker Compose [44480661813](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661813) passaram.

**Limitações:** filesystem local apenas; não existe adapter de object storage, catálogo de outputs com herança de retenção/legal hold, limpeza automática de temporários órfãos após crash, endpoint HTTP de jobs, broker ou worker remoto. A cópia e promoção continuam limitadas pelo `MAX_DATASET_OUTPUT_BYTES` e devem ser monitorizadas antes de workloads grandes.