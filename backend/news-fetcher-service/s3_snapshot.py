"""RSS JSON snapshot upload to S3 (owned by news-fetcher-service)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from fetcher import CATEGORY_SLUGS, get_rss_url

logger = logging.getLogger("news-fetcher")

_BUCKET_NOT_CONFIGURED_LOGGED = False


@dataclass
class RssSnapshotStats:
    uploaded: int = 0
    failed: int = 0
    skipped: int = 0


def build_s3_key(
    *,
    link: str,
    category: str,
    batch_date_kst: str,
    s3_prefix: str = "",
) -> str:
    slug = CATEGORY_SLUGS.get(category, "unknown")
    link_hash = hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]
    prefix = (s3_prefix or "").strip().strip("/")
    parts = [p for p in (prefix, "rss_snapshots", batch_date_kst, slug, f"{link_hash}.json") if p]
    return "/".join(parts)


def build_snapshot_payload(
    item: Dict[str, str],
    *,
    batch_date_kst: str,
    collected_at_kst: str,
) -> Dict[str, Any]:
    category = item.get("category", "")
    return {
        "metadata": {
            "content_source": "rss",
            "trace_id": f"batch-{batch_date_kst}",
            "provider": "nytimes-rss",
            "feed_url": get_rss_url(category) if category in CATEGORY_SLUGS else "",
            "category": category,
            "collected_at_kst": collected_at_kst,
        },
        "article": {
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "pub_date_utc": item.get("pub_date_utc") or "",
            "author": item.get("author") or "",
            "rss_description": item.get("rss_description") or "",
        },
    }


def _s3_bucket_configured() -> bool:
    return bool(os.getenv("S3_BUCKET", "").strip())


def upload_rss_snapshot(
    item: Dict[str, str],
    *,
    batch_metadata: Dict[str, str],
    stats: RssSnapshotStats,
) -> Optional[str]:
    """
    Upload RSS snapshot JSON to S3.

    Returns s3_key on success, None on skip/failure (pipeline continues).
    """
    global _BUCKET_NOT_CONFIGURED_LOGGED

    batch_date_kst = batch_metadata.get("batch_date_kst") or ""
    collected_at_kst = batch_metadata.get("collected_at_kst") or ""

    if not _s3_bucket_configured():
        if not _BUCKET_NOT_CONFIGURED_LOGGED:
            logger.info(
                "S3 bucket not configured, skipping snapshot upload",
                extra={"event": "rss_snapshot_s3_skipped_no_bucket"},
            )
            _BUCKET_NOT_CONFIGURED_LOGGED = True
        stats.skipped += 1
        return None

    link = str(item.get("link", "")).strip()
    category = str(item.get("category", "")).strip()
    if not link or not category or not batch_date_kst:
        stats.skipped += 1
        return None

    s3_prefix = os.getenv("S3_PREFIX", "").strip()
    s3_key = build_s3_key(
        link=link,
        category=category,
        batch_date_kst=batch_date_kst,
        s3_prefix=s3_prefix,
    )
    payload = build_snapshot_payload(
        item,
        batch_date_kst=batch_date_kst,
        collected_at_kst=collected_at_kst,
    )
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    bucket = os.getenv("S3_BUCKET", "").strip()
    region = os.getenv("AWS_REGION", "ap-northeast-2").strip() or "ap-northeast-2"

    try:
        import boto3

        client = boto3.client("s3", region_name=region)
        client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=body,
            ContentType="application/json; charset=utf-8",
        )
        stats.uploaded += 1
        return s3_key
    except Exception as exc:
        stats.failed += 1
        logger.error(
            f"rss_snapshot_s3_upload_failed link={link[:120]} category={category}",
            extra={
                "event": "rss_snapshot_s3_upload_failed",
                "link": link[:300],
                "category": category,
                "s3_key": s3_key,
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        return None


def reset_bucket_not_configured_flag() -> None:
    """Reset one-shot no-bucket log flag (for tests)."""
    global _BUCKET_NOT_CONFIGURED_LOGGED
    _BUCKET_NOT_CONFIGURED_LOGGED = False
