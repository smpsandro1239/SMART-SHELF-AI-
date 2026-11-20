# Isolamento filesystem entre API e vision-worker

## Fronteira aplicada

O volume Docker persistente `shelf_images` é montado:

- na API em modo read-write, porque o endpoint de captura grava uploads e os fluxos administrativos de retenção operam sobre os ficheiros;
- no `vision-worker` em modo read-only (`shelf_images:/app/storage:ro`), porque o worker apenas resolve e lê a captura para executar inferência/OCR e persiste resultados na base de dados.

O smoke `.github/workflows/demo-compose-smoke.yml` inspecciona o container em execução com `docker inspect` e exige que o mount de `/app/storage` tenha `RW=false`. Assim, uma regressão na configuração Compose falha no CI.

## O que este controlo garante

O processo dentro do container `vision-worker` não pode criar, alterar ou apagar ficheiros no volume `shelf_images` através desse mount. Um worker antigo que continue a executar com esta configuração também fica sem capacidade de escrita nesse volume.

## O que não garante

- Não separa utilizadores/grupos Linux: API e worker continuam a usar a identidade definida pela mesma imagem Docker.
- Não protege outros mounts, o filesystem gravável do container ou o volume de outputs de datasets.
- Não prova que um processo antigo terminou, nem que um container antigo com configuração anterior foi efectivamente parado.
- Não define a política de retenção nem autoriza purga física.
- Não constitui isolamento de segurança completo entre serviços; é uma redução específica da capacidade de escrita do worker sobre imagens de captura.

## Próximas etapas

1. Definir UID/GID não privilegiados por serviço e permissões de directórios compatíveis com volumes já existentes.
2. Separar o staging de outputs de datasets do volume de imagens e criar um handoff controlado entre produtor e promotor.
3. Introduzir prova operacional de quiescência/fencing físico antes de expandir a limpeza de staging órfão.
4. Testar uploads, inferência, retry, retenção e restauro em Docker Compose com a política de permissões final.

Não alterar ownership de volumes persistentes existentes nem activar limpeza de staging órfão sem testes de migração e recuperação.
