import pytest
import jwt

from app.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hash_is_not_plain_text_and_can_be_verified():
    password = "Correct-Horse-Battery-42!"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("incorrect-password", hashed)


def test_access_token_contains_user_identity_and_role():
    token, expires_in = create_access_token(user_id=17, role="SUPERVISOR")
    claims = decode_access_token(token)

    assert claims["sub"] == "17"
    assert claims["role"] == "SUPERVISOR"
    assert expires_in > 0


def test_access_token_rejects_tampering():
    token, _ = create_access_token(user_id=17, role="EMPLOYEE")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token + "tampered")


def test_request_user_fails_closed_when_actor_disappears_after_middleware_auth(monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.config import settings
    from app.main import _request_user

    monkeypatch.setattr(settings, "app_env", "production")
    request = SimpleNamespace(
        state=SimpleNamespace(user_id=17),
        method="GET",
        url=SimpleNamespace(path="/api/v1/shelf-images/42/content"),
    )

    class DeletedActorSession:
        def get(self, model, user_id):
            assert user_id == 17
            return None

    with pytest.raises(HTTPException) as error:
        _request_user(DeletedActorSession(), request)

    assert error.value.status_code == 401
    assert error.value.detail == "Authenticated user is no longer active"


def test_request_user_rechecks_role_after_middleware_authentication(monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.config import settings
    from app.main import _request_user

    monkeypatch.setattr(settings, "app_env", "production")
    employee = SimpleNamespace(id=17, is_active=True, role="EMPLOYEE")
    request = SimpleNamespace(
        state=SimpleNamespace(user_id=17, user_role="SUPERVISOR"),
        method="POST",
        url=SimpleNamespace(path="/api/v1/shelf-image-detections/99/reviews"),
    )

    class DemotedActorSession:
        def get(self, model, user_id):
            assert user_id == 17
            return employee

    with pytest.raises(HTTPException) as error:
        _request_user(DemotedActorSession(), request)

    assert error.value.status_code == 403
    assert error.value.detail == "Supervisor role required"


def test_store_scope_allows_admin_to_access_any_store():
    from types import SimpleNamespace
    from app.main import _enforce_store_scope

    admin = SimpleNamespace(role="ADMIN", store_id=None)
    _enforce_store_scope(admin, 987)


def test_store_scope_rejects_supervisor_access_to_another_store():
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.main import _enforce_store_scope

    supervisor = SimpleNamespace(role="SUPERVISOR", store_id=12)
    with pytest.raises(HTTPException) as error:
        _enforce_store_scope(supervisor, 13)
    assert error.value.status_code == 403


def test_store_scope_allows_supervisor_access_to_own_store():
    from types import SimpleNamespace
    from app.main import _enforce_store_scope

    supervisor = SimpleNamespace(role="SUPERVISOR", store_id=12)
    _enforce_store_scope(supervisor, 12)


def test_store_scope_rejects_employee_access_to_another_store():
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.main import _enforce_store_scope

    employee = SimpleNamespace(role="EMPLOYEE", store_id=12)
    with pytest.raises(HTTPException) as error:
        _enforce_store_scope(employee, 13)
    assert error.value.status_code == 403


def test_store_scope_rejects_non_admin_without_store_assignment():
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.main import _enforce_store_scope

    supervisor = SimpleNamespace(role="SUPERVISOR", store_id=None)
    with pytest.raises(HTTPException) as error:
        _enforce_store_scope(supervisor, 13)
    assert error.value.status_code == 403


def test_store_scope_allows_employee_access_to_own_store():
    from types import SimpleNamespace
    from app.main import _enforce_store_scope

    employee = SimpleNamespace(role="EMPLOYEE", store_id=12)
    _enforce_store_scope(employee, 12)


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "17", "iat": 1},
        {"sub": "17", "exp": 2_000_000_000},
        {"iat": 1, "exp": 2_000_000_000},
    ],
)
def test_access_token_requires_subject_issue_time_and_expiration(claims):
    from app.config import settings

    token = jwt.encode(claims, settings.jwt_secret_key, algorithm="HS256")
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_access_token(token)


def test_api_role_policy_is_centralized_and_fail_closed():
    from app.api_security_policy import api_role_denial, classify_api_route

    assert classify_api_route("POST", "/api/v1/stores") == "ADMIN_ONLY"
    assert api_role_denial("POST", "/api/v1/stores", "ADMIN") is None
    assert api_role_denial("POST", "/api/v1/stores", "SUPERVISOR") == "Administrator role required"
    assert classify_api_route("GET", "/api/v1/observation-alerts") == "SUPERVISOR_OR_ADMIN"
    assert api_role_denial("GET", "/api/v1/observation-alerts", "EMPLOYEE") == "Supervisor role required"
    assert api_role_denial("GET", "/api/v1/observation-alerts", "SUPERVISOR") is None
    assert classify_api_route("GET", "/api/v1/tasks") == "EMPLOYEE_ALLOWLIST"
    assert api_role_denial("GET", "/api/v1/tasks", "EMPLOYEE") is None
    assert api_role_denial("POST", "/api/v1/tasks", "EMPLOYEE") == "Supervisor role required"
    assert classify_api_route("GET", "/api/v1/products") == "AUTHENTICATED_STAFF"
    assert api_role_denial("GET", "/api/v1/products", "EMPLOYEE") == "Employee access is limited to assigned tasks"
    assert api_role_denial("GET", "/api/v1/products", "UNKNOWN") == "User role is not authorized"


def test_api_role_policy_requires_path_segment_boundaries():
    from app.api_security_policy import api_role_denial, classify_api_route

    lookalike_admin_path = "/api/v1/auth/users-export"
    lookalike_supervisor_path = "/api/v1/observation-alerts-legacy"

    assert classify_api_route("GET", lookalike_admin_path) == "AUTHENTICATED_STAFF"
    assert api_role_denial("GET", lookalike_admin_path, "EMPLOYEE") == (
        "Employee access is limited to assigned tasks"
    )
    assert classify_api_route("GET", lookalike_supervisor_path) == "AUTHENTICATED_STAFF"
    assert api_role_denial("GET", lookalike_supervisor_path, "EMPLOYEE") == (
        "Employee access is limited to assigned tasks"
    )


def test_api_role_policy_preserves_real_nested_route_prefixes():
    from app.api_security_policy import api_role_denial, classify_api_route

    assert classify_api_route("GET", "/api/v1/observation-alerts/42") == "SUPERVISOR_OR_ADMIN"
    assert api_role_denial("GET", "/api/v1/observation-alerts/42", "SUPERVISOR") is None
    assert classify_api_route("GET", "/api/v1/shelf-images/42/content") == "EMPLOYEE_ALLOWLIST"
    assert api_role_denial("GET", "/api/v1/shelf-images/42/content", "EMPLOYEE") is None

def test_api_role_policy_does_not_match_planogram_lookalike_segments():
    from app.api_security_policy import api_role_denial, classify_api_route

    lookalike_path = "/api/v1/shelves/42/planograms-export"

    assert classify_api_route("GET", lookalike_path) == "AUTHENTICATED_STAFF"
    assert api_role_denial("GET", lookalike_path, "EMPLOYEE") == (
        "Employee access is limited to assigned tasks"
    )

def test_api_role_policy_matches_real_planogram_routes_by_segment():
    from app.api_security_policy import api_role_denial, classify_api_route

    route = "/api/v1/shelves/42/planograms"

    assert classify_api_route("POST", route) == "SUPERVISOR_OR_ADMIN"
    assert api_role_denial("POST", route, "SUPERVISOR") is None
    assert api_role_denial("POST", route, "ADMIN") is None
    assert api_role_denial("POST", route, "EMPLOYEE") == "Supervisor role required"

def test_every_registered_versioned_api_route_has_an_explicit_method_policy():
    from fastapi.routing import APIRoute

    from app.api_security_policy import classify_api_route
    from app.main import app

    unclassified = [
        f"{method} {route.path}"
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/")
        for method in sorted(route.methods or ())
        if classify_api_route(method, route.path) == "UNCLASSIFIED"
    ]

    assert not unclassified, "Unclassified API route methods: " + ", ".join(unclassified)


def test_route_policy_matches_dynamic_templates_and_does_not_inherit_methods():
    from app.api_security_policy import api_role_denial, classify_api_route, is_public_api_route

    assert classify_api_route("GET", "/api/v1/shelf-images/42/artifacts") == "ADMIN_ONLY"
    assert api_role_denial("GET", "/api/v1/shelf-images/42/artifacts", "SUPERVISOR") == (
        "Administrator role required"
    )
    assert classify_api_route("GET", "/api/v1/shelf-images/42/retention/events") == (
        "SUPERVISOR_OR_ADMIN"
    )
    assert api_role_denial("GET", "/api/v1/shelf-images/42/retention/events", "EMPLOYEE") == (
        "Supervisor role required"
    )
    assert is_public_api_route("POST", "/api/v1/auth/login")
    assert not is_public_api_route("GET", "/api/v1/auth/login")
    assert classify_api_route("GET", "/api/v1/auth/login") == "UNCLASSIFIED"
