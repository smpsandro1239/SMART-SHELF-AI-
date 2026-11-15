# Auditoria de isolamento multi-loja — evidência derivada de imagens

**Estado:** auditoria parcial; não constitui aprovação de segurança para produção.

## Âmbito desta ronda

Foram revistos os handlers e as regras de autorização de:

- sessões de captura e upload de imagens;
- conteúdo binário, deteções, OCR, fusão de evidência e revisões humanas;
- fila de revisão e respetivos contadores;
- exemplares de embeddings e matching;
- candidatos de treino derivados de revisões humanas;
- relatório de avaliação SKU revisto por humanos;
- histórico e operações de retenção.

A análise considerou o middleware JWT, as regras por perfil, a resolução da loja através de prateleira/zona e os filtros aplicados às consultas.

## Regras de isolamento observadas

1. Um utilizador não ADMIN só pode consultar ou alterar recursos associados à sua loja.
2. O acesso ao conteúdo de uma imagem verifica a loja antes de verificar o estado de retenção.
3. Imagens que não estejam em estado `ACTIVE` não podem alimentar leitura operacional, revisão, matching ou curadoria de treino.
4. O catálogo de produtos é global por decisão arquitetural; a associação SKU–prateleira continua limitada pela loja.
5. Os endpoints de revisão de evidência e de gestão de datasets exigem perfil de supervisor ou administrador através do middleware.
6. A avaliação SKU aceita um filtro de loja para ADMIN; um SUPERVISOR fica limitado à própria loja e recebe 403 quando tenta indicar outra loja.
7. Candidatos de treino são filtrados pela loja da imagem de origem para utilizadores não ADMIN.

## Regressões adicionadas

O ficheiro `apps/api/tests/test_training_candidates.py` inclui agora testes de integração para:

- supervisor de outra loja não receber candidatos de treino;
- supervisor da loja de origem continuar a receber os seus candidatos;
- supervisor não conseguir consultar a avaliação SKU de uma loja estrangeira;
- supervisor não conseguir carregar imagens para prateleiras de outra loja, sem criar registo nem ficheiro;
- avaliação SKU sem filtro explícito usar automaticamente a loja do supervisor.

Os testes usam um ator de teste injetado no helper de resolução de utilizador. O middleware de autenticação é deliberadamente ignorado em `APP_ENV=test`; estes testes validam a autorização dentro dos handlers e não substituem testes HTTP com JWT real em ambiente de integração.

## Cobertura JWT dos caminhos OCR e revisão humana

Foram adicionados testes com tokens reais para confirmar:
- SUPERVISOR não consulta nem cria OCR para imagem de outra loja;
- SUPERVISOR não repete a análise nem revê deteções de imagem estrangeira;
- a imagem estrangeira de teste está em retenção RESTRICTED, e a resposta esperada é 403 por isolamento, não 410 por retenção;
- EMPLOYEE não inicia OCR nem cria decisões de revisão SKU.

Esta cobertura é complementar aos testes de handlers e não fecha a auditoria global: ainda é necessário rever todos os métodos/rotas, caminhos administrativos e execução indireta dos workers, bem como validar em PostgreSQL 16.

## Separação de funções na aprovação de exemplares

A revisão de embeddings passou a impedir a autoaprovação por SUPERVISOR. O criador recebe HTTP 403 ao tentar aprovar/rejeitar o próprio exemplar; um segundo SUPERVISOR da mesma loja pode rever e ADMIN mantém a capacidade de revisão. A regra é verificada por teste de regressão no handler. Esta salvaguarda reduz o risco de um único utilizador introduzir uma referência e torná-la elegível para matching sem revisão independente.

## Decisões e limitações

- Não foi alterada a política do catálogo global.
- Não foi introduzida purga física nem eliminação de evidência derivada.
- Não se considerou suficiente a análise estática para fechar a auditoria.
- A auditoria completa ainda requer cobertura de todos os endpoints, execução dos testes em PostgreSQL, revisão dos acessos administrativos e verificação do worker e de caminhos indiretos.
- Antes de produção, deve existir uma matriz explícita de permissões por método/rota/perfil e testes de integração com tokens reais para ADMIN, SUPERVISOR e EMPLOYEE.

## Critério para fechar a tarefa

A tarefa só pode ser marcada como concluída quando a matriz de rotas estiver coberta, os testes cross-store passarem em CI com PostgreSQL e não existirem caminhos indiretos que revelem dados de outra loja ou evidência com retenção restrita.


## Cobertura JWT adicional — leituras derivadas por EMPLOYEE

Foi acrescentado um teste HTTP com JWT real de EMPLOYEE da loja A para tentar ler recursos associados a uma imagem RESTRICTED da loja B. O teste exige 403 em conteúdo binário, deteções, OCR evidence/runs/matches, fusão de evidência e histórico de revisão da deteção. Isto fecha uma lacuna na cobertura HTTP dos caminhos de leitura que o middleware permite a EMPLOYEE para imagens da própria loja; o handler continua responsável por validar o âmbito da loja e o estado de retenção.

## Cobertura adicional de operações de armazém e importação

A matriz JWT cobre agora 13 caminhos de escrita reservados a SUPERVISOR/ADMIN que ainda não tinham uma verificação parametrizada explícita para EMPLOYEE: vendas diárias e CSV, vendas/tráfego horários e CSV, localizações, colocações, paletes, políticas e simulações de rotação e eventos de paletes. O teste verifica a rejeição 403 antes do handler. A validação por loja para SUPERVISOR continua a ser uma dimensão separada e não fica fechada por este teste.

## Cobertura JWT — isolamento de armazém por loja

Foi acrescentado um teste de integração HTTP com JWT real de SUPERVISOR da loja A. A cobertura tenta ler localizações, paletes e políticas de rotação da loja B e tenta criar localização, palete, política de rotação e simulação na loja B. Os sete pedidos devem ser rejeitados com HTTP 403 antes de qualquer leitura ou escrita do recurso estrangeiro. Os payloads de criação são válidos ao nível do esquema, evitando falsos positivos causados por erros de validação. A cobertura usa SQLite isolado no fixture JWT; a validação PostgreSQL de todos estes endpoints continua pendente.

## Validação CI da cobertura JWT de armazém

A cobertura JWT de isolamento multi-loja para localizações, paletes e políticas/simulação de rotação foi validada no commit `4b0a023ca7996864c4dfc40dc3703a067785bc4f`: API CI `43468474493` e Quality Gates `43468474322` passaram, com **746 testes aprovados e 1 ignorado**. Os sete pedidos HTTP usam SQLite no fixture de autenticação; o smoke PostgreSQL valida outros fluxos operacionais, não estes sete endpoints individualmente. A auditoria multi-loja permanece parcial.

## Cobertura JWT — inventário e operações de armazém

A cobertura cross-store por JWT foi estendida a snapshots de inventário (listagem, último snapshot e criação), políticas de frescura (consulta e upsert), colocações em localizações e recomendações de slotting. O supervisor da loja A tenta aceder a recursos explicitamente associados à loja B e todos os sete pedidos devem receber 403. O fixture contém uma localização real da loja B para evitar validar apenas identificadores inexistentes. O teste HTTP usa SQLite; a validação PostgreSQL destes handlers, em particular a persistência e concorrência, continua separada.

## Cobertura adicional de retenção e legal hold (novembro de 2026)

A suite JWT foi ampliada com duas verificações complementares:

- Um SUPERVISOR da loja A não pode consultar o histórico, restringir nem restaurar uma imagem da loja B. O teste consulta depois o histórico com ADMIN e confirma que as tentativas recusadas não acrescentaram eventos.
- ADMIN pode aplicar e libertar legal hold; repetir qualquer operação é idempotente, não duplica eventos e não altera o estado operacional `ACTIVE` da imagem. A cronologia deve conter exatamente um evento de aplicação e um de libertação, com os motivos originais normalizados.

Os testes de autorização cross-store e legal hold passaram no API CI [43578500510](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43578500510) e no Quality Gates [43578515611](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43578515611), com 750 testes aprovados e 1 ignorado. Foi acrescentado um caso complementar: SUPERVISOR não pode restaurar uma imagem restrita mesmo quando pertence à sua própria loja; este último teste aguarda CI. A tarefa de auditoria multi-loja permanece aberta até cobrir todos os caminhos administrativos, indiretos e de worker, com validação PostgreSQL onde exista persistência ou concorrência.


## Fronteira explícita de restauro ADMIN-only

O teste `test_supervisor_cannot_restore_restricted_image_even_in_own_store` cria uma imagem restrita por ADMIN e tenta restaurá-la com JWT de SUPERVISOR da mesma loja. A resposta esperada é HTTP 403 e a cronologia consultada por ADMIN tem de continuar a conter apenas o evento `RESTRICTED`. Esta verificação separa deliberadamente a autorização por perfil da autorização por loja, evitando atribuir a um bloqueio cross-store uma prova que, na realidade, decorre do papel ADMIN-only. O teste foi acrescentado no commit `a3fcd94` e aguarda CI.


## Cobertura JWT alargada — matching e persistência de evidência estrangeira

O teste `test_supervisor_jwt_cannot_access_foreign_ocr_or_retry_restricted_image` foi alargado para cobrir, com JWT real de SUPERVISOR da loja A, uma imagem RESTRICTED da loja B. A regressão exige HTTP 403 para:

- leitura de conteúdo binário, deteções, execuções/evidência/resultados OCR, fusão de evidência e histórico de revisão;
- criação de execuções OCR, matching OCR com persistência, fusão visual/OCR com persistência, repetição da análise e submissão de revisão humana.

O teste confirma ainda que uma listagem com filtro explícito para a prateleira estrangeira devolve uma lista vazia, sem revelar a existência da imagem. Antes e depois das tentativas, compara contagens de execuções OCR, evidência OCR, matches, evidência fundida e revisões humanas; nenhuma escrita recusada pode criar registos. A validação é HTTP/JWT sobre SQLite isolado; o smoke PostgreSQL existente valida outros fluxos, não estes handlers individualmente. A auditoria global mantém-se aberta.


## Matching de embeddings — serialização com retenção

A construção do registo de matching foi reforçada para bloquear, com
`SELECT FOR UPDATE`, cada imagem de origem associada a exemplares aprovados.
O estado `ACTIVE` é revalidado depois de adquirir os bloqueios e estes mantêm-se
até ao fim da transação do worker. A operação de restrição já bloqueia a mesma
linha de `shelf_images`, pelo que a restrição e a utilização do exemplar ficam
serializadas em PostgreSQL.

Foi acrescentado um teste de regressão que confirma que um exemplar ligado a
uma imagem ativa pode ser usado e deixa de ser elegível depois de a imagem passar
a `RESTRICTED`. Este teste é sequencial e usa SQLite; não prova a concorrência
real de bloqueios. Falta um teste concorrente PostgreSQL que intercale o
matching com a restrição e confirme a ordem de bloqueio e a ausência de uso
posterior à restrição.


### Prova de bloqueios em PostgreSQL 16

Foi acrescentado o smoke test `postgres_embedding_retention_smoke.py`, integrado
no API CI. Com duas sessões independentes, o teste observa o waiter de retenção
em `pg_stat_activity` e verifica `pg_blocking_pids`, confirmando que a
restrição aguarda o commit do matching que bloqueou a imagem de origem. Depois
confirma que a imagem fica `RESTRICTED` e que o registo reconstruído exclui o
exemplar. A cobertura é específica desta serialização; não representa uma
auditoria concorrente completa de todos os caminhos de dados derivados.


A prova concorrente de matching/retenção em PostgreSQL 16 passou no API CI `43589628653`, juntamente com os restantes smoke tests e 753 testes aprovados (1 ignorado). O Quality Gates `43589628597` também passou.


### Concorrência na aprovação de exemplares

A rota de revisão de embeddings bloqueia e refresca primeiro o exemplar e,
quando aplicável, bloqueia e refresca a imagem de origem antes de verificar
retenção e gravar a decisão. Isto impede atualizações perdidas entre revisores
e evita aprovar com base num estado de retenção obsoleto. O novo smoke test
PostgreSQL postgres_embedding_review_smoke.py disputa APPROVED/REJECTED em
duas sessões HTTP, esperando um único sucesso e um conflito 409.


### Elegibilidade por estado do catálogo

A revisão de exemplares valida o estado atual do produto sob bloqueio de linha.
Um produto desativado não pode receber novos exemplares nem aprovar referências
pendentes; estas podem ser rejeitadas para fechar a fila. O registo do worker
só inclui exemplares aprovados associados a produtos ativos, com bloqueio
transacional do catálogo durante o matching. A informação histórica é
preservada e não é apagada quando o produto é desativado.


### Revisão humana, fusão e histórico face a produtos desativados

A confirmação/correção humana exige um SKU ativo e serializa a validação com
desativação do catálogo e retenção da imagem. A fusão de evidências recém-gerada
não promove sugestões OCR/visuais que já apontem para produtos inativos: os
IDs inativos são removidos da decisão consolidada e o estado passa a
`UNKNOWN`. Os registos OCR/visuais de origem são preservados. Os relatórios de
avaliação usam a decisão humana e a previsão existentes no momento da revisão;
não filtram retroativamente produtos que tenham sido desativados depois.


## Upload positivo de imagem com JWT real — própria loja

Foi acrescentado `test_employee_can_upload_valid_image_to_own_store_capture_session` em `apps/api/tests/test_auth_middleware_jwt.py`. O teste usa JWT real de EMPLOYEE e executa o upload para uma prateleira e sessão de captura da própria loja. Exige HTTP 201 e verifica o nome original, MIME, tamanho, SHA-256, registo persistido, prateleira/sessão, utilizador que carregou, estado `ACTIVE`, conteúdo no diretório isolado da loja e presença da imagem na listagem autorizada. Este cenário complementa o teste negativo cross-store, que exige HTTP 403 e ausência de ficheiro/registo.

A validação passou no API CI [43598971758](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43598971758) e no Quality Gates [43598971764](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43598971764). O API CI concluiu com sucesso as migrações e smoke tests PostgreSQL 16 e a suite API; o Quality Gates concluiu com sucesso os testes API, compilação Python e build web. A auditoria global permanece parcial: este teste comprova o caminho positivo de upload para a própria loja, não a matriz completa de autorização nem os caminhos indiretos/worker.


## Rejeição de upload associado a sessão de captura de outra loja

Foi acrescentado `test_employee_cannot_upload_image_with_foreign_capture_session` em `apps/api/tests/test_auth_middleware_jwt.py`. O teste autentica um EMPLOYEE da loja A com JWT real, envia uma imagem válida para uma prateleira da loja A, mas associa uma sessão de captura da loja B. A API responde HTTP 422 e o teste confirma que não foi criado qualquer ficheiro nem aumentado o número de registos de imagem da prateleira de origem. Este cenário complementa os testes de upload autorizado na própria loja e de upload para prateleira estrangeira.

A validação passou no API CI [43600274027](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43600274027) e no Quality Gates [43600274038](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43600274038). A cobertura continua limitada a estes fluxos de upload; a auditoria global de autorização e dos caminhos indiretos permanece aberta.


## Sessões de captura — autorização positiva do SUPERVISOR

A cobertura JWT foi completada para o ciclo positivo de gestão de sessões na própria loja através de `test_supervisor_can_create_and_close_capture_session_in_own_store`. O teste cria uma sessão numa prateleira da loja A com token real de SUPERVISOR, verifica que a API atribui a sessão à loja e ao utilizador autenticado e fecha-a através do endpoint próprio. Confirma HTTP 201 na criação, HTTP 200 no fecho e persistência de `ended_at`, sem alterar o âmbito de loja nem o criador. Em conjunto com os testes existentes de acesso estrangeiro (403) e de bloqueio a EMPLOYEE (403), cobre os caminhos positivos e negativos do ciclo HTTP.

Validação concluída no API CI [43604700291](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43604700291) e Quality Gates [43604700289](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43604700289), ambos com conclusão `success`. A integração HTTP JWT usa SQLite isolado; não se afirma validação PostgreSQL individual do handler de sessões. A auditoria multi-loja global permanece aberta para os restantes endpoints, caminhos administrativos, workers e operações indiretas.


## Catálogo global e associações por loja — cobertura JWT

Foi acrescentado o teste `test_catalogue_is_global_but_shelf_product_assignments_are_store_scoped` à suite `apps/api/tests/test_auth_middleware_jwt.py`. Com JWT real, confirma que o catálogo de produtos é global para SUPERVISOR, enquanto as associações SKU–prateleira são filtradas pela loja do ator. O SUPERVISOR da loja A vê as três associações locais, não recebe associações ao filtrar pela prateleira da loja B, e ADMIN vê as quatro associações das duas lojas.

A execução do teste HTTP usa SQLite isolado. Não se afirma validação PostgreSQL individual deste endpoint. No mesmo commit, API CI [43608505591](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43608505591) e Quality Gates [43608505546](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43608505546) concluíram com sucesso; os smoke tests PostgreSQL existentes também passaram, sem substituir a validação específica do handler.

A auditoria permanece parcial: falta completar a revisão sistemática dos métodos/rotas administrativas, handlers e caminhos indiretos/worker, bem como validar em PostgreSQL os fluxos em que isso é aplicável.


## Metadados globais de embalagem — autorização de leitura

O endpoint `GET /api/v1/warehouse/product-packaging` expõe níveis de embalagem ativos associados ao catálogo global de produtos. O teste `test_product_packaging_read_is_global_for_supervisors_and_denied_to_employees`, com JWT real, confirma que SUPERVISOR e ADMIN recebem os mesmos metadados e que níveis inativos são excluídos; EMPLOYEE recebe HTTP 403. A distinção é intencional: embalagem define unidades logísticas do produto, enquanto localizações, colocações e paletes são recursos operacionais com âmbito de loja.

A validação passou no API CI [43609023974](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43609023974) e Quality Gates [43609023990](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43609023990), no commit `4cf0f34848cd2beab83d0b12db89888dbdd162d3`. O workflow API concluiu migrações e smoke tests PostgreSQL 16 e a suite completa; Quality Gates passou testes API, compilação Python e build web. A integração HTTP do teste usa SQLite isolado; não se afirma validação PostgreSQL individual deste endpoint.

A cobertura acrescentada não fecha a auditoria global de autorização, nem substitui a revisão de todas as rotas e caminhos indiretos.

## Candidatos de treino revistos — isolamento multi-loja

Foi acrescentado `test_reviewed_training_candidates_are_scoped_to_supervisor_store` à suite JWT HTTP. O teste cria decisões humanas elegíveis para deteções de duas lojas, ativa ambas as imagens e confirma que o SUPERVISOR da loja A recebe apenas o candidato da loja A, ADMIN recebe os dois e EMPLOYEE recebe HTTP 403. A preparação evita que a imagem local seja excluída por já possuir um exemplar de embedding, isolando assim o comportamento do endpoint de candidatos.

O teste foi publicado no commit `895adcee93699ab56b7bec202ce88d554593f214`. API CI [43668452686](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43668452686) e Quality Gates [43668471717](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/43668471717) passaram. O teste usa SQLite isolado e não representa validação PostgreSQL individual. A listagem de candidatos não inicia treino nem substitui a aprovação humana de exemplares. A auditoria global permanece aberta.

## Avaliação histórica de previsões SKU — controlo do âmbito do relatório

Foi acrescentado o teste JWT `test_reviewed_sku_evaluation_is_scoped_to_supervisor_store`. A rota força o âmbito da loja do SUPERVISOR, rejeita um `store_id` estrangeiro antes de invocar o agregador, permite ao ADMIN consultar explicitamente outra loja e bloqueia EMPLOYEE. O teste verifica também que a versão do modelo é transmitida ao serviço de avaliação.

O teste valida a autorização HTTP e o encaminhamento dos filtros, não a precisão do cálculo SQL; o agregador é substituído no teste. Commit `26f3afe93122a7539ca02dc1c718449b2da72c4d`; CI pendente. A auditoria multi-loja dos dados derivados de imagem continua aberta.

## Exemplares de embedding — isolamento multi-loja na listagem

Foi acrescentado `test_product_embedding_exemplar_listing_is_scoped_to_source_image_store` à suite JWT HTTP. O teste cria um exemplar elegível associado à imagem da loja B e confirma que o SUPERVISOR da loja A continua a ver apenas exemplares da loja A; ADMIN recebe ambos os âmbitos e EMPLOYEE recebe HTTP 403. A imagem estrangeira é explicitamente ativada, isolando o controlo multi-loja do controlo de retenção.

Commit `07f46a43c17a9f617aea8b55a242b3d3f7426106`. A validação CI está pendente; o teste usa SQLite isolado e não representa validação PostgreSQL individual do endpoint. A auditoria permanece aberta.



## Integridade da proveniência perante eliminação direta

A migração `0028_embedding_source_image_restrict` impediu a perda silenciosa
da relação entre imagens e exemplares de embeddings. A auditoria posterior
identificou outras relações em cascata: deteções e execuções OCR eram
eliminadas com a imagem, levando consigo revisões humanas, evidência OCR,
matching e fusões.

A migração `0029_image_derived_evidence_restrict` alarga a proteção ao nível
da base de dados. A eliminação de uma imagem é rejeitada quando existem
exemplares de embedding, deteções ou execuções OCR associados. A proteção é
aplicada em PostgreSQL e SQLite; o smoke PostgreSQL verifica a preservação
conjunta da imagem, deteção, execução OCR e texto reconhecido.

O estado `RESTRICTED` continua a ser a operação normal e reversível para
bloquear acesso/uso operacional. A proteção de DELETE não representa uma
implementação de purga nem autoriza apagar evidência. A auditoria da
proveniência de outros dados derivados e caminhos administrativos permanece
aberta.


## Integridade de revisões humanas e fusões visuais/OCR

A auditoria identificou que a eliminação direta de uma deteção podia apagar
o histórico append-only de revisão SKU, anular a associação de regiões OCR
e eliminar matching/fusão. A eliminação direta de uma execução OCR podia
apagar regiões de texto, matching e fusões.

A migração `0030_detection_ocr_audit_restrict` instala proteções de base de
dados para impedir essas eliminações quando existem registos dependentes.
O smoke PostgreSQL verifica que revisão humana, evidência OCR, matching e
fusão permanecem ligados à deteção e execução originais.

A proteção de eliminação direta não substitui a auditoria de concorrência
nem fecha a revisão dos caminhos administrativos/worker. A auditoria global
de dados derivados mantém-se aberta.
