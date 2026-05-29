"""CI smoke tests for mail-service (no cross-service DB imports).

Service ports (문서·환경 기준): User 8000, Mail 8002, Summarizer 8004.
구독자 목록은 user-service HTTP API만 사용하므로 httpx를 모킹합니다.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

import main as mail_main  # noqa: E402 — conftest.py applied migrations first

app = mail_main.app


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_health_returns_200_json_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_health_via_httpx_asgi_transport() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        response = await http_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_load_active_subscribers_calls_user_service_http() -> None:
    """user-service DB를 직접 읽지 않고 GET /internal/subscribers만 호출하는지 검증."""
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"email": "subscriber@example.com", "interest_categories": ["IT/테크", "경제"]},
    ]
    mock_response.raise_for_status = MagicMock()

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response
    mock_session.__enter__.return_value = mock_session
    mock_session.__exit__.return_value = None

    with patch.object(mail_main.httpx, "Client", return_value=mock_session):
        subscribers = mail_main._load_active_subscribers()

    mock_session.get.assert_called_once()
    called_url = mock_session.get.call_args[0][0]
    assert "localhost:8000" in called_url
    assert called_url.rstrip("/").endswith("/internal/subscribers")

    assert subscribers == [
        {"email": "subscriber@example.com", "interest_categories": ["IT/테크", "경제"]},
    ]
