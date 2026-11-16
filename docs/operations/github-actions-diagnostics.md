# GitHub Actions diagnostics

Last checked: 2026-11-15 (UTC)

## Observed failure pattern

The following workflows fail before any recorded runner step:

- Smart Shelf quality gates, run `43777084186`, commit `1008aaca09e715d23ad78bdbfb441dfa2e40cf6d`.
- Runner diagnostics, run `43777317171`, commit `49d216541ff205700a9b3a361bccfe8e09a00e89`.

For the quality-gates run, both jobs (`API tests and Python compilation` and `Web TypeScript and production build`) report failure with no steps. The GitHub Actions jobs endpoint reports `logs_url: null` and `steps: null`; the step endpoint returns an empty array; downloading logs returns HTTP 404 with `BlobNotFound`; no workflow artifacts were produced.

A dedicated diagnostic workflow was added at `.github/workflows/runner-diagnostics.yml`. It deliberately avoids checkout, third-party actions, package installation, services and repository code. Its only job runs a few preinstalled runtime version commands. The first attempt and one explicit retry both failed before any step. The retry job also reports an empty step list, `logs_url: null`, and HTTP 404 `BlobNotFound` when logs are requested. This makes a transient one-off failure less likely. GitHub Status showed all systems operational and no incident for November 15, 2026, at the time of the follow-up check.

This evidence does **not** establish a Python, TypeScript, application, or workflow-command failure: none of those commands were reached. GitHub Status reported all systems operational and no incident on 2026-11-15 when checked, so a broad public outage is not confirmed. The remaining plausible causes include repository/account Actions policy, spending limits or runner provisioning specific to this repository/account; those settings have not been independently inspected. Do not label CI green or blame source code without an executed step and diagnostic output.

## Vercel deployment checks

The commit status for the relevant revisions reported:

- `Vercel – smart-shelf-ai-r5gl`: failure, target URL indicates `build-rate-limit`.
- `Vercel – smart-shelf-ai`: failure or pending depending on the deployment revision; a prior status explicitly reported the same build-rate-limit destination.

This is a deployment quota/rate-limit signal, not evidence of an application compilation error. Repeated commits or forced deployments should not be used as a workaround for a provider limit.

## Follow-up procedure

1. The minimal diagnostic and its retry both failed before the first step. Check GitHub Actions service status, repository Actions enablement, account/organization spending limits and runner policies; escalate to GitHub Support with run/job IDs if those checks are normal.
2. Once a fresh minimal job executes, rerun API CI and quality gates. Diagnose actual Python/TypeScript failures from their step logs.
3. Respect the Vercel build rate limit; resume deployment after the provider allows it rather than changing application code to hide the status.

See [GitHub's workflow run logs guide](https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs) and [workflow troubleshooting guide](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows).


## Follow-up on application changes (2026-11-15)

After the new disposition migration, API endpoint, tests and PostgreSQL smoke script were committed, API CI run `43777489500` also failed before recording any step (`steps: []`, `logs_url: null`). Quality-gates run `43777523625` showed the same pre-step failure for both API and web jobs. This repeats the runner/log symptom on independent jobs and still provides no application-level test result.


The final implementation revision checked in this session, `866f75087b17920b1b5743ec08a578248c46e1f5`, reproduced the same result: API CI run `43777605958` has an empty step list and `logs_url: null`; quality-gates run `43777605937` has the same result for both API and web jobs. The minimal diagnostic retry also failed before its first step. No source-level test result is available from these runs.

After the final database-lineage hardening, API CI run `43777686506` and quality-gates run `43777694940` again failed before any step; the API job and both quality jobs expose empty step lists. This confirms that the latest revisions still have no CI execution evidence.

The database-enforced store-lineage hardening was included in API CI run `43777743145`; that job again failed with `steps: []` and `logs_url: null`, so the new PostgreSQL smoke script has not yet executed in CI.

On 2026-11-16, after the database-enforced disposition state machine and PostgreSQL smoke-test updates, API CI run `43778281274` and quality-gates run `43778281369` again completed as failures with empty step lists and `logs_url: null` for every job. This confirms that neither the new migration trigger nor the PostgreSQL smoke test has been executed by Actions in these runs.

A execução do API CI `43778382827` e do quality-gates `43778382853`, já sobre o commit `0672dc9f04eaac1a357bb9902c1b671126b25fa6`, voltou a terminar sem executar passos (`steps: []`, `logs_url: null`). A migração 0034 inclui agora também a remoção dos triggers de validação no downgrade; esta alteração ainda não foi executada num PostgreSQL real devido à falha de inicialização do runner.


## Follow-up: sequência imutável de disposição (2026-11-16)

A revisão que introduziu `sequence_number` por referência de artefacto, a preservação obrigatória do ator e a ordenação da pré-validação foi publicada na `main`. O Quality Gates run `43779001311` voltou a falhar antes de executar qualquer passo: os jobs API e Web têm `steps: []` e `logs_url: null`. O API CI `43778982758` também terminou com a mesma ausência de passos. Assim, a alteração está publicada, mas a migração, os triggers e o smoke test PostgreSQL ainda não têm resultado de execução CI. Não interpretar estes X como falha de teste do código.


## Signed inventory and migration repair (2026-11-16)

A revisão posterior encontrou e corrigiu dois problemas de implementação antes de continuar: a consulta de pré-validação agora associa o último evento pela chave composta (artefacto, sequência), e a migração `0034` foi reconstruída porque continha blocos duplicados/dangling e mais de uma definição de `downgrade`. A versão corrigida tem uma única função `upgrade`, uma única `downgrade` e cria os triggers SQLite de validação de estado e append-only.

Foi acrescentado o contrato de inventário externo assinado: helper HMAC-SHA-256 canónico, configuração `ARTIFACT_INVENTORY_HMAC_KEYS_JSON`, migração `0035`, modelo append-only, endpoint de ingestão com cobertura exata, validação de frescura e comparação no purge preview. Os testes novos cobrem canonicalização, assinatura, adulteração, cobertura e o facto de o executor de purge continuar desativado.

Os runs `43780304352` (API CI) e `43780304344` (Quality Gates), para o commit `46b16343f1c62c0e60a0565d978cad0f561d3c54`, voltaram a terminar com falha antes de iniciar qualquer step: job API `steps: []`, jobs Web/API `steps: []`, `logs_url: null`. Nenhum teste, compilação Python ou build TypeScript foi executado nesses runs. A implementação está publicada, mas a validação runtime continua pendente.


## Estado após a atestação HMAC (2026-11-16, 00:33 UTC)

A implementação foi reforçada com a declaração assinada obrigatória `inventory_complete: true`, validação dos contadores contra o manifesto guardado, rejeição da reutilização de `snapshot_id` com assinatura diferente e invalidação automática da cobertura quando uma nova referência é registada depois do snapshot. O preview revalida a assinatura com a chave atualmente configurada, a idade, a cobertura, os eventos e a ausência de todos os artefactos. Mesmo quando estas condições passam, mantém `purge_executor_not_implemented` e `eligible: false`.

Os runs mais recentes `43780986800` (API CI) e `43780986819` (Quality Gates), para `c3debd8dc107bf70522e69f63917ba104afa6d04`, continuam sem executar passos (`steps: []`, `logs_url: null`). O estado dos dois checks Vercel para esse commit continua a apontar para `build-rate-limit`. Não há confirmação de execução dos testes, migrações, compilação ou build nesta revisão.

O run seguinte, `43781100724`, associado ao commit `3729c529f3f2fe77cc8a258f3f5204561ca61373`, também terminou em falha com ambos os jobs (`Web TypeScript and production build` e `API tests and Python compilation`) sem passos (`steps: []`). Confirma-se que não foi executado qualquer comando de teste/build neste run.


## Runner provisioning isolated from workflow code (2026-11-16, 00:39 UTC)

A nova notificação do run `43781135963` foi investigada ao nível dos jobs. Os dois jobs iniciaram e terminaram em aproximadamente 1–2 segundos, mas a API do GitHub devolve `runner_id: 0`, `runner_name: ""`, `runner_group_name: ""`, `steps: []` e `logs_url: null`. Isto significa que nenhum runner foi atribuído e nenhum step foi iniciado; não é evidência de falha dos testes Python ou da compilação TypeScript.

Foi introduzido um workflow mínimo de diagnóstico independente de checkout, dependências e código da aplicação. O run `43781531179`, com `runs-on: ubuntu-latest`, falhou no mesmo estado: runner ID zero, sem nome e sem steps. Para excluir um problema específico da etiqueta `ubuntu-latest`, o diagnóstico foi repetido com `runs-on: ubuntu-24.04`; o run `43781577353` voltou a falhar antes do primeiro step, também com runner ID zero. Os quality gates `43781531099` e `43781577446` tiveram o mesmo resultado.

Os refs `actions/checkout@v7`, `actions/setup-python@v7` e `actions/setup-node@v7` foram confirmados como tags existentes no GitHub; portanto, não são refs inexistentes. A evidência disponível aponta para falha de provisionamento/atribuição de GitHub-hosted runners ou política/limite da conta/repositório. A integração disponível não expõe as definições administrativas de Actions, billing ou runner groups; não é possível determinar qual dessas causas se aplica sem a anotação interna do check-run ou acesso às definições administrativas.

A sonda fica agora acionável manualmente (`workflow_dispatch`) e também corre quando o próprio ficheiro é alterado, evitando acrescentar uma execução de diagnóstico a cada push normal. Não foi alterada a etiqueta dos workflows de produção/CI com base numa causa que ainda não está provada.

Na ligação Vercel atualmente disponível, a equipa `smpsandro1239's projects` é identificada como plano Hobby, mas a listagem de projetos acessível não devolve projetos ligados. O estado GitHub continua a mostrar o check `Vercel – smart-shelf-ai-r5gl` como `build-rate-limit`; sem acesso ao projeto e aos eventos de deployment não é possível inspecionar os logs de build nem corrigir a quota a partir desta integração.

A repetição com etiqueta explícita `ubuntu-24.04` foi concluída no run `43781732116` e confirmou novamente `runner_id: 0`, `runner_name: ""` e `steps: []`; a execução mínima não chega sequer ao comando `python --version`. No mesmo commit, `43781732099` falhou nos dois quality jobs pelo mesmo motivo. Depois da última alteração no helper HMAC, os runs `43781832634` (API CI) e `43781832721` (Quality Gates) voltaram a falhar com `runner_id: 0` e `steps: []`. Isto mantém a conclusão: o bloqueio atual é anterior à execução do código e é transversal às workflows e às duas imagens Ubuntu testadas.
