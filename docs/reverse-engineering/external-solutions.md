# REA externa — comparação de soluções existentes para reposição de prateleiras

**Âmbito:** projetos públicos de terceiros e plataformas consolidadas, não os repositórios do autor do SMART SHELF AI.  
**Data da consulta:** 12-11-2026.  
**Método:** inspeção de README, árvores de ficheiros, código-fonte, documentação oficial, metadados GitHub e licenças visíveis. Não foi executado código dos projetos externos nem reproduzido o treino dos seus modelos.

## 1. Objetivo

Identificar componentes comprovados ou promissores para resolver o fluxo completo:

1. detetar produtos e espaços vazios na prateleira;
2. associar deteções a uma posição/planograma;
3. identificar SKU com evidência suficiente;
4. distinguir ausência visual de falta real de stock;
5. calcular quantidade de reposição da prateleira;
6. calcular necessidades de transferência/encomenda com stock previsto;
7. gerar tarefa auditável com validação humana;
8. medir disponibilidade na prateleira, falsos alertas e tempo até reposição.

Uma deteção de espaço vazio não prova, isoladamente, que o produto está em rutura: pode estar temporariamente oculto, deslocado, numa posição diferente ou existir stock na retaguarda.

![Fluxo conceptual derivado da REA externa](../images/external-rea-replenishment-flow.svg)

## 2. Projetos analisados

### 2.1 Alijanloo — Retail Shelf Monitoring

- Repositório: https://github.com/Alijanloo/Retail-Shelf-Monitoring
- Estado observado: público, não arquivado, 105 commits, 17 stars, 2 forks na consulta.
- Licença declarada no repositório: MIT.
- Estrutura: Clean Architecture, módulos de domínio, use cases, adaptadores, persistência, testes unitários e de integração.
- Pipeline documentado: seleção de keyframes → alinhamento da prateleira → deteção de produtos → reconhecimento SKU → grelha/planograma → consenso temporal → alerta → confirmação do colaborador.

**Elementos concretos encontrados no código:**
- `YOLOv11Detector` separa pré-processamento, inferência e pós-processamento.
- `SKUDetector` usa embeddings MobileNet e pesquisa de vizinhos FAISS; o índice pode ser construído com imagens de referência por SKU.
- `DetectionProcessingUseCase` recorta as caixas detetadas e associa cada recorte a um SKU.
- `CellStateComputation` compara deteções com células de um planograma e classifica correspondências, divergências e posições vazias.
- `AlertGenerationUseCase` atualiza um alerta ativo da mesma célula em vez de criar alertas repetidos; guarda primeira/última ocorrência e número de frames consecutivos.
- O relatório técnico descreve tracking SORT/Kalman, alinhamento geométrico e consenso de pelo menos três frames.

**O que vale a pena aproveitar conceptualmente:**
- Separar deteção genérica de identificação SKU.
- Construir uma referência geométrica por prateleira.
- Usar tracking e persistência temporal antes de abrir um alerta.
- Deduplicar alertas por localização e manter evidência.
- Manter o motor de alertas independente do modelo de visão.

**Limitações e verificações necessárias:**
- O README/relatório anuncia YOLOv12-M, mas o adaptador inspecionado chama-se `YOLOv11Detector`; a versão efetivamente usada deve ser confirmada no caminho de configuração/pesos.
- Os valores de mAP e 93% Top-1 são declarações do projeto; não foram reproduzidos nesta análise.
- O código de identificação requer um catálogo de recortes de referência por SKU e uma estratégia para produtos visualmente semelhantes, embalagens novas e variantes.
- A licença MIT cobre o código do repositório; não significa que os pesos, datasets ou dependências tenham automaticamente a mesma licença. SKU-110K está indicado como Research-Only nas referências consultadas.

**Avaliação:** a referência externa mais útil para arquitetura de visão, planograma, tracking e gestão temporal de alertas. Não importar o projeto inteiro nem assumir que as métricas são garantidas.

### 2.2 rickhaile — retail-shelf-monitor

- Repositório: https://github.com/rickhaile/retail-shelf-monitor
- Estado observado: um commit, sem licença declarada visível, 1 star.
- Foco: deteção genérica de produtos em imagens densas, cálculo geométrico de lacunas e métrica On-Shelf Availability (OSA).
- O autor reporta treino YOLO11n com SKU-110K e métricas de teste, incluindo mAP50 0,896, mAP50-95 0,538, MAE de contagem 18,3 e MAPE 12,3%. São resultados declarados no README, não reproduzidos pelo SMART SHELF AI.

**Ideia técnica relevante:**
- Agrupar caixas por filas horizontais.
- Estimar a largura típica de um produto por fila.
- Assinalar espaços vazios maiores do que um limiar proporcional à largura típica.
- Calcular uma métrica de ocupação/OSA a partir da largura ocupada e da extensão observada.

**Valor para o SMART SHELF AI:**
- Introduzir uma métrica de disponibilidade visual da prateleira, separada da contagem de SKU.
- Medir erro de contagem (MAE/MAPE) além de mAP.
- Tratar deteção de espaços vazios como uma hipótese geométrica que necessita de confirmação temporal e humana.

**Limitações:**
- Apenas um commit e ausência de licença identificada; não reutilizar código sem autorização/licença clara.
- O algoritmo de gaps depende da geometria da imagem e da segmentação correta das filas; ângulos, perspetiva, prateleiras curvas, divisórias, promoções e produtos ausentes nas extremidades podem produzir falsos alertas.
- O projeto não demonstra, por si só, ligação a inventário real, gestão de tarefas ou integração com ERP.

**Avaliação:** boa referência para métricas e baseline de deteção de gaps; não é uma plataforma consolidada nem uma base de código a incorporar.

### 2.3 sruthvik — shelfops-ai

- Repositório: https://github.com/sruthvik/shelfops-ai
- Estado observado: um commit inicial, sem licença declarada visível, 0 stars.
- Arquitetura descrita: YOLO para deteção, DINOv2 + FAISS para reconhecimento SKU, regras determinísticas para incidências e LLM apenas para redação de tarefas.

**Ideias aproveitáveis:**
- Separar localização do objeto e identificação SKU.
- Atualizar referências/índice de embeddings quando o catálogo muda, sem treinar um classificador fechado para todos os SKUs.
- Não colocar um LLM no caminho crítico de deteção ou cálculo de stock.
- Usar regras explícitas e revisão humana para decidir a ação operacional.

**Problemas concretos observados no código:**
- API mantém ocorrências e tarefas em listas em memória, perdendo estado ao reiniciar.
- Caminho do checkpoint hard-coded.
- CORS permite qualquer origem.
- Não foi encontrada autenticação ou isolamento multi-loja no backend inspecionado.
- Grelha fixa 3×3 baseada na imagem, sem calibração geométrica real.
- O README chama ao projeto production-grade, mas o estado observado (um commit e backend demonstrativo) não sustenta essa classificação.

**Avaliação:** referência de ideias de separação de componentes, não de implementação de produção. Não copiar backend, configuração de segurança nem afirmações de produção.

## 3. Plataformas de inventário e reposição

### 3.1 Odoo — Reordering Rules

Documentação oficial: https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory/warehouses_storage/replenishment/reordering_rules.html

Capacidades relevantes:
- níveis mínimo e máximo;
- stock previsto, não apenas stock físico;
- rotas de compra ou fabrico;
- modos automático e manual;
- prazo do fornecedor e horizonte de planeamento;
- múltiplos de embalagem, para encomendar caixas/packs completos;
- painel de reposição para validação antes da ordem.

**Aplicação:** o SMART SHELF AI deve distinguir duas decisões diferentes:
- reposição da prateleira a partir do stock disponível na retaguarda;
- reposição do armazém/loja através de transferência ou compra.

### 3.2 ERPNext — Automatic Reordering / Projected Quantity

Documentação:
- https://docs.frappe.io/erpnext/auto-creation-of-material-request
- https://docs.frappe.io/erpnext/item
- Código de stock projetado: https://github.com/frappe/erpnext/blob/develop/erpnext/stock/doctype/bin/bin.py

Capacidades relevantes:
- reorder level e reorder quantity por artigo/armazém;
- quantidade projetada inclui stock físico, encomendas, pedidos/entradas planeadas e reservas;
- criação de Material Request;
- destino da necessidade pode ser compra ou transferência entre armazéns;
- fluxo de aprovação e seguimento da receção.

**Aplicação:** adotar o conceito de posição de inventário projetada e a separação entre recomendação, pedido de material e movimento físico. Não confundir uma ordem emitida com stock recebido.

## 4. Matriz comparativa

| Capacidade | Alijanloo | rickhaile | ShelfOps AI | Odoo | ERPNext |
|---|---|---|---|---|---|
| Deteção de produtos | Sim, código e adaptadores | Sim, YOLO | Sim, YOLO | Não é o foco | Não é o foco |
| Identificação SKU | MobileNet + FAISS | Não | DINOv2 + FAISS descritos | Catálogo ERP | Catálogo ERP |
| Planograma | Sim | Não demonstrado | Grelha demonstrativa | Não é o foco | Não é o foco |
| Deteção de gaps | Por células/planograma | Geometria de filas | Regras descritas | Stock projetado | Stock projetado |
| Consenso temporal | Sim, tracking/frames | Não demonstrado | Não demonstrado | Não aplicável | Não aplicável |
| Stock retaguarda | Não demonstrado como ERP integrado | Não | Em memória/demonstração | Sim | Sim |
| Compra/transferência | Não demonstrado | Não | Não demonstrado | Sim | Sim |
| Tarefas humanas | Alertas/confirmar | Não | Demo | Fluxo ERP | Material Request |
| Persistência operacional | PostgreSQL/Redis descritos | Artefactos locais | Memória | ERP | ERP |
| Licença declarada | MIT (código) | Não identificada | Não identificada | Consultar licença por edição | GPL-3.0 |

## 5. Arquitetura alvo resultante da REA

A proposta é combinar princípios, não fundir repositórios:

1. **Visão:** deteção genérica de facings e caixas delimitadoras.
2. **Geometria:** localização da prateleira, alinhamento e mapeamento para posições.
3. **SKU:** embeddings de catálogo com FAISS ou alternativa; resultado pode ser UNKNOWN.
4. **Consenso:** tracking e múltiplas observações antes de confirmar uma ausência.
5. **OSA:** indicador visual calculado por prateleira/segmento, acompanhado de qualidade e cobertura.
6. **Inventário:** stock físico, reservado, entradas previstas e consumo até à receção.
7. **Motor de decisão:** regras determinísticas para refill da prateleira e para compra/transferência.
8. **Human-in-the-loop:** revisão de baixa confiança, exceções e todas as ações externas no primeiro piloto.
9. **Execução:** tarefa de reposição, registo de quem executou, quantidade efetivamente reposta e confirmação posterior por nova captura.

## 6. Política de reutilização e licenças

- Não copiar código de repositórios sem licença declarada (rickhaile e ShelfOps AI).
- O código MIT de Alijanloo pode ser estudado e reutilizado nos termos da licença, incluindo avisos de copyright e licença, mas é preferível implementar os conceitos através das interfaces próprias do SMART SHELF AI.
- Verificar separadamente a licença dos pesos, do framework, dos dados de treino e dos modelos derivados.
- SKU-110K está marcado como Research-Only nas referências consultadas; não o tratar como dataset comercialmente livre.
- Verificar licença e termos de cada versão/peso antes de integrar YOLO ou qualquer outro modelo.
- ERPNext tem licença GPL-3.0; usar a documentação e os conceitos de negócio não equivale a copiar código. Uma integração por API é uma alternativa a incorporar código GPL no produto.

## 7. Decisões de desenvolvimento

| Decisão | Estado |
|---|---|
| Deteção e reconhecimento SKU separados | Adotar como princípio |
| Gaps baseados apenas em largura vazia | Usar como sinal, nunca como prova de rutura |
| Consenso temporal e deduplicação de alertas | Prioridade alta |
| OSA por prateleira | Introduzir como métrica, após calibrar geometria |
| Refill de prateleira | Implementado como política determinística isolada |
| Reorder de fornecedor | Implementado como política determinística isolada |
| Integração real ERP/POS/WMS | Futuro; exige contrato e ambiente de teste |
| Inferência automática sem revisão | Não ativar no primeiro piloto |

## 8. Limitações desta REA

Esta é uma inspeção documental e estática de código público. Não inclui:
- execução integral dos repositórios externos;
- verificação independente dos resultados de treino publicados;
- auditoria de segurança dos projetos externos;
- validação jurídica de todos os artefactos/modelos/datasets;
- teste numa loja real ou com câmaras reais.

Os números publicados por terceiros devem ser tratados como resultados reportados pelos autores, não como benchmarks diretamente comparáveis. O SMART SHELF AI só deverá publicar métricas depois de reproduzir a avaliação num conjunto de teste autorizado, separado por loja/sessão e com hashes registados.

## 9. Fontes primárias

- [Alijanloo — README](https://github.com/Alijanloo/Retail-Shelf-Monitoring)
- [Alijanloo — YOLO detector](https://github.com/Alijanloo/Retail-Shelf-Monitoring/blob/main/retail_shelf_monitoring/adaptors/ml/yolo_detector.py)
- [Alijanloo — SKU detector](https://github.com/Alijanloo/Retail-Shelf-Monitoring/blob/main/retail_shelf_monitoring/adaptors/ml/sku_detector.py)
- [Alijanloo — cell state computation](https://github.com/Alijanloo/Retail-Shelf-Monitoring/blob/main/retail_shelf_monitoring/usecases/cell_state_computation.py)
- [Alijanloo — alert generation](https://github.com/Alijanloo/Retail-Shelf-Monitoring/blob/main/retail_shelf_monitoring/usecases/alert_generation.py)
- [rickhaile — retail-shelf-monitor](https://github.com/rickhaile/retail-shelf-monitor)
- [ShelfOps AI](https://github.com/sruthvik/shelfops-ai)
- [SKU-110K dataset description and research-only notice](https://github.com/eg4000/SKU110K_CVPR19)
- [Odoo — Reordering Rules](https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory/warehouses_storage/replenishment/reordering_rules.html)
- [ERPNext — Automatic Reorder](https://docs.frappe.io/erpnext/auto-creation-of-material-request)
- [ERPNext — Projected Quantity source](https://github.com/frappe/erpnext/blob/develop/erpnext/stock/doctype/bin/bin.py)
