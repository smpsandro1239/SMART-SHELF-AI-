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
