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
**Estado:** por avaliar.

Antes de selecionar o modelo de visão, analisar licença, utilização comercial, redistribuição, inferência embebida e obrigações de disponibilização de código. Não assumir que um modelo é livre para integração proprietária.
