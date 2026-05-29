"""Unit tests for S3 RSS snapshot helpers."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from s3_snapshot import (
    RssSnapshotStats,
    build_s3_key,
    reset_bucket_not_configured_flag,
    upload_rss_snapshot,
)


@pytest.fixture(autouse=True)
def _reset_s3_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_bucket_not_configured_flag()
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET_NAME", raising=False)


def test_build_s3_key_uses_category_slug_and_hash() -> None:
    key = build_s3_key(
        link="https://example.com/article/1",
        category="IT/테크",
        batch_date_kst="2026-05-21",
        s3_prefix="dev",
    )
    assert key.startswith("dev/rss_snapshots/2026-05-21/it-tech/")
    assert key.endswith(".json")
    assert len(key.split("/")[-1].replace(".json", "")) == 16


def test_upload_rss_snapshot_skipped_when_bucket_unset() -> None:
    stats = RssSnapshotStats()
    item = {
        "category": "IT/테크",
        "title": "Title",
        "link": "https://example.com/a",
        "rss_description": "Desc",
    }
    result = upload_rss_snapshot(
        item,
        batch_metadata={"batch_date_kst": "2026-05-21", "collected_at_kst": "2026-05-21 06:00:00"},
        stats=stats,
    )
    assert result is None
    assert stats.skipped == 1
    assert stats.uploaded == 0
    assert stats.failed == 0


def test_upload_rss_snapshot_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")
    stats = RssSnapshotStats()
    mock_client = MagicMock()

    with patch("boto3.client", return_value=mock_client):
        result = upload_rss_snapshot(
            {
                "category": "경제",
                "title": "Title",
                "link": "https://example.com/b",
                "rss_description": "Economy news",
            },
            batch_metadata={"batch_date_kst": "2026-05-21", "collected_at_kst": "2026-05-21 06:00:00"},
            stats=stats,
        )

    assert result is not None
    assert "rss_snapshots/2026-05-21/economy/" in result
    assert stats.uploaded == 1
    mock_client.put_object.assert_called_once()
    call_kwargs = mock_client.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "test-bucket"
    assert call_kwargs["Key"] == result


def test_upload_rss_snapshot_accepts_s3_bucket_name_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_BUCKET_NAME", "named-bucket")
    stats = RssSnapshotStats()
    mock_client = MagicMock()

    with patch("boto3.client", return_value=mock_client):
        result = upload_rss_snapshot(
            {
                "category": "경제",
                "title": "Title",
                "link": "https://example.com/c",
                "rss_description": "Economy news",
            },
            batch_metadata={"batch_date_kst": "2026-05-21", "collected_at_kst": "2026-05-21 06:00:00"},
            stats=stats,
        )

    assert result is not None
    assert mock_client.put_object.call_args.kwargs["Bucket"] == "named-bucket"
