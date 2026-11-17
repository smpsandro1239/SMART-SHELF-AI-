# SMART SHELF AI — demonstração vertical de 10 minutos

**Estado: implementação integrada na `main`; validação automatizada aprovada; ensaio manual visual ainda pendente.**

A implementação do Demo Vertical está integrada na `main`. A suite API, a compilação Python, o build de produção do frontend e os smokes PostgreSQL foram aprovados no CI. Adicionalmente, o workflow `Demo Docker Compose smoke` construiu e iniciou PostgreSQL, API e `vision-worker`, aguardou a readiness após as migrações, executou o seed, confirmou a imagem sintética e validou a autenticação/autorização dos três perfis. Esta validação de stack foi aprovada no commit `452583eaec108a176190d19cb097cf3a8a872ede` (PR #4, integrado na `main` pelo merge `8df0950ab4590e41f5efdc0e7de5caf059147dbc`).

**Ainda não foi realizado:** o ensaio manual da interface no computador de um utilizador, incluindo upload no browser e percurso de negócio completo até ao dashboard. O CI confirma a integração dos serviços e os acessos autenticados, mas não substitui esse ensaio visual. O provider mock não é um modelo treinado e não deve ser usado para decisões operacionais reais.

## Preparação local

Na raiz do repositório:

```bash
docker compose up --build -d

docker compose exec api alembic upgrade head
docker compose exec api python -m app.demo.seed
```

A API e o worker usam `app.demo.vision:create_provider` por omissão no Docker Compose. Ambos partilham o volume `shelf_images`. O provider é determinístico para o conteúdo do ficheiro e produz uma caixa de demonstração; não analisa semanticamente a fotografia. Para confirmar o processamento: `docker compose logs -f vision-worker`. A imagem sintética é gerada em `apps/api/demo/assets/synthetic-shelf.png` no host quando o seed é executado dentro do container (a pasta está montada no Docker Compose).

Frontend: executar `npm ci && npm run dev` em `apps/web` (porta 5173). O Vite encaminha `/api` para `http://127.0.0.1:8000`. API: `http://localhost:8000`; documentação OpenAPI: `http://localhost:8000/docs`.

## Contas locais de demonstração

| Perfil | Email | Palavra-passe |
|---|---|---|
| ADMIN | admin@demo.smart-shelf.local | DemoAdmin2026! |
| SUPERVISOR | supervisor@demo.smart-shelf.local | DemoSupervisor2026! |
| EMPLOYEE | employee@demo.smart-shelf.local | DemoEmployee2026! |

Estas credenciais são exclusivamente locais. Altera-as antes de expor o ambiente a qualquer rede não confiável. O seed cria a loja **Demo Store Braga**, uma zona, três prateleiras, quinze produtos, associações SKU–prateleira, snapshots de inventário MANUAL e uma política de frescura de 24 horas. O SKU `DEMO-001` começa com apenas 4 unidades na retaguarda; a reposição sugerida fica limitada a esse stock disponível.

## Guião de 10 minutos

1. **00:00–01:00 — Login:** entrar como SUPERVISOR e confirmar a loja Demo Store Braga.
2. **01:00–02:00 — Seleção:** escolher a zona e a prateleira `DEMO-A1`.
3. **02:00–03:00 — Captura:** carregar `synthetic-shelf.png`; a API cria uma sessão e guarda o ficheiro, SHA-256, timestamp e proveniência.
4. **03:00–04:00 — Análise:** aguardar o worker; o provider mock emite uma deteção `empty_facing` com bounding box e confiança. O resultado é sintético e explicitamente identificado como DEMO.
5. **04:00–05:00 — Observação:** rever a evidência e selecionar `DEMO-001` (Leite meio-gordo 1 L), associado à prateleira `DEMO-A1`, para usar o cenário de stock baixo. Não aceitar automaticamente uma identidade de produto que o mock não consegue provar.
6. **05:00–06:00 — Recomendação:** consultar a decisão operacional, inventário disponível e quantidade sugerida.
7. **06:00–07:00 — Aprovação:** ADMIN/SUPERVISOR confirma quantidade e stock. A tarefa é atribuída ao EMPLOYEE; a tarefa mostra também a miniatura da imagem de evidência e o SHA-256. Não há movimento automático de inventário.
8. **07:00–08:30 — Execução:** terminar sessão, entrar como EMPLOYEE, iniciar a tarefa, registar quantidade efetivamente reposta e concluir.
9. **08:30–09:30 — Reconciliação:** voltar ao SUPERVISOR e aprovar a reconciliação com motivo. Se a evidência de stock estiver desatualizada ou insuficiente, a API bloqueia a operação conforme ADR-008.
10. **09:30–10:00 — Resultado:** consultar tarefa, evidência, eventos de auditoria, movimento e snapshot resultante no dashboard.

## Comandos de validação

```bash
# Estado dos serviços e logs do worker
cd <raiz-do-repositório>
docker compose ps
docker compose logs -f vision-worker

# API tests
cd apps/api
pytest -q

# Web TypeScript e build de produção
cd ../web
npm ci
npm run build
```

O serviço API executa `alembic upgrade head` no arranque; o healthcheck `/health/ready` só fica saudável depois desse processo. O worker depende de `api: condition: service_healthy`, evitando consumir tarefas antes das migrações estarem concluídas. O comando explícito `docker compose exec api alembic upgrade head` é seguro para confirmar/aplicar o estado das migrações antes do seed.

## Capturas de ecrã recomendadas

Guardar capturas locais em `docs/screenshots/demo/` (não incluir tokens, emails pessoais ou dados reais):

- `01-login.png` — login e selo Demo Mode.
- `02-shelf-upload.png` — loja/zona/prateleira e imagem carregada.
- `03-detection.png` — bounding box, label, confiança e SHA-256 abreviado.
- `04-recommendation.png` — observação e recomendação com stock disponível.
- `05-task.png` — tarefa atribuída e execução pelo funcionário.
- `06-reconciliation.png` — movimento, snapshots e auditoria.
- `07-dashboard-final.png` — indicadores finais.

## Limitações conhecidas

- O provider mock não classifica visualmente o conteúdo da imagem: gera uma deteção de demonstração determinística a partir do hash do ficheiro.
- A deteção não contém SKU. A atribuição do SKU é uma revisão humana explícita, limitada às associações da prateleira.
- Não existe integração POS/ERP/WMS neste demo. O inventário é local e semeado.
- A reconciliação não altera snapshots antigos e pode ser recusada por frescura, concorrência ou stock insuficiente.


## Checklist do ensaio manual (pendente)

Executar depois de arrancar o stack e iniciar o frontend. Marcar cada ponto apenas após o observar na interface e, quando aplicável, confirmar o resultado na API/base de dados.

- [ ] Abrir a aplicação em `http://localhost:5173` e autenticar como SUPERVISOR.
- [ ] Confirmar Demo Store Braga, a zona e a prateleira `DEMO-A1`.
- [ ] Carregar `synthetic-shelf.png`; confirmar sessão de captura, imagem e hash.
- [ ] Aguardar o worker e confirmar deteção `empty_facing` identificada como DEMO.
- [ ] Rever a deteção e selecionar manualmente `DEMO-001`; confirmar que a associação é limitada à prateleira.
- [ ] Consultar a recomendação e verificar o stock disponível antes da aprovação.
- [ ] Aprovar a reposição como SUPERVISOR ou ADMIN e atribuir a tarefa ao EMPLOYEE.
- [ ] Terminar a sessão e entrar como EMPLOYEE; iniciar, executar e concluir a tarefa com a quantidade efetiva.
- [ ] Voltar a entrar como SUPERVISOR; reconciliar com motivo explícito.
- [ ] Confirmar movimento, novo snapshot e eventos de auditoria; confirmar que os snapshots anteriores permanecem imutáveis.
- [ ] Confirmar que o dashboard apresenta o estado final esperado.
- [ ] Guardar as sete capturas indicadas acima, sem tokens nem dados pessoais.

**Critério de aceitação manual:** todos os passos acima concluídos, sem intervenção direta na base de dados para forçar estados, e com evidência visual dos resultados. Se um passo falhar, registar o perfil, ação, resposta/erro e logs relevantes antes de alterar código.
