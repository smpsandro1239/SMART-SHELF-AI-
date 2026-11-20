# Isolamento filesystem entre API e vision-worker

## Fronteira aplicada

O armazenamento persistente está dividido em dois volumes Docker:

- `shelf_images` é montado na API em read-write em `/app/storage`; contém as capturas em `/app/storage/shelf-images`.
- `dataset_outputs` é montado apenas na API em read-write em `/app/storage/dataset-outputs`, e é explicitamente seleccionado por `DATASET_OUTPUT_STORAGE_PATH`.
- O `vision-worker` recebe apenas `shelf_images`, em read-only, e não recebe qualquer mount de `dataset_outputs`.

O mount aninhado de `dataset_outputs` separa fisicamente staging e publicações de outputs do volume de imagens, sem alterar os caminhos relativos usados pelo serviço de publicação/consumo. O smoke `.github/workflows/demo-compose-smoke.yml` inspecciona os mounts efectivos: exige API read-write nos dois volumes, worker read-only em `shelf_images`, ausência de mount de datasets no worker e escrita temporária bem-sucedida pela API no directório de outputs.

## Hardening adicional do processo worker

O serviço `vision-worker` também executa com UID/GID `65532:65532`, `read_only: true`, `cap_drop: [ALL]` e `security_opt: [no-new-privileges:true]`. O único espaço temporário gravável é `/tmp`, montado como tmpfs limitado a 64 MiB, com `noexec`, `nosuid` e `nodev`. `HOME`, `XDG_CACHE_HOME` e `TMPDIR` apontam para `/tmp`. Os modelos continuam montados em modo só de leitura.

O smoke Docker Compose verifica a configuração efectiva através de `docker inspect` e executa uma asserção dentro do worker: UID efectivo 65532, `/tmp` gravável e `/app`, `/app/storage/shelf-images` e `/models` não graváveis.

## O que este controlo garante

O processo dentro do container `vision-worker` não pode criar, alterar ou apagar ficheiros no volume `shelf_images` através desse mount e não tem acesso ao volume `dataset_outputs`. Um worker antigo que continue a executar com esta configuração também fica sem capacidade de escrita no volume de imagens.

## O que não garante

- A identidade do worker é distinta da identidade predefinida da API, mas não existe ainda uma política completa de UID/GID e ownership para todos os serviços/volumes.
- O volume de outputs de datasets está separado e não é montado no worker de visão; ainda não existe worker remoto de transformação integrado no Compose.
- A API continua a ser a fronteira de escrita para ambos os volumes no stack demo; a separação não define ainda um handoff para um futuro worker de datasets.
- Não prova que um processo antigo terminou, nem que um container antigo com configuração anterior foi efectivamente parado.
- Não define a política de retenção nem autoriza purga física.
- Não constitui isolamento de segurança completo entre serviços; é uma redução específica da capacidade de escrita do worker sobre imagens de captura.

## Próximas etapas

1. Definir política uniforme de UID/GID para API, workers de datasets e tarefas operacionais, com migração de permissões testada em volumes existentes.
2. Definir um handoff controlado e mounts mínimos quando existir um worker de transformação de datasets; o worker remoto ainda não está integrado.
3. Introduzir prova operacional de quiescência/fencing físico antes de expandir a limpeza de staging órfão.
4. Testar uploads, inferência, promoção, consumo, retry, retenção e restauro em Docker Compose com a política de permissões final.

Não alterar ownership de volumes persistentes existentes nem activar limpeza de staging órfão sem testes de migração e recuperação.
