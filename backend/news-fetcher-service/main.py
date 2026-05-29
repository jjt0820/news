from __future__ import annotations

import json
import os
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import FastAPI, Request

from fetcher import DEFAULT_NEWS_LIMIT, fetch_latest_news_all_categories
from s3_snapshot import RssSnapshotStats, upload_rss_snapshot
from json_logging import (
    SCHEDULER_TIMEZONE,
    register_scheduler_logging,
    reset_trace_id,
    resolve_request_trace_id,
    set_trace_id,
    setup_service_logging,
    uvicorn_log_config,
)

_SERVICE_DIR = Path(__file__).resolve().parent
load_dotenv(_SERVICE_DIR / ".env")
load_dotenv()

logger = setup_service_logging("news-fetcher")
scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
register_scheduler_logging(scheduler, logger, service_name="news-fetcher")


DEFAULT_SUMMARIZER_URL = "http://localhost:8004/summarize"
DEFAULT_NEWS_STORE_BASE_URL = "http://localhost:8004"
NEWS_STORE_HTTP_TIMEOUT = 60.0
DEFAULT_HTTP_TIMEOUT_SECONDS = 600.0
DEFAULT_HTTP_RETRIES_ON_QUOTA = 3
FETCH_CRON_HOUR_KST = 6
FETCH_CRON_MINUTE_KST = 0


def _news_store_base_url() -> str:
    return (os.getenv("NEWS_STORE_BASE_URL") or DEFAULT_NEWS_STORE_BASE_URL).rstrip("/")


def _http_get_existing_links(client: httpx.Client, links: List[str]) -> set[str]:
    clean = [str(link).strip() for link in links if str(link).strip()]
    if not clean:
        return set()
    params = [("links", lk) for lk in clean]
    timeout = _env_float("NEWS_STORE_HTTP_TIMEOUT_SECONDS", NEWS_STORE_HTTP_TIMEOUT)
    url = f"{_news_store_base_url()}/news"
    try:
        response = client.get(url, params=params, timeout=timeout)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        logger.error(
            "news_store_existing_links_timeout",
            extra={"event": "news_store_existing_links_timeout", "url": url, "error": str(exc)},
        )
        raise
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code is not None and status_code >= 500:
            logger.error(
                "news_store_existing_links_5xx",
                extra={
                    "event": "news_store_existing_links_5xx",
                    "url": url,
                    "http_status": status_code,
                    "error": str(exc),
                },
            )
        raise
    data = response.json()
    return set(data.get("existing_links", []))


def _http_post_news(client: httpx.Client, body: Dict[str, Any]) -> bool:
    timeout = _env_float("NEWS_STORE_HTTP_TIMEOUT_SECONDS", NEWS_STORE_HTTP_TIMEOUT)
    url = f"{_news_store_base_url()}/news"
    try:
        response = client.post(url, json=body, timeout=timeout)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        logger.error(
            "news_store_save_timeout",
            extra={"event": "news_store_save_timeout", "url": url, "error": str(exc)},
        )
        raise
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code is not None and status_code >= 500:
            logger.error(
                "news_store_save_5xx",
                extra={
                    "event": "news_store_save_5xx",
                    "url": url,
                    "http_status": status_code,
                    "error": str(exc),
                },
            )
        raise
    payload = response.json()
    return bool(payload.get("inserted"))


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or not str(raw).strip():
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _summarizer_http_should_retry(status_code: int) -> bool:
    return status_code in (429, 502)


def _format_kst_datetime(value: datetime) -> str:
    return value.astimezone(SCHEDULER_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def _build_batch_metadata(*, scheduled_run_time: datetime | None = None) -> Dict[str, str]:
    scheduled_local = (scheduled_run_time or datetime.now(SCHEDULER_TIMEZONE)).astimezone(
        SCHEDULER_TIMEZONE
    )
    collected_local = datetime.now(SCHEDULER_TIMEZONE)
    return {
        "batch_date_kst": scheduled_local.date().isoformat(),
        "scheduled_run_time_kst": _format_kst_datetime(scheduled_local),
        "collected_at_kst": _format_kst_datetime(collected_local),
    }


def _post_summarize_with_retries(
    client: httpx.Client,
    url: str,
    payload: Dict[str, Any],
    *,
    category: str,
    item_count: int,
    max_extra_tries: int,
) -> Dict[str, Any]:
    """
    첫 시도 + 429/502 시 최대 max_extra_tries번 재시도(총 1+max_extra_tries회까지).
    retrying_count: 재시도 차수(0=첫 요청 직후 성공 또는 첫 시도 전, 1=첫 실패 후 첫 재시도 전 …).
    """
    total_attempts = 1 + max(0, max_extra_tries)
    last_error: BaseException | None = None

    for attempt in range(1, total_attempts + 1):
        retrying_count = attempt - 1
        try:
            logger.info(
                "summarizer_http_request",
                extra={
                    "event": "summarizer_http_request",
                    "category": category,
                    "attempt": attempt,
                    "retrying_count": retrying_count,
                    "max_attempts": total_attempts,
                    "item_count": item_count,
                    "url": url,
                },
            )
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()
            logger.info(
                "summarizer_http_success",
                extra={
                    "event": "summarizer_http_success",
                    "category": category,
                    "attempt": attempt,
                    "retrying_count": retrying_count,
                    "item_count": item_count,
                    "http_status": resp.status_code,
                },
            )
            return body
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else 0
            body_snip = (exc.response.text[:2000] if exc.response is not None else "") or ""
            log = logger.error if status >= 500 else logger.warning
            log(
                "summarizer_http_error",
                extra={
                    "event": "summarizer_http_error",
                    "category": category,
                    "attempt": attempt,
                    "retrying_count": retrying_count,
                    "http_status": status,
                    "will_retry": bool(
                        _summarizer_http_should_retry(status) and attempt < total_attempts
                    ),
                    "response_body_preview": body_snip[:500] if body_snip else None,
                },
            )
            if not _summarizer_http_should_retry(status) or attempt >= total_attempts:
                raise
            backoff = (2 ** (attempt - 1)) + random.uniform(0.0, 0.35)
            logger.info(
                "summarizer_http_backoff",
                extra={
                    "event": "summarizer_http_backoff",
                    "category": category,
                    "attempt": attempt,
                    "retrying_count": retrying_count + 1,
                    "sleep_seconds": round(backoff, 3),
                    "reason_http_status": status,
                },
            )
            time.sleep(backoff)
        except httpx.TimeoutException as exc:
            last_error = exc
            logger.error(
                "summarizer_http_timeout",
                extra={
                    "event": "summarizer_http_timeout",
                    "category": category,
                    "attempt": attempt,
                    "retrying_count": retrying_count,
                    "error": str(exc),
                },
            )
            raise
        except httpx.RequestError as exc:
            last_error = exc
            logger.error(
                "summarizer_http_transport_error",
                extra={
                    "event": "summarizer_http_transport_error",
                    "category": category,
                    "attempt": attempt,
                    "retrying_count": retrying_count,
                    "error": str(exc),
                },
            )
            raise

    if last_error:
        raise last_error
    raise RuntimeError("summarizer HTTP: unexpected empty retry loop")


def run_pipeline(
    *,
    per_category_limit: int | None = None,
    summarizer_url: str | None = None,
    http_timeout_seconds: float | None = None,
    summarizer_http_max_extra_tries: int | None = None,
    batch_metadata: Dict[str, str] | None = None,
) -> Dict[str, int]:
    """
    1) 카테고리별 뉴스 수집
    2) news-summarizer HTTP GET /news 로 이미 저장된 링크 선필터링
    3) 신규 뉴스를 summarizer HTTP API로 요약 요청(429/502 시 재시도)
    4) 요약 결과를 news-summarizer POST /news 로 저장
    """
    effective_limit = (
        per_category_limit
        if per_category_limit is not None
        else _env_int("NEWS_PER_CATEGORY_LIMIT", DEFAULT_NEWS_LIMIT)
    )
    timeout = (
        http_timeout_seconds
        if http_timeout_seconds is not None
        else _env_float("SUMMARIZER_HTTP_TIMEOUT_SECONDS", DEFAULT_HTTP_TIMEOUT_SECONDS)
    )
    max_extra = (
        summarizer_http_max_extra_tries
        if summarizer_http_max_extra_tries is not None
        else _env_int("SUMMARIZER_HTTP_MAX_EXTRA_TRIES", DEFAULT_HTTP_RETRIES_ON_QUOTA)
    )

    url = (summarizer_url or os.environ.get("SUMMARIZER_URL") or DEFAULT_SUMMARIZER_URL).rstrip("/")
    if not url.endswith("/summarize"):
        url = f"{url.rstrip('/')}/summarize"

    logger.info(
        "pipeline_run_start",
        extra={
            "event": "pipeline_run_start",
            "summarizer_url": url,
            "news_store_base_url": _news_store_base_url(),
            "news_per_category_limit": effective_limit,
            "summarizer_http_max_extra_tries": max_extra,
            "http_timeout_seconds": timeout,
            "batch_date_kst": (batch_metadata or {}).get("batch_date_kst"),
            "scheduled_run_time_kst": (batch_metadata or {}).get("scheduled_run_time_kst"),
        },
    )

    fetched_by_category = fetch_latest_news_all_categories(limit=effective_limit)

    stats: Dict[str, int] = {
        "fetched_total": 0,
        "already_saved": 0,
        "to_summarize": 0,
        "summarized": 0,
        "saved": 0,
        "save_ignored": 0,
        "failed": 0,
    }
    rss_snapshot_stats = RssSnapshotStats()
    batch_meta = batch_metadata or {}

    with httpx.Client(timeout=timeout) as client:
        for category, items in fetched_by_category.items():
            logger.info(
                "category_batch_start",
                extra={"event": "category_batch_start", "category": category},
            )
            if not items:
                logger.info(
                    "category_no_items",
                    extra={"event": "category_no_items", "category": category},
                )
                continue

            stats["fetched_total"] += len(items)
            links = [item["link"] for item in items if item.get("link")]
            existing_links = _http_get_existing_links(client, links)
            fresh_items: List[Dict[str, str]] = [
                item for item in items if item.get("link") and item["link"] not in existing_links
            ]

            already_count = len(items) - len(fresh_items)
            stats["already_saved"] += already_count
            stats["to_summarize"] += len(fresh_items)
            logger.info(
                "category_fetch_stats",
                extra={
                    "event": "category_fetch_stats",
                    "category": category,
                    "fetched": len(items),
                    "already_saved": already_count,
                    "to_summarize": len(fresh_items),
                },
            )

            if not fresh_items:
                continue

            try:
                for it in fresh_items:
                    s3_key = upload_rss_snapshot(
                        it,
                        batch_metadata=batch_meta,
                        stats=rss_snapshot_stats,
                    )
                    it["s3_key"] = s3_key

                payload: Dict[str, Any] = {
                    "items": [
                        {
                            "title": it["title"],
                            "link": it["link"],
                            "category": it.get("category", category),
                            "rss_description": it.get("rss_description") or "",
                        }
                        for it in fresh_items
                    ]
                }
                body = _post_summarize_with_retries(
                    client,
                    url,
                    payload,
                    category=category,
                    item_count=len(fresh_items),
                    max_extra_tries=max_extra,
                )
                summaries = body.get("summaries")
                if not isinstance(summaries, list):
                    raise RuntimeError("summarizer 응답에 'summaries' 배열이 없습니다.")
                if len(summaries) != len(fresh_items):
                    raise RuntimeError(
                        f"요약 개수 불일치: 요청 {len(fresh_items)}건, 응답 {len(summaries)}건"
                    )

                for news, summary_text in zip(fresh_items, summaries):
                    if not isinstance(summary_text, str):
                        raise RuntimeError("요약 항목이 문자열이 아닙니다.")
                    inserted = _http_post_news(
                        client,
                        {
                            "category": news["category"],
                            "title": news["title"],
                            "summary": summary_text,
                            "link": news["link"],
                            "s3_key": news.get("s3_key"),
                            "batch_date_kst": batch_meta.get("batch_date_kst"),
                            "scheduled_run_time_kst": batch_meta.get("scheduled_run_time_kst"),
                            "collected_at_kst": batch_meta.get("collected_at_kst"),
                        },
                    )
                    stats["summarized"] += 1
                    if inserted:
                        stats["saved"] += 1
                        logger.info(
                            "news_saved",
                            extra={
                                "event": "news_saved",
                                "category": news["category"],
                                "title": news["title"],
                                "link": news["link"],
                            },
                        )
                    else:
                        stats["save_ignored"] += 1
                        logger.info(
                            "news_save_skipped_duplicate",
                            extra={
                                "event": "news_save_skipped_duplicate",
                                "category": news["category"],
                                "title": news["title"],
                                "link": news["link"],
                            },
                        )
            except httpx.HTTPStatusError as exc:
                stats["failed"] += 1
                body = (exc.response.text[:2000] if exc.response is not None else "") or ""
                logger.error(
                    "category_pipeline_http_failed",
                    extra={
                        "event": "category_pipeline_http_failed",
                        "category": category,
                        "error": str(exc),
                        "response_body_preview": body.strip()[:1500] if body.strip() else None,
                    },
                )
            except Exception as exc:
                stats["failed"] += 1
                logger.exception(
                    "category_pipeline_failed",
                    extra={"event": "category_pipeline_failed", "category": category, "error": str(exc)},
                )

    logger.info(
        f"rss_snapshot_batch_done uploaded={rss_snapshot_stats.uploaded} "
        f"failed={rss_snapshot_stats.failed} skipped={rss_snapshot_stats.skipped}",
        extra={
            "event": "rss_snapshot_batch_done",
            "uploaded": rss_snapshot_stats.uploaded,
            "failed": rss_snapshot_stats.failed,
            "skipped": rss_snapshot_stats.skipped,
        },
    )

    return stats


def run_pipeline_once(*, scheduled_run_time: datetime | None = None) -> Dict[str, int]:
    resolved = (os.environ.get("SUMMARIZER_URL") or DEFAULT_SUMMARIZER_URL).rstrip("/")
    if not resolved.endswith("/summarize"):
        resolved = f"{resolved}/summarize"
    batch_metadata = _build_batch_metadata(scheduled_run_time=scheduled_run_time)

    logger.info(
        "pipeline_start",
        extra={
            "event": "pipeline_start",
            "summarizer_url": resolved,
            "batch_date_kst": batch_metadata["batch_date_kst"],
            "scheduled_run_time_kst": batch_metadata["scheduled_run_time_kst"],
        },
    )
    summary = run_pipeline(batch_metadata=batch_metadata)
    logger.info(
        "pipeline_summary",
        extra={
            "event": "pipeline_summary",
            "stats": summary,
            "stats_json": json.dumps(summary, ensure_ascii=False),
            "batch_date_kst": batch_metadata["batch_date_kst"],
            "scheduled_run_time_kst": batch_metadata["scheduled_run_time_kst"],
        },
    )
    return summary


def _scheduled_pipeline_job() -> Dict[str, int]:
    scheduled_slot = datetime.now(SCHEDULER_TIMEZONE).replace(
        hour=FETCH_CRON_HOUR_KST,
        minute=FETCH_CRON_MINUTE_KST,
        second=0,
        microsecond=0,
    )
    return run_pipeline_once(scheduled_run_time=scheduled_slot)


def _format_next_run_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(SCHEDULER_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def _configure_scheduler_jobs() -> None:
    job = scheduler.add_job(
        _scheduled_pipeline_job,
        trigger=CronTrigger(
            hour=FETCH_CRON_HOUR_KST,
            minute=FETCH_CRON_MINUTE_KST,
            timezone=SCHEDULER_TIMEZONE,
        ),
        id="news-fetcher-pipeline",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60 * 60,
    )
    logger.info(
        "scheduler_configured",
        extra={
            "event": "scheduler_configured",
            "service": "news-fetcher",
            "timezone": str(SCHEDULER_TIMEZONE),
            "scheduler_timezone": str(SCHEDULER_TIMEZONE),
            "fetch_cron_hour_kst": FETCH_CRON_HOUR_KST,
            "fetch_cron_minute_kst": FETCH_CRON_MINUTE_KST,
            "next_run_time": _format_next_run_time(getattr(job, "next_run_time", None)),
        },
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler_enabled = _env_bool("ENABLE_SCHEDULER", True)
    if scheduler_enabled:
        _configure_scheduler_jobs()
        if not scheduler.running:
            scheduler.start()
        logger.info(
            "service_startup",
            extra={
                "event": "service_startup",
                "scheduler_enabled": True,
                "scheduler_timezone": str(SCHEDULER_TIMEZONE),
                "fetch_cron_hour_kst": FETCH_CRON_HOUR_KST,
                "fetch_cron_minute_kst": FETCH_CRON_MINUTE_KST,
            },
        )
    else:
        logger.info(
            "service_startup",
            extra={
                "event": "service_startup",
                "scheduler_enabled": False,
            },
        )
    try:
        yield
    finally:
        if scheduler.running:
            logger.info(
                "scheduler_shutdown_start",
                extra={
                    "event": "scheduler_shutdown_start",
                    "service": "news-fetcher",
                    "wait_for_running_jobs": True,
                },
            )
            scheduler.shutdown(wait=True)
            logger.info(
                "scheduler_stopped",
                extra={"event": "scheduler_stopped", "service": "news-fetcher"},
            )


app = FastAPI(title="News Fetcher Service", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    trace_id = resolve_request_trace_id(request.headers.get("x-trace-id"))
    token = set_trace_id(trace_id)
    try:
        response = await call_next(request)
        response.headers["x-trace-id"] = trace_id
        return response
    finally:
        reset_trace_id(token)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    if not _env_bool("ENABLE_SCHEDULER", True):
        run_pipeline_once()

    host = os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0"
    raw_port = os.getenv("PORT", "8003")
    try:
        port = int(raw_port) if str(raw_port).strip() else 8003
    except ValueError:
        port = 8003

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_config=uvicorn_log_config(),
    )
