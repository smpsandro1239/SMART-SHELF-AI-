# Ciclo de vida, retenção e eliminação de imagens

## Estado

Implementação parcial. As migrações `0023_shelf_image_retention_metadata` e `0024_shelf_image_retention_events` (inclui triggers de imutabilidade no PostgreSQL/SQLite) introduzem metadados e auditoria append-only, protegida por triggers contra UPDATE/DELETE em PostgreSQL e SQLite. Existem endpoints de restrição/restauro, consulta de eventos e bloqueio de acesso/worker para imagens não ativas. O worker volta a verificar o estado de retenção imediatamente após a inferência e antes de iniciar OCR ou persistir deteções; se a imagem tiver sido restringida durante a inferência, aborta a fase derivada, descarta os resultados e marca a análise como falhada. O worker também resolve o caminho do ficheiro contra o diretório da loja proprietária, rejeitando caminhos externos, traversal, symlinks no ficheiro, no diretório da loja e em diretórios intermédios antes de chamar o provider de visão. As regressões `test_worker_rejects_image_path_outside_owning_store_directory` e `test_worker_rejects_symlinked_image_file` cobrem caminhos externos e symlinks. As regressões para caminhos externos e symlinks e para estados não ativos (`RESTRICTED`, `PENDING_PURGE`, `PURGED`) passaram no Quality Gates `43415274889` (681 testes). O API CI `43415274873` também passou integralmente, incluindo migrações, smoke PostgreSQL de ciclo de vida/concorrência/reconciliação e suite pytest. O teste `test_worker_stops_before_ocr_when_image_is_restricted_during_inference` passou no API CI `43413405704` e Quality Gates `43413405691`. O histórico de revisões por deteção e os relatórios de avaliação SKU também excluem imagens restritas; as imagens restritas não são elegíveis para candidatos de treino, fila de revisão nem contadores agregados da fila; `test_restricted_image_is_removed_from_review_queue_and_summary` validou esta fronteira no API CI run `43406526808` e Quality Gates run `43406526859`. O estado inicial é `ACTIVE`. **Ainda não existem pedidos de purga agendada, worker de purga física nem política de retenção aprovada.** A gestão operacional de legal hold foi acrescentada: aplicação e libertação exclusivas de ADMIN, motivo obrigatório e eventos append-only; o hold não altera o estado operacional da imagem nem ativa purga. A matriz JWT também cobre retenção: EMPLOYEE não consulta histórico nem restringe imagens; SUPERVISOR não aplica/liberta legal hold nem consulta/restringe imagens de outra loja, mas pode restringir uma imagem da sua loja com evento de auditoria. Os testes `test_employee_cannot_read_or_mutate_shelf_image_retention`, `test_supervisor_cannot_apply_or_release_legal_hold`, `test_supervisor_cannot_access_foreign_store_retention_history_or_restrict_image` e `test_supervisor_can_restrict_image_in_own_store_with_audit_event` passaram no Quality Gates `43415636103` (685 testes). A migração, os triggers append-only e o smoke PostgreSQL foram validados no API CI run `43401542425`. Foi também reforçada a fronteira de embeddings: exemplares associados a imagens não ativas são excluídos da listagem e do registo de matching, e criação/revisão de exemplares rejeitam imagens restritas; o teste `test_restricted_source_image_blocks_embedding_exemplar_access_and_matching` passou no API CI run `43405896953` e no Quality Gates run `43405955454`.

## Validação CI mais recente

O commit `4559365` passou no API CI `43456601696` e no Quality Gates `43456602071`. A validação inclui também o gate dinâmico de autenticação de todas as rotas versionadas, a compilação Python e o build TypeScript/Vite. O commit `23155bce` e os respetivos workflows anteriores continuam no histórico como validação de funcionalidades de retenção e concorrência. A execução inclui a suite de testes de worker, incluindo rejeição de caminhos externos e symlinks, exclusão de estados não ativos e corrida entre inferência e restrição da imagem, além das migrações PostgreSQL 16 e dos smoke tests de concorrência. Esta validação não cobre purga física, porque essa funcionalidade continua intencionalmente desativada.


### Regressões de autorização e legal hold

A cobertura JWT foi reforçada para verificar que um SUPERVISOR não consegue consultar o histórico, restringir nem restaurar uma imagem pertencente a outra loja. O teste confirma, através de ADMIN, que as tentativas cross-store não acrescentam eventos nem alteram o histórico. Foi também acrescentado um teste de ciclo de vida do legal hold por ADMIN: aplicar e libertar duas vezes é idempotente, mantém a imagem operacionalmente `ACTIVE` e produz exatamente um evento `LEGAL_HOLD_APPLIED` e um `LEGAL_HOLD_RELEASED`, com motivos normalizados. Os testes de autorização cross-store e idempotência do legal hold passaram no API CI [43578500510](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43578500510) e no Quality Gates [43578515611](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43578515611). A suite terminou com 750 testes aprovados e 1 ignorado. Foi acrescentada uma regressão adicional para provar que SUPERVISOR também não consegue restaurar uma imagem restrita da própria loja; essa nova regressão aguarda CI.

## Objetivos e invariantes

- Aplicar minimização e limitação da conservação: conservar a imagem apenas pelo período e finalidade aprovados pela organização.
- Separar ocultação operacional, eliminação do ficheiro binário e eliminação de evidência derivada.
- Preservar a rastreabilidade necessária a revisões, auditoria, investigação de incidentes e obrigações legais.
- Impedir acesso cross-store e impedir que uma referência de armazenamento alcance ficheiros fora da raiz configurada e do diretório da loja.
- Não inferir que uma fotografia de prateleira está livre de dados pessoais. A captura deve minimizar pessoas e áreas não necessárias; a retenção requer avaliação de privacidade e aprovação do responsável competente.

## Dependências existentes

Uma linha `shelf_images` é referenciada por:

- `shelf_image_detections` — deteções de visão;
- `shelf_image_ocr_runs` — execuções OCR;
- `product_embedding_exemplars.shelf_image_id` — exemplar de embedding, com `ON DELETE SET NULL`.

As deteções são referenciadas por:

- `detection_sku_reviews` — decisões humanas;
- `shelf_image_ocr_evidence` — evidência OCR, com `ON DELETE SET NULL` para a deteção;
- `shelf_image_ocr_matches` — matching OCR;
- `shelf_image_fused_evidence` — fusão visual/OCR.

As execuções OCR são referenciadas por evidência, matches e fusões. As relações atuais usam várias regras `ON DELETE CASCADE`; apagar fisicamente uma imagem pode, portanto, apagar histórico técnico e decisões humanas. A eliminação física direta não deve ser exposta como operação normal.

## Ciclo de vida proposto

1. **ACTIVE** — imagem visível e elegível para análise conforme permissões e estado operacional.
2. **RESTRICTED** — acesso operacional bloqueado enquanto existe pedido de eliminação, incidente, revisão ou retenção legal; o binário não é servido por endpoints normais.
3. **PENDING_PURGE** — pedido aprovado e elegível para purga após período de segurança configurado; não permite novas análises nem retry.
4. **PURGED** — binário removido e metadados identificadores minimizados conforme política aprovada; manter apenas recibo de purga não reversível quando necessário.

A transição deve ser explícita, auditada, idempotente e autorizada. A purga não deve começar enquanto a análise estiver `PROCESSING`, enquanto existir uma operação dependente em curso ou enquanto uma retenção legal estiver ativa.

## Política de retenção

- Não fixar um prazo universal no código. O prazo depende da finalidade, enquadramento jurídico, contrato e política da loja.
- Antes de ativar o piloto, definir por escrito prazo por categoria de imagem, evento que inicia a contagem, exceções, retenção legal, responsável e processo de revisão.
- Tornar o prazo configurável por ambiente/loja, com limites validados e registo da versão da política aplicada a cada decisão.
- Separar a retenção do binário da retenção de métricas agregadas e de evidência técnica. A conservação de metadados derivados também exige finalidade e prazo definidos.
- Não usar imagens para treino ou dataset apenas porque continuam armazenadas; exigir autorização, proveniência e processo de release próprios.

## Requisitos de implementação da purga

- Usar um worker/job separado da API de pedidos, com lote limitado, reexecução segura e métricas.
- Revalidar autorização, loja, estado, prazo e retenção legal imediatamente antes da operação.
- Resolver o caminho real sob a raiz configurada e diretório da loja; rejeitar traversal, symlinks e ficheiros fora do âmbito.
- Evitar corrida entre validação e remoção: abrir/operar com diretório controlado, permissões restritas e estratégia resistente a troca de symlink (por exemplo, operações baseadas em descritores de diretório quando suportadas).
- Remover primeiro o binário de forma idempotente e registar o resultado. Não apagar metadados de evidência em cascata sem uma política de preservação aprovada.
- Se a remoção do ficheiro falhar, manter estado recuperável e registar erro; não declarar a imagem purgada.
- Se o ficheiro já não existir, tratar como resultado idempotente, mas registar que estava ausente.
- Garantir que backups, réplicas, caches e exports têm prazos próprios e que a eliminação neles é tratada pela política de backup; apagar o ficheiro principal não elimina cópias.
- Emitir evento de auditoria com ator ou identidade do job, motivo, política/versão, timestamps, resultado e identificador técnico não reversível. Não incluir o conteúdo da imagem nem dados pessoais desnecessários no evento.

## Critérios mínimos de aceitação

- Um utilizador de outra loja não consegue consultar, restringir ou purgar a imagem.
- Um EMPLOYEE não consegue executar ações administrativas de retenção.
- Uma imagem em processamento ou sob retenção legal não pode ser purgada.
- Uma repetição do job não causa erro nem apaga recursos não relacionados.
- Traversal, symlink e caminhos de outra loja são rejeitados.
- Falha de I/O deixa estado recuperável, não marca falsamente como purgado e permite retry auditado.
- Evidência OCR, deteções, revisões humanas e exemplares derivados seguem a política definida, sem cascatas acidentais.
- Testes de integração PostgreSQL verificam concorrência entre pedido de retenção, worker e análise.
- Testes verificam que os endpoints de listagem, conteúdo, retry, OCR, matching e fusão respeitam o estado de retenção.

## Sequência de implementação

1. [x] Adicionar estados, timestamps e metadados de retenção (`0023_shelf_image_retention_metadata`).
2. [x] Implementar restrição/restauro, eventos append-only, bloqueio dos endpoints de imagem e exclusão do worker (`0024_shelf_image_retention_events` e commits associados).
2.a. [x] Revalidar retenção após inferência e antes de OCR/persistência derivada; a regressão de corrida foi validada em API CI e Quality Gates em 2026-11-13.
3. [ ] Rever cobertura dos endpoints de imagem e garantir que filas, métricas agregadas e operações indiretas não expõem dados restritos. A cobertura de retenção cross-store e legal hold passou no API CI `43578500510` e Quality Gates `43578515611` (750 testes aprovados, 1 ignorado); a regressão adicional de restauro ADMIN-only na própria loja foi acrescentada depois e aguarda CI. O worker valida o caminho físico contra o diretório da loja e rejeita caminhos externos, traversal e symlinks no ficheiro, no diretório da loja e em diretórios intermédios antes da inferência. A cobertura dos symlinks de diretório foi acrescentada no commit `f7fc3cc` e passou no API CI `43457363760` e Quality Gates `43457363686`. A suite API desse commit passou, assim como as migrações e smoke tests PostgreSQL 16. A auditoria dos restantes endpoints e caminhos indiretos continua aberta.
4. [x] Adicionar gestão de legal hold: aplicação/libertação ADMIN-only, motivo obrigatório, bloqueio de hold em imagens purgadas e eventos append-only; não altera visibilidade nem elimina dados.
5. [ ] Adicionar pedido de purga com política configurável, proteção de caminhos e tratamento de falhas — apenas após aprovação formal da política.
6. [ ] Definir tratamento de evidência derivada e anonimização/minimização dos metadados após validação jurídica.
7. [ ] Testar em PostgreSQL 16, incluindo concorrência, rollback, falhas de filesystem e reexecução idempotente.

## Limitação

Este documento é uma especificação técnica inicial, não um parecer jurídico nem uma política de retenção aprovada. A duração e as condições de conservação têm de ser definidas pela organização com o responsável de proteção de dados e assessoria jurídica antes de ativar a funcionalidade.


## Proteção da proveniência dos exemplares de embedding

A FK histórica `product_embedding_exemplars.shelf_image_id` usa
`ON DELETE SET NULL`, porque o modelo também admite referências externas
licenciadas sem captura interna. Sem proteção adicional, uma eliminação direta
da linha de uma imagem interna poderia converter silenciosamente um exemplar
derivado numa referência sem origem, que o motor trata como referência externa.

A migração `0028_embedding_source_image_restrict` acrescenta uma proteção
ao nível da base de dados: a eliminação de uma linha `shelf_images` é
rejeitada enquanto existir um exemplar de embedding associado. A proteção é
implementada por trigger em PostgreSQL e SQLite e é exercitada pelo smoke
PostgreSQL `postgres_embedding_retention_smoke.py`.

Esta proteção preserva a proveniência; não elimina exemplares, não implementa
purga e não substitui uma política formal para binários, embeddings, evidência
derivada, backups e caches. A remoção deliberada de uma imagem com exemplares
associados permanece bloqueada até existir um fluxo de eliminação aprovado
que trate explicitamente todos os dados dependentes.


## Proteção da evidência visual e OCR

A auditoria identificou que `shelf_image_detections` e
`shelf_image_ocr_runs` também usavam `ON DELETE CASCADE` em relação à
imagem. Uma eliminação direta podia, por isso, remover deteções, revisões
humanas associadas, execuções OCR, regiões de texto, resultados de matching e
fusões de evidência.

A migração `0029_image_derived_evidence_restrict` alarga o trigger de
integridade: além dos exemplares de embeddings, bloqueia a eliminação da
imagem quando existem deteções ou execuções OCR. As relações dependentes
(matching OCR, regiões e fusões) ficam protegidas pela preservação das linhas
de deteção/execução que as sustentam. O smoke PostgreSQL
`postgres_embedding_retention_smoke.py` verifica que a tentativa de
eliminação não apaga a imagem, a deteção, a execução OCR nem a região de texto.

Esta proteção é uma barreira contra eliminação acidental e perda de
proveniência. Não define prazos, não elimina dados derivados e não substitui
uma política formal que trate separadamente binários, evidência, backups e
caches. A purga física continua desativada.


## Proteção da auditoria humana e dos resultados derivados

A proteção da imagem de origem não é suficiente se uma deteção ou execução OCR
puder ser apagada diretamente. As relações históricas usam cascatas que
podem remover revisões humanas, regiões OCR, resultados de matching e
fusões de evidência.

A migração `0030_detection_ocr_audit_restrict` acrescenta triggers para
rejeitar a eliminação de uma deteção quando existem revisões humanas,
associações OCR, resultados de matching ou fusões. Também rejeita a
eliminação de uma execução OCR quando existem regiões de texto, resultados
de matching ou fusões associados. O smoke PostgreSQL
`postgres_embedding_retention_smoke.py` verifica a preservação desses
registos perante tentativas diretas de eliminação.

Esta proteção cobre eliminações diretas e não constitui uma política de
retenção nem um fluxo de purga. A validação de concorrência específica destas
novas relações continua pendente; a validação funcional sequencial é
executada no smoke PostgreSQL 16.


## Imutabilidade da proveniência visual/OCR

A proteção contra eliminação dos registos-pai não impedia alterações ou
eliminações diretas nas próprias linhas de histórico. A migração
`0031_visual_ocr_evidence_append_only` instala triggers de base de dados
para rejeitar `UPDATE` e `DELETE` em revisões humanas de SKU, execuções OCR,
regiões OCR, resultados de matching e fusões visuais/OCR.

O smoke PostgreSQL `postgres_embedding_retention_smoke.py` exercita ambas as
operações nas cinco tabelas e confirma que os valores e registos originais
permanecem. Esta proteção é uma regra de imutabilidade, não um mecanismo de
purga ou anonimização. A validação CI da migração e do smoke permanece
pendente.


## Serialização das operações OCR com a retenção

As operações HTTP que criam evidência derivada ou alteram o estado de análise têm de disputar o mesmo bloqueio de linha da imagem que a operação de restrição. Os handlers de criação de execuções OCR, matching OCR manual e retry obtêm `SELECT FOR UPDATE`, refrescam o registo e só depois validam `ACTIVE`. A fusão visual/OCR adquire igualmente o bloqueio antes de persistir resultados e revalida o estado. A revisão humana já seguia a ordem imagem → produto e refrescava a deteção depois do bloqueio.

O smoke `postgres_embedding_retention_smoke.py` acrescenta uma corrida real entre uma transação que bloqueia/restringe a imagem e o endpoint de matching OCR manual. O teste observa o pedido bloqueado em `pg_stat_activity`/ `pg_blocking_pids`, confirma que não termina antes do commit de retenção e exige HTTP 410 após a imagem ficar `RESTRICTED`, sem novos matches. API CI [43710660312](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43710660312) e Quality Gates [43710660309](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43710660309) passaram, com 778 testes aprovados e 1 ignorado.

Esta prova cobre o matching OCR manual e não deve ser interpretada como prova concorrente individual de todos os handlers. As restantes rotas de escrita e os fluxos de exportação continuam na matriz de auditoria.

## Limite de retenção nos datasets COCO offline

Os utilitários `app.coco_dataset`, `app.coco_review` e `app.dataset_review` operam sobre ficheiros COCO e diretórios fornecidos por quem executa o comando. Validam estrutura, anotações, caminhos e registos de revisão, mas não consultam a base de dados operacional, não resolvem um `shelf_image_id`, não verificam a loja proprietária, o estado `ACTIVE/RESTRICTED` ou o legal hold. O campo de revisor do registo offline é texto fornecido no ficheiro e não uma identidade autenticada pela API.

Estes utilitários não estão ligados a treino automático nem constituem, por si, um processo de exportação das imagens da aplicação. Contudo, se forem usados com imagens provenientes das capturas SMART SHELF AI, não existe atualmente uma ligação técnica que propague uma restrição posterior aos ficheiros COCO, cópias, relatórios ou datasets externos. Antes de qualquer exportação/treino operacional, exigir um manifesto de proveniência que ligue cada imagem/crop à origem, loja e hash, mais uma verificação de elegibilidade no momento de exportação e de release. O tratamento de cópias, backups e caches permanece dependente de política formal aprovada; não implementar purga por inferência.


## Contrato de proveniência por imagem para datasets offline

O módulo `app.dataset_provenance` define um sidecar JSON versionado (`schema_version: 1`) que liga cada imagem do dataset ao manifesto SHA-256 através de `split`, `file_name` e `image_sha256`. O validador exige cobertura exata: entradas em falta, duplicadas, fora do manifesto ou com hash divergente bloqueiam a validação.

Cada entrada declara `source_type`:

- `internal`: exige `shelf_image_id`, `store_id` e `source_image_sha256`.
- `external`: exige `source_name`, `license`, `rights_reference` e `source_image_sha256`; não aceita IDs operacionais internos.

Todas as entradas declaram uma `purpose` e uma transformação. `original` exige que o hash do ficheiro corresponda ao hash da origem; `crop` e `derived` exigem hash do progenitor igual ao hash declarado da origem e uma descrição da operação. O contrato é um registo de declarações e hashes, não uma prova criptográfica de direitos, de identidade do revisor ou de correspondência com a base de dados.

**Limites atuais:** o sidecar é validado como utilitário offline e ainda não está ligado ao `dataset_approval`, ao exportador operacional ou à base de dados. Não verifica se uma imagem interna continua `ACTIVE), se existe legal hold, nem se a referência `store_id` corresponde ao `shelf_image_id`. Antes de treino/exportação operacional, é necessário integrar uma verificação autenticada na origem e no release, revalidando estado e legal hold, e definir a propagação de restrições a crops, cópias, relatórios, backups e caches. A purga física continua desativada.
