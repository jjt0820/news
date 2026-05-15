"""CI smoke tests for user-service (no other service database imports).

Ports: User 8000, Mail 8002, Summarizer 8004 (문서 기준).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVICE_DIR = _REPO_ROOT / "user-service"

_user_db_dir = tempfile.mkdtemp(prefix="user-ci-")
_user_db_path = Path(_user_db_dir) / "user_test.sqlite"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_user_db_path.as_posix()}")

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


def test_internal_subscribers_returns_json_list(client: TestClient) -> None:
    """내부 API는 JSON 배열만 반환 (mail-service 연동 계약)."""
    response = client.get("/internal/subscribers")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
