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
