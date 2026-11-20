"""Central, auditable role policy for versioned API routes."""

PUBLIC_API_PATHS = frozenset({
    "/api/v1/auth/bootstrap",
    "/api/v1/auth/login",
})
VALID_API_ROLES = frozenset({"ADMIN", "SUPERVISOR", "EMPLOYEE"})

ADMIN_ONLY_POST_PATHS = frozenset({
    "/api/v1/stores",
    "/api/v1/zones",
    "/api/v1/shelves",
    "/api/v1/products",
    "/api/v1/shelf-products",
    "/api/v1/warehouse/product-profiles",
    "/api/v1/warehouse/product-packaging",
})

SUPERVISOR_OR_ADMIN_POST_PATHS = frozenset({
    "/api/v1/tasks/from-operational-decision",
    "/api/v1/sales/daily",
    "/api/v1/sales/import-csv",
    "/api/v1/warehouse/locations",
    "/api/v1/warehouse/placements",
    "/api/v1/warehouse/pallets",
    "/api/v1/warehouse/pallet-rotation/policies",
    "/api/v1/warehouse/pallet-rotation/simulate",
    "/api/v1/sales/hourly",
    "/api/v1/sales/traffic/hourly",
    "/api/v1/sales/hourly/batch",
    "/api/v1/sales/traffic/hourly/batch",
    "/api/v1/sales/hourly/import-csv",
    "/api/v1/sales/traffic/hourly/import-csv",
    "/api/v1/inventory/snapshots",
})


def _is_path_or_subpath(path: str, prefix: str) -> bool:
    """Match a route prefix only at a path-segment boundary."""
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def _is_admin_only(method: str, path: str) -> bool:
    return _is_path_or_subpath(path, "/api/v1/auth/users") or (
        method == "POST" and path in ADMIN_ONLY_POST_PATHS
    )


def _is_supervisor_or_admin(method: str, path: str) -> bool:
    return (
        _is_path_or_subpath(path, "/api/v1/observation-alerts")
        or (_is_path_or_subpath(path, "/api/v1/shelves") and "planograms" in path.split("/"))
        or _is_path_or_subpath(path, "/api/v1/planograms")
        or (method == "POST" and path.endswith("/observation-alerts/evaluate"))
        or (method == "POST" and path in SUPERVISOR_OR_ADMIN_POST_PATHS)
        or (
            method == "POST"
            and _is_path_or_subpath(path, "/api/v1/warehouse/pallets")
            and path.endswith("/events")
        )
        or (
            method == "PATCH"
            and path.startswith("/api/v1/warehouse/pallet-rotation/policies/")
        )
        or path == "/api/v1/product-embedding-exemplars"
        or _is_path_or_subpath(path, "/api/v1/product-embedding-exemplars")
        or (method == "GET" and path == "/api/v1/training-candidates/reviewed")
        or (
            method == "GET"
            and path in {
                "/api/v1/shelf-image-review-queue",
                "/api/v1/shelf-image-review-queue/summary",
                "/api/v1/sku-evaluation/reviewed",
            }
        )
        or (method == "POST" and _is_path_or_subpath(path, "/api/v1/shelf-image-detections"))
        or (
            method == "POST"
            and _is_path_or_subpath(path, "/api/v1/shelf-images")
            and path.endswith(("/ocr-runs", "/ocr-matches", "/evidence-fusion"))
        )
    )


def _is_employee_allowed(method: str, path: str) -> bool:
    if method == "GET" and path in {
        "/api/v1/tasks",
        "/api/v1/auth/me",
        "/api/v1/dashboard/summary",
        "/api/v1/shelf-images",
    }:
        return True
    if method == "POST" and path == "/api/v1/shelf-images":
        return True
    if method == "GET" and path.startswith("/api/v1/shelf-images/"):
        return path.endswith(("/content", "/detections", "/ocr-evidence", "/ocr-runs", "/ocr-matches", "/evidence-fusion"))
    if method == "GET" and path.startswith("/api/v1/shelf-image-detections/"):
        return path.endswith("/reviews")
    return (
        method == "PATCH"
        and _is_path_or_subpath(path, "/api/v1/tasks")
        and path.endswith("/status")
    )


def classify_api_route(method: str, path: str) -> str:
    """Return the effective route policy category for audit and tests."""
    method = method.upper()
    if path in PUBLIC_API_PATHS:
        return "PUBLIC"
    if _is_admin_only(method, path):
        return "ADMIN_ONLY"
    if _is_supervisor_or_admin(method, path):
        return "SUPERVISOR_OR_ADMIN"
    if _is_employee_allowed(method, path):
        return "EMPLOYEE_ALLOWLIST"
    return "AUTHENTICATED_STAFF"


def api_role_denial(method: str, path: str, role: str) -> str | None:
    """Return the 403 detail for a denied role; None means the role is allowed."""
    method = method.upper()
    if role not in VALID_API_ROLES:
        return "User role is not authorized"
    if _is_admin_only(method, path) and role != "ADMIN":
        return "Administrator role required"
    if _is_supervisor_or_admin(method, path) and role not in {"ADMIN", "SUPERVISOR"}:
        return "Supervisor role required"
    if role == "EMPLOYEE" and not _is_employee_allowed(method, path):
        return "Employee access is limited to assigned tasks"
    return None
