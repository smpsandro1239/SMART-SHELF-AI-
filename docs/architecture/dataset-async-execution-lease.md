# Contrato de execução assíncrona de datasets: lease e fencing

## Estado

Desenho técnico aprovado para orientar a implementação. **Não existe ainda um executor remoto, uma fila de treino nem este contrato persistido em código.** O processo actualmente suportado continua a ser o consumidor local síncrono de `app.dataset_execution`.

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

**Compatibilidade e validação:** a migration e triggers suportam PostgreSQL e SQLite. O smoke PostgreSQL integrado no API CI prova a atribuição única e takeover; a suite de testes SQLite não substitui essa prova. A validação de runtime deste commit permanece pendente.
