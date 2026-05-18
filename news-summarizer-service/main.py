from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError

from database import (
    Base,
    engine,
    ensure_news_schema,
    get_existing_links,
    list_newsletter_rows_for_batch,
    save_news,
)
from json_logging import (
    SCHEDULER_TIMEZONE,
    register_scheduler_logging,
    reset_trace_id,
    set_trace_id,
    setup_service_logging,
    uvicorn_log_config,
)

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path, encoding="utf-8-sig")
load_dotenv(encoding="utf-8-sig")

logger = setup_service_logging("news-summarizer")
scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
register_scheduler_logging(scheduler, logger, service_name="news-summarizer")

DEFAULT_SCHEDULER_HEARTBEAT_MINUTES = 60

from summarizer import summarize_news_list

def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _scheduler_readiness_job() -> Dict[str, Any]:
    api_key = (
        (os.getenv("GEMINI_API_KEY") or "")
        .strip()
        .strip("\ufeff")
        .strip()
        .strip('"')
        .strip("'")
    )
    if not api_key:
        logger.critical(
            "required_environment_missing",
            extra={"event": "required_environment_missing", "env_var": "GEMINI_API_KEY"},
        )
        raise RuntimeError("GEMINI_API_KEY가 설정되어 있지 않습니다.")

    return {
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
        "api_key_configured": True,
    }


def _configure_scheduler_jobs() -> int:
    interval_minutes = max(
        1,
        _env_int("SCHEDULER_HEARTBEAT_MINUTES", DEFAULT_SCHEDULER_HEARTBEAT_MINUTES),
    )
    scheduler.add_job(
        _scheduler_readiness_job,
        trigger="interval",
        minutes=interval_minutes,
        id="news-summarizer-readiness-check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=max(60, interval_minutes * 60),
        next_run_time=datetime.now(SCHEDULER_TIMEZONE),
    )
    return interval_minutes


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        Base.metadata.create_all(bind=engine)
        ensure_news_schema()
    except OperationalError as exc:
        logger.critical(
            "database_connection_failed",
            extra={"event": "database_connection_failed", "error": str(exc)},
        )
        raise
    interval_minutes = _configure_scheduler_jobs()
    if not scheduler.running:
        scheduler.start()
    logger.info(
        "service_startup",
        extra={
            "event": "service_startup",
            "scheduler_timezone": str(SCHEDULER_TIMEZONE),
            "scheduler_heartbeat_minutes": interval_minutes,
        },
    )
    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


app = FastAPI(title="News Summarizer Service", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or request.headers.get("traceparent")
    token = set_trace_id(trace_id)
    try:
        response = await call_next(request)
        if trace_id:
            response.headers["x-trace-id"] = trace_id
        return response
    finally:
        reset_trace_id(token)


class NewsItem(BaseModel):
    title: str
    link: str
    category: str = ""


class SummarizeRequest(BaseModel):
    items: List[NewsItem] = Field(..., min_length=1)
    model: Optional[str] = None
    delay_seconds: Optional[float] = None
    max_retries: Optional[int] = None
    timeout_seconds: Optional[int] = None


class SummarizeResponse(BaseModel):
    summaries: List[str]


@app.get("/health")
def health() -> Dict[str, str]:
    logger.info("health_check", extra={"event": "health_check"})
    return {"status": "ok"}


class NewsCreateBody(BaseModel):
    category: str
    title: str
    summary: str
    link: str
    batch_date_kst: Optional[str] = None
    scheduled_run_time_kst: Optional[str] = None
    collected_at_kst: Optional[str] = None


class NewsCreateResponse(BaseModel):
    inserted: bool


@app.post("/news", response_model=NewsCreateResponse)
def create_news_record(body: NewsCreateBody) -> NewsCreateResponse:
    try:
        inserted = save_news(body.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return NewsCreateResponse(inserted=inserted)


@app.get("/news")
def read_news(
    batch_date: Optional[date] = None,
    links: Annotated[Optional[list[str]], Query()] = None,
) -> Dict[str, Any]:
    if batch_date is not None:
        rows = list_newsletter_rows_for_batch(batch_date)
        return {"items": rows}
    if links:
        existing = get_existing_links(links)
        return {"existing_links": sorted(existing)}
    raise HTTPException(
        status_code=400,
        detail="batch_date 또는 links 쿼리 파라미터가 필요합니다.",
    )


@app.post("/summarize", response_model=SummarizeResponse)
def summarize(req: SummarizeRequest) -> SummarizeResponse:
    news_list: List[Dict[str, Any]] = [
        {"title": it.title, "link": it.link, "category": it.category} for it in req.items
    ]
    kwargs: Dict[str, Any] = {}
    if req.model is not None:
        kwargs["model"] = req.model
    if req.delay_seconds is not None:
        kwargs["delay_seconds"] = req.delay_seconds
    if req.max_retries is not None:
        kwargs["max_retries"] = req.max_retries
    if req.timeout_seconds is not None:
        kwargs["timeout_seconds"] = req.timeout_seconds

    logger.info(
        "summarize_request",
        extra={
            "event": "summarize_request",
            "item_count": len(news_list),
            "kwargs": {k: v for k, v in kwargs.items()},
        },
    )

    try:
        summaries = summarize_news_list(news_list, **kwargs)
    except ValueError as exc:
        logger.warning(
            "summarize_validation_error",
            extra={"event": "summarize_validation_error", "error": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.error(
            "summarize_runtime_error",
            extra={"event": "summarize_runtime_error", "error": str(exc)},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "summarize_unexpected_error",
            extra={"event": "summarize_unexpected_error", "error": str(exc)},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info(
        "summarize_success",
        extra={"event": "summarize_success", "item_count": len(news_list), "summary_count": len(summaries)},
    )
    return SummarizeResponse(summaries=summaries)


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0"
    raw_port = os.getenv("PORT", "8004")
    try:
        port = int(raw_port) if str(raw_port).strip() else 8004
    except ValueError:
        port = 8004

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_config=uvicorn_log_config(),
    )
