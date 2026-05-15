"""CI smoke tests for news-summarizer-service.

Ports: User 8000, Mail 8002, Summarizer 8004.
뉴스 DB는 본 서비스의 SQLAlchemy만 사용 — 타 서비스 database 모듈을 import하지 않습니다.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVICE_DIR = _REPO_ROOT / "news-summarizer-service"

os.environ.setdefault("GEMINI_API_KEY", "ci-placeholder-not-used-for-summarize-endpoint")

_news_db_dir = tempfile.mkdtemp(prefix="summarizer-ci-")
_news_db_path = Path(_news_db_dir) / "news_test.sqlite"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_news_db_path.as_posix()}")

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
