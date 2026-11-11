# SMART SHELF AI

**Inteligência operacional para supermercados: visão computacional, inventário, previsão de procura e reposição assistida.**

> Estado do projeto: **fase de fundação — documentação e arquitetura inicial**. As funcionalidades descritas neste repositório são objetivos e propostas, não capacidades já implementadas ou validadas.

## Visão

O SMART SHELF AI pretende ajudar operações de retalho a detetar situações de baixa disponibilidade nas prateleiras, relacioná-las com o inventário de retaguarda, antecipar ruturas e organizar tarefas de reposição.

A solução está a ser concebida para combinar:
- câmaras fixas autorizadas;
- câmaras instaladas num robô de limpeza já existente, sujeito a validação de compatibilidade;
- aplicação móvel/PWA para observações e confirmação de tarefas;
- processamento Edge AI e serviços Cloud.

## Objetivos do piloto

- Começar com uma loja e um conjunto limitado de corredores e produtos.
- Registar observações de prateleiras e respetiva origem.
- Distinguir estimativa visual de stock contabilístico.
- Consultar inventário de retaguarda antes de recomendar reposição.
- Estimar procura por hora/dia e risco de rutura.
- Criar tarefas priorizadas e permitir a sua confirmação.
- Medir resultados com métricas verificáveis.

## Arquitetura de alto nível

1. **Recolha:** câmaras fixas, robô e dispositivos móveis.
2. **Edge:** captura seletiva, inferência local, proteção de privacidade e fila offline.
3. **Plataforma:** API, base de dados, integração de inventário, previsão e gestão de tarefas.
4. **Experiência operacional:** dashboard web e PWA móvel.
5. **Integrações:** POS/ERP/WMS e interface do robô, apenas após autorização e validação técnica.

## Stack inicial proposta

| Camada | Tecnologia proposta |
|---|---|
| API | Python + FastAPI |
| Dados | PostgreSQL |
| Dashboard/PWA | Angular + TypeScript |
| Visão computacional | OpenCV + PyTorch |
| Mensagens IoT | MQTT |
| Cache/fila (se necessário) | Redis |
| Ambiente local | Docker Compose |
| CI | GitHub Actions |

As escolhas serão revistas durante a implementação. A seleção de modelos de IA deve incluir uma análise de licença adequada a utilização comercial.

## Estrutura prevista

```text
apps/
  dashboard/          # Aplicação web Angular
  mobile-pwa/         # Experiência móvel/PWA
services/
  api/                # API central
  vision/             # Análise de imagens
  inventory/          # Estado de inventário e integrações
  forecast/           # Previsão de procura e ruturas
  tasks/              # Tarefas de reposição
  robot/              # Integração com robô
edge/
  camera-agent/
  inference-engine/
  event-buffer/
  privacy-filter/
database/
  migrations/
  seeds/
integrations/
  pos/
  erp/
  wms/
  robot/
infrastructure/
  docker/
  monitoring/
docs/
  requirements/
  architecture/
  api/
  security/
  testing/
  business-case/
tests/
  unit/
  integration/
  e2e/
.github/
  workflows/
```

## Princípios de engenharia

- Não confundir deteção visual com quantidade real em stock.
- Não recomendar reposição sem verificar disponibilidade na retaguarda.
- Guardar proveniência, timestamp, confiança e versão do modelo em cada observação.
- Privacidade por conceção: sem reconhecimento facial, áudio ou identificação de clientes.
- Segredos apenas em variáveis de ambiente/secret stores; nunca em commits.
- Alterações de modelos devem ser avaliadas, versionadas e reversíveis.
- Todas as métricas e resultados devem ser medidos; não declarar resultados sem evidência.

## Começar

A primeira milestone deverá preparar o ambiente Docker, PostgreSQL e API FastAPI, criar o modelo inicial de lojas/prateleiras e permitir registar uma observação de teste. O dashboard e a inferência visual serão acrescentados de forma incremental.

Consulte:
- [Âmbito e requisitos](docs/requirements/scope.md)
- [Arquitetura](docs/architecture/overview.md)
- [Plano do piloto](docs/requirements/pilot-plan.md)
- [Privacidade e segurança](docs/security/privacy.md)
- [Registo de decisões](docs/architecture/decisions.md)

## Estado e transparência

Este repositório foi criado para centralizar o desenvolvimento. A documentação inicial regista a visão e as decisões propostas. Não existe ainda integração com sistemas de supermercado, robô, câmaras ou dados reais. Qualquer integração dependerá de acessos, autorizações, documentação técnica e testes.

## Licença

A licença ainda não foi definida. Não reutilize nem distribua este código/documentação como software open-source até ser publicada uma licença explícita.
