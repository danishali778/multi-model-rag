from tests.helpers.app_factory import build_test_client
from app.core.config import settings


def test_unauthorized_error_includes_correlation_id_in_body_and_header():
    correlation_id = "corr-unauthorized-123"

    with build_test_client() as client:
        response = client.get(
            "/v1/documents",
            headers={"X-Correlation-ID": correlation_id},
        )

    assert response.status_code == 401
    assert response.headers["X-Correlation-ID"] == correlation_id
    assert response.json()["error"]["correlation_id"] == correlation_id
    assert response.json()["error"]["code"] == "unauthorized"


def test_validation_error_includes_correlation_id_in_body_and_header():
    correlation_id = "corr-validation-123"

    with build_test_client() as client:
        response = client.post(
            "/v1/auth/sign-in",
            headers={"X-Correlation-ID": correlation_id},
            json={"email": "not-an-email", "password": "password123"},
        )

    assert response.status_code == 422
    assert response.headers["X-Correlation-ID"] == correlation_id
    assert response.json()["error"]["correlation_id"] == correlation_id
    assert response.json()["error"]["code"] == "validation_error"


def test_request_size_limit_returns_bad_request_with_correlation_id():
    correlation_id = "corr-size-123"
    original_limit = settings.max_request_body_bytes
    settings.max_request_body_bytes = 32

    try:
        with build_test_client() as client:
            response = client.post(
                "/v1/auth/sign-in",
                headers={"X-Correlation-ID": correlation_id},
                json={"email": "dev@example.com", "password": "password123"},
            )
    finally:
        settings.max_request_body_bytes = original_limit

    assert response.status_code == 400
    assert response.headers["X-Correlation-ID"] == correlation_id
    body = response.json()
    assert body["error"]["correlation_id"] == correlation_id
    assert body["error"]["code"] == "bad_request"
    assert body["error"]["details"]["max_body_bytes"] == 32
