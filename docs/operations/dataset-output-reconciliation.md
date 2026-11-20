# Reconciliação de ficheiros de outputs de datasets

## Objectivo

O módulo `app.dataset_job_output_reconciliation` identifica temporários de promoção abandonados e cópias de staging que permaneceram depois de uma publicação já confirmada. A ferramenta é manual e conservadora; não existe scheduler nem limpeza automática em background.

## Modo de simulação

Executar dentro do ambiente da API:

```bash
cd apps/api
python -m app.dataset_job_output_reconciliation --grace-hours 168
```

O modo predefinido é read-only. O relatório separa temporários de promoção, staging elegível, staging órfão sem publicação, ficheiros ignorados, número de candidatos e número de remoções. O campo `orphan_staging` é exclusivamente informativo e nunca é apagado, mesmo com `--apply`.

## Aplicar a limpeza

Depois de rever o relatório, a eliminação exige a opção explícita:

```bash
python -m app.dataset_job_output_reconciliation --grace-hours 168 --apply
```

O período de segurança predefinido é sete dias. O CLI aceita entre uma hora e um ano; não reduzir esse período sem conhecer a duração máxima de operações de publicação e o comportamento dos workers no ambiente.

## Regras de segurança

- Temporários só são considerados quando têm o nome interno `.promotion-<32 hex>.tmp`, são ficheiros regulares (não symlinks) e excedem o período de segurança.
- Um ficheiro de staging só é elegível se existir uma linha append-only de publicação para o mesmo job/token, o job continuar `SUCCEEDED`, a referência de destino for canónica e o destino publicado corresponder ao digest e tamanho auditados.
- O próprio staging também tem de corresponder ao mesmo SHA-256 e tamanho antes de ser removido.
- Um job `SUCCEEDED` sem linha de publicação mantém o staging: esse ficheiro pode ainda ser necessário para uma repetição da promoção.
- Ficheiros recentes, caminhos não canónicos, symlinks, jobs desconhecidos e conteúdos divergentes são preservados.
- Staging antigo sem publicação é inventariado por job/token e classificado como job desconhecido, job concluído ainda promovível, token obsoleto, job terminal ou worker potencialmente activo.
- A classificação de staging órfão é sempre report-only, incluindo com `--apply`: lease/fencing na base de dados não prova que um processo antigo deixou de escrever no filesystem.
- A ferramenta não remove directórios vazios, fontes de treino, artefactos publicados, nem dados em object storage.
- A remoção de staging é posterior à publicação e à verificação dos dois conteúdos; a auditoria append-only nunca é alterada.

## Limitações

A limpeza é best-effort e tem de ser executada periodicamente por um operador ou por uma futura tarefa operacional controlada. O modo `--apply` deve ser usado apenas depois de inspeccionar a simulação e confirmar a configuração de armazenamento. O reconciliador inventaria staging antigo de jobs falhados/revogados, cancelados, desconhecidos e concluídos sem publicação, mas não o remove. Continua sem provar que um processo worker antigo deixou de escrever; a limpeza dessas categorias exige um contrato de isolamento/permissões filesystem entre API e worker e uma prova operacional de quiescência.

A implementação actual suporta apenas o filesystem local configurado por `DATASET_OUTPUT_STORAGE_PATH`. Não equivale a um adapter de object storage nem a uma política de retenção/legal hold para artefactos derivados.


## Regressão de symlinks

A suite API inclui também um caso em que um nome de temporário válido aponta por symlink para um ficheiro externo. O reconciliador deve ignorar a entrada e preservar tanto o link como o destino. Esta cobertura complementa a regra de só remover ficheiros regulares e nunca seguir symlinks.

## Recuperação após falha entre filesystem e SQL

A promoção cria o destino final com hard link sem sobrescrever um destino existente e só depois confirma a linha de publicação na base de dados. Se o commit SQL falhar, o destino verificado pode permanecer sem linha de auditoria, enquanto o staging original continua disponível. Uma repetição da promoção volta a validar o destino existente pelo SHA-256 e tamanho, cria a linha de publicação e só então tenta remover o staging.

Esta recuperação é intencionalmente conservadora: um destino existente com digest diferente é tratado como conflito de integridade; o reconciliador não inventaria nem apaga destinos publicados sem uma política explícita. O teste de regressão simula a falha do commit antes de a transação SQL ser confirmada e verifica a recuperação por retry. Não cobre falhas físicas do filesystem, perda de energia, garantias de durabilidade do volume Docker ou comportamento de storage remoto.

## Falha de sincronização do directório durante a promoção

A criação do hard link de destino é seguida por `fsync` do directório. Se essa sincronização falhar, a promoção aborta e reverte a transação SQL. O destino pode continuar visível no filesystem, mas a sua durabilidade após falha do sistema não está confirmada. O staging original é preservado.

Uma repetição não confia apenas na existência do destino: volta a abrir o ficheiro sem seguir symlinks e valida tipo, tamanho e SHA-256 antes de o reutilizar. Só depois regista a publicação e remove o staging. Este comportamento foi coberto por um teste com falha injectada de `fsync`; não constitui uma garantia contra perda de energia, corrupção do volume ou limitações do driver/storage subjacente.

