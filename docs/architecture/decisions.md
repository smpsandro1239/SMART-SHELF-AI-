# Registo de decisões de arquitetura

As decisões abaixo são iniciais e podem ser revistas mediante evidência técnica.

## ADR-001 — Arquitetura híbrida Edge + Cloud
**Estado:** proposta.

Usar Edge para captura, filtragem, inferência local quando útil e funcionamento offline; Cloud para coordenação, histórico, integração, previsão e analytics. A divisão exata depende do hardware, conectividade, custo e requisitos de privacidade.

## ADR-002 — Separar stock visual de stock de inventário
**Estado:** aceite como princípio.

A visão estima disponibilidade visível. O inventário oficial provém do sistema de stock identificado. Os dois valores devem ser armazenados e apresentados separadamente, com timestamps e proveniência.

## ADR-003 — Stack inicial
**Estado:** proposta.

FastAPI, PostgreSQL, Angular/TypeScript, OpenCV/PyTorch e Docker Compose. MQTT/Redis são opcionais até existir necessidade comprovada.

## ADR-004 — Integração do robô condicionada
**Estado:** bloqueada por informação em falta.

Não assumir ROS 2, SDK, acesso à navegação ou possibilidade de montagem. A decisão depende da marca/modelo, documentação e autorização do fabricante.

## ADR-005 — Licenciamento de modelos
**Estado:** avaliação técnica iniciada; seleção final pendente.

Antes de selecionar o modelo de visão, analisar a licença do código, dos pesos concretos e dos dados de treino, incluindo utilização comercial, redistribuição, inferência embebida e obrigações de disponibilização de código. Não assumir que um modelo é livre para integração proprietária.

Avaliação documental em 12-11-2026:
- **Ultralytics YOLO26:** a documentação oficial identifica YOLO26 como a família atualmente lançada e recomenda YOLO26/YOLO11 para workloads de produção. Contudo, a Ultralytics declara que o uso do seu código, modelos, pipelines ou modelos afinados exige AGPL-3.0 com disponibilização do projeto correspondente, ou uma licença Enterprise para manter o produto fechado. O repositório SMART SHELF AI não declara atualmente uma licença de projeto; por isso, não adicionar a dependência Ultralytics sem decisão explícita de licenciamento.
- **RT-DETR oficial (lyuwenyu/RT-DETR):** o repositório oficial declara Apache-2.0 e disponibiliza implementações PyTorch/Paddle e checkpoints RT-DETR/RT-DETRv2. É um candidato inicial mais compatível com uma futura distribuição comercial fechada, sujeito à verificação da licença do checkpoint exato e dos respetivos avisos de terceiros.
- **Limite funcional:** os pesos pré-treinados em COCO detetam classes genéricas, não identificam automaticamente SKUs específicos de uma loja. O reconhecimento de referências comerciais exige dataset próprio, anotação, treino/ajuste, validação por classe e avaliação em fotografias reais das prateleiras.

Fontes consultadas:
- [Ultralytics — documentação oficial](https://docs.ultralytics.com/)
- [Ultralytics — licenciamento oficial](https://www.ultralytics.com/license)
- [RT-DETR — repositório oficial e licença](https://github.com/lyuwenyu/RT-DETR)

**Decisão provisória:** manter a interface `VisionProvider` agnóstica ao modelo. Avaliar RT-DETR PyTorch como primeira implementação experimental depois de confirmar hardware e dataset. Não descarregar pesos, instalar runtimes de ML ou ativar inferência em produção nesta fase.


## ADR-006 — Arquitetura implementada (as-built)
**Estado:** aceite como registo do estado atual.

O frontend presente no repositório é React 18, TypeScript e Vite; a referência antiga a Angular descreve uma intenção anterior e não a implementação atual. A API é FastAPI/SQLAlchemy, com PostgreSQL/Alembic, autenticação JWT/Argon2, captura de imagens e worker de visão configurável sem provider ativo por omissão. Edge AI, MQTT, robô e integrações POS/ERP/WMS permanecem propostas. O detalhe e as consequências desta decisão estão em [ADR-006](adr-006-as-built-stack.md) e no [relatório REA](../reverse-engineering/README.md).
