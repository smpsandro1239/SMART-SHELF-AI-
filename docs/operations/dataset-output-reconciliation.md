# Reconciliação de ficheiros de outputs de datasets

## Objectivo

O módulo `app.dataset_job_output_reconciliation` identifica temporários de promoção abandonados e cópias de staging que permaneceram depois de uma publicação já confirmada. A ferramenta é manual e conservadora; não existe scheduler nem limpeza automática em background.

## Modo de simulação

Executar dentro do ambiente da API:

```bash
cd apps/api
python -m app.dataset_job_output_reconciliation --grace-hours 168
```

O modo predefinido é read-only. O relatório separa temporários de promoção, staging elegível, ficheiros ignorados, número de candidatos e número de remoções.

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
- A ferramenta não remove directórios vazios, fontes de treino, artefactos publicados, nem dados em object storage.
- A remoção de staging é posterior à publicação e à verificação dos dois conteúdos; a auditoria append-only nunca é alterada.

## Limitações

A limpeza é best-effort e tem de ser executada periodicamente por um operador ou por uma futura tarefa operacional controlada. O modo `--apply` deve ser usado apenas depois de inspeccionar a simulação e confirmar a configuração de armazenamento. O reconciliador actual não limpa staging de jobs falhados/revogados sem referência de publicação, nem prova que um processo worker antigo deixou de escrever; essas categorias exigem um contrato de isolamento/permissões filesystem entre API e worker.

A implementação actual suporta apenas o filesystem local configurado por `DATASET_OUTPUT_STORAGE_PATH`. Não equivale a um adapter de object storage nem a uma política de retenção/legal hold para artefactos derivados.
