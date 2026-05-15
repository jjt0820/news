"""Health route smoke test for CI (imports live service from repo root)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVICE_DIR = _REPO_ROOT / "mail-service"

for _key, _value in {
    "SMTP_HOST": "localhost",
    "SMTP_USER": "ci_user",
    "SMTP_PASS": "ci_pass",
    "MAIL_FROM": "ci@example.com",
}.items():
    os.environ.setdefault(_key, _value)

sys.path.insert(0, str(_SERVICE_DIR))

from main import app  # noqa: E402


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
