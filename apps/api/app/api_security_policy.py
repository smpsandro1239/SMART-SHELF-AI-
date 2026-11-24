"""Explicit, method-specific authorization policy for every versioned HTTP route.

Policies are keyed by FastAPI route templates, not broad path prefixes. A new
route or HTTP method is denied until it receives an explicit entry here.
"""

from __future__ import annotations

VALID_API_ROLES = frozenset({"ADMIN", "SUPERVISOR", "EMPLOYEE"})

API_ROUTE_POLICIES = (
    # Device bearer + HMAC authentication is enforced by the dedicated Edge router.
    ("POST", "/api/v1/edge/events", "PUBLIC"),
    ("POST", "/api/v1/auth/bootstrap", "PUBLIC"),
    ("POST", "/api/v1/auth/login", "PUBLIC"),
    ("GET", "/api/v1/auth/me", "EMPLOYEE_ALLOWLIST"),
    ("GET", "/api/v1/auth/users", "ADMIN_ONLY"),
    ("POST", "/api/v1/auth/users", "ADMIN_ONLY"),
    ("GET", "/api/v1/capture-sessions", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/capture-sessions", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/capture-sessions/{session_id}/close", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/dashboard/summary", "EMPLOYEE_ALLOWLIST"),
    ("GET", "/api/v1/dashboard/operations", "EMPLOYEE_ALLOWLIST"),
    ("GET", "/api/v1/forecasting/demand", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/forecasting/hourly-demand", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/forecasting/stockout-risk", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/forecasting/stockout-risk/portfolio", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/forecasting/traffic-peaks", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/inventory/freshness-policies", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/inventory/freshness-policies", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/inventory/latest", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/inventory/movements", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/inventory/reconciliation", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/inventory/reconciliations", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/inventory/reconciliations", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/inventory/reconciliations/{reconciliation_id}/review", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/inventory/snapshots", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/inventory/snapshots", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/observation-alerts", "SUPERVISOR_OR_ADMIN"),
    ("PATCH", "/api/v1/observation-alerts/{alert_id}", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/observation-alerts/{alert_id}/events", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/observations", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/observations", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/operational-decisions", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/planograms/{planogram_id}/activate", "SUPERVISOR_OR_ADMIN"),
    ("PUT", "/api/v1/planograms/{planogram_id}/cells", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/planograms/{planogram_id}/retire", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/product-embedding-exemplars", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/product-embedding-exemplars", "SUPERVISOR_OR_ADMIN"),
    ("PATCH", "/api/v1/product-embedding-exemplars/{exemplar_id}/review", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/products", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/products", "ADMIN_ONLY"),
    ("POST", "/api/v1/replenishment/auto-assign", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/replenishment/plan", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/replenishment/recommendations", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/replenishment/workload", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/sales/daily", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/sales/daily", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/sales/hourly", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/sales/hourly", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/sales/hourly/batch", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/sales/hourly/import-csv", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/sales/import-csv", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/sales/traffic/hourly", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/sales/traffic/hourly", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/sales/traffic/hourly/batch", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/sales/traffic/hourly/import-csv", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/shelf-image-detections/{detection_id}/observation", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/shelf-image-detections/{detection_id}/reviews", "EMPLOYEE_ALLOWLIST"),
    ("POST", "/api/v1/shelf-image-detections/{detection_id}/reviews", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/shelf-image-review-queue", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/shelf-image-review-queue/summary", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/shelf-images", "EMPLOYEE_ALLOWLIST"),
    ("POST", "/api/v1/shelf-images", "EMPLOYEE_ALLOWLIST"),
    ("POST", "/api/v1/shelf-images/{image_id}/artifact-inventory-snapshots", "ADMIN_ONLY"),
    ("GET", "/api/v1/shelf-images/{image_id}/artifacts", "ADMIN_ONLY"),
    ("POST", "/api/v1/shelf-images/{image_id}/artifacts", "ADMIN_ONLY"),
    ("GET", "/api/v1/shelf-images/{image_id}/artifacts/{artifact_id}/access", "ADMIN_ONLY"),
    ("GET", "/api/v1/shelf-images/{image_id}/artifacts/{artifact_id}/disposition-events", "ADMIN_ONLY"),
    ("POST", "/api/v1/shelf-images/{image_id}/artifacts/{artifact_id}/disposition-events", "ADMIN_ONLY"),
    ("GET", "/api/v1/shelf-images/{image_id}/content", "EMPLOYEE_ALLOWLIST"),
    ("GET", "/api/v1/shelf-images/{image_id}/detections", "EMPLOYEE_ALLOWLIST"),
    ("GET", "/api/v1/shelf-images/{image_id}/evidence-fusion", "EMPLOYEE_ALLOWLIST"),
    ("POST", "/api/v1/shelf-images/{image_id}/evidence-fusion", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/shelf-images/{image_id}/ocr-evidence", "EMPLOYEE_ALLOWLIST"),
    ("GET", "/api/v1/shelf-images/{image_id}/ocr-matches", "EMPLOYEE_ALLOWLIST"),
    ("POST", "/api/v1/shelf-images/{image_id}/ocr-matches", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/shelf-images/{image_id}/ocr-runs", "EMPLOYEE_ALLOWLIST"),
    ("POST", "/api/v1/shelf-images/{image_id}/ocr-runs", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/shelf-images/{image_id}/retention/events", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/shelf-images/{image_id}/retention/legal-hold/apply", "ADMIN_ONLY"),
    ("POST", "/api/v1/shelf-images/{image_id}/retention/legal-hold/release", "ADMIN_ONLY"),
    ("GET", "/api/v1/shelf-images/{image_id}/retention/purge-eligibility", "ADMIN_ONLY"),
    ("POST", "/api/v1/shelf-images/{image_id}/retention/purge-schedule", "ADMIN_ONLY"),
    ("POST", "/api/v1/shelf-images/{image_id}/retention/purge-schedule/cancel", "ADMIN_ONLY"),
    ("POST", "/api/v1/shelf-images/{image_id}/retention/restore", "ADMIN_ONLY"),
    ("POST", "/api/v1/shelf-images/{image_id}/retention/restrict", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/shelf-images/{image_id}/retry", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/shelf-products", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/shelf-products", "ADMIN_ONLY"),
    ("GET", "/api/v1/shelves", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/shelves", "ADMIN_ONLY"),
    ("POST", "/api/v1/shelves/{shelf_id}/observation-alerts/evaluate", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/shelves/{shelf_id}/observation-consensus", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/shelves/{shelf_id}/planograms", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/shelves/{shelf_id}/planograms", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/shelves/{shelf_id}/planograms/active", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/shelves/{shelf_id}/planograms/comparison/{image_id}", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/sku-evaluation/reviewed", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/staff/shifts", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/staff/shifts", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/staff/skills", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/staff/skills", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/staff/availability", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/staff/availability", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/store-employees", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/stores", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/stores", "ADMIN_ONLY"),
    ("GET", "/api/v1/stores/{store_id}/external-integrations", "ADMIN_ONLY"),
    ("POST", "/api/v1/stores/{store_id}/external-integrations", "ADMIN_ONLY"),
    ("PATCH", "/api/v1/stores/{store_id}/external-integrations/{integration_id}", "ADMIN_ONLY"),
    ("GET", "/api/v1/stores/{store_id}/external-integrations/coverage", "ADMIN_ONLY"),
    ("GET", "/api/v1/tasks", "EMPLOYEE_ALLOWLIST"),
    ("POST", "/api/v1/tasks", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/tasks/{task_id}/events", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/tasks/{task_id}/reconcile-inventory", "SUPERVISOR_OR_ADMIN"),
    ("PATCH", "/api/v1/tasks/{task_id}/status", "EMPLOYEE_ALLOWLIST"),
    ("POST", "/api/v1/tasks/from-operational-decision", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/tasks/from-recommendation", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/training-candidates/reviewed", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/warehouse/locations", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/warehouse/locations", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/warehouse/pallet-rotation/hourly-profile", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/warehouse/pallet-rotation/policies", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/warehouse/pallet-rotation/policies", "SUPERVISOR_OR_ADMIN"),
    ("PATCH", "/api/v1/warehouse/pallet-rotation/policies/{policy_id}", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/warehouse/pallet-rotation/portfolio", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/warehouse/pallet-rotation/portfolio-from-history", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/warehouse/pallet-rotation/simulate", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/warehouse/pallet-rotation/weekday-hourly-profile", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/warehouse/pallet-rotation/window-plan", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/warehouse/pallets", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/warehouse/pallets", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/warehouse/pallets/{pallet_id}/events", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/warehouse/pallets/{pallet_id}/events", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/warehouse/physical-slotting", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/warehouse/placements", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/warehouse/product-packaging", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/warehouse/product-packaging", "ADMIN_ONLY"),
    ("POST", "/api/v1/warehouse/product-profiles", "ADMIN_ONLY"),
    ("GET", "/api/v1/warehouse/replenishment-units", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/warehouse/slotting-recommendations", "SUPERVISOR_OR_ADMIN"),
    ("GET", "/api/v1/zones", "SUPERVISOR_OR_ADMIN"),
    ("POST", "/api/v1/zones", "ADMIN_ONLY"),
)

POLICY_CATEGORIES = frozenset({
    "PUBLIC",
    "ADMIN_ONLY",
    "SUPERVISOR_OR_ADMIN",
    "EMPLOYEE_ALLOWLIST",
})


def _path_matches_template(path: str, template: str) -> bool:
    """Match a concrete URL path against a registered FastAPI route template."""
    path_parts = path.strip("/").split("/")
    template_parts = template.strip("/").split("/")
    return len(path_parts) == len(template_parts) and all(
        expected == actual
        or (expected.startswith("{") and expected.endswith("}") and bool(actual))
        for actual, expected in zip(path_parts, template_parts)
    )


def classify_api_route(method: str, path: str) -> str:
    """Return the explicit policy for one method/path, or UNCLASSIFIED."""
    normalized_method = method.upper()
    matches = {
        policy
        for route_method, template, policy in API_ROUTE_POLICIES
        if route_method == normalized_method and _path_matches_template(path, template)
    }
    if len(matches) == 1:
        return matches.pop()
    if len(matches) > 1:
        raise RuntimeError(
            f"Conflicting authorization policies for {normalized_method} {path}"
        )
    return "UNCLASSIFIED"


def is_public_api_route(method: str, path: str) -> bool:
    """Return whether this exact HTTP method/path pair is intentionally public."""
    return classify_api_route(method, path) == "PUBLIC"


def api_role_denial(method: str, path: str, role: str) -> str | None:
    """Return the denial reason; None means the explicit route policy permits the role."""
    if role not in VALID_API_ROLES:
        return "User role is not authorized"

    policy = classify_api_route(method, path)
    if policy == "UNCLASSIFIED":
        return "API route has no explicit authorization policy"
    if policy == "PUBLIC" or policy == "EMPLOYEE_ALLOWLIST":
        return None
    if policy == "ADMIN_ONLY" and role != "ADMIN":
        return "Administrator role required"
    if policy == "SUPERVISOR_OR_ADMIN" and role not in {"ADMIN", "SUPERVISOR"}:
        return "Supervisor role required"
    return None
