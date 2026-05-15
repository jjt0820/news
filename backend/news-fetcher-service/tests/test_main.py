"""CI smoke tests for news-fetcher-service.

Ports: User 8000, Mail 8002, Fetcher 8003, Summarizer 8004.
뉴스 저장·요약은 HTTP로 summarizer(8004)에만 의존 — 다른 서비스의 database.py를 import하지 않습니다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVICE_DIR = _REPO_ROOT / "news-fetcher-service"

os.environ.setdefault("SUMMARIZER_URL", "http://localhost:8004/summarize")
os.environ.setdefault("NEWS_STORE_BASE_URL", "http://localhost:8004")

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
