# Governação de retenção dos outputs de jobs de datasets

## Estado

Decisão de arquitectura e auditoria concluídas. A elegibilidade fail-closed na promoção está implementada através do serviço e da migration 0064; a cobertura multi-origem passou no CI. A migration 0065 e o serviço interno de eventos append-only de governação estão agora implementados; a política de autorização por perfil/loja, a exposição HTTP, a integração de bloqueio em consumidores e a disposição física permanecem pendentes. Este documento não autoriza eliminação física nem define prazos comerciais ou legais de retenção.

## Contexto observado

A publicação de um output de job já tem identidade durável em `dataset_execution_job_output_publications`: job, worker, credencial, fencing token, SHA-256, referência de staging, referência publicada, tamanho e timestamp. A linha é append-only e a migration 0063 valida a publicação contra o evento terminal e a autoridade do worker.

O repositório também possui um catálogo de referências externas em `shelf_image_artifact_references`, mas esse catálogo é deliberadamente orientado a uma única imagem e loja. As suas referências são declarações administrativas, e os snapshots assinados de inventário são recolhidos por imagem/sistema externo. Não é correcto inserir um output de job multi-origem nesse catálogo como se tivesse uma única imagem progenitora, nem tratar uma declaração de referência como prova de inventário completo.

A linhagem de entrada do job já está persistida em `dataset_execution_job_sources`, com imagem, loja e SHA-256, e é protegida por constraints/triggers de imutabilidade. A publicação referencia o job, pelo que existe uma cadeia auditável entre output e fontes, mas ainda não existe uma política de retenção própria do output.

## Decisões

1. **Não duplicar o catálogo.** A linha append-only de `dataset_execution_job_output_publications` deve ser a identidade canónica do artefacto publicado. Não criar uma segunda tabela que volte a copiar hash, tamanho, caminho e identidade da publicação.
2. **Preservar linhagem multi-origem.** A governação deve resolver todas as fontes imutáveis do job, sem escolher arbitrariamente uma imagem. Se for criada uma relação materializada publicação-origem para consulta, deve ser uma projecção verificável das fontes do job, com FK/trigger que prove que cada fonte pertence ao mesmo job.
3. **Separar identidade, linhagem e disposição.** A publicação permanece imutável; restrições, legal holds, propostas, aprovações, cancelamentos e atestações devem ser eventos append-only próprios, nunca updates à publicação.
4. **Herdar restrições de todas as fontes.** Qualquer operação futura de leitura, exportação, cópia ou disposição do output tem de bloquear se uma fonte estiver inexistente, não estiver `ACTIVE`, tiver legal hold ou não puder ser validada. Os locks devem respeitar a ordem global existente e bloquear todas as imagens por ID crescente.
5. **Não inferir ausência a partir de inventário incompleto.** Backups, caches, réplicas, relatórios e cópias externas não podem ser considerados inexistentes por falta de registos. A cobertura externa tem de ser explicitamente atestada e verificada.
6. **Sem purga automática.** A idade do ficheiro, isoladamente, nunca é autorização para apagar. A purga física continua desactivada até existir política aprovada, inventário completo, aprovação independente, evidência de disposição e procedimento de recuperação.
7. **Compatibilidade de base de dados.** Qualquer extensão deve ter guards equivalentes em PostgreSQL e SQLite para constraints de linhagem, sequência de eventos e append-only. A validação concorrente real deve usar PostgreSQL 16 no CI.

## Modelo de implementação proposto

- Manter `dataset_execution_job_output_publications` como raiz canónica do output.
- Acrescentar uma migration incremental para eventos de governação do output, ligados por FK à publicação e com sequência monotónica por publicação. O vocabulário inicial deve distinguir, no mínimo, aplicação/libertação de legal hold e restrição/restauro; os eventos de disposição física só devem ser activados depois de aprovada a política.
- Cada evento deve identificar actor, motivo, timestamp e, quando aplicável, referência e SHA-256 de evidência. A autorização deve ser validada no serviço e novamente por guards SQL.
- Implementar uma função de elegibilidade fail-closed que bloqueie a publicação/consumo se qualquer fonte do job não puder ser revalidada. A avaliação informativa não deve ser apresentada como autorização para uma leitura posterior.
- Antes de expor endpoints ou workers remotos, ligar a verificação à operação efectiva de consumo/publicação dentro da mesma transacção protegida pelos locks.
- Criar testes SQLite para contrato/migration e smoke PostgreSQL para concorrência entre operações de consumo e restrição/hold, incluindo múltiplas fontes e tenants.

## Questões que não devem ser inventadas

- Prazo de retenção por tipo de output e finalidade.
- Quem pode aplicar, libertar ou aprovar legal hold no contexto dos outputs.
- Se a libertação de hold exige dois administradores distintos.
- Cobertura obrigatória de sistemas externos por loja/ambiente.
- Regras de retenção de backups, caches e réplicas, incluindo cópias imutáveis.
- Processo e evidência aceitável para destruição/anonimização.

Até estas decisões serem aprovadas, o comportamento seguro é preservar os outputs e bloquear qualquer operação destrutiva. O reconciliador actual continua limitado à limpeza de temporários que cumprem os seus critérios técnicos; não é um motor de retenção.


## Revalidação transaccional antes da promoção

A auditoria identificou que a elegibilidade era confirmada no enqueue, claim e conclusão do job, mas não na fronteira final de promoção. Uma restrição ou legal hold aplicado depois de `SUCCEEDED` e durante a preparação do output podia, portanto, não ser observado.

A implementação acrescenta uma revalidação final de todas as linhas `dataset_execution_job_sources`, confirmando a cadeia loja/imagem, o SHA-256 original, `retention_status = ACTIVE` e `legal_hold = false`. As imagens, prateleiras e zonas são bloqueadas por ID crescente até ao commit. A migration `0064_dataset_output_source_eligibility` replica a regra no INSERT SQL para evitar bypass do serviço. A publicação falha fechada e preserva o staging se uma fonte estiver inelegível.

A verificação não define prazos de retenção nem permite purga: limita-se a impedir a criação/publicação do derivado quando a origem já não é elegível. A validação PostgreSQL 16, a suite API, os Quality Gates e o Docker Compose passaram no commit `01abce944e7d883ea53aca17a09ac589701fdfc9`: [API CI 44516774051](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774051), [Quality Gates 44516774058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774058) e [Docker Compose 44516774048](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774048).


## Cobertura multi-origem acrescentada — 2026-11-19

Os testes de promoção passam a construir jobs com duas fontes internas, incluindo submissão deliberada fora da ordem crescente dos IDs. A segunda fonte é tornada `RESTRICTED` ou recebe legal hold durante a preparação, e a promoção tem de falhar sem publicar nem remover staging. O contrato SQLite da migration 0064 testa também uma publicação com uma fonte válida e outra restrita. O smoke PostgreSQL 16 usa duas fontes e aplica o hold concorrente à segunda. Esta extensão de cobertura passou no API CI [44516774051](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774051), incluindo o smoke PostgreSQL 16; Quality Gates [44516774058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774058) e Docker Compose [44516774048](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774048) também passaram. A suite terminou com 1241 testes aprovados, 1 ignorado e 1 aviso. A cobertura não altera a decisão de não permitir purga física sem política aprovada.


## Eventos append-only de governação — migration 0065

A migration `0065_dataset_output_governance_events` cria `dataset_execution_job_output_governance_events`, uma cronologia separada ligada por FK à publicação canónica. A publicação original não é alterada e não são duplicados hash, tamanho ou caminho do output.

O vocabulário inicial é limitado a quatro transições: `RESTRICTION_APPLIED`, `RESTRICTION_RELEASED`, `LEGAL_HOLD_APPLIED` e `LEGAL_HOLD_RELEASED`. Cada evento exige actor humano activo, motivo não vazio, sequência consecutiva por publicação e timestamp. A evidência externa é opcional, mas a referência e o SHA-256 têm de ser fornecidos em conjunto. O campo `details` aceita apenas um objecto JSON limitado a 16 KiB pelo serviço.

Os triggers PostgreSQL e SQLite serializam a sequência na linha da publicação, rejeitam transições duplicadas/ilegais e impedem UPDATE/DELETE. O serviço `app.dataset_output_governance.append_output_governance_event` bloqueia a publicação e o actor, exige um callback de autorização que devolva explicitamente `True`, valida motivo/evidência/metadados e deixa commit/rollback a cargo do chamador. `get_output_governance_state` reconstrói a projecção de restrição e legal hold a partir da sequência imutável.

**Limites deliberados:** não foi inventada uma matriz de permissões para restrição/libertação de outputs. O callback obrigatório é a fronteira de autorização para futuras integrações; não existe endpoint HTTP nem callback permissivo por omissão. A projecção ainda não está ligada ao serviço de leitura/publicação de bytes, porque não há consumidor HTTP/worker remoto de outputs. Não se implementou política temporal, aprovação independente, executor de disposição ou purga física. A migration e os testes SQLite/serviço passaram na suite; o smoke concorrente PostgreSQL 16 passou no API CI. Validação final no commit `b2247031a7d651a4efdc423f83bf7947723e27ff`: API CI [44519805058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44519805058) e Quality Gates [44519805055](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44519805055) passaram com **1244 passed, 1 skipped, 1 warning**; Docker Compose [44519805067](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44519805067) também passou.


## Fronteira de consumo dos outputs publicados

A leitura de bytes de uma publicação deve passar por `app.dataset_job_output_consumption.consume_dataset_job_output_bytes`. O serviço bloqueia a publicação e o job, exige callback de autorização estritamente positivo, verifica a projecção dos eventos de governação, valida todas as fontes internas do job sob locks ordenados e confirma a referência canónica, o ficheiro regular sem symlink, o tamanho e o SHA-256 antes de devolver os bytes.

A operação é síncrona e integral: não devolve streams nem referências diferidas. O caller controla a transacção e não deve libertar os locks antes de terminar o consumo. A ordem de locks desta fronteira começa pela publicação e pelo job, seguindo-se as imagens/prateleiras/zonas em ordem crescente. A governação de outputs também começa pela publicação, permitindo serializar uma restrição concorrente com uma leitura.

Esta implementação é uma fronteira de serviço, não uma integração de produto: não cria endpoints, downloads, exports, workers, broker ou autorização por perfil. Todos os consumidores futuros devem reutilizá-la. Cópias externas, caches, backups e derivados não estão abrangidos; purga física continua proibida até existir política aprovada.


### Verificação de integração PostgreSQL

O smoke PostgreSQL 16 exercita agora o serviço de consumo sobre uma publicação real: primeiro confirma a devolução dos bytes com autorização positiva; depois persiste uma restrição através da cronologia append-only e confirma que a leitura é recusada. A suite SQLite também cobre a tentativa de substituir o destino publicado por um symlink, preservando o ficheiro externo.
