# SMART SHELF AI — Roadmap

## Prioridade atual: concluir e validar o demo vertical de 10 minutos

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

### Validação

- [x] Suite API completa: 1 097 testes aprovados, 1 ignorado; compilação Python aprovada.
- [x] Build TypeScript/produção do frontend aprovado.
- [x] CI PostgreSQL: migrações e smokes de integridade, isolamento, concorrência, ciclo de tarefa e reconciliação aprovados.
- [x] Validar automaticamente o stack Docker Compose no GitHub Actions: build e arranque de PostgreSQL/API/worker, readiness após migrações, seed, imagem sintética, worker ativo e autenticação/autorização dos três perfis (PR #4, commit `452583eaec108a176190d19cb097cf3a8a872ede`). Esta validação corre num runner efémero; não equivale a ensaio manual no computador do utilizador.
- [ ] Executar localmente a interface e percorrer manualmente o cenário integral com os três perfis, confirmando movimento/snapshot/auditoria finais (checklist em [DEMO.md](DEMO.md)).
- [ ] Capturar screenshots reais do percurso; as instruções de captura estão em [DEMO.md](DEMO.md).

## Fora do âmbito desta fase

- Integrações POS, ERP ou WMS reais.
- Treino ou inferência de modelos de visão production-grade.
- Rotação de paletes, slotting, picking ou previsão avançada.

## Regras de conclusão

Só marcar uma tarefa de validação como concluída quando existir implementação e evidência de teste/build. Um provider mock não é um modelo de IA treinado; um seed não é inventário real; uma reconciliação local não equivale a integração com um sistema externo.
