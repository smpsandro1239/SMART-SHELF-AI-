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

O validador verifica IDs duplicados, referências a imagens/categorias inexistentes, dimensões, caixas fora da imagem, áreas inválidas e, opcionalmente, existência dos ficheiros e tentativas de escapar ao diretório de imagens. Não substitui revisão visual das anotações nem valida o conteúdo real das imagens.
