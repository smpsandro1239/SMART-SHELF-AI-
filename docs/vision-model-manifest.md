# Manifesto assinado e confiança persistente de modelos ONNX

## Objetivo e fronteira de confiança

O provider ONNX real só carrega pesos quando todas estas condições são satisfeitas:

1. O manifesto é JSON UTF-8 válido, sem chaves duplicadas, e segue o schema v2.
2. A assinatura Ed25519 é válida para uma chave pública explicitamente confiada pelo deployment.
3. A chave não consta da lista explícita de chaves revogadas.
4. Os SHA-256 assinados correspondem exactamente aos ficheiros ONNX montados no container.
5. O deployment aceita a versão através do registo persistente de releases, sem rollback ou colisão de versão.
6. O runtime continua a executar a versão exacta registada; um worker obsoleto deixa de poder publicar inferências.

As variáveis SHA-256 continuam a funcionar como segunda confirmação operacional. Não substituem a assinatura. A chave privada pertence ao processo de release e nunca deve existir no repositório, na imagem Docker, no container de inferência ou no volume de modelos.

## Formato do manifesto — schema v2

O manifesto é um envelope com `payload` e `signature`. A assinatura Ed25519 cobre os bytes UTF-8 do payload serializado em JSON canónico: chaves ordenadas, separadores compactos e ASCII escapado.

```json
{
  "payload": {
    "schema_version": 2,
    "key_id": "release-2026",
    "model_id": "shelf-detector",
    "release_version": 12,
    "detector_sha256": "<64 caracteres hexadecimais minúsculos>",
    "embedding_sha256": null
  },
  "signature": "<assinatura Ed25519 em Base64>"
}
```

- `model_id` é a identidade estável do modelo dentro do deployment slot.
- `release_version` é um inteiro positivo de 32 bits, estritamente crescente por deployment.
- `key_id` identifica a chave de release e está incluído na assinatura.
- `embedding_sha256` é obrigatório quando existe embedder; sem embedder tem de ser `null`.
- Campos desconhecidos, campos em falta, JSON ambíguo, schema v1, versões inválidas e hashes malformados são rejeitados.

Os manifestos schema v1 deixam de ser aceites pelo provider real. Os releases têm de ser novamente assinados com schema v2.

## Registo persistente anti-rollback

A migration `0069_vision_model_release_trust_state` cria:

- `vision_model_release_states`: um high-water mark por `deployment_id`, com `model_id`, maior `release_version`, digest canónico do payload assinado, `key_id` e digests dos modelos.
- `vision_model_release_events`: trilho append-only de releases aceites e tentativas rejeitadas.

O serviço `app.vision_model_release` usa uma transacção e bloqueio da linha para serializar upgrades concorrentes. A primeira inicialização cria o high-water mark. Depois:

- versão superior: aceite e persistida;
- mesma versão + mesmo manifesto: retry idempotente;
- mesma versão + manifesto diferente: rejeitado como colisão;
- versão inferior: rejeitada e registada como rollback;
- mudança de `model_id` no mesmo deployment slot: rejeitada.

Triggers PostgreSQL e SQLite impedem diminuir/apagar o high-water mark, alterar a identidade do modelo ou modificar/eliminar eventos de auditoria; PostgreSQL também bloqueia `TRUNCATE` das duas tabelas. O downgrade da migration recusa-se a remover o estado quando já existe pelo menos um release aceite. Esta protecção é intencionalmente não reversível por downgrade normal.

`VISION_MODEL_DEPLOYMENT_ID` identifica o slot lógico e tem de permanecer estável entre reinícios e réplicas que partilham a mesma política de release. API e worker recebem o mesmo valor através do Docker Compose. Em `APP_ENV=production`, o valor tem de ser explícito e diferente de `default`; apenas desenvolvimento/testes usam o fallback `default`. Não o alteres para contornar uma versão mínima; slots independentes exigem uma decisão de arquitectura e isolamento próprios.

O provider constrói e valida as sessões ONNX antes de avançar o high-water mark. A cada inferência verifica o release actual antes e depois do cálculo. O worker volta a verificar a versão dentro da transacção que publica deteções e mantém o lock da linha de confiança até ao commit. Se uma versão mais recente for aceite durante uma inferência, o resultado antigo não é persistido, a captura volta a `PENDING` e o worker obsoleto termina para reiniciar com a configuração actual.

A disponibilidade da base de dados é obrigatória no modo ONNX real. Falhas de leitura/escrita do registo bloqueiam o arranque ou a inferência; não existe fallback para ficheiros locais ou memória.

## Configuração do deployment

Definir no ambiente do host antes de iniciar API e worker:

- `VISION_PROVIDER_MODE=real`
- `VISION_PROVIDER_FACTORY=app.vision_onnx:create_provider`
- `VISION_DETECTOR_MODEL_PATH=/models/shelf-detector.onnx`
- `VISION_DETECTOR_MODEL_SHA256=<sha256 aprovado>`
- `VISION_MODEL_MANIFEST_PATH=/models/manifest.json`
- `VISION_MODEL_TRUSTED_KEYS_JSON={"release-2026":"<Base64 da chave pública Ed25519 raw de 32 bytes>"}`
- `VISION_MODEL_REVOKED_KEY_IDS_JSON=[]`
- `VISION_MODEL_DEPLOYMENT_ID=<identificador estável do slot>`
- `VISION_CLASS_LABELS_JSON={"0":"product"}`

Se existir embedder, configurar também `VISION_EMBEDDING_MODEL_PATH` e `VISION_EMBEDDING_MODEL_SHA256`. O manifesto, detector e embedder são lidos a partir do volume de modelos montado como read-only.

O keyring contém apenas chaves públicas. O serviço rejeita key IDs desconhecidos/revogados, chaves que não tenham exactamente 32 bytes, assinaturas que não tenham 64 bytes, ficheiros de manifesto acima de 64 KiB e keyrings acima de 16 KiB/32 chaves. Os caminhos do manifesto e modelos não podem ser symlinks.

## Processo de release e assinatura offline

1. Aprovar o modelo, rótulos/classes, pré-processamento e resultados de avaliação fora do runtime.
2. Atribuir um `model_id` estável e escolher uma `release_version` superior à versão actualmente registada.
3. Calcular os SHA-256 dos pesos aprovados e disponibilizar pesos e manifesto no volume read-only.
4. Assinar o manifesto num ambiente de release controlado, com a chave privada Ed25519 protegida.
5. Publicar no deployment apenas o manifesto, modelos e chave pública confiável.
6. Iniciar API/worker em ambiente de validação e confirmar a aceitação do release no registo persistente.
7. Verificar que os workers estão a executar o mesmo `deployment_id` e a versão aprovada.

Utilitário:

```bash
python apps/api/scripts/create_vision_model_manifest.py \
  --key-id release-2026 \
  --model-id shelf-detector \
  --release-version 12 \
  --private-key-pem /caminho-protegido/release-ed25519.pem \
  --detector ./models/shelf-detector.onnx \
  --output ./models/manifest.json
```

Acrescentar `--embedding ./models/shelf-embedder.onnx` quando existir embedder. O utilitário suporta PEM Ed25519 encriptado e solicita a passphrase interactivamente. A chave privada permanece no ambiente de release.

## Rotação e revogação de chaves

A rotação normal deve preservar a continuidade:

1. Gerar uma nova chave Ed25519 e um novo `key_id` fora do repositório.
2. Adicionar a nova chave pública ao `VISION_MODEL_TRUSTED_KEYS_JSON`, mantendo temporariamente a anterior.
3. Assinar um novo manifesto schema v2 com a nova chave e `release_version` superior.
4. Distribuir manifesto, pesos e keyring; reiniciar os workers e confirmar que o high-water mark e o evento `ACCEPTED` reflectem o novo release.
5. Só depois de todas as instâncias estarem no novo release, remover a chave antiga do keyring e acrescentar o seu ID a `VISION_MODEL_REVOKED_KEY_IDS_JSON`.
6. Reiniciar as instâncias e confirmar que manifestos assinados pela chave antiga são rejeitados.

A revogação explícita prevalece mesmo que a chave permaneça acidentalmente no keyring. Omitir uma chave do keyring também a torna não confiável.

Em caso de comprometimento, revogar imediatamente a chave comprometida e distribuir uma versão assinada por uma chave independente. Um manifesto assinado pela chave revogada deixa de arrancar; esta interrupção é preferível a aceitar pesos cuja cadeia de confiança foi comprometida. Nunca baixar a versão nem apagar o high-water mark para recuperar um deployment.

## Comportamento fail-closed e limitações

O provider real falha antes da inferência se faltar manifesto, trust root, digest, estado persistente, se a assinatura for inválida, se a chave estiver revogada/desconhecida, se o schema for inválido, se os pesos divergirem ou se a versão tentar retroceder. A indisponibilidade do PostgreSQL também bloqueia a inferência.

A assinatura autentica a aprovação dos bytes identificados pelo manifesto; o high-water mark impede rollback dentro do deployment slot. Os triggers protegem contra DML acidental/malicioso sem privilégios de DDL, mas um owner/superuser PostgreSQL pode alterar schema ou desactivar triggers. Antes de produção, separar o principal de migrations do principal runtime e retirar a este último permissões de DDL, ALTER, TRUNCATE e gestão de triggers. O Compose de demonstração ainda não implementa essa separação. Nenhum destes mecanismos demonstra precisão, segurança semântica ou adequação comercial do modelo. Continuam necessários pesos autorizados, dataset anotado independente, métricas reproduzíveis por SKU/cenário, revisão de licenças e aprovação operacional.

O modo mock/desactivado não carrega nem exige manifesto nem registo anti-rollback. O Docker Compose local continua a usar o provider mock por omissão; não activar o modo real sem pesos autorizados e avaliação independente.

## Testes e evidência exigida

- Testes unitários de assinatura, schema v2, IDs, versões, revogação e integridade dos pesos.
- Testes de registo: primeira aceitação, retry idempotente, upgrade, rollback, colisão de versão e mudança de identidade.
- Migration SQLite: high-water mark monotónico, estado não eliminável, eventos append-only e downgrade bloqueado quando há releases.
- Smoke PostgreSQL: concorrência entre upgrades, rejeição de runtime obsoleto e guards SQL.
- API CI: migration PostgreSQL 16, smoke dedicado e suite pytest.
- Quality Gates e Security Scans para o SHA final.

A execução destes testes não equivale a avaliação da precisão do detector. Não existem métricas reais publicáveis enquanto não existir dataset autorizado e avaliação independente.


## Separação entre principal de migrations e principal runtime

Em Docker Compose, o serviço one-shot `migrate` aplica as migrations com o principal owner da base de dados. API e vision-worker usam `APP_DB_USER`/`APP_DB_PASSWORD`, um principal separado com apenas `CONNECT`, `USAGE` no schema, DML nas tabelas e acesso às sequências. Não recebe `CREATE`, `TRUNCATE`, `ALTER`, gestão de triggers nem propriedade dos objetos. As permissões default são configuradas para que novas tabelas e sequências criadas pelo principal de migrations também fiquem acessíveis ao runtime.

O bootstrap `infra/postgres/10-create-runtime-role.sh` é executado automaticamente apenas quando o volume PostgreSQL é inicializado pela primeira vez. Para volumes já existentes, após configurar as credenciais runtime, executa explicitamente:

```bash
docker compose exec db bash /docker-entrypoint-initdb.d/10-create-runtime-role.sh
```

Este script actualiza a palavra-passe e os grants de forma idempotente. Em produção, usa segredo forte e único para `APP_DB_PASSWORD`; nunca reutilizes a palavra-passe do owner. A migração continua a correr como owner e a API não executa Alembic no arranque. A configuração de Compose e os testes estáticos não substituem o smoke PostgreSQL com as credenciais runtime nem a validação no deployment alvo.
