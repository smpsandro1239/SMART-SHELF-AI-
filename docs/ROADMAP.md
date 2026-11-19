### Reconciliação conservadora de outputs (2026-11-19)

- Implementado CLI manual com simulação por defeito e `--apply` explícito, período de segurança configurável (7 dias por omissão).
- Temporários privados antigos só são removidos se forem ficheiros regulares com nome interno esperado. Staging só é removido quando publicação append-only, job, token, digest e tamanho coincidem e o destino publicado foi revalidado.
- Jobs `SUCCEEDED` sem publicação, symlinks, caminhos desconhecidos, ficheiros recentes e conteúdos divergentes são preservados. Sem scheduler e sem suporte a object storage.
- Quality Gates [44484598129](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44484598129) e Docker Compose [44484598370](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44484598370) passaram; API CI [44484598295](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44484598295) passou, incluindo smokes PostgreSQL e suite API.
- Procedimento: [dataset-output-reconciliation.md](operations/dataset-output-reconciliation.md).

### Publicação de outputs — redução de locks (2026-11-19)

- A preparação/cópia/hash do output foi retirada da transacção com locks PostgreSQL; a autorização é revalidada sob locks imediatamente antes da publicação final.
- A secção crítica contém apenas o hard link no-clobber e o registo append-only. O staging é limpo após commit e a reconciliação de um destino criado antes de um crash verifica o digest fora dos locks.
- Teste de regressão cobre revogação durante a preparação e exige recusa sem publicação.
- Código integrado na `main`: `5767468ad8058a593474695b2cb0dee9ef3118e7`; documentação: `5e84a0cec8cc15ca829aa6eda1694d8013819858`.
- Validação concluída: API CI [44483199562](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44483199562), Quality Gates [44483436546](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44483436546) e Docker Compose [44483199541](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44483199541) passaram. A evidência é CI; não foram executados testes localmente.
- O smoke PostgreSQL dedicado confirma que a revogação faz commit numa segunda sessão enquanto a preparação está pausada e que a publicação é recusada na revalidação final. API CI [44485569053](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44485569053) passou.
- Próxima prioridade: reconciliador de temporários e staging órfãos; depois catálogo de outputs com herança de retenção/legal hold.

### Auditoria HTTP de integrações externas — percurso ADMIN (2026-11-18)

- Acrescentado teste JWT positivo para criação, listagem, consulta de cobertura e revogação de integrações externas por ADMIN.
- Verificado o isolamento entre lojas e a resposta 404 para tentativa de actualizar uma integração através do caminho de outra loja.
- Confirmado que a resposta não inclui campos de credenciais e que a alteração regista o utilizador ADMIN responsável.
- O teste usa SQLite isolado; validação CI pendente no commit desta ronda. A auditoria global de autorização permanece aberta.

# SMART SHELF AI — Roadmap

## Prioridade atual: preparar um piloto controlado com validação operacional e evidência

### Ronda em curso — 2026-11-18

- Reforçado o protocolo para leitura integral do README antes de cada ronda de desenvolvimento.
- Corrigida uma expectativa demasiado restritiva no smoke PostgreSQL do diretório de funcionários: a listagem global ADMIN pode incluir funcionários activos criados por outros smokes na base de CI partilhada.
- Aguardar API CI/PostgreSQL para validar a correcção. O run anterior `44308942806` falhou apenas na asserção de igualdade global do smoke; o Docker Compose smoke `44308942877` passou.
- A auditoria global de autorização por handler continua pendente.

### Estado de validação — 2026-11-18

- API CI [44271596288](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44271596288), commit `30f3b4e`: suite API e smokes PostgreSQL concluídos com sucesso, incluindo os novos testes de picking.
- Quality Gates [44271717562](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44271717562), commit `93abecc`: testes API/compilação Python e build TypeScript/produção Web concluídos com sucesso.
- Docker Compose smoke [44271596168](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44271596168), commit `30f3b4e`: build, arranque, readiness, seed e validação dos perfis aprovados.
- A ronda de picking está validada por CI; a auditoria de desempenho abaixo está preparada, mas ainda carece de planos obtidos em dados representativos. A preparação da auditoria de desempenho passou no API CI [44291136290](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291136290) (**1148 passed, 1 skipped, 1 warning**), Quality Gates [44291194461](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291194461) e Docker Compose [44291133419](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291133419).

### Ronda adicional — integridade do picking (2026-11-18)

- O planeador exclui todas as linhas quando a entrada contém duplicados para o mesmo SKU/localização, impedindo dupla contagem de stock. A mesma localização para SKUs diferentes continua válida.
- Testes de regressão e validação CI concluídos: API CI `44271596288`, Quality Gates `44271717562` e Docker Compose smoke `44271596168` passaram.

### Preparação da auditoria de desempenho — 2026-11-18

- [x] Criar script read-only para planos das consultas de imagens, deteções, OCR, retenção e fila de revisão SKU, com timeout e validação de loja/imagem.
- [x] Acrescentar testes unitários aos SELECTs limitados e à validação de IDs.
- [x] Documentar execução, segurança e critérios de interpretação em [PERFORMANCE-QUERY-AUDIT.md](PERFORMANCE-QUERY-AUDIT.md).
- [ ] Executar em staging/réplica com volume representativo; nenhuma decisão de índice deve ser tomada antes dessa evidência.

- [x] Usar botão HTML nativo nos cartões de resumo de zona e anunciar o carregamento da avaliação operacional através de uma região de estado acessível.
- [x] Web CI [44296222519](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44296222519) passou; Quality Gates [44296524262](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44296524262) passou com testes API/compilação Python e build Web/TypeScript aprovados no commit `897d6946d0641ee8201cd14c7df8549c60c55a9b`.
### Acessibilidade e navegação responsiva — 2026-11-18

- [x] Corrigir semântica dos cartões de zona com botão nativo e anunciar o carregamento da avaliação operacional; Quality Gates [44296524262](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44296524262) passou no commit `897d6946d0641ee8201cd14c7df8549c60c55a9b`.

- [x] Adicionar skip link para o conteúdo principal e landmark de navegação com nome acessível.
- [x] Disponibilizar navegação equivalente em ecrãs pequenos, onde a barra lateral deixa de estar visível.
- [x] Reforçar indicadores de foco visível e anúncio do estado inicial de carregamento.
- [x] Validar Web CI [44292103581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44292103581) e Quality Gates [44292103676](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44292103676), ambos aprovados no commit `5ca7babcd3529f4459a50eaf5542aa289db91d05`.
- [ ] Validar manualmente teclado, leitor de ecrã, contraste de todos os estados e comportamento real em browser; não declarar conformidade WCAG 2.2 AA apenas com o build.

### Auditoria de autorização HTTP — actualização de evidência (2026-11-18)

- [x] Confirmar os testes JWT de upload na suite API: [API CI 44291136290](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44291136290), 1148 aprovados, 1 ignorado, 1 aviso.
- [x] Confirmar o smoke PostgreSQL de autorização multi-loja das sessões de captura no mesmo workflow.
- [ ] Continuar auditoria por rota/handler; não inferir cobertura exaustiva a partir dos cenários já aprovados.

### Prioridades ainda abertas

1. **P1 — desempenho:** executar `apps/api/scripts/postgres_image_query_plan_audit.py` numa réplica/staging com volume representativo; analisar planos `EXPLAIN (ANALYZE, BUFFERS)` e medir paginação profunda antes de acrescentar índices ou alterar contratos. Procedimento em [PERFORMANCE-QUERY-AUDIT.md](PERFORMANCE-QUERY-AUDIT.md).
2. **P1 — aceitação manual:** percorrer o demo completo no browser com ADMIN, SUPERVISOR e EMPLOYEE, sem alterar directamente a base de dados; guardar evidência real em `docs/screenshots/demo/`.
3. **P1 — acessibilidade:** verificar navegação por teclado, foco, leitores de ecrã e contraste de todos os estados; não declarar conformidade WCAG 2.2 AA apenas com base no build.
4. **P1 — dados existentes:** executar o preflight da migração 0054 sobre uma cópia representativa dos dados de cada ambiente antes de qualquer aplicação com histórico real.
5. **P2 — armazém:** definir com o responsável operacional as regras de transferência palete↔colocação e reconciliação com stock agregado; manter os domínios separados até existir decisão aprovada.
6. **P2 — capacidade:** validar a política de capacidade/peso/temperatura com perfis físicos completos e regras reais de negócio; dados desconhecidos continuam a bloquear recomendações em vez de serem assumidos como zero.
7. **P2 — IA e integrações:** provider de visão production-grade treinado/avaliado e conectores POS/ERP/WMS reais continuam fora da validação actual.

### Implementado nesta fase

- [x] Criar provider mock determinístico compatível com `VisionProvider`, selecionável por `VISION_PROVIDER_FACTORY`.
- [x] Configurar API e worker no Docker Compose para usar o provider mock por omissão no ambiente local.
- [x] Criar seed idempotente com loja Demo Store Braga, três prateleiras, quinze produtos, três perfis, snapshots e política de frescura.
- [x] Gerar imagem sintética local sem dados pessoais ou fotografia de terceiros; persistir o ficheiro gerado na pasta do repositório através de bind mount.
- [x] Ligar o upload do frontend à criação de sessão e ao registo de imagem, hash e proveniência.
- [x] Ligar deteções mock à revisão humana de SKU e à criação idempotente de observação.
- [x] Corrigir o motor de decisões para associar a observação ao SKU correto, sem propagar evidência de um produto a todos os produtos da prateleira.
- [x] Ligar recomendação, aprovação humana, validação de stock, atribuição a EMPLOYEE e criação de tarefa.
- [x] Incluir referência da imagem, deteção, observação e SHA-256 na tarefa e mostrar a miniatura protegida pela autorização da imagem.
- [x] Suportar execução da tarefa, registo de quantidade efetiva, motivo para reposição parcial e reconciliação explícita.
- [x] Disponibilizar cronologia auditável da tarefa a ADMIN/SUPERVISOR.
- [x] Aplicar a política de frescura configurada também na avaliação operacional; o seed fornece 24 horas e limita o SKU principal a 4 unidades.
- [x] Disponibilizar listagem de funcionários ativos com isolamento por loja para atribuição por SUPERVISOR.
- [x] Acrescentar testes do provider, seed, worker, revisão/observação idempotente e isolamento da listagem de funcionários.
- [x] Criar um pré-validador local read-only para Docker Compose, serviços, readiness da API, frontend e imagem sintética.
- [x] Criar workflow dedicado para validar a sintaxe Bash do pré-validador.
- [x] Documentar checklist de aceitação ponta-a-ponta por perfil, proveniência, reconciliação e dashboard.

### Validação

- [x] Suite API completa: 1 097 testes aprovados, 1 ignorado; compilação Python aprovada.
- [x] Build TypeScript/produção do frontend aprovado.
- [x] CI PostgreSQL: migrações e smokes de integridade, isolamento, concorrência, ciclo de tarefa e reconciliação aprovados.
- [x] Confirmar execução bem-sucedida do workflow Docker Compose smoke: build e arranque de PostgreSQL/API/worker, readiness após migrações, seed, imagem sintética, worker ativo e autenticação/autorização dos três perfis (PR #4, commit `452583eaec108a176190d19cb097cf3a8a872ede`). Esta validação corre num runner efémero; não equivale a ensaio manual local.
- [ ] Executar localmente a interface e percorrer manualmente o cenário integral com os três perfis, confirmando movimento/snapshot/auditoria finais (checklist em [DEMO.md](DEMO.md)).
- [ ] Capturar screenshots reais do percurso; as instruções de captura estão em [DEMO.md](DEMO.md).

## Limitações e fronteiras actuais

- O provider do demo é mock determinístico; não é um modelo treinado nem valida semanticamente a imagem.
- Não existe integração POS/ERP/WMS real configurada.
- Não existe executor de purga física; os endpoints de retenção são de governação/preview e falham fechados.
- O ensaio manual ponta-a-ponta, capturas reais e auditoria formal de acessibilidade continuam pendentes.
- Slotting físico e picking existem como recomendações consultivas; não reservam stock nem executam movimentos.
- Registos de paletes e inventário agregado permanecem separados para evitar dupla contabilização.

## Regras de conclusão

Só marcar uma tarefa de validação como concluída quando existir implementação e evidência de teste/build. Um provider mock não é um modelo de IA treinado; um seed não é inventário real; uma reconciliação local não equivale a integração com um sistema externo.


## Pré-validação local reforçada — 2026-11-17

- [x] O preflight continua read-only e verifica a configuração Docker Compose e a presença dos três serviços.
- [x] A readiness da API é agora validada semanticamente: exige `status=ready`, `database=connected` e `migrations=current`; um HTTP 200 com payload incompleto/malformado não é considerado sucesso.
- [x] A imagem sintética é validada dentro do container API através do Pillow: ficheiro regular (não symlink), PNG íntegro e dimensões esperadas de 1200×700.
- [x] A verificação da sintaxe Bash já tinha workflow dedicado; a nova versão do script aguarda a execução CI deste commit.
- [x] O workflow Docker Compose smoke confirmou no commit `b618c0ac` a subida de PostgreSQL/API/worker, seed e autenticação dos três perfis, incluindo a restrição de acesso do EMPLOYEE.
- [ ] Executar a nova versão do preflight num ambiente local com Docker Compose e frontend iniciado.
- [ ] Percorrer manualmente o fluxo completo de captura, revisão, tarefa, execução, reconciliação e dashboard com os três perfis.
- [ ] Guardar capturas reais do percurso e preencher `docs/DEMO-ACCEPTANCE.md`.

**Limite:** o CI de Docker Compose prova o arranque, seed e autenticação/permissões básicas; não prova ainda o percurso operacional completo na interface web. O preflight valida a integridade do asset e a readiness, mas não substitui a aceitação manual.


## Critérios de prontidão para piloto

O demo só deve ser anunciado como aceite ponta-a-ponta depois da checklist manual de [DEMO-ACCEPTANCE.md](DEMO-ACCEPTANCE.md) estar preenchida com evidência real. CI verde valida código e testes automatizados, mas não substitui ensaio de browser, acessibilidade, dados representativos, backups/restauro ou integrações externas.

## Auditoria de autorização — integrações externas (2026-11-18)

- [x] Confirmar controlo ADMIN nos handlers de criação, listagem, alteração e cobertura de integrações externas por loja.
- [x] Acrescentar teste de integração HTTP com JWT para SUPERVISOR e EMPLOYEE nas quatro operações, incluindo verificação de ausência de efeitos laterais.
- [x] API CI `44299045159`: 1149 passed, 1 skipped, 1 warning; Quality Gates `44299324366` aprovou testes API, compilação Python e build Web.
- [x] Reconciliar `docs/security/http-route-inventory.md`: 16 rotas integradas na tabela principal; total 123 declarações, sem entradas obsoletas (commit `a60ac242`).
- [ ] Continuar a auditoria handler-a-handler dos restantes endpoints e caminhos indirectos.

**Limite:** o teste acrescentado usa SQLite isolado. Não prova concorrência PostgreSQL nem fecha a auditoria global de autorização.

### Inventário de rotas HTTP — reconciliação (2026-11-18)

- [x] Comparar o inventário com as declarações literais do módulo FastAPI principal.
- [x] Acrescentar 16 rotas omitidas e actualizar o total documentado para 123; nenhuma entrada anterior ficou obsoleta.
- [ ] Concluir a revisão de autorização por handler, incluindo caminhos indirectos e isolamento multi-loja.

A reconciliação estática não constitui uma auditoria de segurança concluída. O Docker Compose `44299045038` também passou (build, readiness, seed, worker e perfis).

## Diretório de funcionários — autorização (2026-11-18)

- [x] Confirmar a política no handler: ADMIN global, SUPERVISOR limitado à loja atribuída e apenas funcionários activos.
- [x] Adicionar teste HTTP JWT para isolamento cross-store, papéis e estado activo.
- [x] Validar no API CI/Quality Gates (runs 44337777007 e 44337776819).
- [ ] Decidir, com base no risco operacional, se é necessário smoke PostgreSQL específico.

A cobertura usa SQLite isolado e não deve ser apresentada como prova de concorrência ou isolamento PostgreSQL.



### Diretório de funcionários — validação PostgreSQL (2026-11-18)

- [x] Acrescentar smoke HTTP/JWT em PostgreSQL 16 para `GET /api/v1/store-employees`, cobrindo isolamento do SUPERVISOR, exclusão de inactivos, filtro cross-store, acesso ADMIN e recusa EMPLOYEE.
- [x] Integrar o smoke no workflow API CI.
- [x] Confirmar a execução do smoke PostgreSQL no API CI (run 44337777007).


### Reforço do smoke de funcionários — 2026-11-18

- [x] Cobrir 401 para ausência de Bearer, JWT inválido e conta SUPERVISOR inactiva.
- [x] Verificar que a listagem global de ADMIN exclui funcionários inactivos.
- [x] Preservar cobertura de isolamento por loja, filtro ADMIN e recusa EMPLOYEE.
- [x] Confirmar execução no API CI/PostgreSQL (run 44337777007).


### Governação de artefactos externos — autorização (18-11-2026)

- [x] Rever os seis handlers de governação de artefactos externos e confirmar a exigência de ADMIN no início de cada operação.
- [x] Acrescentar teste HTTP/JWT para SUPERVISOR e EMPLOYEE em registo, listagem, snapshot de inventário, decisão de acesso e eventos de disposição.
- [x] Confirmar no teste que as recusas não criam registos de artefactos, snapshots ou eventos.
- [x] Validar no API CI e Quality Gates (runs 44337777007 e 44337776819).
- [ ] Continuar auditoria global de autorização; não inferir cobertura total a partir deste conjunto.


### Validação integrada — commit 4b45ae4 (2026-11-18)

- [x] API CI: smoke PostgreSQL e suite `pytest -q` aprovados — [run 44337777007](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44337777007).
- [x] Quality Gates: build Web de produção aprovado — [run 44337776819](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44337776819).
- [x] Docker Compose: API, PostgreSQL, worker e perfis de demonstração aprovados — [run 44337776893](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44337776893).


### Gestão de integrações externas — autorização HTTP (2026-11-18)

- [x] Rever os quatro handlers de criação, listagem, cobertura e actualização de integrações externas.
- [x] Acrescentar teste JWT para SUPERVISOR e EMPLOYEE nos quatro métodos.
- [x] Confirmar no teste a recusa HTTP 403 e a ausência de efeitos laterais sobre registos e política.
- [x] Validar a nova cobertura no API CI e Quality Gates (runs 44338653668 e 44338651433); Docker Compose smoke também passou (run 44338651406).


### Validação CI — gestão de integrações externas (18-11-2026)

- [x] API CI e suite API aprovados — [run 44338653668](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44338653668).
- [x] Quality Gates e build de produção aprovados — [run 44338651433](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44338651433).
- [x] Docker Compose smoke aprovado — [run 44338651406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44338651406).


### Fluxo ADMIN de integrações externas por HTTP (18-11-2026)

- [x] Cobrir criação, listagem, cobertura e revogação com JWT ADMIN.
- [x] Confirmar ausência de campo de segredo nas respostas e estado de cobertura coerente.
- [ ] Validar no API CI e Quality Gates.

### Fluxos de revisão humana — controlo de perfil (18-11-2026)
- [x] Identificar as rotas de fila/resumo de revisão, avaliação de SKU e candidatos de treino como operações reservadas a ADMIN/SUPERVISOR.
- [x] Acrescentar teste JWT HTTP que exige 403 para EMPLOYEE nas cinco operações, incluindo criação de revisão de deteção.
- [x] Confirmar no teste que a operação de escrita recusada não cria registos.
- [ ] Validar o teste no API CI e Quality Gates.
- [ ] Prosseguir a auditoria de autorização por handler e isolamento multi-loja.

**Limite:** teste HTTP com SQLite isolado; não equivale a validação PostgreSQL nem a conclusão da auditoria global.

### Isolamento multi-loja — armazém (18-11-2026)
- [x] Cobrir leitura de localizações de outra loja por supervisor.
- [x] Cobrir criação de localização noutra loja por supervisor.
- [x] Cobrir criação de colocação numa localização de outra loja.
- [x] Verificar 403 e ausência de efeitos laterais.
- [ ] Validar no CI e continuar a cobertura dos recursos de armazém.

**Limite:** evidência HTTP SQLite; a auditoria multi-loja permanece aberta.

### Isolamento multi-loja — paletes e rotação (18-11-2026)
- [x] Cobrir listagem e registo de paletes da loja B por supervisor da loja A.
- [x] Cobrir alteração de política de rotação da loja B por identificador.
- [x] Cobrir leitura e escrita de eventos de ciclo de vida de palete da loja B.
- [x] Confirmar 403 e ausência de efeitos laterais em estado, política e eventos.
- [ ] Validar no API CI e Quality Gates.
- [ ] Continuar a revisão de simulação, portefólio e histórico de rotação.

**Limite:** teste HTTP com SQLite isolado; não prova concorrência PostgreSQL nem conclui a auditoria global.

### Isolamento multi-loja — vendas e forecasting (2026-11-18)
- [x] Cobrir ingestão diária/horária, tráfego e batches.
- [x] Cobrir histórico, previsão de procura, risco de rutura, portefólio e perfil horário.
- [x] Verificar 403 e ausência de efeitos laterais.
- [ ] Validar no CI e continuar auditoria dos restantes fluxos.

**Limite:** teste HTTP/JWT com SQLite isolado; não prova isolamento PostgreSQL nem conclui a auditoria global.


### Importações CSV horárias — isolamento multi-loja (18-11-2026)

- [x] Rever a ordem de autorização dos handlers de importação CSV de vendas e tráfego: a verificação de loja ocorre antes da leitura/parsing do ficheiro.
- [x] Acrescentar teste HTTP/JWT multipart para SUPERVISOR da loja A a tentar importar dados para a loja B.
- [x] Verificar HTTP 403 e ausência de efeitos laterais nas tabelas de vendas e tráfego.
- [ ] Validar o teste no API CI e Quality Gates.
- [ ] Criar/confirmar smoke PostgreSQL específico para isolamento multi-loja nas importações CSV.

**Limite:** a cobertura HTTP adicionada usa SQLite isolado. A revisão estática da ordem de execução não substitui um teste PostgreSQL nem encerra a auditoria global.


### Autorização das importações CSV horárias em PostgreSQL — 18-11-2026

- [x] Smoke PostgreSQL com JWT real para importação de vendas horárias e tráfego.
- [x] Rejeição cross-store antes de parsing e verificação de ausência de efeitos laterais.
- [x] Caminho positivo: SUPERVISOR importa ambos os ficheiros na própria loja.
- [x] Validar API CI, Quality Gates e Docker Compose smoke no commit `1e3499c8c80ef75494a29d06807469898471e4e1`; todos passaram.


### Cobertura completa das importações CSV — 18-11-2026

A auditoria foi alargada para incluir a importação diária `POST /api/v1/sales/import-csv`, além das importações horárias. O teste HTTP/JWT e o smoke PostgreSQL agora cobrem os três endpoints. A evidência PostgreSQL da ronda horária anterior passou no API CI; a extensão diária aguarda validação no novo commit.


**Evidência de validação (18-11-2026):** commit `1e3499c8c80ef75494a29d06807469898471e4e1`; API CI [44404814359](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44404814359), Quality Gates [44404814406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44404814406) e Docker Compose smoke [44404813670](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44404813670) passaram. A prova PostgreSQL cobre os três endpoints CSV com JWT real, isolamento cross-store, ausência de efeitos laterais e caminho positivo na loja autorizada.


### Hierarquia de zonas e prateleiras — autorização (18-11-2026)

- [x] Rever as regras ADMIN-only de criação de zonas/prateleiras.
- [x] Cobrir listagens SUPERVISOR por loja, filtro cross-store e recusa de EMPLOYEE.
- [x] Verificar ausência de efeitos laterais em escritas recusadas e caminho positivo ADMIN.
- [ ] Validar API CI e Quality Gates.
- [ ] Confirmar no smoke PostgreSQL as constraints/triggers de linhagem da hierarquia, sem inferir essa validação a partir de SQLite.


### Batches e consultas de forecasting — isolamento multi-loja (18-11-2026)

- [x] Confirmar validator de loja única nos schemas dos batches de vendas horárias e tráfego.
- [x] Testar payloads com duas lojas: HTTP 422 e ausência de efeitos laterais nas duas lojas.
- [x] Alargar cobertura HTTP/JWT a vendas diárias, traffic peaks, hourly demand e slotting recommendations.
- [ ] Validar os testes no API CI e Quality Gates.
- [ ] Prosseguir auditoria handler-a-handler; a cobertura actual não fecha a matriz global.


### Linhagem de registos associados a prateleiras — PostgreSQL (18-11-2026)

- [x] Rever triggers da migration 0050 para alerts, capture sessions e replenishment tasks.
- [x] Acrescentar smoke PostgreSQL para INSERT/UPDATE cross-store e movimentos da hierarquia.
- [ ] Validar API CI e registar resultado.


### Linhagem multi-loja shelf → zone → store — validada (18-11-2026)

- A migration `0050_shelf_record_store_lineage_guard` e o smoke PostgreSQL foram validados no API CI [44408063719](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44408063719): PostgreSQL 16, migrações, smokes operacionais e suite API passaram.
- O smoke confirmou a rejeição de INSERT/UPDATE divergentes em alertas, sessões de captura e tarefas, bem como movimentos de prateleiras/zonas com dependências existentes.
- Quality Gates [44408063767](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44408063767) passou no mesmo SHA `04c542320ad892a06c81c2295f518f5583428bc4`.
- A auditoria global de autorização e isolamento multi-loja permanece aberta; a validação não deve ser generalizada para rotas não cobertas.


### Linhagem pai/filho de artefactos externos — reforço de contrato e HTTP (18-11-2026)

- O endpoint existente valida o pai no mesmo recurso de imagem e loja e mantém a ordem de bloqueios imagem → integração → referência.
- O schema de criação passa a rejeitar booleanos em `parent_reference_id`, evitando a coerção Python `True == 1`.
- Foi acrescentado teste HTTP/JWT para raiz, descendente, repetição idempotente, conflito de linhagem, pai inexistente, pai de outra imagem e pai de outra loja.
- A validação CI ainda está pendente; a cobertura de integração usa SQLite isolado e não fecha a validação PostgreSQL nem a auditoria global.


### Elegibilidade operacional de datasets — locks da linhagem multi-loja (18-11-2026)

A validação de proveniência interna passa a bloquear explicitamente imagem, prateleira e zona, pois as três linhas determinam a loja efectiva e a retenção aplicável ao artefacto. A query usa ordenação determinística e o teste de contrato compila SQL PostgreSQL para confirmar `FOR UPDATE OF shelf_images, shelves, zones`. Falta smoke de concorrência PostgreSQL com alteração hierárquica em transação concorrente e auditoria dos consumidores que possam contornar o release gate.


### Smoke concorrente PostgreSQL — elegibilidade de datasets (18-11-2026)

Foi criado e integrado no API CI o smoke `postgres_dataset_eligibility_concurrency_smoke.py`. Duas sessões PostgreSQL independentes exercitam actualizações a `shelves.zone_id` e `zones.store_id` enquanto o gate mantém os locks de imagem/prateleira/zona. O smoke exige evidência de bloqueio real através de `pg_stat_activity` e `pg_blocking_pids`, e confirma que as alterações só terminam depois do commit do gate. A validação de runtime permanece pendente até o workflow concluir.


## 2026-11-18 — Elegibilidade de datasets: concorrência PostgreSQL validada

- [x] Confirmar no API CI [44410444406](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444406) o smoke `postgres_dataset_eligibility_concurrency_smoke.py`: PostgreSQL 16 observou bloqueios reais a alterações concorrentes de `shelves.zone_id` e `zones.store_id` enquanto o gate mantinha locks de imagem/prateleira/zona.
- [x] Confirmar no mesmo API CI a suite API completa, incluindo o teste HTTP/JWT de registo de linhagem pai/filho.
- [x] Confirmar Quality Gates [44410444404](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444404) e Docker Compose [44410444721](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44410444721).
- [ ] Auditar consumidores COCO, galeria, revisão offline, aprovação, exportação e treino para identificar caminhos que não passam pelo release gate.
- [ ] Definir linhagem operacional e propagação de retenção para derivados, exports, relatórios, caches e backups; não activar purge físico sem política aprovada.
- [ ] Desenhar coordenação durável com lease/claim e fencing para consumidores remotos ou destacados, porque locks da sessão síncrona não cobrem trabalho assíncrono.

**Limites:** a prova HTTP/JWT da linhagem usa SQLite isolado; o smoke PostgreSQL prova os locks do gate, não o uso universal do gate por todos os consumidores. A suite verde não demonstra integração com fornecedores externos nem execução de treino real.


## 2026-11-18 — Gate de aprovação obrigatório no consumidor síncrono

- [x] Ligar `dataset_execution` ao gate completo de aprovação antes de iniciar o consumidor.
- [x] Exigir release record e os três splits COCO; aceitar os três registos de revisão visual em conjunto e exigir aprovação visual quando configurado.
- [x] Incluir hashes do registo e do relatório do gate na fingerprint imutável da release.
- [x] Manter os locks de elegibilidade operacional durante a criação da release e o consumidor síncrono, adquirindo-os apenas depois das verificações de ficheiros.
- [ ] Validar suite API e Quality Gates no CI.
- [ ] Desenhar leases/claims duráveis com fencing para filas e consumidores remotos/destacados.
- [ ] Auditar exports, caches, backups e artefactos derivados quanto a herança de retenção.

**Limites:** a garantia é local e síncrona. Não autoriza jobs remotos nem substitui política formal de retenção/purge.


### Gate de aprovação no consumidor síncrono — validado (18-11-2026)

- [x] API CI [44412024791](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44412024791): **1168 passed, 1 skipped, 1 warning**; migrações PostgreSQL 16 e smokes operacionais passaram.
- [x] Quality Gates [44412024893](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44412024893): compilação Python e build Web passaram.
- [x] Docker Compose [44412025214](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44412025214): stack de demonstração passou.
- [x] Gate de aprovação, evidência SHA-256 vinculada à release e execução síncrona com locks mantidos validados pela suite API.
- [ ] Criar lease/claim durável com fencing para consumidores remotos ou destacados.
- [ ] Propagar linhagem e retenção aos derivados, exports, relatórios, caches e backups; manter purge físico desactivado.

**Limites:** a evidência é CI automatizado; não comprova treino real nem integração externa. O lock transaccional não protege trabalho que sobreviva ao processo consumidor.


### Auditoria das fronteiras dos consumidores de datasets — 18-11-2026

- [x] Classificar validação COCO, galeria offline, diff, qualidade, revisão, aprovação, release e execução.
- [x] Identificar `dataset_execution` como a única fronteira inspeccionada que inicia um processo externo; está ligada ao gate de aprovação.
- [x] Documentar que relatórios/galeria/releases candidatas não são autorização operacional nem autenticam revisores.
- [ ] Implementar catálogo persistente de artefactos derivados e herança de retenção para relatórios, exports, caches e backups.
- [ ] Implementar lease/claim/fencing durável para consumidores assíncronos e condicionar a publicação ao token actual.
- [ ] Substituir revisão por ficheiro declarativo por aprovação autenticada quando existir contrato de utilizadores/revisores.


### Execução assíncrona de datasets — contrato de lease/fencing definido (18-11-2026)

- [x] Definir identidade imutável do job, idempotência, estados e transições.
- [x] Definir claim `FOR UPDATE SKIP LOCKED`, expiração, takeover e fencing token monotónico.
- [x] Definir revalidação de retenção/legal hold em enqueue, claim, heartbeat e conclusão.
- [x] Definir staging e promoção condicionada ao token actual.
- [x] Implementar persistência, serviço de lease e auditoria append-only.
- [x] Validar concorrência, takeover, token obsoleto e retenção em PostgreSQL 16 no API CI [44416138879](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138879); suite API: 1177 passed, 1 skipped, 1 warning.
- [ ] Integrar worker/fila apenas depois da validação do serviço.


### Persistência de jobs de datasets e fencing — implementação inicial (18-11-2026)

- [x] Criar migration/modelos para jobs, fontes internas e eventos append-only.
- [x] Implementar enqueue idempotente, claim `SKIP LOCKED`, lease, heartbeat, falha, conclusão em staging e fencing monotónico.
- [x] Revalidar retenção/loja/hash das fontes em cada fronteira de autorização e revogar jobs inelegíveis.
- [x] Acrescentar testes unitários/SQLite e smoke PostgreSQL concorrente.
- [x] Validar migration PostgreSQL 16, suite API e smoke concorrente no API CI [44416138879](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138879), Quality Gates [44416138669](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138669) e Docker Compose [44416138628](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44416138628).
- [ ] Integrar broker/worker apenas depois da validação PostgreSQL.
- [ ] Implementar leitura de artefactos autorizada por chamada e promoção de outputs condicionada ao token actual.


### Fencing reforçado na base de dados — implementação preparada (2026-11-18)

- [x] Adicionar migration para incremento exacto de fencing token/attempt count em claims e takeovers.
- [x] Impedir heartbeat sobre lease expirado ou redução da expiração.
- [x] Exigir lease válido para sucesso/falha, timestamp terminal e output staged com digest.
- [x] Validar sequência de eventos na base de dados e bloquear eventos posteriores à transição terminal, preservando o evento terminal.
- [x] Adicionar testes SQLite e ampliar o smoke PostgreSQL com tentativas SQL directas.
- [x] Validar API CI [44419928230](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928230), Quality Gates [44419928281](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928281) e Docker Compose [44419928382](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44419928382): migration PostgreSQL 16, smokes e 1179 testes aprovados, 1 ignorado, 1 aviso.
- [ ] Implementar autenticação de workers e serviço de leitura/promoção com fencing.


### Máquina de estados e identidade dos jobs assíncronos — 2026-11-18

- [x] Especificar transições válidas: `QUEUED → LEASED/REVOKED/CANCELLED`; `LEASED → LEASED/SUCCEEDED/FAILED/REVOKED/CANCELLED`.
- [x] Bloquear actualizações a jobs terminais e alterações à identidade imutável depois do enqueue.
- [x] Acrescentar guards equivalentes para PostgreSQL e SQLite, testes de migration e smoke SQL directo.
- [ ] Confirmar a migration 0058 e os workflows de CI antes de marcar a garantia como validada.
- [ ] Implementar autenticação de workers, consumo de bytes autorizado por chamada e promoção de outputs com fencing.


### Validação da migration 0058 — 18-11-2026

- [x] API CI [44421831066](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44421831066): migration PostgreSQL 16, smoke de execução assíncrona e 1179 testes aprovados, 1 ignorado, 1 aviso.
- [x] Quality Gates [44421831076](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44421831076) e Docker Compose [44421831148](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44421831148) passaram.
- [x] A migration 0059 de estado inicial obrigatório foi validada no API CI [44428496117](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496117), com PostgreSQL 16, smoke de leases/fencing e 1179 testes aprovados, 1 ignorado e 1 aviso; Quality Gates [44428496156](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496156) e Docker Compose [44428496204](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496204) passaram.


### Guard de estado inicial dos jobs assíncronos — 19-11-2026

- [x] Acrescentar cobertura SQLite para os oito campos que não podem ser definidos num INSERT inicial de job.
- [x] Acrescentar tentativas equivalentes no smoke PostgreSQL 16, com transacções independentes e rejeição esperada pela base de dados.
- [x] Corrigir os INSERTs de teste sem colunas duplicadas e validar PostgreSQL 16, smoke de leases/fencing e suite API (**1179 passed, 1 skipped, 1 warning**) no API CI [44428496117](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496117); Quality Gates [44428496156](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496156) e Docker Compose [44428496204](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44428496204) passaram.
- [ ] Implementar autenticação/identidade de workers antes de disponibilizar endpoints de claim/heartbeat; manter a API de jobs não exposta enquanto essa fronteira não existir.


### Autenticação de workers de datasets — estado atualizado (19-11-2026)

- [x] Definir credenciais individuais, emissão segura, expiração, rotação e revogação de workers.
- [x] Vincular `worker_id` à identidade autenticada e autorizar scopes por operação.
- [x] Testar tokens inválidos/expirados/revogados, scopes insuficientes e vínculo de identidade entre worker e credencial.
- [ ] Implementar assinatura por pedido/nonce e testes anti-replay.
- [x] Manter endpoints de jobs não expostos enquanto a autenticação HTTP não estiver integrada.


## 2026-11-19 — Autenticação individual de workers (implementação inicial validada)

**Implementado no código:**
- Migration `0060_dataset_worker_credentials`: identidades de workers, credenciais individuais e eventos de segurança append-only.
- Credencial bearer com segredo aleatório de 256 bits, hash SHA-256 persistido, comparação em tempo constante, validade máxima de 90 dias, rotação, revogação e desativação.
- Scopes explícitos sem wildcard; wrappers de claim/heartbeat/complete/fail derivam a identidade exclusivamente do principal autenticado.
- CLI de provisionamento local; nenhuma rota HTTP pública de emissão foi criada.
- Testes SQLite e smoke PostgreSQL de ciclo de vida e imutabilidade integrados no workflow API CI.

**Validação concluída no commit de código `d7c84125d35a5fff5d2254a3ee33a08cd41edcc7`:** API CI [44431378398](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378398) passou (PostgreSQL 16, smoke de credenciais e **1202 passed, 1 skipped, 1 warning**), Quality Gates [44431378324](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378324) e Docker Compose [44431378349](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44431378349) também passaram.

**Riscos e trabalho restante:**
1. A autenticação bearer não é anti-replay; falta assinatura por pedido/nonce ou protocolo equivalente.
2. O middleware/handlers HTTP ainda não autenticam workers e os endpoints de jobs permanecem não expostos.
3. Os scopes `artifacts:read` e `outputs:publish` são apenas reservados; faltam leitura de bytes por chamada e promoção com fencing.
4. Não existe broker nem worker remoto de treino; a persistência de leases não equivale a execução operacional.
5. A credencial só pode ser emitida pelo CLI local confiável; a operação em produção precisa de secret manager, TLS e procedimento de provisionamento controlado.

Referência de implementação: [Autenticação e autorização de workers](security/dataset-worker-authentication.md).


## 2026-11-19 — Autenticação HTTP assinada e proteção contra replay

A migration `0061_dataset_worker_request_nonces` e o módulo `app.dataset_worker_http` implementam uma fronteira reutilizável para pedidos de workers. A dependência `require_dataset_worker(scope)` exige bearer individual, timestamp com tolerância de 60 segundos, nonce aleatório, assinatura HMAC-SHA-256 e scope específico. A assinatura cobre a identidade da credencial, método, caminho/query exactos e SHA-256 do corpo. O servidor persiste apenas o digest do nonce, com unicidade por credencial, e confirma-o antes de entregar o principal ao handler.

**Validação concluída no commit `7bb67412cdb6b63b8221a2a29a12d7347005a451`:** API CI [44471171581](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171581) passou em PostgreSQL 16, incluindo duas sessões concorrentes que reutilizam o mesmo nonce (**uma aceite, uma rejeitada**) e **1211 testes aprovados, 1 ignorado e 1 aviso**. Quality Gates [44471171526](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171526) e Docker Compose [44471171533](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44471171533) também passaram.

**Decisão:** as futuras rotas de workers devem usar um prefixo separado da API humana, por exemplo `/internal/v1/dataset-jobs`, e aplicar a dependência em todos os handlers. Não expor rotas enquanto leitura autorizada de artefactos, publicação fenced e worker remoto não estiverem implementados. A tabela de nonces retém os digests durante 121 segundos; pedidos assinados posteriores limpam os expirados.

**Próximas tarefas P0:** leitura de bytes autorizada por chamada (`artifacts:read`), promotor de outputs condicionado ao fencing token actual (`outputs:publish`), e só depois integração de broker/worker remoto.


## 2026-11-19 — Leitura de fontes de treino com fencing e auditoria

A migration `0062_dataset_job_artifact_reads` e o serviço `read_dataset_job_source_bytes` fecham a operação de leitura interna para jobs. O worker necessita do scope `artifacts:read`, lease não expirado, identidade autenticada e fencing token actual. O serviço valida a fonte imutável do job, revalida credencial/scope, bloqueia imagem/prateleira/zona, verifica loja, retenção, legal hold, caminho sem symlinks, tamanho e SHA-256, e só devolve bytes em memória.

A tabela `dataset_execution_job_artifact_reads` regista cada leitura bem-sucedida e é append-only. Triggers SQL rejeitam inserções sem lease/fonte/loja/retention/worker/credencial/scope válidos e impedem UPDATE/DELETE. O smoke PostgreSQL confirmou que uma restrição de retenção concorrente espera pelos locks da leitura e que a leitura posterior é recusada sem criar auditoria de sucesso.

**Validação concluída no commit `c6b00478514812e094b960f5fefe4b6380b0fb9a`:** API CI [44473560217](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560217), Quality Gates [44473560287](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560287) e Docker Compose [44473560252](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44473560252) passaram; suite API com **1223 testes aprovados, 1 ignorado e 1 aviso**.

**Próxima fronteira P0:** implementar `outputs:publish` com validação do estado `SUCCEEDED`, digest e fencing token actual, protocolo de staging/publicação recuperável e compensação de ficheiros órfãos. Só depois integrar broker e worker remoto. O serviço de leitura existe, mas não está ainda exposto por endpoint HTTP; a execução assíncrona continua não operacional.


## 2026-11-19 — Promoção de outputs de datasets com fencing

A migration `0063_dataset_job_output_publications` e o serviço `app.dataset_job_output_publications.promote_dataset_job_output` implementam a promoção interna de outputs concluídos. A operação valida o estado `SUCCEEDED`, o fencing token actual, o evento terminal do worker, o digest do output e a credencial activa com `outputs:publish`. A referência de staging é limitada ao job/token, os caminhos são abertos sem seguir symlinks, o conteúdo é copiado para temporário privado e verificado por tamanho/SHA-256, e o destino é publicado com hard link atómico sem sobrescrita.

A tabela de publicação é append-only e as triggers PostgreSQL/SQLite impedem inserções que não correspondam ao evento terminal e à autorização persistida. A referência final é determinística e content-addressed. Uma repetição após a promoção filesystem mas antes do commit SQL valida o destino existente e reconcilia a auditoria.

**Validação concluída no commit `46006afcc5167e04f77037f985e65981a78248e3`:** API CI [44480661837](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661837) passou com PostgreSQL 16, smoke concorrente e **1231 testes aprovados, 1 ignorado e 1 aviso**; Quality Gates [44480661851](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661851) e Docker Compose [44480661813](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44480661813) também passaram.

**Riscos e próximas prioridades P0/P1:** automatizar limpeza/reconciliação de temporários órfãos após crash; integrar outputs no catálogo de artefactos derivados e propagar retenção/legal hold; separar permissões filesystem entre staging e publicação para o futuro worker; só depois criar handlers HTTP internos, broker e worker remoto. Não expor endpoints nem declarar execução assíncrona operacional enquanto estes elementos não estiverem concluídos.

## Reconciliador: preservação perante destino adulterado — 2026-11-19

Foi acrescentada cobertura para a divergência entre o destino publicado e a auditoria imutável. O staging só pode ser removido quando o destino publicado e o próprio staging correspondem simultaneamente ao digest e tamanho registados. A nova regressão verifica que um destino adulterado impede a limpeza, mesmo quando o staging ainda contém os bytes esperados. A execução CI desta cobertura está pendente.


### Governação de outputs assíncronos — decisão arquitectural (19-11-2026)

- [x] Auditar os registos existentes de publicação, linhagem de fontes e catálogo externo por imagem.
- [x] Decidir que `dataset_execution_job_output_publications` é a raiz canónica do output; evitar catálogo duplicado e associação artificial a uma única imagem.
- [x] Documentar a herança de restrições de todas as fontes e a necessidade de eventos de governação append-only separados.
- [ ] Implementar eventos de retenção/legal hold associados à publicação, sem mutação da auditoria de publicação.
- [ ] Implementar avaliação fail-closed e locks de todas as imagens de origem em ordem crescente.
- [ ] Validar concorrência e migration em PostgreSQL 16 e SQLite.
- [ ] Manter purga física desactivada até existir política de retenção e cobertura externa aprovadas.

Ver [decisão de governação de retenção dos outputs](architecture/dataset-output-artifact-governance.md).


### Revalidação de fontes na promoção de outputs — 19-11-2026

- [x] Revalidar as fontes imutáveis do job na transacção final de promoção, depois da preparação do ficheiro.
- [x] Manter locks de imagem/prateleira/zona até ao commit da publicação, com ordem por ID crescente.
- [x] Impedir INSERT SQL directo se qualquer fonte estiver ausente, com loja/hash divergente, RESTRICTED ou sob legal hold (PostgreSQL e SQLite).
- [x] Acrescentar testes SQLite para restrição/legal hold e smoke PostgreSQL para a corrida entre hold e promoção.
- [ ] Validar migration 0064, suite API e workflows de CI.


### Promoção de outputs — cobertura multi-origem (2026-11-19)

- Regressões SQLite/serviço acrescentadas para duas fontes, entrada fora da ordem dos IDs e inelegibilidade da segunda origem por restrição ou legal hold.
- Migration 0064 coberta com trigger a rejeitar publicação quando apenas uma das fontes está inelegível.
- Smoke PostgreSQL 16 alargado para job multi-origem e corrida de legal hold sobre a segunda imagem durante a preparação.
- Validação CI pendente no commit desta ronda; não declarar a cobertura PostgreSQL concluída antes do API CI.


### Validação final — publicação multi-origem e retenção (2026-11-19)

- API CI [44516774051](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774051): **1241 passed, 1 skipped, 1 warning**, incluindo migration 0064 e smoke PostgreSQL 16 com duas fontes e hold concorrente sobre a segunda.
- Quality Gates [44516774058](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774058): compilação Python, suite API e build Web aprovados.
- Docker Compose [44516774048](https://github.com/smpsandro1239/SMART-SHELF-AI-/actions/runs/44516774048): aprovado.
- O aviso Starlette/AnyIO é uma depreciação externa; sem falhas associadas.


### Governação append-only dos outputs publicados — 2026-11-19

- Implementada migration 0065 e modelo para eventos separados da publicação canónica.
- Implementados eventos de restrição/restauro e legal hold/libertação, actor activo, motivo, evidência e detalhes JSON limitados.
- Triggers PostgreSQL/SQLite impõem sequência consecutiva, máquina de estados por tipo de evento e imutabilidade UPDATE/DELETE.
- Serviço interno exige callback de autorização positivo; a projecção de estado deriva a situação efectiva da cronologia.
- Testes SQLite e smoke concorrente PostgreSQL acrescentados; aguarda CI do commit.
- Permanecem em aberto a matriz de permissões, integração com consumidores de bytes, endpoints/worker remoto, política de retenção e disposição física.
