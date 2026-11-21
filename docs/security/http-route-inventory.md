# Inventário de rotas HTTP — SMART SHELF AI

> Atualizado a partir do código da branch `main`, commit `311fecc9e13641e6d5eb55465fda646fb2909601` (21-11-2026). Inclui as rotas versionadas `/api/v1/*` e exclui as duas rotas de health check. A política indicada é a entrada explícita em `apps/api/app/api_security_policy.py`; a cobertura dinâmica é verificada pelo teste `test_every_registered_versioned_api_route_has_an_explicit_method_policy` e pelo auditor `audit_api_route_policy.py --strict`.

Total de declarações únicas encontradas: **128**.

Distribuição das 128 políticas explícitas: **2 PUBLIC**, **25 ADMIN_ONLY**, **88 SUPERVISOR_OR_ADMIN** e **13 EMPLOYEE_ALLOWLIST**. Uma rota ou método não registado é `UNCLASSIFIED` e o middleware recusa-o para todos os perfis, incluindo ADMIN; não existe fallback `AUTHENTICATED_STAFF`.

| Método | Caminho | Handler | Política |
|---|---|---|---|
| `POST` | `/api/v1/auth/bootstrap` | `bootstrap_first_admin` | `PUBLIC` |
| `POST` | `/api/v1/auth/login` | `login` | `PUBLIC` |
| `GET` | `/api/v1/auth/me` | `current_user` | `EMPLOYEE_ALLOWLIST` |
| `GET` | `/api/v1/auth/users` | `list_users` | `ADMIN_ONLY` |
| `POST` | `/api/v1/auth/users` | `create_user` | `ADMIN_ONLY` |
| `GET` | `/api/v1/capture-sessions` | `list_capture_sessions` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/capture-sessions` | `create_capture_session` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/capture-sessions/{session_id}/close` | `close_capture_session` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/dashboard/summary` | `dashboard_summary` | `EMPLOYEE_ALLOWLIST` |
| `GET` | `/api/v1/forecasting/demand` | `get_product_demand_forecast` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/forecasting/hourly-demand` | `get_hourly_demand_forecast` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/forecasting/stockout-risk` | `get_product_stockout_risk` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/forecasting/stockout-risk/portfolio` | `get_store_stockout_risk_portfolio` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/forecasting/traffic-peaks` | `get_store_traffic_peaks` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/inventory/freshness-policies` | `list_inventory_freshness_policies` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/inventory/freshness-policies` | `upsert_inventory_freshness_policy` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/inventory/latest` | `get_latest_inventory_snapshot` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/inventory/snapshots` | `list_inventory_snapshots` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/inventory/snapshots` | `create_inventory_snapshot` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/observation-alerts` | `list_observation_alerts` | `SUPERVISOR_OR_ADMIN` |
| `PATCH` | `/api/v1/observation-alerts/{alert_id}` | `update_observation_alert` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/observation-alerts/{alert_id}/events` | `list_observation_alert_events` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/observations` | `list_observations` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/observations` | `create_observation` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/operational-decisions` | `operational_decisions` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/planograms/{planogram_id}/activate` | `activate_shelf_planogram` | `SUPERVISOR_OR_ADMIN` |
| `PUT` | `/api/v1/planograms/{planogram_id}/cells` | `update_draft_planogram_cells` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/planograms/{planogram_id}/retire` | `retire_shelf_planogram` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/product-embedding-exemplars` | `list_product_embedding_exemplars` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/product-embedding-exemplars` | `create_product_embedding_exemplar` | `SUPERVISOR_OR_ADMIN` |
| `PATCH` | `/api/v1/product-embedding-exemplars/{exemplar_id}/review` | `review_product_embedding_exemplar` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/products` | `list_products` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/products` | `create_product` | `ADMIN_ONLY` |
| `GET` | `/api/v1/replenishment/plan` | `get_replenishment_plan` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/replenishment/recommendations` | `list_replenishment_recommendations` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/replenishment/workload` | `get_replenishment_workload` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/sales/daily` | `list_daily_sales_records` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/sales/daily` | `create_daily_sales_record` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/sales/hourly` | `list_hourly_sales_records` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/sales/hourly` | `create_hourly_sales_record` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/sales/hourly/batch` | `create_hourly_sales_batch` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/sales/hourly/import-csv` | `import_hourly_sales_csv` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/sales/import-csv` | `import_daily_sales_csv` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/sales/traffic/hourly` | `list_hourly_store_traffic_records` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/sales/traffic/hourly` | `create_hourly_store_traffic_record` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/sales/traffic/hourly/batch` | `create_hourly_traffic_batch` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/sales/traffic/hourly/import-csv` | `import_hourly_traffic_csv` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/shelf-image-detections/{detection_id}/observation` | `create_observation_from_demo_detection` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/shelf-image-detections/{detection_id}/reviews` | `list_detection_sku_reviews` | `EMPLOYEE_ALLOWLIST` |
| `POST` | `/api/v1/shelf-image-detections/{detection_id}/reviews` | `create_detection_sku_review` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/shelf-image-review-queue` | `list_shelf_image_review_queue` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/shelf-image-review-queue/summary` | `get_shelf_image_review_queue_summary` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/shelf-images` | `list_shelf_images` | `EMPLOYEE_ALLOWLIST` |
| `POST` | `/api/v1/shelf-images` | `upload_shelf_image` | `EMPLOYEE_ALLOWLIST` |
| `POST` | `/api/v1/shelf-images/{image_id}/artifact-inventory-snapshots` | `create_shelf_image_artifact_inventory_snapshot` | `ADMIN_ONLY` |
| `GET` | `/api/v1/shelf-images/{image_id}/artifacts` | `list_shelf_image_artifact_references` | `ADMIN_ONLY` |
| `POST` | `/api/v1/shelf-images/{image_id}/artifacts` | `register_shelf_image_artifact_reference` | `ADMIN_ONLY` |
| `GET` | `/api/v1/shelf-images/{image_id}/artifacts/{artifact_id}/access` | `get_shelf_image_artifact_access_decision` | `ADMIN_ONLY` |
| `GET` | `/api/v1/shelf-images/{image_id}/artifacts/{artifact_id}/disposition-events` | `list_shelf_image_artifact_disposition_events` | `ADMIN_ONLY` |
| `POST` | `/api/v1/shelf-images/{image_id}/artifacts/{artifact_id}/disposition-events` | `create_shelf_image_artifact_disposition_event` | `ADMIN_ONLY` |
| `GET` | `/api/v1/shelf-images/{image_id}/content` | `get_shelf_image_content` | `EMPLOYEE_ALLOWLIST` |
| `GET` | `/api/v1/shelf-images/{image_id}/detections` | `list_shelf_image_detections` | `EMPLOYEE_ALLOWLIST` |
| `GET` | `/api/v1/shelf-images/{image_id}/evidence-fusion` | `list_shelf_image_fused_evidence` | `EMPLOYEE_ALLOWLIST` |
| `POST` | `/api/v1/shelf-images/{image_id}/evidence-fusion` | `fuse_shelf_image_evidence` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/shelf-images/{image_id}/ocr-evidence` | `list_shelf_image_ocr_evidence` | `EMPLOYEE_ALLOWLIST` |
| `GET` | `/api/v1/shelf-images/{image_id}/ocr-matches` | `list_shelf_image_ocr_matches` | `EMPLOYEE_ALLOWLIST` |
| `POST` | `/api/v1/shelf-images/{image_id}/ocr-matches` | `match_shelf_image_ocr_to_catalogue` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/shelf-images/{image_id}/ocr-runs` | `list_shelf_image_ocr_runs` | `EMPLOYEE_ALLOWLIST` |
| `POST` | `/api/v1/shelf-images/{image_id}/ocr-runs` | `create_shelf_image_ocr_run` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/shelf-images/{image_id}/retention/events` | `list_shelf_image_retention_events` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/shelf-images/{image_id}/retention/legal-hold/apply` | `apply_shelf_image_legal_hold` | `ADMIN_ONLY` |
| `POST` | `/api/v1/shelf-images/{image_id}/retention/legal-hold/release` | `release_shelf_image_legal_hold` | `ADMIN_ONLY` |
| `GET` | `/api/v1/shelf-images/{image_id}/retention/purge-eligibility` | `get_shelf_image_purge_eligibility` | `ADMIN_ONLY` |
| `POST` | `/api/v1/shelf-images/{image_id}/retention/purge-schedule` | `schedule_shelf_image_purge` | `ADMIN_ONLY` |
| `POST` | `/api/v1/shelf-images/{image_id}/retention/purge-schedule/cancel` | `cancel_shelf_image_purge_schedule` | `ADMIN_ONLY` |
| `POST` | `/api/v1/shelf-images/{image_id}/retention/restore` | `restore_shelf_image` | `ADMIN_ONLY` |
| `POST` | `/api/v1/shelf-images/{image_id}/retention/restrict` | `restrict_shelf_image` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/shelf-images/{image_id}/retry` | `retry_shelf_image_analysis` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/shelf-products` | `list_shelf_products` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/shelf-products` | `assign_product_to_shelf` | `ADMIN_ONLY` |
| `GET` | `/api/v1/shelves` | `list_shelves` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/shelves` | `create_shelf` | `ADMIN_ONLY` |
| `POST` | `/api/v1/shelves/{shelf_id}/observation-alerts/evaluate` | `evaluate_and_persist_observation_alert` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/shelves/{shelf_id}/observation-consensus` | `get_shelf_observation_consensus` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/shelves/{shelf_id}/planograms` | `list_shelf_planograms` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/shelves/{shelf_id}/planograms` | `create_shelf_planogram` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/shelves/{shelf_id}/planograms/active` | `get_active_shelf_planogram` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/shelves/{shelf_id}/planograms/comparison/{image_id}` | `compare_shelf_image_with_active_planogram` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/sku-evaluation/reviewed` | `get_reviewed_sku_evaluation` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/store-employees` | `list_store_employees` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/stores` | `list_stores` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/stores` | `create_store` | `ADMIN_ONLY` |
| `GET` | `/api/v1/stores/{store_id}/external-integrations` | `list_store_external_integrations` | `ADMIN_ONLY` |
| `POST` | `/api/v1/stores/{store_id}/external-integrations` | `create_store_external_integration` | `ADMIN_ONLY` |
| `PATCH` | `/api/v1/stores/{store_id}/external-integrations/{integration_id}` | `update_store_external_integration` | `ADMIN_ONLY` |
| `GET` | `/api/v1/stores/{store_id}/external-integrations/coverage` | `get_store_external_integration_coverage` | `ADMIN_ONLY` |
| `GET` | `/api/v1/tasks` | `list_replenishment_tasks` | `EMPLOYEE_ALLOWLIST` |
| `POST` | `/api/v1/tasks` | `create_replenishment_task` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/tasks/{task_id}/events` | `list_replenishment_task_events` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/tasks/{task_id}/reconcile-inventory` | `reconcile_completed_replenishment` | `SUPERVISOR_OR_ADMIN` |
| `PATCH` | `/api/v1/tasks/{task_id}/status` | `update_replenishment_task_status` | `EMPLOYEE_ALLOWLIST` |
| `POST` | `/api/v1/tasks/from-operational-decision` | `create_task_from_operational_decision` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/tasks/from-recommendation` | `create_task_from_recommendation` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/training-candidates/reviewed` | `list_reviewed_training_candidates` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/warehouse/locations` | `list_warehouse_locations` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/warehouse/locations` | `create_warehouse_location` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/warehouse/pallet-rotation/hourly-profile` | `get_pallet_rotation_hourly_profile` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/warehouse/pallet-rotation/policies` | `list_pallet_rotation_policies` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/warehouse/pallet-rotation/policies` | `create_pallet_rotation_policy` | `SUPERVISOR_OR_ADMIN` |
| `PATCH` | `/api/v1/warehouse/pallet-rotation/policies/{policy_id}` | `update_pallet_rotation_policy` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/warehouse/pallet-rotation/portfolio` | `get_pallet_rotation_portfolio` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/warehouse/pallet-rotation/portfolio-from-history` | `get_pallet_rotation_portfolio_from_history` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/warehouse/pallet-rotation/simulate` | `simulate_pallet_rotation` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/warehouse/pallet-rotation/weekday-hourly-profile` | `get_pallet_rotation_weekday_hourly_profile` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/warehouse/pallet-rotation/window-plan` | `plan_pallet_rotation_window` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/warehouse/pallets` | `list_store_pallets` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/warehouse/pallets` | `register_store_pallet` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/warehouse/pallets/{pallet_id}/events` | `list_pallet_lifecycle_events` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/warehouse/pallets/{pallet_id}/events` | `record_pallet_lifecycle_update` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/warehouse/physical-slotting` | `get_physical_warehouse_slotting` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/warehouse/placements` | `create_warehouse_placement` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/warehouse/product-packaging` | `list_product_packaging_levels` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/warehouse/product-packaging` | `create_product_packaging_level` | `ADMIN_ONLY` |
| `POST` | `/api/v1/warehouse/product-profiles` | `create_warehouse_product_profile` | `ADMIN_ONLY` |
| `GET` | `/api/v1/warehouse/replenishment-units` | `calculate_replenishment_units` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/warehouse/slotting-recommendations` | `get_warehouse_slotting_recommendations` | `SUPERVISOR_OR_ADMIN` |
| `GET` | `/api/v1/zones` | `list_zones` | `SUPERVISOR_OR_ADMIN` |
| `POST` | `/api/v1/zones` | `create_zone` | `ADMIN_ONLY` |

## Limitações

- O inventário não avalia as regras de autorização nem os filtros de loja.
- A existência de uma rota no inventário não implica que todos os perfis possam aceder-lhe.
- A matriz de permissões e os testes JWT/integração continuam a ser a fonte de validação comportamental.
