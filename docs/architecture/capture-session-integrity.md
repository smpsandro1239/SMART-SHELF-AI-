# Integridade de sessões de captura e preparação de dados

## Objetivo

Impedir que fotografias quase idênticas da mesma sessão operacional sejam distribuídas por treino, validação e teste. O agrupamento atual por hash de imagem é uma proteção mínima: não impede leakage entre frames diferentes da mesma sequência, rajadas de uma câmara ou capturas repetidas por dispositivos diferentes.

## Modelo proposto

Introduzir uma entidade `capture_sessions` e associar cada `shelf_images` a uma sessão opcional.

Campos mínimos da sessão:
- `id`: identificador interno.
- `store_id`: loja proprietária, obrigatório.
- `shelf_id`: prateleira observada, obrigatório.
- `source_type`: `fixed_camera`, `robot` ou `mobile`.
- `source_device_id`: identificador pseudónimo do dispositivo, sem guardar credenciais ou números de série desnecessários.
- `started_at` e `ended_at`: timestamps UTC.
- `capture_mode`: `single`, `burst` ou `video_sample`.
- `created_by_user_id`: utilizador responsável, opcional para dispositivos registados.

Cada imagem deve manter `captured_at`, `sha256` e proveniência; a sessão acrescenta o contexto temporal e operacional sem substituir estes campos.

## Regras de integridade

1. Uma sessão pertence a uma única loja e prateleira.
2. Uma imagem ligada a uma sessão tem de pertencer à mesma prateleira e loja.
3. O dispositivo é identificado por ID pseudónimo gerido no sistema; nunca por token/API key.
4. Sessões fechadas não aceitam novas imagens, salvo reabertura auditada.
5. Sessões sem metadados permanecem válidas para operação, mas não são elegíveis para um split de treino garantidamente independente.
6. A chave de agrupamento para dataset passa a ser `session_id`; se for nula, usar um grupo conservador por hash e marcar a amostra como `SESSION_UNKNOWN`.
7. Nunca dividir imagens da mesma sessão por treino/validação/teste.
8. A separação final deve ainda ser temporal e, quando aplicável, por loja/dispositivo para medir generalização real.

## API implementada

- `POST /api/v1/capture-sessions`: criar sessão para uma prateleira da loja do utilizador autenticado.
- `GET /api/v1/capture-sessions`: listar sessões no âmbito da loja, com filtros `shelf_id`, `include_closed` e `limit`.
- `POST /api/v1/capture-sessions/{session_id}/close`: fechar sessão de forma idempotente.
- `POST /api/v1/shelf-images`: aceita agora `capture_session_id` opcional em multipart/form-data e valida prateleira, loja e estado aberto.
- `GET /api/v1/training-candidates/reviewed`: devolve `capture_session_id` e usa `session:{id}` como chave de agrupamento; imagens antigas sem sessão continuam agrupadas por SHA-256.

A criação e o fecho são reservados a ADMIN/SUPERVISOR; o upload de imagens mantém as permissões operacionais existentes. A migração `0016_capture_sessions` usa alteração em batch para suportar SQLite e PostgreSQL.

## API proposta

- `POST /api/v1/capture-sessions`: criar sessão.
- `GET /api/v1/capture-sessions/{session_id}`: consultar sessão no âmbito da loja.
- `POST /api/v1/capture-sessions/{session_id}/close`: fechar sessão.
- `POST /api/v1/shelf-images`: aceitar `capture_session_id` opcional e validar a pertença.
- `GET /api/v1/training-candidates/reviewed`: devolver `capture_session_id` e `group_key` estável.

As operações de criação/fecho devem ser auditáveis e sujeitas ao isolamento por loja já aplicado na API. A sessão não concede acesso adicional às imagens.

## Critérios de aceitação

- Uma imagem de uma sessão de outra loja é rejeitada.
- Uma imagem de outra prateleira não pode ser anexada à sessão.
- Uma sessão fechada rejeita novas imagens.
- O endpoint de candidatos devolve a mesma chave de grupo para todas as imagens da sessão.
- O auditor de dataset falha se uma sessão surgir em mais do que um split.
- Registos antigos sem sessão continuam consultáveis, mas são sinalizados como não agrupados por sessão.
- Testes cobrem ADMIN, SUPERVISOR e EMPLOYEE, incluindo tentativas cross-store.

## Estado e validação

Implementação publicada no backend e testes automatizados adicionados em `apps/api/tests/test_capture_sessions.py`. Os testes cobrem ciclo de vida, listagem, ligação de imagem, rejeição de prateleira incorreta, bloqueio de upload após fecho e agrupamento de candidatos. O workflow GitHub Actions `API CI` concluiu com sucesso no commit de testes `9f2cb7632c7869de301b9c9852fb409fd2188d69`.

## Sequência de implementação

1. Concluído: migração aditiva, modelos e schemas.
2. Concluído: endpoints, isolamento por loja e fecho idempotente.
3. Concluído: associação opcional no upload e validação de sessão aberta.
4. Concluído: candidatos supervisionados agrupados por sessão ou SHA-256 legado.
5. Em curso: auditor de split que falha perante a mesma sessão em mais do que um split.
6. Seguinte: integração no dashboard para iniciar/terminar sessões.

## Limites

Esta alteração não deve iniciar treino automático, copiar fotografias para terceiros, aprovar exemplares SKU nem alterar inventário. A utilização de imagens continua dependente de autorização, direitos, retenção e revisão de privacidade.


## Auditor de splits ligado ao contrato da API

O auditor `app.dataset_audit` reconhece, por ordem de precedência, `capture_group_id`, `capture_group_key`, `capture_session_id` e `sequence_id`. O identificador de base de dados é normalizado para `session:<id>`, alinhando a validação COCO com os candidatos devolvidos por `GET /api/v1/training-candidates/reviewed`. O SHA-256 continua a ser verificado independentemente como segunda barreira contra duplicados exatos.

Execução:

```bash
cd apps/api
python -m app.dataset_audit \
  --train /data/annotations/instances_train.json \
  --val /data/annotations/instances_val.json \
  --test /data/annotations/instances_test.json \
  --json-report /data/reports/split-audit.json
```

Os testes incluem agora fuga entre splits através de `capture_group_key` e `capture_session_id`, além do identificador canónico COCO.
