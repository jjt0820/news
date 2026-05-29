"""CI smoke tests for news-summarizer-service.

Ports: User 8000, Mail 8002, Summarizer 8004.
뉴스 DB는 본 서비스의 SQLAlchemy만 사용 — 타 서비스 database 모듈을 import하지 않습니다.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from database import SessionLocal, SummarizedNews
from main import app  # noqa: E402 — conftest.py applied migrations first


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_health_returns_200_json_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_post_news_persists_s3_key(client: TestClient) -> None:
    unique_link = f"https://example.com/news/{uuid.uuid4().hex}"
    s3_key = "dev/rss_snapshots/2026-05-21/it-tech/abc123def4567890.json"
    response = client.post(
        "/news",
        json={
            "category": "IT/테크",
            "title": "Test headline",
            "summary": "[오늘의 한 줄]: 테스트\n\n🔗 원문 보기: link",
            "link": unique_link,
            "s3_key": s3_key,
            "batch_date_kst": "2026-05-21",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"inserted": True}

    with SessionLocal() as session:
        row = session.scalar(select(SummarizedNews).where(SummarizedNews.link == unique_link))
        assert row is not None
        assert row.s3_key == s3_key
