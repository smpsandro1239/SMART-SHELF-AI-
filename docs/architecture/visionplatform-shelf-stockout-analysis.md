# Análise REA — Visionplatform.ai: deteção de ruturas em prateleiras

**Data:** 2026-11-19  
**Fonte:** [Detecção em tempo real de falta de estoque em prateleiras usando câmeras](https://visionplatform.ai/pt/deteccao-falta-de-estoque-em-prateleiras-usando-cameras/) (artigo publicado em 2025-10-06).

## 1. Síntese

O artigo descreve uma solução de monitorização visual contínua com câmaras fixas/CCTV, inferência em Edge e Cloud, deteção de produto e espaços vazios/low-stock, conformidade com planogramas, alertas estruturados, encaminhamento de tarefas, integração com inventário/ERP e dashboards. Refere ainda desafios de iluminação, reflexos, embalagens, oclusão, produtos empilhados e novos SKUs.

A comparação com o SMART SHELF AI confirma que a maior parte dos conceitos já consta do roadmap e vários já têm implementação real. O artigo não justifica copiar a plataforma nem adotar as métricas comerciais citadas. Os valores de precisão acima de 90% e ganhos de produtividade até 2,5x são alegações/fontes externas, não metas nem resultados demonstrados pelo nosso sistema.

## 2. Matriz de cobertura

| Capacidade descrita | Estado no SMART SHELF AI | Conclusão |
|---|---|---|
| Captura por câmara fixa, robô e telemóvel | Sessões de captura e upload já suportam as três origens; integração contínua RTSP/VMS ainda não está operacional | Parcial |
| Reutilização de CCTV/VMS existente | Gateway comum e adaptadores IP/RTSP estão no TODO; descoberta, ingestão e compatibilidade com VMS ainda por implementar | Em falta |
| Monitorização contínua e alertas em segundos | Consenso temporal e alertas persistentes já existem; falta ligar a produção de observações ao worker/captura contínua e definir SLO p95 de ponta a ponta | Parcial |
| Deteção de produtos e matching SKU | ONNX, embeddings, OCR e matching têm contratos e componentes; faltam pesos aprovados, dataset real e avaliação operacional | Experimental |
| Espaços vazios | Classe `empty_facing`, comparador geométrico e estados conservadores existem; faltam visibilidade calibrada por captura, worker e validação real | Parcial |
| Low-stock e contagem de facings | `expected_facings` e comparação esperado/observado existem; NMS/deduplicação e contagem física ainda não foram validadas com dados reais | Parcial |
| Distinguir vazio de produto escondido atrás de outro | Oclusão e `UNKNOWN` são tratados conservadoramente; não existe estimativa de profundidade validada | Em falta / investigação |
| Planogramas digitais e produto deslocado | Planogramas versionados, células, SKU/facings esperados, API e comparação read-only estão implementados; importação/exportação e revisão completa ainda pendentes | Parcial, núcleo implementado |
| Alertas com localização, SKU, gravidade e deduplicação | Consenso temporal, alertas persistentes, eventos e resolução humana existem; falta ligar a evidência real do worker e o ciclo de eventos ao fluxo completo | Parcial |
| Reposição e tarefas | Motor de inventário/retaguarda, recomendações, tarefas, atribuição, confirmação e reconciliação já existem; integração automática da visão ainda bloqueada | Parcial |
| ERP/POS/WMS | Contratos/adaptadores e reconciliação externa estão no roadmap; integrações reais não estão operacionais | Em falta |
| Edge + Cloud | Estratégia híbrida e operação Edge estão planeadas; gateway, inferência local, buffer/offline e gestão de dispositivos ainda não estão operacionais | Em falta |
| MQTT e eventos estruturados | Catálogo de eventos, envelope, MQTT e outbox constam do TODO; falta implementação e testes end-to-end | Planeado |
| Dashboard OSA e tendências multi-loja | Dashboard e métricas operacionais existentes; OSA, duração de ruturas, share-of-shelf e comparações com cobertura/qualidade ainda pendentes | Parcial |
| Robustez a luz, reflexos, blur, oclusões e packaging | Já consta do plano de dataset/avaliação; falta dataset real e resultados por cenário | Planeado |
| Adaptação rápida a novos SKUs/embalagens | Registry de exemplares e revisão SKU existem; fluxo de novas embalagens, versionamento de packaging e avaliação few-shot/semi-supervisionada não estão formalizados | Parcial / em falta |

## 3. Itens adicionais a explicitar no TODO

1. **Reaproveitamento de CCTV/VMS:** adaptadores RTSP/ONVIF/VMS, descoberta de câmaras, credenciais por dispositivo, seleção de streams/ROI, associação a corredor/prateleira, health checks e compatibilidade documentada. Não assumir que qualquer CCTV tem resolução, ângulo ou direitos de acesso adequados.
2. **Monitorização quase em tempo real:** definir SLOs mensuráveis para captura→inferência→consenso→alerta→notificação (p50/p95), frequência de amostragem, limites por stream, backpressure e degradação quando a câmara/rede/worker falha. O artigo menciona alertas em segundos, mas o nosso alvo só deve ser fixado após medir hardware e volume.
3. **Profundidade e stock atrás da primeira fila:** avaliar multi-view, RGB-D ou estimativa monocular de profundidade apenas como investigação. A imagem 2D não deve ser usada para inferir unidades escondidas ou stock total. Separar profundidade visual, facings visíveis e quantidades físicas.
4. **Share-of-shelf e perda de facings ao longo do tempo:** medir participação visual por SKU/marca e alterações face ao planograma, com denominadores, perspetiva e cobertura da imagem explícitos.
5. **Novas embalagens e SKUs:** versionar imagens de referência/packaging, associar embalagem antiga e nova ao SKU com vigência, medir confusões entre variantes e criar um fluxo de curadoria rápida. Avaliar few-shot/semi-supervised learning sem promoção automática de modelos.
6. **Alertas accionáveis:** contrato de notificação com SKU, loja/zona/corredor/prateleira/célula, severidade, confiança, primeira/última ocorrência, frames de suporte, motivo, tarefa associada e estado de reconhecimento/resolução. Reutilizar o motor de alertas existente, não criar um segundo.
7. **Cobertura e saúde da rede de câmaras:** dashboard de câmaras online/offline, última captura, idade da evidência, zonas sem cobertura, qualidade/oclusão e falhas de inferência. Uma zona sem imagem recente deve ser `UNKNOWN`, nunca `AVAILABLE` ou `OUT_OF_STOCK`.
8. **Privacidade por desenho:** processar vídeo localmente quando viável, extrair eventos/crops mínimos, limitar retenção de frames e impedir analytics de pessoas/identificação facial. A prioridade é a prateleira, não a vigilância de clientes.

## 4. O que já está implementado e não deve ser refeito

- Sessões de captura para câmara fixa, robô e telemóvel; upload e proveniência.
- Worker de visão com provider configurável, separação disabled/mock/real e validações ONNX; ainda não há modelo comercial validado.
- Matching de SKU com embeddings/OCR, exemplares aprovados e revisão humana; ainda depende de dados e modelos validados.
- Consenso temporal e alertas persistentes idempotentes com auditoria e resolução humana; falta ligar observações reais do worker ao fluxo.
- Classe semântica `empty_facing`, comparação geométrica conservadora, estados `EMPTY`/`UNKNOWN`/`OCCUPIED`/`MISPLACED` e regras de confiança/oclusão.
- Planogramas versionados, células, SKU esperado, `expected_facings`, ativação/retirada e comparação read-only por captura.
- Recomendações, tarefas, stock de retaguarda, picking, atribuição, confirmação e reconciliação auditável; não ativar efeitos automáticos a partir de uma deteção incerta.

## 5. Sequência recomendada

1. Corrigir a reconciliação documental do estado real (não deixar tarefas já implementadas marcadas como inteiramente por fazer).
2. Completar manifesto/proveniência do modelo, dataset autorizado e avaliação real por classe/cenário.
3. Calibrar NMS/deduplicação, visibilidade e facings com imagens anotadas; integrar planograma e observações no worker sem persistência indevida.
4. Ligar observações ao consenso/alertas existentes e depois às tarefas de reposição, em modo sombra e com revisão humana.
5. Implementar gateway CCTV/VMS/RTSP, health monitoring e captura contínua; medir latência antes de prometer tempo real.
6. Acrescentar métricas OSA, share-of-shelf, duração de ruturas e cobertura/saúde das câmaras.
7. Avaliar profundidade/RGB-D, novas embalagens e adaptação few-shot como experiências separadas, apenas se o piloto demonstrar valor.
8. Só depois implementar Edge/offline, MQTT/outbox e integrações POS/ERP/WMS de ponta a ponta.

## 6. Referências e cautelas

- [Visionplatform.ai — artigo de deteção de ruturas](https://visionplatform.ai/pt/deteccao-falta-de-estoque-em-prateleiras-usando-cameras/).
- [REA externa de soluções de reposição](../reverse-engineering/external-solutions.md).
- [REA de visão computacional no retalho](retail-vision-rea.md).
- As afirmações de precisão, produtividade e ROI do artigo não foram verificadas de forma independente e não devem ser copiadas para a apresentação do SMART SHELF AI.
- Não adicionar contagem de pessoas, reconhecimento facial ou heatmaps de clientes ao âmbito deste produto; não são necessários para detetar ruturas.

## Evidência de testes do contrato ONNX e worker — 2026-11-21

A matriz de regressão de descodificação inclui coordenadas invertidas, caixas de área nula, caixas inteiramente no padding de letterbox e clipping de caixas que intersectam parcialmente o padding. O teste do worker cobre RuntimeError e TimeoutError, garantindo estado FAILED, mensagem sanitizada, preservação das deteções anteriores e ausência de snapshots de inventário.

A validação CI no commit a345746 passou com 1422 testes aprovados e 1 ignorado. Estes testes não medem precision/recall/mAP nem substituem a avaliação de um modelo treinado com dataset autorizado.
