# Provider ONNX para visão computacional

## Estado

O provider está implementado como adaptador experimental CPU-first. A sua existência **não significa que o SMART-SHELF-AI já identifique produtos em produção**: são necessários dois modelos ONNX exportados para o contrato abaixo, imagens de validação autorizadas e calibração no conjunto de validação.

## 1. Contrato dos modelos

### Detetor

- Um input float32 com forma `[1, 3, H, W]`.
- RGB, valores entre 0 e 1.
- O tamanho quadrado é configurado por `VISION_INPUT_SIZE` (por defeito 640).
- Um output com forma `[N, 6]` ou `[1, N, 6]`.
- Cada linha: `x1, y1, x2, y2, confidence, class_id`.
- Coordenadas normalizadas entre 0 e 1 relativamente à imagem quadrada de entrada.
- O modelo exportado tem de incluir NMS (Non-Maximum Suppression). O provider não interpreta raw YOLO heads nem executa NMS adicional.

O provider desfaz o letterboxing, limita as caixas às dimensões originais e descarta caixas degeneradas, scores inválidos e deteções abaixo do limiar.

### Extrator de embeddings (opcional)

- Um input com o mesmo contrato de imagem.
- Um output com um único vetor numérico por crop.
- O provider normaliza o vetor L2 antes de o entregar ao matching.
- `VISION_EMBEDDING_MODEL_VERSION` identifica os vetores e tem de coincidir com a versão usada nos exemplares aprovados do catálogo.

Sem extrator de embeddings, as caixas são persistidas como deteções visuais sem SKU identificado; o matching abstém com `UNKNOWN`.

## 2. Configuração local

Copiar `apps/api/.env.vision.example` como referência e colocar os pesos autorizados numa pasta local `models/` na raiz do repositório. Não versionar pesos, datasets ou imagens comerciais no Git.

Exemplo de variáveis no ficheiro `.env` da raiz:

```dotenv
VISION_PROVIDER_FACTORY=app.vision_onnx:create_provider
VISION_MODELS_DIR=./models
VISION_DETECTOR_MODEL_PATH=/models/shelf-detector.onnx
VISION_EMBEDDING_MODEL_PATH=/models/product-embedder.onnx
VISION_MODEL_VERSION=shelf-detector-v1
VISION_EMBEDDING_MODEL_VERSION=product-embedding-v1
VISION_INPUT_SIZE=640
VISION_CONFIDENCE_THRESHOLD=0.25
VISION_MAX_DETECTIONS=300
```

Para executar apenas deteção, deixar `VISION_EMBEDDING_MODEL_PATH` vazio. Não ativar o provider até os pesos e a sua licença estarem aprovados.

O Compose monta a pasta de modelos em modo só de leitura. A API continua sem executar inferência: o processamento é feito pelo worker separado.

## 3. Execução do worker

Com API e base de dados disponíveis e as variáveis carregadas no ambiente do worker:

```bash
cd apps/api
python -m app.vision_worker --once
```

Para processamento contínuo:

```bash
python -m app.vision_worker --poll-interval 5
```

O worker exige `VISION_PROVIDER_FACTORY`. Sem configuração, termina sem processar imagens. A API não deve iniciar inferência síncrona durante o upload.

## 4. Dependências e execução

O provider utiliza ONNX Runtime CPU, NumPy e Pillow. O runtime permite carregar uma sessão ONNX e executar tensores através de `InferenceSession`; a seleção explícita de `CPUExecutionProvider` mantém a configuração reproduzível em máquinas sem GPU.

- [ONNX Runtime Python API](https://onnxruntime.ai/docs/api/python/api_summary)
- [ONNX Runtime — instalação e primeiros passos](https://onnxruntime.ai/docs/get-started/with-python.html)
- [Execution Providers](https://onnxruntime.ai/docs/execution-providers/)

## 5. Critérios antes de piloto

1. Confirmar a licença e proveniência do detetor, extrator e dados de treino.
2. Validar o contrato dos tensores com os modelos exportados reais.
3. Testar fotos com diferentes resoluções, proporções, reflexos, oclusões e densidade.
4. Calibrar confiança do detetor e limiares/margens de matching apenas na validação.
5. Medir latência CPU, memória e taxa de falhas.
6. Avaliar falsos SKU, desconhecidos e variantes visualmente semelhantes.
7. Manter o teste final separado e intocado.
8. Só depois ativar o worker num piloto controlado, com revisão humana.

## 6. Limitações conhecidas

- O provider espera output de deteção pós-NMS com seis colunas; não é um conversor universal de modelos YOLO.
- Não existe ainda seleção de classes por SKU: todas as caixas são rotuladas genericamente como `product`.
- O extrator é opcional e requer exemplares aprovados na mesma versão de embedding.
- O provider não calcula quantidade física na prateleira, planograma, stock contabilístico ou quantidade a repor.
- Não foram incluídos pesos ONNX no repositório nem executado benchmark de um modelo real.
