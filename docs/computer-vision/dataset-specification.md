# SMART SHELF AI — Especificação do dataset visual

**Estado:** especificação inicial; ainda não existem imagens de treino aprovadas no repositório.

## 1. Objetivo do primeiro dataset

Treinar e avaliar um detetor de objetos em fotografias reais de prateleiras. A primeira tarefa é localizar produtos e elementos visuais relevantes. A identificação do SKU exato, a contagem de unidades parcialmente ocultas e a decisão de reposição são tarefas posteriores e não devem ser presumidas a partir de uma caixa delimitadora.

## 2. Classes iniciais

| ID | Classe | Regra de anotação |
|---:|---|---|
| 0 | `product` | Uma caixa por unidade/produto visível, tão justa quanto possível à embalagem. |
| 1 | `empty_space` | Região contínua e claramente visível da superfície de exposição sem produto. Não anotar sombras, reflexos ou zonas fora da prateleira. |
| 2 | `price_label` | Etiqueta de preço física visível. Não inferir nem transcrever o preço nesta tarefa. |
| 3 | `shelf_edge` | Frente/aresta física da prateleira, quando visível e distinguível. |

Não criar classes `out_of_stock`, `misplaced` ou SKU nesta primeira versão. Uma fotografia isolada não prova rutura de stock nem posicionamento incorreto. Essas conclusões exigem contexto temporal, inventário e/ou planograma.

## 3. Estrutura de diretórios

O dataset não deve incluir imagens reais no Git. Guardar dados em armazenamento privado e versionado separadamente.

```text
shelf-dataset/
├── images/
│   ├── train/
│   ├── val/
│   └── test/
├── annotations/
│   ├── instances_train.json
│   ├── instances_val.json
│   └── instances_test.json
├── metadata/
│   ├── image_manifest.csv
│   └── dataset_card.md
└── README.md
```

A estrutura de anotação de referência é COCO Object Detection: imagens com ID, nome, largura e altura; anotações com ID, image_id, category_id e bbox `[x, y, width, height]` em píxeis; categorias com IDs e nomes. Ver `coco-example.json`.

## 4. Regras de recolha

- Recolher apenas fotografias obtidas com autorização do responsável pela loja e do titular do equipamento.
- Usar diferentes corredores, alturas, distâncias, ângulos, condições de luz e níveis de ocupação.
- Incluir embalagens parcialmente ocultas, reflexos, etiquetas e prateleiras com espaços vazios, sem forçar rótulos quando a evidência não é suficiente.
- Não procurar captar clientes ou trabalhadores. Evitar rostos, crachás, ecrãs, documentos, matrículas e outros dados pessoais.
- Se uma imagem incluir incidentalmente pessoas ou dados pessoais, não a adicionar ao dataset; eliminar ou aplicar anonimização irreversível antes de qualquer utilização autorizada.
- Remover EXIF/GPS e não guardar nomes de clientes ou dados pessoais nos metadados.
- Guardar proveniência, consentimento/autorização, data, loja pseudonimizada, dispositivo/câmara e condições de captura num manifesto privado.

## 5. Separação de treino, validação e teste

Divisão inicial sugerida: 70% treino, 15% validação e 15% teste. Não dividir aleatoriamente frames quase idênticos da mesma sequência entre conjuntos. Agrupar por sessão de captura e, sempre que possível, por loja/corredor para reduzir fuga de dados (*data leakage*). Manter o conjunto de teste intocado até à avaliação final.

## 6. Controlo de qualidade das anotações

- Uma caixa por instância visível, sem incluir produtos adjacentes.
- Coordenadas dentro dos limites da imagem e largura/altura estritamente positivas.
- Não inventar o conteúdo de uma embalagem parcialmente oculta.
- Usar a mesma interpretação de classe em todo o dataset.
- Rever por segunda pessoa uma amostra de pelo menos 10% das imagens.
- Registar imagens difíceis, casos ambíguos e decisões no dataset card.
- Não treinar se houver classes sem exemplos suficientes ou erros sistemáticos por corredor/loja.

## 7. Métricas e critérios de avaliação

Reportar pelo menos precision, recall, mAP@0.50 e mAP@0.50:0.95 por classe, matriz de confusão e resultados por condições de captura. Avaliar separadamente objetos pequenos, parcialmente ocultos e embalagens visualmente semelhantes. Definir limiares de confiança com base no conjunto de validação; não escolher um limiar apenas por conveniência visual.

O modelo só deve gerar observações operacionais após validação em imagens representativas e revisão humana. A confiança do detetor não é probabilidade de stock correto nem prova de SKU.

## 8. Identificação de SKU — fase posterior

Para associar uma deteção a `products.id`, será necessária uma fase de reconhecimento de produto: classificação fina, OCR de códigos de barras/embalagens ou correspondência com catálogo. Exigir um limiar calibrado e permitir resultado `UNKNOWN`. Não associar automaticamente um SKU com base apenas na classe genérica `product`.

## 9. Licença e governação

Registar a licença e origem de cada imagem, modelo base, pesos, código e ferramenta de anotação. Não incorporar imagens de terceiros sem direitos de utilização adequados. A licença do dataset deve ser decidida antes de partilha ou distribuição.

## 10. Referências técnicas

- [RT-DETR — repositório oficial](https://github.com/lyuwenyu/RT-DETR)
- [NVIDIA — formato COCO e preparação de dados RT-DETR](https://docs.nvidia.com/tao/tao-toolkit/7.3.0/text/cv_finetuning/pytorch/object_detection/rt_detr.html)

Esta especificação não afirma que existe um dataset, modelo treinado ou capacidade de inferência em produção.


## 11. Validar anotações antes do treino

Foi disponibilizado um validador Python baseado apenas na biblioteca standard. A partir de `apps/api`, executar:

```bash
python -m app.coco_dataset --annotations /caminho/annotations/instances_train.json
python -m app.coco_dataset --annotations /caminho/annotations/instances_train.json --image-root /caminho/images/train --check-files
```

O validador verifica a estrutura JSON, tipos e IDs duplicados, referências a imagens/categorias inexistentes, dimensões, valores numéricos não finitos, caixas fora da imagem, áreas inválidas e, opcionalmente, existência dos ficheiros e tentativas de escapar ao diretório de imagens. Não substitui revisão visual das anotações nem valida o conteúdo real das imagens.


## 12. Auditor separação treino/validação/teste

Além de validar cada ficheiro COCO isoladamente, existe um auditor que compara os três conjuntos e procura fuga de dados entre splits. Executar a partir de `apps/api`:

```bash
python -m app.dataset_audit \
  --train /dados/annotations/instances_train.json \
  --val /dados/annotations/instances_val.json \
  --test /dados/annotations/instances_test.json \
  --json-report /dados/reports/dataset-audit.json
```

O auditor valida cada split antes de o comparar, compara o mapeamento de classes e deteta nomes de ficheiros e hashes SHA-256 repetidos, tanto dentro de um split como entre splits. Para detetar sequências da mesma sessão, incluir `capture_group_id` em cada objeto de imagem COCO (ou `sequence_id`, como alternativa). Várias imagens do mesmo grupo são permitidas no mesmo split; o grupo não pode aparecer em splits diferentes. O relatório inclui imagens, anotações, imagens sem anotações e instâncias por classe.

O auditor não consegue inferir que duas fotografias pertencem à mesma sessão se os metadados de agrupamento não forem fornecidos. O resultado deve ser complementado por uma revisão do manifesto e da proveniência.


## 13. Gerar manifesto de imagens e hashes

Para criar um CSV reproduzível com o caminho relativo, split, tamanho e SHA-256 de cada imagem, executar a partir de `apps/api`:

```bash
python -m app.dataset_manifest \
  --train /dados/images/train \
  --val /dados/images/val \
  --test /dados/images/test \
  --output /dados/metadata/image_manifest.csv
```

O gerador percorre os diretórios de forma determinística, suporta JPEG, PNG, WebP, BMP e TIFF e calcula SHA-256 em blocos para evitar carregar cada imagem inteira em memória. Não altera as imagens nem remove EXIF; a remoção de metadados pessoais continua a ser uma etapa de preparação separada. O manifesto também não consegue inferir sessões de captura ou autorizações: esses dados têm de ser registados a partir da recolha.


## 14. Verificar correspondência entre manifesto e COCO

Depois de gerar o manifesto e validar os três ficheiros COCO, executar esta verificação adicional:

```bash
python -m app.dataset_integrity \
  --manifest /dados/metadata/image_manifest.csv \
  --train /dados/annotations/instances_train.json \
  --val /dados/annotations/instances_val.json \
  --test /dados/annotations/instances_test.json
```

A verificação confirma que cada imagem COCO tem uma entrada no manifesto no split correto e que não existem imagens extra no manifesto. Se o COCO incluir os campos opcionais `sha256` e `file_size_bytes` por imagem, compara-os também com os valores do CSV. O manifesto exige colunas `split`, `file_name`, `size_bytes` e `sha256`, e rejeita caminhos absolutos ou com traversal.

Fluxo recomendado antes de preparar qualquer treino:

1. Gerar o manifesto com `app.dataset_manifest`.
2. Validar cada COCO com `app.coco_dataset`.
3. Auditar leakage com `app.dataset_audit`.
4. Cruzar o manifesto e os três COCO com `app.dataset_integrity`.
5. Rever manualmente a proveniência, as autorizações e uma amostra visual das anotações.

Estas ferramentas verificam metadados e estrutura. Não confirmam que um ficheiro é realmente uma imagem válida, que as caixas estão bem anotadas ou que existe autorização legal para utilizar os dados.


A opção `--enriched-dir` é opcional. Quando indicada, escreve cópias dos três JSON COCO com os campos `sha256` e `file_size_bytes` preenchidos a partir do manifesto. Os ficheiros originais não são alterados. Essas cópias permitem que verificações futuras comparem os hashes e tamanhos, em vez de se limitarem a confirmar nomes e splits. O enriquecimento só é feito depois de a correspondência entre manifesto e COCO passar.


## 15. Relatório de qualidade e equilíbrio do dataset

Depois das validações estruturais, gerar um relatório de qualidade dos três splits:

```bash
python -m app.dataset_quality \\
  --train /dados/annotations/instances_train.json \\
  --val /dados/annotations/instances_val.json \\
  --test /dados/annotations/instances_test.json \\
  --json-report /dados/reports/dataset-quality.json
```

O relatório apresenta, por split e no total:

- número de imagens e anotações;
- instâncias e proporção por classe, incluindo classes com zero instâncias;
- imagens sem anotações e respetiva proporção;
- mínimo, mediana, máximo e média de instâncias por imagem;
- rácio entre a classe mais frequente e a menos frequente entre as classes com instâncias.

Imagens sem anotações são assinaladas como aviso, não como erro automático: podem ser exemplos negativos válidos, mas têm de ser revistos. Classes com zero instâncias são sempre visíveis no relatório. Os limites são opcionais e configuráveis, sem impor um mínimo universal:

```bash
python -m app.dataset_quality \\
  --train /dados/annotations/instances_train.json \\
  --val /dados/annotations/instances_val.json \\
  --test /dados/annotations/instances_test.json \\
  --min-instances-per-class 20 \\
  --max-class-imbalance-ratio 10 \\
  --json-report /dados/reports/dataset-quality-gated.json
```

Os valores acima são apenas um exemplo de configuração, não critérios aprovados para este projeto. O limite mínimo é aplicado a cada classe em cada split; o rácio ignora classes com zero instâncias e compara as restantes. Definir os limites apenas depois de observar a dimensão e os objetivos do dataset. O relatório mede distribuição quantitativa; não avalia qualidade visual das caixas, validade semântica das classes ou representatividade das imagens.


## 16. Gate de aprovação de uma versão do dataset

Foi adicionada a ferramenta `app.dataset_approval`. Ao contrário de uma simples checklist, executa novamente os controlos técnicos sobre os artefactos indicados e exige um registo explícito de proveniência, privacidade e aprovação humana.

Começar por copiar `docs/computer-vision/dataset-release-template.json` para uma localização privada de trabalho e preencher apenas dados comprovados. O template começa deliberadamente com aprovações a `false`; não é uma autorização.

A partir de `apps/api`:

```bash
python -m app.dataset_approval \\
  --release-record /dados/private/dataset-release.json \\
  --manifest /dados/metadata/image_manifest.csv \\
  --provenance-manifest /dados/metadata/image-provenance.json \\
  --train /dados/annotations/instances_train.json \\
  --val /dados/annotations/instances_val.json \\
  --test /dados/annotations/instances_test.json \\
  --mode training \\
  --json-report /dados/reports/release-gate.json
```

O gate verifica:

1. Identificação e versão do dataset, data, responsável e SHA-256 do manifesto.
2. Finalidade, utilizações permitidas/excluídas, origem, autorização de recolha, direitos e licença declarados.
3. Revisão de privacidade, remoção EXIF/GPS declarada, revisão de dados pessoais, retenção e incidentes.
4. Protocolo e revisão de qualidade das anotações.
5. Aprovação técnica e aprovação de privacidade/licença, com revisor, data e decisão explícita.
6. Hash real do manifesto, sidecar de proveniência por imagem, verificação operacional de imagens internas (`shelf_image_id`, `store_id`, SHA-256, estado `ACTIVE` e ausência de legal hold), estrutura do CSV, correspondência COCO/manifesto, auditoria de leakage e relatório quantitativo de qualidade.

O resultado `APPROVED` significa apenas que os campos declarados e os controlos automatizados passaram para o modo escolhido. Não autentica a identidade dos revisores, não verifica a veracidade de autorizações, não presta aconselhamento jurídico e não substitui inspeção visual humana.

Para treino, é obrigatória a aprovação explícita `approved_for_training: true`. Para inferência operacional, usar `--mode inference`: além da aprovação para treino, exige aprovação operacional separada, identificação/licença do modelo, protocolo de avaliação e métricas medidas por classe (`precision`, `recall`, `ap50`). Não preencher métricas com estimativas ou valores de exemplo.

Para imagens de origem `internal`, o comando liga-se à base de dados configurada em `app.database`; se a ligação não estiver disponível, o gate bloqueia. O sidecar é obrigatório para todas as imagens. A ferramenta não faz upload de imagens nem publica o registo privado. Manter dataset, manifesto e registos de autorização em armazenamento com acesso controlado; não colocar dados pessoais, contratos ou credenciais no GitHub.


## 17. Revisão visual das caixas delimitadoras

A ferramenta `app.coco_review` gera uma galeria HTML local para inspecionar as caixas e os nomes das classes sobre as fotografias originais. É recomendada depois da validação estrutural e antes do gate de aprovação.

A partir de `apps/api`:

```bash
python -m app.coco_review \
  --annotations /dados/annotations/instances_train.json \
  --image-root /dados/images/train \
  --output /dados/review/train/index.html \
  --include-unannotated
```

Para filtrar classes, repetir `--class-id` (por exemplo, `--class-id 0 --class-id 2`). `--limit` permite rever uma amostra determinística na ordem do ficheiro COCO. Sem `--include-unannotated`, as imagens sem anotações correspondentes aos filtros são omitidas.

O HTML é estático e funciona sem servidor ou dependências JavaScript. Mantém referências relativas às imagens de origem, pelo que os ficheiros têm de continuar acessíveis no caminho original. Não copia, modifica ou transmite fotografias. O gerador rejeita documentos COCO inválidos, ficheiros ausentes e caminhos que escapem à raiz indicada. A revisão visual continua a exigir uma pessoa: o programa não avalia se a caixa envolve o objeto correto, se a classe é semanticamente adequada ou se existe autorização para usar a imagem.



## 18. Registo de revisão humana por imagem

A revisão visual deve deixar um registo estruturado e associado à versão do COCO. O módulo `app.dataset_review` cria um template por split com uma entrada por imagem, o SHA-256 do ficheiro COCO e um SHA-256 canónico das anotações de cada imagem.

Criar os três templates em armazenamento privado:

```bash
python -m app.dataset_review --coco /dados/annotations/instances_train.json --split train --create-template /dados/private/review-train.json
python -m app.dataset_review --coco /dados/annotations/instances_val.json --split val --create-template /dados/private/review-val.json
python -m app.dataset_review --coco /dados/annotations/instances_test.json --split test --create-template /dados/private/review-test.json
```

Para cada imagem, o revisor tem de preencher:
- `decision`: `APPROVED`, `NEEDS_CORRECTION` ou `REJECTED`;
- `reviewer`: identificador legível do revisor;
- `reviewed_at`: timestamp ISO 8601;
- `notes`: observações opcionais.

Validar um registo:

```bash
python -m app.dataset_review --coco /dados/annotations/instances_train.json --split train --record /dados/private/review-train.json
```

O gate `app.dataset_approval` aceita `--require-visual-review` e os três caminhos `--review-train`, `--review-val`, `--review-test`. Quando ativado, exige uma decisão `APPROVED` para todas as imagens dos três splits, sem duplicados ou omissões, e verifica os hashes da versão atual. Uma alteração ao COCO invalida o registo anterior.

Este mecanismo regista decisões declaradas; não autentica a identidade do revisor, não prova que a inspeção foi executada e não substitui controlos de acesso. Guardar os registos fora do repositório, em armazenamento controlado.



## 14. Avaliação reproduzível de deteções

O módulo `app.detection_metrics` compara resultados de inferência em formato
COCO Results (`image_id`, `category_id`, `bbox`, `score`) com anotações
COCO revistas. Executar a partir de `apps/api`:

```bash
python -m app.detection_metrics \
  --ground-truth /dados/annotations/instances_test.json \
  --predictions /dados/predictions/test-results.json \
  --confidence-threshold 0.25 \
  --output /dados/reports/model-v1-test.json
```

O relatório inclui mAP@0.50, mAP@0.50:0.95 com AP interpolada em 101 pontos,
precisão/recall a IoU 0.50 no limiar de confiança escolhido, contagens TP/FP/FN
e resultados por classe. O limiar de confiança deve ser escolhido no conjunto
de validação; o conjunto de teste deve permanecer intocado até à avaliação
final. Para comparar modelos, manter iguais o conjunto de teste, as categorias,
os limiares e as regras de avaliação.

Este avaliador é uma implementação transparente do projeto, não uma
substituição certificada da API oficial COCO: exclui `iscrowd=1` em vez de
implementar a semântica de crowd do COCO. Os resultados só são fiáveis quando
as anotações de referência são completas e aprovadas por revisão humana.


## 19. Criar o registo imutável de release

Depois de concluir os controlos anteriores, o criador de releases exige novamente
o sidecar e revalida a elegibilidade operacional antes de escrever no registry.
Executar a partir de `apps/api`:

```bash
python -m app.dataset_release \
  --manifest /dados/metadata/image_manifest.csv \
  --provenance-manifest /dados/metadata/image-provenance.json \
  --split-audit /dados/reports/dataset-audit.json \
  --visual-audit /dados/reports/visual-similarity.json \
  --registry /dados/private/dataset-registry
```

Para fontes internas, a base de dados configurada em `app.database` tem de
estar acessível. O comando bloqueia as imagens elegíveis durante a validação e
a escrita do registo, verifica novamente loja, hash, estado `ACTIVE` e ausência
de legal hold, e inclui o hash do sidecar na fingerprint do release. O
sidecar incompleto ou uma imagem operacionalmente inelegível impede a criação.

O registry é um registo local imutável de metadados; não copia nem publica as
imagens e não inicia treino ou inferência. A elegibilidade pode mudar depois
do comando terminar. Qualquer consumidor/treinador tem de revalidar e manter a
proteção durante a utilização efetiva dos dados.
