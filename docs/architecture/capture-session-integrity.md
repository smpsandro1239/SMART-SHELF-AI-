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

## Sequência de implementação

1. Migração aditiva: criar `capture_sessions` e adicionar `shelf_images.capture_session_id` nullable.
2. Modelos SQLAlchemy e schemas Pydantic.
3. Endpoints e validação de escopo por loja.
4. Integração no upload de imagens.
5. Atualização dos candidatos supervisionados.
6. Auditor de split por sessão e testes de regressão.
7. Atualizar documentação e dashboard para iniciar/terminar sessões de captura.

## Limites

Esta alteração não deve iniciar treino automático, copiar fotografias para terceiros, aprovar exemplares SKU nem alterar inventário. A utilização de imagens continua dependente de autorização, direitos, retenção e revisão de privacidade.
