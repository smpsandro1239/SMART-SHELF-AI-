# Manifesto assinado de modelos ONNX

## Objetivo e fronteira de confiança

O provider ONNX real só deve carregar pesos que cumpram simultaneamente três condições:

1. O manifesto é JSON válido e segue o schema suportado.
2. A assinatura Ed25519 é válida para uma chave pública explicitamente confiada pelo deployment.
3. Os SHA-256 assinados correspondem exactamente aos ficheiros ONNX montados no container.

As variáveis SHA-256 continuam a funcionar como segunda confirmação operacional. Não substituem a assinatura. A chave privada de assinatura pertence ao processo de release e nunca deve existir no repositório, na imagem Docker, no container de inferência ou no volume de modelos.

## Formato do manifesto

O ficheiro é um envelope com `payload` e `signature`. A assinatura Ed25519 cobre os bytes UTF-8 do payload serializado em JSON canónico: chaves ordenadas, separadores compactos e ASCII escapado.

```json
{
  "payload": {
    "schema_version": 1,
    "key_id": "release-2026",
    "detector_sha256": "<64 caracteres hexadecimais minúsculos>",
    "embedding_sha256": null
  },
  "signature": "<assinatura Ed25519 em Base64>"
}
```

Quando existe embedder, `embedding_sha256` é obrigatório e tem de corresponder ao ficheiro configurado. Sem embedder, o campo tem de ser `null`. O payload rejeita campos desconhecidos, campos em falta, chaves JSON duplicadas e versões de schema não suportadas.

## Configuração do deployment

Definir no ambiente do host, antes de iniciar API e worker:

- `VISION_PROVIDER_MODE=real`
- `VISION_DETECTOR_MODEL_PATH=/models/shelf-detector.onnx`
- `VISION_DETECTOR_MODEL_SHA256=<sha256 aprovado>`
- `VISION_MODEL_MANIFEST_PATH=/models/manifest.json`
- `VISION_MODEL_TRUSTED_KEYS_JSON={"release-2026":"<Base64 da chave pública Ed25519 raw de 32 bytes>"}`
- `VISION_CLASS_LABELS_JSON={"0":"product"}`

Se existir embedder, configurar também `VISION_EMBEDDING_MODEL_PATH` e `VISION_EMBEDDING_MODEL_SHA256`. O manifesto, detector e embedder são lidos a partir do volume de modelos montado como read-only.

O keyring contém apenas chaves públicas. O serviço rejeita key IDs desconhecidos, chaves que não tenham exactamente 32 bytes, assinaturas que não tenham 64 bytes, ficheiros de manifesto acima de 64 KiB e keyrings acima de 16 KiB/32 chaves. Os caminhos do manifesto e modelos não podem ser symlinks.

## Processo de release

1. Aprovar o modelo, os rótulos/classes, o pré-processamento e os resultados de avaliação fora do runtime.
2. Calcular os SHA-256 dos pesos aprovados e disponibilizar os pesos e o manifesto no volume read-only.
3. Assinar o manifesto num ambiente de release controlado, com a chave privada Ed25519 protegida. Nunca copiar a chave privada para o deployment.
4. Publicar no deployment apenas o manifesto, os modelos e a chave pública confiável.
5. Configurar os SHA-256 no ambiente e iniciar primeiro em ambiente de validação.
6. Confirmar que API e worker rejeitam qualquer divergência antes de carregar o runtime ONNX.

Utilitário de assinatura:

```bash
python apps/api/scripts/create_vision_model_manifest.py \
  --key-id release-2026 \
  --private-key-pem /caminho-protegido/release-ed25519.pem \
  --detector ./models/shelf-detector.onnx \
  --output ./models/manifest.json
```

Acrescentar `--embedding ./models/shelf-embedder.onnx` quando existir embedder. O utilitário suporta PEM Ed25519 encriptado e solicita a passphrase interactivamente. O ficheiro de chave privada deve permanecer no ambiente de release.

## Comportamento fail-closed

O provider real falha antes da criação de sessões ONNX se faltar o caminho do manifesto, o keyring, um digest aprovado, se a assinatura for inválida, se a chave não for confiável, se o schema for inválido ou se os bytes do modelo não corresponderem ao manifesto. O modo mock/desactivado não carrega nem exige manifesto.

A verificação da assinatura autentica a aprovação dos bytes identificados pelo manifesto; não demonstra precisão, segurança semântica ou adequação comercial do modelo. Também não impede, por si só, a reutilização de um manifesto antigo que continue assinado por uma chave confiável. A prevenção de rollback requer política de release/versão monotónica e estado persistente de versão mínima, ainda não implementados. A rotação/revogação de chaves deve ser feita actualizando o keyring de confiança e reiniciando API e worker.

## Testes

A suite cobre assinatura válida, chave desconhecida, assinatura inválida, ficheiro adulterado, hash de embedder incorrecto, divergência entre embedder e configuração, JSON malformado/ambíguo e keyrings ausentes ou malformados. A aprovação CI continua a ser necessária antes de considerar esta funcionalidade validada.
