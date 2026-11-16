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
