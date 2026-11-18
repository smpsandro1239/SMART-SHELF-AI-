# SMART SHELF AI — Roadmap

## Prioridade atual: preparar um piloto controlado com validação operacional e evidência

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
- [ ] Validar no API CI/Quality Gates.
- [ ] Decidir, com base no risco operacional, se é necessário smoke PostgreSQL específico.

A cobertura usa SQLite isolado e não deve ser apresentada como prova de concorrência ou isolamento PostgreSQL.



### Diretório de funcionários — validação PostgreSQL (2026-11-18)

- [x] Acrescentar smoke HTTP/JWT em PostgreSQL 16 para `GET /api/v1/store-employees`, cobrindo isolamento do SUPERVISOR, exclusão de inactivos, filtro cross-store, acesso ADMIN e recusa EMPLOYEE.
- [x] Integrar o smoke no workflow API CI.
- [ ] Confirmar a execução CI antes de considerar o isolamento PostgreSQL validado.


### Reforço do smoke de funcionários — 2026-11-18

- [x] Cobrir 401 para ausência de Bearer, JWT inválido e conta SUPERVISOR inactiva.
- [x] Verificar que a listagem global de ADMIN exclui funcionários inactivos.
- [x] Preservar cobertura de isolamento por loja, filtro ADMIN e recusa EMPLOYEE.
- [ ] Confirmar execução no API CI/PostgreSQL antes de fechar a validação.
