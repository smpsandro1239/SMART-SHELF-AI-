# ADR-006 — Registar a arquitetura efetivamente implementada

**Estado:** aceite como registo do estado atual  
**Data:** 12-11-2026

## Contexto

A documentação inicial descrevia uma stack pretendida que incluía Angular, enquanto o frontend atualmente presente no repositório usa React 18, TypeScript e Vite. A documentação também descrevia vários componentes Edge, integrações empresariais e visão computacional como parte da arquitetura de referência, embora não estejam operacionalmente ligados.

## Decisão

A arquitetura as-built deve ser descrita com base no código:
- API: FastAPI, SQLAlchemy, Pydantic e PostgreSQL.
- Migrações: Alembic.
- Frontend atual: React 18, TypeScript e Vite.
- CI da API: GitHub Actions e Pytest.
- Capturas: armazenamento persistente e metadados SHA-256.
- Visão: contrato `VisionProvider` e worker independente, sem provider ativo por omissão.
- Dataset: COCO, manifesto SHA-256, auditorias, revisão humana e gate documental.

Angular, Edge AI, MQTT, robô e integrações POS/ERP/WMS permanecem opções/propostas, não componentes confirmados do produto atual.

## Consequências

- A documentação deve distinguir arquitetura implementada, arquitetura proposta e integração futura.
- Não migrar React para Angular apenas para alinhar a documentação antiga; qualquer migração exige decisão e justificação separadas.
- Não ativar modelo nem importar pesos até verificar licenças, dados, hardware e métricas.
- Os diagramas as-built não devem representar integrações externas como ativas.

## Evidência

- `apps/web/package.json`, `apps/web/src/main.tsx`
- `apps/api/app/main.py`, `apps/api/app/models.py`
- `apps/api/app/vision.py`, `apps/api/app/vision_worker.py`
- `docker-compose.yml`, `.github/workflows/api-ci.yml`
- `apps/api/app/dataset_*.py`, `apps/api/app/coco_*.py`
