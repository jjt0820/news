"""CI smoke tests for user-service (no other service database imports).

Ports: User 8000, Mail 8002, Summarizer 8004 (문서 기준).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app  # noqa: E402 — conftest.py에서 migrate 후 로드


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_health_returns_200_json_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_internal_subscribers_returns_json_list(client: TestClient) -> None:
    """내부 API는 JSON 배열만 반환 (mail-service 연동 계약)."""
    response = client.get("/internal/subscribers")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)


@patch("main.send_verification_email", new_callable=AsyncMock)
def test_subscribe_accepts_category_slug(
    _mock_send_mail: AsyncMock,
    client: TestClient,
) -> None:
    import uuid

    email = f"slug-{uuid.uuid4().hex}@example.com"
    response = client.post(
        "/subscribe",
        json={"email": email, "category": ["tech", "economy"]},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email
    assert "IT/테크" in body["category"]


@patch("main.httpx.AsyncClient")
def test_api_news_list_passes_through_summarizer_items(
    mock_async_client: MagicMock,
    client: TestClient,
) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "items": [
            {
                "source": "IT/테크",
                "time": "2026-05-29 09:00:00",
                "title": "Test headline",
                "desc": "Summary text",
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_async_client.return_value.__aenter__.return_value = mock_client

    response = client.get("/api/news/list", params={"category": "tech"})
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "source": "IT/테크",
                "time": "2026-05-29 09:00:00",
                "title": "Test headline",
                "desc": "Summary text",
            }
        ]
    }


def test_cors_allows_preflight_for_frontend_origin(client: TestClient) -> None:
    response = client.options(
        "/subscribe",
        headers={
            "Origin": "https://patrasche.cloud",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://patrasche.cloud"
