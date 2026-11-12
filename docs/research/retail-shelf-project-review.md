# REA — revisão de projetos externos de monitorização de prateleiras

**Data da revisão:** 12-11-2026  
**Objetivo:** identificar componentes e padrões reutilizáveis para acelerar o SMART SHELF AI sem importar código sem avaliação técnica e jurídica.

## Critério

A revisão distingue técnicas úteis, maturidade demonstrada, limitações declaradas e compatibilidade com a arquitetura existente. Métricas publicadas pelos autores não são tratadas como resultados reproduzidos por este projeto.

## Projetos analisados

### 1. Retail-Shelf-Monitoring — Alijanloo
Repositório: https://github.com/Alijanloo/Retail-Shelf-Monitoring

**Contributos a estudar**
- Pipeline CCTV → seleção de keyframes → deteção de prateleira → alinhamento → deteção de produtos → reconhecimento SKU → mapeamento em grelha → consenso temporal → alerta.
- Separação entre deteção genérica de objetos e reconhecimento SKU.
- Tracking SORT/Kalman para reduzir oscilações entre frames.
- Otimização de inferência com ONNX Runtime, OpenVINO e TensorRT.
- Processamento multi-thread e interface de revisão humana.

**Limitações e validação**
- A descrição anuncia YOLOv12-M, embeddings e métricas de reconhecimento; estas métricas carecem de reprodução independente no nosso hardware/dataset.
- Verificar pesos, configuração, dependências e licença de cada artefacto antes de reutilizar.
- A interface PySide6 não deve ser copiada para o frontend React existente; aproveitar sobretudo contratos e ideias do pipeline.

**Decisão:** candidato prioritário para estudo de arquitetura de visão, tracking e otimização Edge. Não importar diretamente o pipeline inteiro.

### 2. Shelf-Sight — Jackson Marcus
Repositório: https://github.com/jackson-marcus/Shelf-Sight

**Contributos a estudar**
- Baseline OpenCV sem GPU nem treino para segmentação de facings, deteção geométrica de espaços vazios e conformidade com planograma.
- Artefactos intermédios inspecionáveis, úteis para explicar decisões a supervisores.
- Geração de prateleiras sintéticas com ground truth para testes determinísticos.

**Limitações**
- A abordagem depende de cor/hue e contornos, sendo sensível à iluminação, sombras, perspetiva e embalagens com cores semelhantes.
- Não identifica SKUs de forma robusta nem fornece quantidades de inventário contabilístico.

**Licença:** o README indica MIT; confirmar a licença do snapshot e dependências antes de copiar código.

**Decisão:** candidato adequado para baseline explicável e geração de testes sintéticos, não substitui um modelo SKU-aware.

### 3. shelfops-ai — sruthvik
Repositório: https://github.com/sruthvik/shelfops-ai

**Contributos a estudar**
- Deteção de produto com YOLO e reconhecimento separado por embeddings DINOv2/FAISS.
- Catálogo incremental de exemplares sem treinar novamente o detetor.
- Separação do agente de linguagem do caminho crítico de visão.
- Revisão humana condicionada pela confiança.

**Limitações**
- O README descreve um protótipo com poucos SKUs de referência e não apresenta evidência de operação em loja.
- Métricas e tempos publicados devem ser reproduzidos.
- Não assumir licença permissiva sem verificar LICENSE e os direitos dos pesos/modelos externos.

**Decisão:** estudar o desacoplamento deteção/reconhecimento e o fluxo human-in-the-loop. Não depender de LLM para decisões quantitativas de stock.

### 4. retail-shelf-monitor — rickhaile
Repositório: https://github.com/rickhaile/retail-shelf-monitor

**Contributos a estudar**
- Deteção genérica densa de produtos e cálculo de gaps a partir de geometria.
- Métricas de contagem e erro absoluto, para além de mAP.
- Atenção explícita ao limite máximo de deteções em imagens de prateleiras densas.

**Limitações**
- O README refere erros de contagem e dificuldades em ângulos extremos/bordas.
- SKU-110K fornece caixas de objetos genéricas; não resolve identificação individual de SKU.
- Resultados do autor não foram reproduzidos.

**Decisão:** aproveitar a preocupação com métricas operacionais de contagem e configuração de max_det; comparar com o nosso conjunto de avaliação.

### 5. Retail-Shelf-Monitoring — tyrndev
Repositório: https://github.com/tyrndev/Retail-Shelf-Monitoring

**Contributos a estudar**
- Arquitetura de monitorização com CCTV existente.
- Pipeline YOLO + embeddings/FAISS + tracking e conformidade de planograma.
- Otimização por runtimes de inferência.

**Limitações**
- Confirmar se é independente do projeto Alijanloo ou uma derivação/fork antes de contar como evidência separada.
- Verificar licença, histórico, testes e proveniência dos modelos.

**Decisão:** referência secundária; não duplicar trabalho se a base de código for comum.

## Decisões de arquitetura para SMART SHELF AI

1. **Manter o contrato VisionProvider.** A API não deve ficar dependente de Ultralytics, OpenVINO, TensorRT ou de um fornecedor de embeddings.
2. **Separar deteção de SKU matching.** O detetor localiza objetos; o matcher procura candidatos no catálogo e pode abster-se (UNKNOWN/AMBIGUOUS).
3. **Aplicar consenso temporal.** Uma observação isolada não deve gerar tarefa física sem regras de confiança, frescura e confirmação.
4. **Construir baseline explicável.** OpenCV pode ser útil para segmentação/gaps e testes, mas nunca converter diretamente pixels em stock contabilístico.
5. **Avaliar em métricas de negócio.** Medir recall de ruturas, falsos alertas por prateleira/dia, erro de contagem, latência Edge, taxa de abstenção e recomendações confirmadas.
6. **Preservar o caminho operacional existente.** A saída de visão alimenta observações; o motor de inventário, previsão, rotação de paletes e tarefas continua separado.
7. **Manter agentes de linguagem fora do caminho crítico.** Podem explicar e resumir tarefas; não podem decidir quantidades, reservar stock ou movimentar paletes.

## Plano de validação antes de reutilização

- Registar URL, commit SHA, licença e data de cada componente considerado.
- Inspecionar LICENSE, NOTICE, dependências, pesos e licenças dos datasets.
- Executar testes e exemplos do projeto externo num ambiente isolado.
- Comparar o componente com o baseline atual em imagens próprias autorizadas e separadas por loja/sessão.
- Medir latência no hardware Edge pretendido.
- Importar apenas módulos pequenos e isolados, com atribuição de autoria e licença.
- Não copiar datasets, pesos ou imagens de produto sem direitos de utilização adequados.

## Estado

Esta revisão é pesquisa documental inicial, não uma auditoria de código linha a linha nem uma validação experimental. Os projetos são referências para selecionar técnicas; não são dependências do SMART SHELF AI.
