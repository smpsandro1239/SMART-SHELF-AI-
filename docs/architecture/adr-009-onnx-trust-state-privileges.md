# ADR-009 — Isolar o estado de confiança de releases ONNX do principal runtime

**Estado:** aceite e implementado; camada read-only validada em `5e16a9cb`; serviço de provisionamento recorrente aguarda CI  
**Data:** 22-11-2026

## Contexto

A migration 0069 introduziu o high-water mark persistente e eventos append-only para releases ONNX. Os triggers PostgreSQL impedem regressões de versão, alterações de identidade, UPDATE/DELETE indevidos e TRUNCATE. Contudo, o principal runtime inicialmente recebia DML em todas as tabelas: podia tentar inserir eventos arbitrários ou avançar artificialmente o high-water mark. Os triggers impediam algumas alterações, mas não impediam um principal com UPDATE de provocar denial-of-service através de uma versão futura falsa.

A separação owner/runtime introduzida no Docker Compose resolve privilégios DDL, mas não é suficiente se o runtime continuar a escrever directamente no registo de confiança.

## Decisão

1. O principal de migrations é o owner das tabelas e executa Alembic no serviço one-shot `migrate`.
2. API e vision-worker usam `APP_DB_USER` e têm apenas SELECT nas tabelas `vision_model_release_states` e `vision_model_release_events`. Não recebem INSERT, UPDATE, DELETE, TRUNCATE nem privilégios da sequência de eventos.
3. O serviço one-shot `provision-runtime-role` executa o bootstrap idempotente em cada arranque Compose, antes de migrations, criando/reconciliando o papel em volumes novos e existentes. O papel é `NOINHERIT`; a migration 0070 revoga privilégios quando o papel já existe.
4. O provider ONNX não regista releases durante o arranque. O registo é uma operação explícita de deployment através de `register_vision_model_release.py`, exposta no Compose pelo perfil one-shot `register-model-release`.
5. O CLI verifica novamente assinatura Ed25519, hashes dos artefactos, digests configurados e identidade de deployment; exige que o utilizador da ligação seja o owner da tabela de confiança.
6. Verificações e registos usam o mesmo advisory transaction lock, calculado a partir do identificador estável de deployment. O runtime consegue serializar a leitura com o registo sem obter privilégios UPDATE ou usar SELECT FOR UPDATE.
7. As triggers de monotonicidade e append-only permanecem como defesa em profundidade contra erros e caminhos de escrita autorizados.

## Alternativas consideradas

- **Manter DML no runtime e confiar apenas nos triggers:** rejeitada; um UPDATE permitido poderia elevar arbitrariamente o high-water mark e bloquear releases legítimas.
- **SECURITY DEFINER para registar releases:** rejeitada nesta fase; a função teria de confiar em parâmetros que o mesmo runtime comprometido poderia forjar, sem verificar Ed25519 no servidor.
- **Credenciais owner na API/worker:** rejeitada; alargaria o impacto de comprometimento do processo e anularia a separação de privilégios.
- **Conexão separada de trust dentro da API/worker:** rejeitada; as credenciais privilegiadas continuariam presentes no mesmo processo e superfície de ataque.
- **Registo explícito por processo de deployment:** escolhida; limita a escrita ao operador/deployment com acesso ao owner e mantém os processos de inferência read-only.

## Consequências

- O provider real falha fechado se a release ainda não estiver registada. O operador tem de executar `docker compose --profile model-release run --rm register-model-release` antes de activar a inferência real.
- A rotação/actualização de modelos passa a ser uma operação de deployment auditável e separada do arranque/restart da API e worker.
- O runtime continua a poder adquirir advisory locks e ler o estado de confiança; não consegue avançar, apagar ou fabricar directamente o estado.
- Em volumes existentes, o serviço `provision-runtime-role` reconcilia grants automaticamente antes das migrations; a rotação de credenciais continua a exigir rollout coordenado dos processos.
- A suite API executada com owner não prova por si só que todos os fluxos operacionais funcionam com o runtime. O smoke de privilégios e o Docker Compose smoke são gates separados.
- O owner continua a ser uma identidade privilegiada; deve ficar limitada ao serviço de migrations e à operação explícita de registo, com segredos protegidos fora do repositório.

## Evidência e validação

- Migration: `apps/api/migrations/versions/0070_vision_model_trust_runtime_readonly.py`.
- Bootstrap: `infra/postgres/10-create-runtime-role.sh`.
- Serviço: `apps/api/app/vision_model_release.py`.
- Provider: `apps/api/app/vision_onnx.py`.
- CLI: `apps/api/scripts/register_vision_model_release.py`.
- Smoke: `apps/api/scripts/postgres_runtime_role_smoke.py`.
- CI: API CI e Docker Compose smoke executam os testes com PostgreSQL 16 e o principal runtime.

A camada read-only foi validada no SHA `5e16a9cb` (API CI, Quality Gates, Security Scans e Compose; 1552 passed, 1 skipped). A alteração do serviço recorrente `provision-runtime-role` e `NOINHERIT` aguarda nova CI e validação de volume legado. A decisão não autoriza a activação do provider real sem pesos licenciados, dataset autorizado, avaliação independente e aprovação operacional.
