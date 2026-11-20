# Reconciliação de ficheiros de outputs de datasets

## Objectivo

O módulo `app.dataset_job_output_reconciliation` identifica temporários de promoção abandonados e cópias de staging que permaneceram depois de uma publicação já confirmada. A ferramenta é manual e conservadora; não existe scheduler nem limpeza automática em background.

## Modo de simulação

Executar dentro do ambiente da API:

```bash
cd apps/api
python -m app.dataset_job_output_reconciliation --grace-hours 168
```

O modo predefinido é read-only. O relatório separa temporários de promoção, staging elegível, staging órfão sem publicação, outputs finais sem registo de publicação, ficheiros ignorados, número de candidatos e número de remoções. Os campos `orphan_staging` e `orphan_published` são exclusivamente informativos e nunca são apagados, mesmo com `--apply`.

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

## Falha na limpeza de staging depois do commit

A remoção do staging ocorre apenas depois do commit SQL da publicação. Se o processo não tiver permissões para remover o ficheiro, a publicação permanece concluída e o staging fica como resíduo recuperável. O reconciliador pode removê-lo mais tarde quando a linha append-only da publicação, o job concluído, o destino canónico e o digest/tamanho de ambos os ficheiros coincidirem e o período de segurança tiver expirado.

Este cenário não é equivalente a staging órfão sem publicação: nesse caso continua a não existir prova suficiente para apagar o ficheiro e a ferramenta mantém apenas inventário report-only.


## Inventário de outputs finais sem registo SQL

O reconciliador percorre apenas directórios numéricos e ficheiros regulares com o nome canónico `<fencing-token>-<sha256>.artifact`. Se não encontrar a referência numa linha append-only de publicação, e o ficheiro tiver ultrapassado o período de segurança, adiciona-o a `orphan_published` com job status, digest e tamanho. Não segue symlinks e não calcula que o nome do ficheiro prove integridade: o digest no nome é apenas uma pista para investigação.

Esta categoria é sempre report-only, incluindo com `--apply`. Pode representar uma falha de commit SQL, uma publicação interrompida ou uma situação que exige reconciliação manual. Nunca é apagada automaticamente porque a ausência de uma linha SQL não prova que o ficheiro é descartável. A publicação retry continua a ser o caminho preferido quando o job e o worker mantêm autoridade válida.

## Durabilidade da árvore de armazenamento e recuperação de `fsync`

A promoção percorre a raiz e os componentes internos do caminho com abertura relativa a descritores de directório e `O_NOFOLLOW`. O caminho configurado não deve conter componentes simbólicos. Ao criar ou reutilizar componentes em modo de escrita, cada entrada é confirmada com `fsync` do directório-pai. Isto permite que uma repetição repare uma tentativa anterior em que a criação do directório teve sucesso mas a sincronização do pai falhou.

Antes de criar o hard link final, o conteúdo é copiado para um temporário no mesmo directório, verificado por tamanho e SHA-256 e sincronizado com `fsync` do ficheiro. Depois do hard link, o directório é sincronizado antes de a transacção SQL registar a publicação. Uma falha de sincronização antes do commit aborta a publicação e preserva o staging original; qualquer temporário residual é removido em modo best-effort.

Quando o destino determinístico já existe (por exemplo, depois de uma falha entre filesystem e SQL), a repetição não confia na sua mera existência. Reabre o ficheiro sem seguir symlinks, verifica tipo, tamanho, SHA-256 e estabilidade de identidade/metadados durante a leitura, sincroniza o próprio ficheiro e o directório que contém a entrada. Só depois pode continuar para o commit SQL.

A remoção de staging continua a ocorrer depois do commit. Se o unlink ou o `fsync` do directório de staging falhar, a publicação e a auditoria permanecem confirmadas. A API regista um aviso com o ID do job e o tipo de erro, sem incluir caminhos internos. Se o unlink tiver ocorrido mas o `fsync` falhar, a remoção pode não sobreviver a uma falha abrupta e o ficheiro poderá reaparecer após reinício; o reconciliador continua a ser a via segura para limpar resíduos quando a publicação, o job, o destino, o digest/tamanho e o período de segurança são confirmados.

Os testes de regressão cobrem falha do `fsync` do temporário, criação/sincronização da árvore de directórios, recuperação de destino existente, libertação de descritores após erro, e falha de sincronização da limpeza pós-commit. A validação CI no commit `4beb3f002b809de8ef50f9990a377db2f7f7c36d` passou com 1404 testes aprovados, 1 ignorado e 1 aviso.

**Limite da garantia:** `fsync` só oferece as garantias que o filesystem, driver, volume Docker e dispositivo subjacente realmente implementam. Os testes CI demonstram o tratamento das chamadas e falhas injectadas num runner Linux; não simulam perda física de energia, corrupção do volume, falha de hardware nem garantias de object storage remoto.
