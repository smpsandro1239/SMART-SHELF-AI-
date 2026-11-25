# Provider ONNX para visão computacional

## Estado

O provider está implementado como adaptador experimental CPU-first. A sua existência **não significa que o SMART-SHELF-AI já identifique produtos em produção**: são necessários dois modelos ONNX exportados para o contrato abaixo, imagens de validação autorizadas e calibração no conjunto de validação.

## 1. Contrato dos modelos

### Detetor

- Um input float32 com forma `[1, 3, H, W]`.
- RGB, valores entre 0 e 1.
- O tamanho quadrado é configurado por `VISION_INPUT_SIZE` (por defeito 640).
- Um output float32 com forma `[N, 6]` ou `[1, N, 6]`.
- Uma única entrada e uma única saída; o input tem de ser NCHW RGB com três canais e dimensões compatíveis com `VISION_INPUT_SIZE`.
- `class_id` tem de ser inteiro não negativo; confiança e coordenadas têm de estar em `[0, 1]`.
- Cada linha: `x1, y1, x2, y2, confidence, class_id`.
- Coordenadas normalizadas entre 0 e 1 relativamente à imagem quadrada de entrada.
- O modelo exportado tem de incluir NMS (Non-Maximum Suppression). O provider não interpreta raw YOLO heads nem executa NMS adicional.

O provider valida o contrato de metadados antes de inferir, desfaz o letterboxing, limita as caixas às dimensões originais e descarta caixas degeneradas e deteções abaixo do limiar. Scores, coordenadas e IDs não finitos/malformados são rejeitados.

### Extrator de embeddings (opcional)

- Um input com o mesmo contrato de imagem.
- Um output com um único vetor numérico por crop.
- O provider normaliza o vetor L2 antes de o entregar ao matching.
- `VISION_EMBEDDING_MODEL_VERSION` identifica os vetores e tem de coincidir com a versão usada nos exemplares aprovados do catálogo.

Sem extrator de embeddings, as caixas são persistidas como deteções visuais sem SKU identificado; o matching abstém com `UNKNOWN`. Só etiquetas incluídas em `VISION_SKU_MATCH_LABELS` podem gerar embeddings e entrar no matching de SKU. Por omissão, apenas `product` é elegível; classes como `empty_facing` continuam a ser evidência visual, nunca candidatos de catálogo. O worker repete esta whitelist antes de consultar exemplares, protegendo também providers alternativos.

## 2. Configuração local

Copiar `apps/api/.env.vision.example` como referência e colocar os pesos autorizados numa pasta local `models/` na raiz do repositório. Não versionar pesos, datasets ou imagens comerciais no Git.

Exemplo de variáveis no ficheiro `.env` da raiz:

```dotenv
VISION_PROVIDER_MODE=real
VISION_PROVIDER_FACTORY=app.vision_onnx:create_provider
VISION_CLASS_LABELS_JSON={"0":"product","1":"empty_facing"}
VISION_SKU_MATCH_LABELS=product
VISION_MODELS_DIR=./models
VISION_DETECTOR_MODEL_PATH=/models/shelf-detector.onnx
VISION_DETECTOR_MODEL_SHA256=<64-character-approved-sha256>
VISION_MODEL_MANIFEST_PATH=/models/manifest.json
VISION_MODEL_TRUSTED_KEYS_JSON={"release-2026":"<base64-public-key>"}
VISION_MODEL_REVOKED_KEY_IDS_JSON=[]
VISION_MODEL_DEPLOYMENT_ID=store-a-shelf-detector
VISION_EMBEDDING_MODEL_PATH=/models/product-embedder.onnx
VISION_EMBEDDING_MODEL_SHA256=<64-character-approved-sha256>
VISION_MODEL_VERSION=shelf-detector-v1
VISION_EMBEDDING_MODEL_VERSION=product-embedding-v1
VISION_INPUT_SIZE=640
VISION_CONFIDENCE_THRESHOLD=0.25
VISION_MAX_DETECTIONS=300
```

Para executar apenas deteção, deixar `VISION_EMBEDDING_MODEL_PATH` vazio; nesse caso, `VISION_EMBEDDING_MODEL_SHA256` não é necessário. O factory real exige sempre `VISION_DETECTOR_MODEL_SHA256` e exige `VISION_EMBEDDING_MODEL_SHA256` quando existe um extrator. Cada valor tem de ser um digest SHA-256 hexadecimal de 64 caracteres obtido a partir do artefacto aprovado, não um hash calculado e aceite automaticamente no arranque. O provider compara os digests configurados com os ficheiros antes de abrir sessões ONNX e volta a calcular os hashes depois de abrir cada sessão para detectar substituição durante o carregamento. O digest aprovado deve ser injectado por configuração de deployment protegida e revisto juntamente com a origem/licença do artefacto. O mapa JSON tem de corresponder exactamente à ordem/IDs de classe exportados pelo modelo. O provider verifica os SHA-256 dos pesos contra digests aprovados e calcula um fingerprint SHA-256 da configuração efectiva (digest dos pesos, mapa de classes, dimensão, threshold, limite de deteções e versão de pré-processamento). A versão persistida em cada deteção é `versão-configurada@fingerprint`; para o embedder, a versão efectiva inclui o fingerprint dos seus pesos e pré-processamento. Alterações ao modelo, labels ou configuração geram uma identidade diferente. As versões efectivas dos embeddings têm de ser usadas ao aprovar novos exemplares; exemplares aprovados sob uma versão anterior não são reutilizados automaticamente. Sem mapa de classes, o provider ONNX não arranca. O `class_id` devolvido pelo modelo é preservado até à resolução da etiqueta; um ID ausente no mapa interrompe a análise em vez de ser convertido em `product`. Não ativar o modo `real` até os pesos e a sua licença estarem aprovados.

O Compose monta a pasta de modelos em modo só de leitura. A API continua sem executar inferência: o processamento é feito pelo worker separado.

## 3. Manifesto assinado e prevenção de rollback

O provider real exige agora manifesto Ed25519 schema v2. O payload assinado liga `key_id`, `model_id`, `release_version` e SHA-256 dos pesos. O utilitário offline `apps/api/scripts/create_vision_model_manifest.py` exige `--model-id` e `--release-version`; releases antigos schema v1 têm de ser novamente assinados.

A migration `0069_vision_model_release_trust_state` mantém o high-water mark de cada `VISION_MODEL_DEPLOYMENT_ID` em PostgreSQL, com eventos append-only. Em produção, a identidade tem de ser explicitamente configurada e não pode usar `default`. Versões inferiores, colisões na mesma versão e alterações de `model_id` são recusadas. A lista `VISION_MODEL_REVOKED_KEY_IDS_JSON` bloqueia explicitamente chaves comprometidas mesmo que ainda estejam no keyring. API e worker recebem a mesma identidade de deployment através do Compose.

O provider verifica a release persistida antes/depois da inferência. O worker volta a validá-la e mantém um advisory transaction lock por deployment durante a transacção que publica deteções; o registo de uma nova release usa o mesmo lock. Assim, a API/worker precisa apenas de SELECT nas tabelas de confiança, não de UPDATE/INSERT para bloquear concorrência. Um worker obsoleto não publica resultados, devolve a captura a PENDING e termina para reiniciar com a release actual. A indisponibilidade do registo PostgreSQL bloqueia o modo real. O registo é uma operação explícita de deployment, executada pelo owner através de `docker compose --profile model-release run --rm register-model-release`; a API/worker não regista releases no arranque.

O processo de rotação de chaves, a revogação de emergência e o formato exacto do manifesto estão em [docs/vision-model-manifest.md](../vision-model-manifest.md). Não alterar `VISION_MODEL_DEPLOYMENT_ID` para contornar o high-water mark.

## 4. Execução do worker

Com API e base de dados disponíveis e as variáveis carregadas no ambiente do worker:

```bash
cd apps/api
python -m app.vision_worker --once
```

Para processamento contínuo:

```bash
python -m app.vision_worker --poll-interval 5
```

O worker exige uma escolha explícita de `VISION_PROVIDER_MODE`: `disabled` recusa processamento, `mock` só aceita `app.demo.vision:create_provider` e é recusado em `APP_ENV=production`, e `real` recusa o provider determinístico de demonstração. Para inferência real, configurar `VISION_PROVIDER_FACTORY=app.vision_onnx:create_provider`, pesos autorizados e o mapa `VISION_CLASS_LABELS_JSON`. O modo `disabled` é o default das Settings; o Compose usa explicitamente `mock` para o percurso local. A API não deve iniciar inferência síncrona durante o upload.

## 5. Dependências e execução

O provider utiliza ONNX Runtime CPU, NumPy e Pillow. O runtime permite carregar uma sessão ONNX e executar tensores através de `InferenceSession`; a seleção explícita de `CPUExecutionProvider` mantém a configuração reproduzível em máquinas sem GPU.

- [ONNX Runtime Python API](https://onnxruntime.ai/docs/api/python/api_summary)
- [ONNX Runtime — instalação e primeiros passos](https://onnxruntime.ai/docs/get-started/with-python.html)
- [Execution Providers](https://onnxruntime.ai/docs/execution-providers/)

## 6. Critérios antes de piloto

1. Confirmar a licença e proveniência do detetor, extrator e dados de treino.
2. Validar o contrato dos tensores com os modelos exportados reais.
3. Testar fotos com diferentes resoluções, proporções, reflexos, oclusões e densidade.
4. Calibrar confiança do detetor e limiares/margens de matching apenas na validação.
5. Medir latência CPU, memória e taxa de falhas.
6. Avaliar falsos SKU, desconhecidos e variantes visualmente semelhantes.
7. Manter o teste final separado e intocado.
8. Só depois ativar o worker num piloto controlado, com revisão humana.

## 7. Limitações conhecidas

- O provider espera output de deteção pós-NMS com seis colunas; não é um conversor universal de modelos YOLO.
- O mapa de classes converte `class_id` em etiquetas semânticas, mas ainda não identifica SKU; apenas labels explicitamente autorizadas em `VISION_SKU_MATCH_LABELS` geram embeddings/entram no matching. `empty_facing` não pode ser associado a um SKU.
- O provider recusa symlinks, valida os hashes assinados antes de abrir as sessões ONNX e volta a calcular os digests depois do carregamento para detectar substituição concorrente. A migration 0069 guarda separadamente o high-water mark, identidade do modelo, key ID e hashes aprovados.
- O extrator é opcional e requer exemplares aprovados na mesma versão de embedding.
- A assinatura autentica o release aprovado, não prova a qualidade nem a licença dos pesos. O deployment tem de proteger a chave pública confiável e a chave privada permanece offline.
- O provider não calcula quantidade física na prateleira, planograma, stock contabilístico ou quantidade a repor.
- Não foram incluídos pesos ONNX no repositório nem executado benchmark de um modelo real.


## 8. Geometria explícita de células — estado experimental

`app.shelf_layout` inclui agora `ShelfCell` e `compare_detections_to_cells`, que comparam caixas normalizadas com células fornecidas por calibração/planograma. O comparador devolve `OCCUPIED`, `OCCUPIED_UNIDENTIFIED`, `MISPLACED`, `EMPTY` ou `UNKNOWN`, preservando os índices das deteções e os SKU observados.

- Uma célula só pode ser considerada `EMPTY` quando a visibilidade foi explicitamente confirmada (`is_visible=True`) e não está marcada como ocluída.
- A visibilidade por omissão é falsa; uma célula sem calibração fica `UNKNOWN`.
- Células sobrepostas ou IDs duplicados são rejeitados.
- O comparador não cria planogramas, não estima profundidade/unidades físicas e não altera inventário.
- A geometria ainda não está persistida nem ligada à API, ao detector de regiões ou à interface. Os resultados são um primitivo determinístico para testes e futura integração supervisionada.
