# SMART SHELF AI — checklist de aceitação do demo vertical

Este documento complementa [DEMO.md](DEMO.md). Serve para registar evidência de uma execução real, não para substituir testes automatizados.

## 1. Pré-condições

- [ ] Repositório atualizado na branch pretendida.
- [ ] Docker Engine e Docker Compose disponíveis.
- [ ] Ficheiro de ambiente local configurado; não reutilizar segredos de produção.
- [ ] PostgreSQL, API e worker iniciados com `docker compose up --build -d`.
- [ ] Migrações aplicadas e seed concluído.
- [ ] Frontend iniciado em `apps/web`.
- [ ] `bash scripts/demo-preflight.sh` termina com sucesso.
- [ ] A API apresenta `status=ready`, `database=connected` e `migrations=current` em `/health/ready`.

**Registo da execução**

| Campo | Valor |
|---|---|
| Data/hora e fuso | |
| Commit testado | |
| Sistema operativo | |
| Versões Docker / Compose | |
| Resultado do preflight | |
| Responsável pela execução | |

## 2. Percurso funcional por perfil

### SUPERVISOR — captura e revisão

- [ ] Login aceite com a conta local SUPERVISOR.
- [ ] Loja Demo Store Braga e zona de demonstração visíveis.
- [ ] Prateleira `DEMO-A1` selecionável.
- [ ] Upload de `apps/api/demo/assets/synthetic-shelf.png` aceite.
- [ ] Imagem apresenta identificador, timestamp e SHA-256.
- [ ] Worker processa a imagem e o estado deixa de estar pendente.
- [ ] Deteção apresentada com label, confiança e bounding box.
- [ ] Interface identifica claramente que a deteção é sintética/mock.
- [ ] Revisão humana permite selecionar apenas um SKU associado à prateleira.
- [ ] Observação resultante fica associada ao SKU revisto, sem ser propagada aos restantes produtos.
- [ ] Recomendação mostra a evidência e o estado/frescura do inventário.
- [ ] Quantidade proposta não excede o stock disponível nem ignora uma evidência insuficiente.
- [ ] Aprovação exige ação humana e permite atribuir a tarefa ao EMPLOYEE.

### EMPLOYEE — execução

- [ ] Login aceite com a conta local EMPLOYEE.
- [ ] Só são apresentadas tarefas autorizadas/atribuídas ao funcionário.
- [ ] Tarefa apresenta prateleira, SKU, quantidade e evidência autorizada.
- [ ] Funcionário consegue iniciar a tarefa.
- [ ] Quantidade efetivamente reposta é registada.
- [ ] Conclusão da tarefa é aceite.
- [ ] Funcionário não consegue executar ações reservadas a ADMIN/SUPERVISOR.

### SUPERVISOR — reconciliação e dashboard

- [ ] Tarefa concluída e respetiva cronologia visíveis.
- [ ] Quantidade efetiva coincide com o movimento proposto ou a divergência tem motivo.
- [ ] Reconciliação exige decisão explícita e motivo.
- [ ] Movimento de inventário fica ligado à tarefa e à evidência de origem.
- [ ] Novo snapshot é criado sem alterar snapshots históricos.
- [ ] Dashboard reflete a alteração de estado das tarefas.
- [ ] Contagens do dashboard são coerentes com os registos consultados.

### ADMIN — controlo administrativo

- [ ] Login aceite com a conta local ADMIN.
- [ ] ADMIN consegue consultar o estado da loja e utilizadores do demo.
- [ ] Ações administrativas não expõem dados de outras lojas.
- [ ] A conta ADMIN não é usada para contornar as decisões humanas do percurso operacional.

## 3. Critérios de aprovação

A execução só pode ser marcada como aceite quando:

1. Todos os passos aplicáveis às três contas terminam sem erro bloqueante.
2. A imagem, deteção, revisão, observação, recomendação, tarefa, evento de execução, movimento e snapshot mantêm uma cadeia de proveniência coerente.
3. Não existe movimento de inventário antes da reconciliação autorizada.
4. O histórico de snapshots permanece append-only.
5. As permissões por perfil e o isolamento por loja são respeitados.
6. O dashboard reflete os dados persistidos e não apresenta contagens incompatíveis.
7. As limitações do provider mock são visíveis e não é apresentado como IA treinada.

**Falhas bloqueantes:** perda de proveniência, associação de SKU não autorizada, reconciliação sem motivo/autoridade, alteração de snapshots históricos, fuga entre lojas, tarefa executável por utilizador não atribuído ou dashboard incompatível com os registos persistidos.

## 4. Evidência a guardar

Guardar apenas capturas sintéticas e sem tokens, cookies, palavras-passe ou dados pessoais em `docs/screenshots/demo/`:

- [ ] Login e perfil ativo.
- [ ] Prateleira e imagem carregada.
- [ ] Deteção mock e hash.
- [ ] Revisão humana e SKU selecionado.
- [ ] Recomendação e stock disponível/frescura.
- [ ] Tarefa atribuída e execução pelo EMPLOYEE.
- [ ] Reconciliação, movimento e snapshot final.
- [ ] Dashboard final.

Anexar também, quando possível, o output de `docker compose ps`, `docker compose logs --since=10m vision-worker`, o resultado do preflight e o SHA do commit testado. Remover credenciais e dados sensíveis antes de partilhar logs.

## 5. Diagnóstico rápido

| Sintoma | Verificação |
|---|---|
| API não fica ready | `docker compose logs --tail=200 api db`; confirmar migrações e healthcheck do PostgreSQL. |
| Worker não processa | `docker compose logs --tail=200 vision-worker`; confirmar provider factory e volume `shelf_images`. |
| Imagem sintética em falta | Executar o seed no serviço API e confirmar o bind mount `apps/api/demo/assets`. |
| Frontend não responde | Confirmar `npm ci`, `npm run dev`, porta 5173 e proxy Vite para a API. |
| SKU não aparece na revisão | Confirmar que o SKU está associado à prateleira escolhida; não forçar uma associação manual fora do catálogo permitido. |
| Recomendação bloqueada | Verificar idade/frescura do snapshot, quantidade observada, confiança e stock disponível. Não contornar as salvaguardas. |
| Reconciliação recusada | Consultar o motivo devolvido pela API, estado da tarefa, concorrência, frescura e stock; atualizar a evidência e repetir apenas se autorizado. |

## 6. Resultado final

- [ ] APROVADO — todos os critérios obrigatórios cumpridos.
- [ ] REPROVADO — existe pelo menos uma falha bloqueante.
- [ ] PARCIAL — percurso incompleto; não anunciar como demo ponta-a-ponta validado.

**Incidentes / observações:**

