# Inventário de rotas HTTP — SMART SHELF AI

> Gerado por leitura estática de `apps/api/app/main.py` na branch `main`, a partir do commit `297f92453791331ab9788920f6a8e0b28367818f` (18-11-2026). É um inventário de declarações FastAPI, não uma prova de autorização efetiva. Rotas dinâmicas, dependências, middleware e permissões aplicadas dentro dos handlers devem ser confirmados em testes.

Total de declarações únicas encontradas: **123**.

| Método | Caminho | Handler |
|---|---|---|
| `POST` | `/api/v1/auth/bootstrap` | `bootstrap_first_admin` |
| `POST` | `/api/v1/auth/login` | `login` |
| `GET` | `/api/v1/auth/me` | `current_user` |
| `GET` | `/api/v1/auth/users` | `list_users` |
| `POST` | `/api/v1/auth/users` | `create_user` |
| `POST` | `/api/v1/capture-sessions/{session_id}/close` | `close_capture_session` |
| `GET` | `/api/v1/capture-sessions` | `list_capture_sessions` |
| `POST` | `/api/v1/capture-sessions` | `create_capture_session` |
| `GET` | `/api/v1/dashboard/summary` | `dashboard_summary` |
| `GET` | `/api/v1/forecasting/demand` | `get_product_demand_forecast` |
| `GET` | `/api/v1/forecasting/hourly-demand` | `get_hourly_demand_forecast` |
| `GET` | `/api/v1/forecasting/stockout-risk/portfolio` | `get_store_stockout_risk_portfolio` |
| `GET` | `/api/v1/forecasting/stockout-risk` | `get_product_stockout_risk` |
| `GET` | `/api/v1/forecasting/traffic-peaks` | `get_store_traffic_peaks` |
| `GET` | `/api/v1/inventory/freshness-policies` | `list_inventory_freshness_policies` |
| `POST` | `/api/v1/inventory/freshness-policies` | `upsert_inventory_freshness_policy` |
| `GET` | `/api/v1/inventory/latest` | `get_latest_inventory_snapshot` |
| `GET` | `/api/v1/inventory/snapshots` | `list_inventory_snapshots` |
| `POST` | `/api/v1/inventory/snapshots` | `create_inventory_snapshot` |
| `GET` | `/api/v1/observation-alerts/{alert_id}/events` | `list_observation_alert_events` |
| `PATCH` | `/api/v1/observation-alerts/{alert_id}` | `update_observation_alert` |
| `GET` | `/api/v1/observation-alerts` | `list_observation_alerts` |
| `GET` | `/api/v1/observations` | `list_observations` |
| `POST` | `/api/v1/observations` | `create_observation` |
| `GET` | `/api/v1/operational-decisions` | `operational_decisions` |
| `PATCH` | `/api/v1/product-embedding-exemplars/{exemplar_id}/review` | `review_product_embedding_exemplar` |
| `GET` | `/api/v1/product-embedding-exemplars` | `list_product_embedding_exemplars` |
| `POST` | `/api/v1/product-embedding-exemplars` | `create_product_embedding_exemplar` |
| `GET` | `/api/v1/products` | `list_products` |
| `POST` | `/api/v1/products` | `create_product` |
| `GET` | `/api/v1/replenishment/plan` | `get_replenishment_plan` |
| `GET` | `/api/v1/replenishment/recommendations` | `list_replenishment_recommendations` |
| `GET` | `/api/v1/replenishment/workload` | `get_replenishment_workload` |
| `GET` | `/api/v1/sales/daily` | `list_daily_sales_records` |
| `POST` | `/api/v1/sales/daily` | `create_daily_sales_record` |
| `POST` | `/api/v1/sales/hourly/batch` | `create_hourly_sales_batch` |
| `POST` | `/api/v1/sales/hourly/import-csv` | `import_hourly_sales_csv` |
| `GET` | `/api/v1/sales/hourly` | `list_hourly_sales_records` |
| `POST` | `/api/v1/sales/hourly` | `create_hourly_sales_record` |
| `POST` | `/api/v1/sales/import-csv` | `import_daily_sales_csv` |
| `POST` | `/api/v1/sales/traffic/hourly/batch` | `create_hourly_traffic_batch` |
| `POST` | `/api/v1/sales/traffic/hourly/import-csv` | `import_hourly_traffic_csv` |
| `GET` | `/api/v1/sales/traffic/hourly` | `list_hourly_store_traffic_records` |
| `POST` | `/api/v1/sales/traffic/hourly` | `create_hourly_store_traffic_record` |
| `GET` | `/api/v1/shelf-image-detections/{detection_id}/reviews` | `list_detection_sku_reviews` |
| `POST` | `/api/v1/shelf-image-detections/{detection_id}/reviews` | `create_detection_sku_review` |
| `GET` | `/api/v1/shelf-image-review-queue/summary` | `get_shelf_image_review_queue_summary` |
| `GET` | `/api/v1/shelf-image-review-queue` | `list_shelf_image_review_queue` |
| `GET` | `/api/v1/shelf-images/{image_id}/content` | `get_shelf_image_content` |
| `GET` | `/api/v1/shelf-images/{image_id}/detections` | `list_shelf_image_detections` |
| `GET` | `/api/v1/shelf-images/{image_id}/evidence-fusion` | `list_shelf_image_fused_evidence` |
| `POST` | `/api/v1/shelf-images/{image_id}/evidence-fusion` | `fuse_shelf_image_evidence` |
| `GET` | `/api/v1/shelf-images/{image_id}/ocr-evidence` | `list_shelf_image_ocr_evidence` |
| `GET` | `/api/v1/shelf-images/{image_id}/ocr-matches` | `list_shelf_image_ocr_matches` |
| `POST` | `/api/v1/shelf-images/{image_id}/ocr-matches` | `match_shelf_image_ocr_to_catalogue` |
| `GET` | `/api/v1/shelf-images/{image_id}/ocr-runs` | `list_shelf_image_ocr_runs` |
| `POST` | `/api/v1/shelf-images/{image_id}/ocr-runs` | `create_shelf_image_ocr_run` |
| `GET` | `/api/v1/shelf-images/{image_id}/retention/events` | `list_shelf_image_retention_events` |
| `POST` | `/api/v1/shelf-images/{image_id}/retention/legal-hold/apply` | `apply_shelf_image_legal_hold` |
| `POST` | `/api/v1/shelf-images/{image_id}/retention/legal-hold/release` | `release_shelf_image_legal_hold` |
| `POST` | `/api/v1/shelf-images/{image_id}/retention/restore` | `restore_shelf_image` |
| `POST` | `/api/v1/shelf-images/{image_id}/retention/restrict` | `restrict_shelf_image` |
| `POST` | `/api/v1/shelf-images/{image_id}/retry` | `retry_shelf_image_analysis` |
| `GET` | `/api/v1/shelf-images` | `list_shelf_images` |
| `POST` | `/api/v1/shelf-images` | `upload_shelf_image` |
| `GET` | `/api/v1/shelf-products` | `list_shelf_products` |
| `POST` | `/api/v1/shelf-products` | `assign_product_to_shelf` |
| `POST` | `/api/v1/shelves/{shelf_id}/observation-alerts/evaluate` | `evaluate_and_persist_observation_alert` |
| `GET` | `/api/v1/shelves/{shelf_id}/observation-consensus` | `get_shelf_observation_consensus` |
| `GET` | `/api/v1/shelves` | `list_shelves` |
| `POST` | `/api/v1/shelves` | `create_shelf` |
| `GET` | `/api/v1/sku-evaluation/reviewed` | `get_reviewed_sku_evaluation` |
| `GET` | `/api/v1/stores` | `list_stores` |
| `POST` | `/api/v1/stores` | `create_store` |
| `GET` | `/api/v1/tasks/{task_id}/events` | `list_replenishment_task_events` |
| `POST` | `/api/v1/tasks/{task_id}/reconcile-inventory` | `reconcile_completed_replenishment` |
| `PATCH` | `/api/v1/tasks/{task_id}/status` | `update_replenishment_task_status` |
| `POST` | `/api/v1/tasks/from-operational-decision` | `create_task_from_operational_decision` |
| `POST` | `/api/v1/tasks/from-recommendation` | `create_task_from_recommendation` |
| `GET` | `/api/v1/tasks` | `list_replenishment_tasks` |
| `POST` | `/api/v1/tasks` | `create_replenishment_task` |
| `GET` | `/api/v1/training-candidates/reviewed` | `list_reviewed_training_candidates` |
| `GET` | `/api/v1/warehouse/locations` | `list_warehouse_locations` |
| `POST` | `/api/v1/warehouse/locations` | `create_warehouse_location` |
| `GET` | `/api/v1/warehouse/pallet-rotation/hourly-profile` | `get_pallet_rotation_hourly_profile` |
| `PATCH` | `/api/v1/warehouse/pallet-rotation/policies/{policy_id}` | `update_pallet_rotation_policy` |
| `GET` | `/api/v1/warehouse/pallet-rotation/policies` | `list_pallet_rotation_policies` |
| `POST` | `/api/v1/warehouse/pallet-rotation/policies` | `create_pallet_rotation_policy` |
| `GET` | `/api/v1/warehouse/pallet-rotation/portfolio-from-history` | `get_pallet_rotation_portfolio_from_history` |
| `GET` | `/api/v1/warehouse/pallet-rotation/portfolio` | `get_pallet_rotation_portfolio` |
| `POST` | `/api/v1/warehouse/pallet-rotation/simulate` | `simulate_pallet_rotation` |
| `GET` | `/api/v1/warehouse/pallet-rotation/weekday-hourly-profile` | `get_pallet_rotation_weekday_hourly_profile` |
| `GET` | `/api/v1/warehouse/pallet-rotation/window-plan` | `plan_pallet_rotation_window` |
| `GET` | `/api/v1/warehouse/pallets/{pallet_id}/events` | `list_pallet_lifecycle_events` |
| `POST` | `/api/v1/warehouse/pallets/{pallet_id}/events` | `record_pallet_lifecycle_update` |
| `GET` | `/api/v1/warehouse/pallets` | `list_store_pallets` |
| `POST` | `/api/v1/warehouse/pallets` | `register_store_pallet` |
| `GET` | `/api/v1/warehouse/physical-slotting` | `get_physical_warehouse_slotting` |
| `POST` | `/api/v1/warehouse/placements` | `create_warehouse_placement` |
| `GET` | `/api/v1/warehouse/product-packaging` | `list_product_packaging_levels` |
| `POST` | `/api/v1/warehouse/product-packaging` | `create_product_packaging_level` |
| `POST` | `/api/v1/warehouse/product-profiles` | `create_warehouse_product_profile` |
| `GET` | `/api/v1/warehouse/replenishment-units` | `calculate_replenishment_units` |
| `GET` | `/api/v1/warehouse/slotting-recommendations` | `get_warehouse_slotting_recommendations` |
| `POST` | `/api/v1/zones` | `create_zone` |
| `GET` | `/health/ready` | `readiness` |
| `GET` | `/health` | `health` |
| `GET` | `/api/v1/zones` | `list_zones` |
| `POST` | `/api/v1/shelf-images/{image_id}/retention/purge-schedule` | `schedule_shelf_image_purge` |
| `POST` | `/api/v1/shelf-images/{image_id}/retention/purge-schedule/cancel` | `cancel_shelf_image_purge_schedule` |
| `POST` | `/api/v1/stores/{store_id}/external-integrations` | `create_store_external_integration` |
| `GET` | `/api/v1/stores/{store_id}/external-integrations` | `list_store_external_integrations` |
| `PATCH` | `/api/v1/stores/{store_id}/external-integrations/{integration_id}` | `update_store_external_integration` |
| `GET` | `/api/v1/stores/{store_id}/external-integrations/coverage` | `get_store_external_integration_coverage` |
| `POST` | `/api/v1/shelf-images/{image_id}/artifacts` | `register_shelf_image_artifact_reference` |
| `GET` | `/api/v1/shelf-images/{image_id}/artifacts` | `list_shelf_image_artifact_references` |
| `POST` | `/api/v1/shelf-images/{image_id}/artifact-inventory-snapshots` | `create_shelf_image_artifact_inventory_snapshot` |
| `GET` | `/api/v1/shelf-images/{image_id}/artifacts/{artifact_id}/access` | `get_shelf_image_artifact_access_decision` |
| `POST` | `/api/v1/shelf-images/{image_id}/artifacts/{artifact_id}/disposition-events` | `create_shelf_image_artifact_disposition_event` |
| `GET` | `/api/v1/shelf-images/{image_id}/artifacts/{artifact_id}/disposition-events` | `list_shelf_image_artifact_disposition_events` |
| `GET` | `/api/v1/shelf-images/{image_id}/retention/purge-eligibility` | `get_shelf_image_purge_eligibility` |
| `POST` | `/api/v1/shelf-image-detections/{detection_id}/observation` | `create_observation_from_demo_detection` |
| `GET` | `/api/v1/store-employees` | `list_store_employees` |

## Regras de utilização

- Cada rota deve ser classificada por perfil (`ADMIN`, `SUPERVISOR`, `EMPLOYEE`) e por âmbito de recurso (global, loja, prateleira, imagem, sessão de captura, tarefa, armazém).
- Para cada operação de leitura e escrita, criar pelo menos um teste JWT positivo no âmbito permitido e um teste negativo fora do âmbito.
- Confirmar que as respostas 403/404 não deixam alterações em base de dados, ficheiros, eventos de auditoria, filas ou tarefas.
- Distinguir rotas que são intencionalmente globais (por exemplo, catálogo e metadados de embalagem) de dados operacionais pertencentes a uma loja.
- Verificar rotas com sufixos e caminhos dinâmicos: a classificação do middleware por `startswith`, igualdade e sufixo deve corresponder exatamente à política pretendida.
- Complementar testes HTTP SQLite com smoke tests PostgreSQL para handlers que dependam de bloqueios, constraints, transações ou triggers.
- Atualizar este inventário sempre que uma rota for adicionada, removida ou alterada.

## Limitações desta geração

- O inventário é extraído das declarações `@app.get/post/put/patch/delete` com caminhos literais num único módulo. Não deteta rotas montadas por subaplicações, routers externos, caminhos construídos dinamicamente ou métodos registados programaticamente.
- A presença de uma rota nesta lista não significa que esteja acessível a todos os perfis; o middleware e os handlers podem impor controlos adicionais.
- Esta lista não fecha a auditoria multi-loja. Serve como checklist de cobertura e deve ser reconciliada com a matriz de autorização e os testes existentes.


## Reconciliação do inventário — 2026-11-18

A comparação estática das declarações literais `@app.get/post/put/patch/delete` em `apps/api/app/main.py` confirmou **123 declarações únicas**: 107 entradas previamente inventariadas e 16 agora integradas na tabela principal. Não foram encontradas entradas obsoletas.

**Limite:** esta reconciliação cobre declarações com caminhos literais no módulo principal. Não prova a política de autorização dos handlers nem deteta rotas montadas dinamicamente; a revisão de autorização continua separada.


## Autorização dos artefactos externos — evidência de teste (18-11-2026)

Os seis handlers de artefactos listados acima exigem perfil `ADMIN` directamente no handler. O teste `test_shelf_image_external_artifact_governance_is_admin_only_over_http` exercita os seis caminhos com JWT de `SUPERVISOR` e `EMPLOYEE`, espera HTTP 403 e confirma ausência de efeitos laterais nas tabelas de referências, snapshots e eventos. A cobertura foi validada pela suite API no CI (run 44337777007). O teste HTTP usa SQLite isolado e não substitui a revisão de isolamento multi-loja para os restantes handlers nem constitui, por si só, prova PostgreSQL.


## Gestão de integrações externas — cobertura de autorização (18-11-2026)

Os handlers de criação, listagem, consulta de cobertura e actualização de integrações externas por loja exigem ADMIN directamente. O teste `test_store_external_integration_governance_is_admin_only_over_http` verifica os quatro métodos com JWT de SUPERVISOR e EMPLOYEE, espera 403 e confirma que a contagem e a política da integração preexistente não se alteram. Validação CI concluída: API CI run 44338653668 e Quality Gates run 44338651433 passaram; Docker Compose smoke run 44338651406 também passou. O teste HTTP corre na suite API com SQLite isolado.


### Caminho autorizado ADMIN — integrações externas

O teste `test_admin_can_manage_store_external_integrations_over_http` complementa a cobertura negativa: confirma o fluxo positivo de criação, listagem, cobertura e revogação por ADMIN, incluindo ausência de campo `secret` na resposta e alteração coerente da cobertura após revogação. Validação CI pendente.

## Fluxos de revisão humana — autorização por perfil (18-11-2026)

A middleware reserva a ADMIN/SUPERVISOR a consulta da fila de revisão, resumo, avaliação de SKU revista, candidatos de treino revistos e submissão de revisão de deteção. O teste test_employee_cannot_access_human_review_workflows_over_http envia JWT EMPLOYEE para as cinco operações e exige HTTP 403; compara também a contagem de DetectionSkuReview antes/depois para confirmar ausência de efeitos laterais na escrita recusada.

**Limite:** esta evidência cobre o perfil EMPLOYEE através da middleware com SQLite isolado. Não demonstra o isolamento multi-loja de todos os handlers nem fecha a auditoria global.
