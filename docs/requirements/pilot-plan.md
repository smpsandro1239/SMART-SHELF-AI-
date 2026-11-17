# Plano de piloto — proposta de 16 semanas

Este calendário é uma estimativa de planeamento, não um compromisso. Depende de acesso a dados, equipamentos, equipa e autorizações.

| Período | Trabalho | Evidência de conclusão |
|---|---|---|
| Semanas 1–2 | Requisitos, arquitetura, repositório, Docker e base de dados | Ambiente reproduzível e decisões registadas |
| Semanas 3–4 | Captura e registo de imagens de teste; primeiro fluxo de visão | Dataset autorizado e observações persistidas |
| Semanas 5–6 | API, catálogo e inventário simulado | Endpoints testados e dados rastreáveis |
| Semanas 7–8 | Dashboard/PWA inicial | Consulta de prateleiras e observações |
| Semanas 9–10 | Baseline de previsão | Métricas comparadas com baseline simples |
| Semanas 11–12 | Motor de tarefas e exceções | Fluxo de tarefa testado de ponta a ponta |
| Semanas 13–14 | Experiência Edge/robô, se autorizado | Compatibilidade demonstrada ou risco documentado |
| Semanas 15–16 | Validação, KPIs e relatório | Relatório de resultados e decisão de continuidade |

## Âmbito inicial sugerido

- Uma loja.
- Uma ou duas secções.
- Dois a quatro corredores.
- 50–100 referências de produto.
- Duas a quatro câmaras fixas autorizadas.
- Um ou dois telemóveis.
- Um robô existente, apenas se a integração for aprovada e tecnicamente viável.

## KPIs a medir

Os valores-alvo só devem ser definidos após estabelecer dataset, método de amostragem e baseline. Medir pelo menos:
- precisão e recall por classe de deteção;
- recall de situações críticas de baixa disponibilidade;
- falsos positivos por prateleira/dia;
- latência entre observação e evento;
- erro de previsão por horizonte;
- tempo até conclusão de tarefa;
- disponibilidade do serviço e dos dispositivos;
- proporção de recomendações confirmadas pelos operadores.

Não apresentar metas como resultados alcançados. Registar amostra, período, condições e versão do modelo em cada avaliação.
