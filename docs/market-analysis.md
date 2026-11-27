# Relatório de Análise de Mercado — SMART SHELF AI

**Âmbito:** concorrentes (gratuitos e pagos) e lacunas de produto face ao roadmap do SMART SHELF AI, com fundamento em pesquisa de mercado, páginas oficiais, documentação pública e metodologia de REA do projeto.

## 1. Tamanho do mercado (2026)

| Segmento | 2026 | Projeção | CAGR |
|---|---|---|---|
| Smart Shelf (global) | USD 6,28 bi | USD 17,76 bi (2031) | **23,1%** |
| Shelf Image Recognition AI | USD 1,82 bi (2025) | USD 5,86 bi (2030) | **26,3%** |
| Shelf Intelligence Software | ~USD 2,36 bi | ~USD 2,36 bi (2032) | 8,7% |
| Autonomous Shelf Scanning Robots | USD 1,6 bi | USD 3,4 bi (2034) | 9,8% |

Drivers: escassez de mão de obra, fase-out de etiquetas em papel/ESL, edge AI para conformidade de planograma, convergência RFID + visão, perdas por *shrink* (USD 52 bi/ano).

**Concentrado:** VusionGroup, Pricer, Hanshow, Displaydata, SoluM; Trax, Focal Systems, Simbe, Bossa Nova, Zebra.

## 2. Concorrentes pagos — capacidades identificadas

- **Standard AI — VISION:** câmaras existentes → *digital twin*, zones, edge, *verified impressions*, comportamento/experiência do shopper, conversão. Privacidade-first, sem facial recognition.
- **Crisp — Halo** (adquireiro Shelf Engine): plataforma full-stack de IA retail — Replenishment Desk, Buyer/Category/Commercial Desk, data foundation, ferramentas agenticas, análise conversacional, workflow automation, reporting agendado, custom apps, multi-cloud (Databricks/Snowflake/GCP). Shelf Engine: forecasting de demanda para perecíveis, ordering automatizado, *Results-as-a-Service*, EDI, garantia de resultado.
- **Simbe (Tally), Bossa Nova, Focal Systems, Pensa, VusionGroup, Hanshow, Displaydata, SoluM, Trax, Zebra:** robótica, câmeras fixas contínuas, action tools, picking/replenishment, dashboards de impacto.

## 3. Concorrentes gratuitos / open-source — capacidades identificadas

- **Alijanloo — Retail Shelf Monitoring** (MIT): pipeline CCTV→keyframe→deteção→SKU→grid→consenso→alerta; YOLOv11, MobileNet+FAISS, SORT/Kalman, ONNX/OpenVINO/TensorRT.
- **rickhaile — retail-shelf-monitor:** YOLO11n no SKU-110K, gaps por geometria, métrica OSA, MAE/MAPE.
- **ShelfOps AI** (sruthvik): YOLO + DINOv2/FAISS, catálogo incremental, LLM só redação.
- **ShelfSight** (Jackson Marcus): OpenCV, gaps, **share-of-shelf**, compliance, sintético.
- **swd07 — Retail Shelf Detection:** GroundingDINO→OCR/VLM→embeddings→fusão→guardrails; offline-first; shadow mode.
- **Sanket758 — SKU Vision:** YOLO + DINOv2/MobileNetV2, exemplar registry, review.
- **AnKu-02 — MAiRA:** robótica (fase futura).

## 4. Lacunas do SMART SHELF AI face a concorrentes (internas de REA)

**Implementado:** captura multi-origem, consenso temporal, alertas persistentes, `empty_facing`, comparador de células, planogramas versionados, expected_facings, comparação read-only, motor de reposição/tarefas.

**Não implementado / parcial (roadmap TODO):**

1. Share-of-shelf por SKU/marca e evolução de facings vs planograma — não implementado.
2. Importação/exportação validada de planogramas — não implementado.
3. Versão efetiva de planograma por data/hora — não implementado.
4. Política de tarefas obsoletas / alertas resolvidos / stock reposto — não implementado.
5. Indicadores OSA (On-Shelf Availability), taxa/duração de rutura, low-stock, conformidade, tempo de reposição — não implementado como métricas.
6. Monitorização contínua CCTV/VMS, SLO de latência, saúde/cobertura de câmaras, profundidade, versionamento de embalagens — lacuna (análise Visionplatform).

**Limitações vigentes:** contagem por deteções frontais, não unidades em profundidade; comparador sem ligação ao worker com células/planogramas persistidos.

## 5. Síntese — lacunas de produto vs. concorrentes

| Capacidade | Concorrentes | SMART SHELF AI | Prioridade |
|---|---|---|---|
| Detecção + identificação SKU + UNKNOWN/AMBIGUOUS | Shelf Management, ShelfOps, swd07, Sanket758 | **Sim** | Alta |
| Consenso temporal + dedup alertas | Alijanloo, Shelf Monitoring | **Sim** | Alta |
| Gaps/OOS por geometria | rickhaile, ShelfSight | **Parcial** (OSA ausente) | Alta |
| Share-of-shelf / facings | ShelfSight, ShelfIQ, Focal, Simbe | **Não** | Alta |
| Medição de mídia/shopper (verified impressions, conversão) | Standard AI, Crisp | **Não** | Alta |
| RaaS reposição com garantia (Shelf Engine) | Shelf Engine | **Não** | Média |
| Execução robótica integrada | Simbe, Bossa Nova, MAiRA, Focal | **Não** (fase futura) | Média |

## 6. Conclusão

O SMART SHELF AI já está acima da maioria dos projetos open-source em arquitetura (detecção/SKU separados, consenso, alertas, planogramas, reposição). As principais ausências frente aos concorrentes/pagas: **share-of-shelf, OSA/métricas de disponibilidade, import/export de planogramas, versionamento efetivo, política de tarefas obsoletas e analytics de mídia/shopper**.

**Próximo salto recomendado** (ciclo de valor *capture → locate → identify → cross → prioritize → execute → confirm → measure*): fechar as lacunas 1–5 antes de avançar para robótica ou RaaS.

## 7. Fontes primárias

- Mordor Intelligence — Smart Shelf Market.
- The Business Research Company — Shelf Image Recognition AI.
- Stratistics Market Research / GII — Autonomous Shelf Scanning Robots.
- Market Publishers — Shelf Intelligence Software.
- Standard AI, Crisp, visionplatform.ai, Shelf Engine — páginas oficiais.
- GitHub — Alijanloo/Retail-Shelf-Monitoring, rickhaile/retail-shelf-monitor, sruthvik/ShelfOps, jackson-marcus/Shelf-Sight, swd07/retail-shelf-detection, Sanket758/sku-vision-pipeline, AnKu-02/Maira-shelf-replenishment, eg4000/SKU110K_CVPR19.
- Odoo, ERPNext — documentação oficial.
- Documentação interna — `docs/reverse-engineering/external-solutions.md`, `docs/research/retail-shelf-project-review.md`, `docs/architecture/retail-vision-rea.md`, `docs/architecture/visionplatform-shelf-stockout-analysis.md`, `README.md`, `TODO.md`.
