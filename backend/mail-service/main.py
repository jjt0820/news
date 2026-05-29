from __future__ import annotations

import os
from contextlib import asynccontextmanager
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from json_logging import (
    SCHEDULER_TIMEZONE,
    register_scheduler_logging,
    reset_trace_id,
    resolve_request_trace_id,
    set_trace_id,
    setup_service_logging,
    uvicorn_log_config,
)
from models import MailSendLog
from schemas import NewsCardItem, NewsSummaryEmailRequest, VerifyEmailRequest
from settings import settings

FETCH_BATCH_HOUR_KST = 6
NEWSLETTER_CRON_HOUR_KST = 7
NEWSLETTER_CRON_MINUTE_KST = 0

logger = setup_service_logging("mail-service")
scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
register_scheduler_logging(scheduler, logger, service_name="mail-service")

TEMPLATE_DIR = Path(__file__).parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)


def _format_kst_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(SCHEDULER_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def _newsletter_batch_token(batch_date: date) -> str:
    return f"NEWSLETTER:{batch_date.isoformat()}"


def _newsletter_subject(batch_date: date) -> str:
    return f"{batch_date.isoformat()} 오늘의 큐레이션 뉴스"


def _render_template(template_name: str, context: dict[str, Any]) -> str:
    template = jinja_env.get_template(template_name)
    return template.render(**context)


def _load_active_subscribers() -> list[dict[str, Any]]:
    base = settings.USER_SERVICE_URL.rstrip("/")
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{base}/internal/subscribers")
            response.raise_for_status()
            body = response.json()
    except httpx.TimeoutException as exc:
        logger.error(
            "user_service_subscribers_timeout",
            extra={"event": "user_service_subscribers_timeout", "url": f"{base}/internal/subscribers", "error": str(exc)},
        )
        raise
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code is not None and status_code >= 500:
            logger.error(
                "user_service_subscribers_5xx",
                extra={
                    "event": "user_service_subscribers_5xx",
                    "url": f"{base}/internal/subscribers",
                    "http_status": status_code,
                    "error": str(exc),
                },
            )
        raise
    if not isinstance(body, list):
        raise RuntimeError("user-service /internal/subscribers 응답이 배열이 아닙니다.")
    result: list[dict[str, Any]] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        email = str(item.get("email", "")).strip()
        if not email:
            continue
        raw_cats = item.get("interest_categories")
        if isinstance(raw_cats, list):
            categories = [str(c).strip() for c in raw_cats if str(c).strip()]
        else:
            categories = []
        result.append({"email": email, "interest_categories": categories})
    return result


def _row_display_time(row: Mapping[str, Any]) -> str:
    scheduled_run_time_kst = str(row["scheduled_run_time_kst"] or "").strip()
    if scheduled_run_time_kst:
        return f"{scheduled_run_time_kst} KST"
    return f"{FETCH_BATCH_HOUR_KST:02d}:00 KST"


def _load_news_cards_by_category(batch_date: date) -> dict[str, list[NewsCardItem]]:
    base = settings.NEWS_DATA_SERVICE_URL.rstrip("/")
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.get(
                f"{base}/news",
                params={"batch_date": batch_date.isoformat()},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as exc:
        logger.error(
            "news_data_service_timeout",
            extra={"event": "news_data_service_timeout", "url": f"{base}/news", "error": str(exc)},
        )
        raise
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code is not None and status_code >= 500:
            logger.error(
                "news_data_service_5xx",
                extra={
                    "event": "news_data_service_5xx",
                    "url": f"{base}/news",
                    "http_status": status_code,
                    "error": str(exc),
                },
            )
        raise
    rows = payload.get("items") or []
    if not isinstance(rows, list):
        raise RuntimeError("뉴스 API 응답에 'items' 배열이 없습니다.")

    news_by_category: dict[str, list[NewsCardItem]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        category = str(raw.get("category", ""))
        news_by_category.setdefault(category, []).append(
            NewsCardItem(
                source=category,
                time=_row_display_time(raw),
                title=str(raw.get("title", "")),
                summary=str(raw.get("summary", "")),
            )
        )
    return news_by_category


def _build_personalized_payload(
    *,
    email: str,
    categories: list[str],
    news_by_category: dict[str, list[NewsCardItem]],
    batch_date: date,
) -> NewsSummaryEmailRequest | None:
    selected_cards: list[NewsCardItem] = []
    for category in categories:
        selected_cards.extend(news_by_category.get(category, []))

    if not selected_cards:
        return None

    return NewsSummaryEmailRequest(
        email=email,
        categories=categories,
        title="좋은 아침이에요,\n관심 카테고리 뉴스가 도착했어요",
        subtitle=f"{batch_date.isoformat()} 맞춤 뉴스",
        news_cards=selected_cards,
    )


def _persist_mail_send_log(
    db: Session,
    *,
    to_email: str,
    token: str,
    subject: str,
    status_value: str,
    error: str | None,
) -> None:
    try:
        db.add(
            MailSendLog(
                to_email=to_email,
                token=token,
                subject=subject,
                status=status_value,
                error=error,
            )
        )
        db.commit()
    except OperationalError as exc:
        db.rollback()
        logger.critical(
            "database_connection_failed",
            extra={
                "event": "database_connection_failed",
                "operation": "mail_log_persist",
                "user_email": to_email,
                "token": token,
                "status": status_value,
                "error": str(exc),
            },
        )
        raise
    except Exception:
        db.rollback()
        logger.exception(
            "mail_log_persist_failed",
            extra={
                "event": "mail_log_persist_failed",
                "user_email": to_email,
                "token": token,
                "status": status_value,
            },
        )
        raise


conf = ConnectionConfig(
    MAIL_USERNAME=settings.SMTP_USER,
    MAIL_PASSWORD=settings.SMTP_PASS,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_FROM_NAME=settings.MAIL_FROM_NAME,
    MAIL_PORT=settings.SMTP_PORT,
    MAIL_SERVER=settings.SMTP_HOST,
    MAIL_STARTTLS=settings.SMTP_TLS,
    MAIL_SSL_TLS=settings.SMTP_SSL,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
)


async def _send_html_email(
    *,
    recipient: str,
    subject: str,
    body: str,
    token: str,
    db: Session,
    success_event: str,
    failure_event: str,
    extra: dict[str, Any],
) -> None:
    message = MessageSchema(
        subject=subject,
        recipients=[recipient],
        body=body,
        subtype=MessageType.html,
    )

    logger.info(
        "메일 발송을 시도합니다",
        extra={
            "event": "mail_send_attempt",
            "user_email": recipient,
            "subject": subject,
            "token": token,
            **extra,
        },
    )

    try:
        await FastMail(conf).send_message(message)
        _persist_mail_send_log(
            db,
            to_email=recipient,
            token=token,
            subject=subject,
            status_value="sent",
            error=None,
        )
    except Exception as exc:
        _persist_mail_send_log(
            db,
            to_email=recipient,
            token=token,
            subject=subject,
            status_value="failed",
            error=str(exc),
        )
        logger.error(
            failure_event,
            extra={
                "event": failure_event,
                "user_email": recipient,
                "subject": subject,
                "token": token,
                "error": str(exc),
                **extra,
            },
        )
        raise

    logger.info(
        success_event,
        extra={
            "event": success_event,
            "user_email": recipient,
            "subject": subject,
            "token": token,
            **extra,
        },
    )


async def _send_news_summary_email_payload(
    *,
    payload: NewsSummaryEmailRequest,
    db: Session,
    batch_token: str,
    batch_date_kst: str | None,
) -> dict[str, Any]:
    subject = _newsletter_subject(
        date.fromisoformat(batch_date_kst) if batch_date_kst else datetime.now(SCHEDULER_TIMEZONE).date()
    )
    body = _render_template(
        "news_summary.html",
        {
            "subtitle": payload.subtitle,
            "title": payload.title,
            "categories": payload.categories,
            "news_cards": [item.model_dump() for item in payload.news_cards],
        },
    )
    await _send_html_email(
        recipient=payload.email,
        subject=subject,
        body=body,
        token=batch_token,
        db=db,
        success_event="newsletter_email_send_success",
        failure_event="newsletter_email_send_failure",
        extra={
            "batch_date_kst": batch_date_kst,
            "category_count": len(payload.categories),
            "news_cards_count": len(payload.news_cards),
        },
    )
    return {
        "ok": True,
        "email": payload.email,
        "news_cards_count": len(payload.news_cards),
    }


async def _send_daily_newsletters_job() -> dict[str, int]:
    batch_date = datetime.now(SCHEDULER_TIMEZONE).date()
    subscribers = _load_active_subscribers()
    news_by_category = _load_news_cards_by_category(batch_date)
    stats = {
        "subscriber_total": len(subscribers),
        "matched_subscriber_total": 0,
        "sent": 0,
        "skipped_no_categories": 0,
        "skipped_no_news": 0,
        "failed": 0,
    }

    logger.info(
        "newsletter_batch_start",
        extra={
            "event": "newsletter_batch_start",
            "batch_date_kst": batch_date.isoformat(),
            "subscriber_total": len(subscribers),
            "available_categories": sorted(news_by_category.keys()),
        },
    )

    with SessionLocal() as db:
        for subscriber in subscribers:
            email = str(subscriber["email"])
            categories = list(subscriber["interest_categories"])

            if not categories:
                stats["skipped_no_categories"] += 1
                logger.info(
                    "newsletter_batch_skip_no_categories",
                    extra={
                        "event": "newsletter_batch_skip_no_categories",
                        "user_email": email,
                        "batch_date_kst": batch_date.isoformat(),
                    },
                )
                continue

            payload = _build_personalized_payload(
                email=email,
                categories=categories,
                news_by_category=news_by_category,
                batch_date=batch_date,
            )
            if payload is None:
                stats["skipped_no_news"] += 1
                logger.info(
                    "newsletter_batch_skip_no_news",
                    extra={
                        "event": "newsletter_batch_skip_no_news",
                        "user_email": email,
                        "batch_date_kst": batch_date.isoformat(),
                        "interest_categories": categories,
                    },
                )
                continue

            stats["matched_subscriber_total"] += 1
            try:
                await _send_news_summary_email_payload(
                    payload=payload,
                    db=db,
                    batch_token=_newsletter_batch_token(batch_date),
                    batch_date_kst=batch_date.isoformat(),
                )
                stats["sent"] += 1
            except Exception:
                stats["failed"] += 1
                logger.exception(
                    "newsletter_batch_user_failed",
                    extra={
                        "event": "newsletter_batch_user_failed",
                        "user_email": email,
                        "batch_date_kst": batch_date.isoformat(),
                        "interest_categories": categories,
                    },
                )

    logger.info(
        "newsletter_batch_summary",
        extra={
            "event": "newsletter_batch_summary",
            "batch_date_kst": batch_date.isoformat(),
            "stats": stats,
        },
    )
    return stats


def _configure_scheduler_jobs():
    return scheduler.add_job(
        _send_daily_newsletters_job,
        trigger=CronTrigger(
            hour=NEWSLETTER_CRON_HOUR_KST,
            minute=NEWSLETTER_CRON_MINUTE_KST,
            timezone=SCHEDULER_TIMEZONE,
        ),
        id="mail-service-newsletter-batch",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60 * 60,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    job = _configure_scheduler_jobs()
    if not scheduler.running:
        scheduler.start()
    logger.info(
        "service_startup",
        extra={
            "event": "service_startup",
            "timezone": str(SCHEDULER_TIMEZONE),
            "scheduler_timezone": str(SCHEDULER_TIMEZONE),
            "newsletter_cron_hour_kst": NEWSLETTER_CRON_HOUR_KST,
            "newsletter_cron_minute_kst": NEWSLETTER_CRON_MINUTE_KST,
            "next_run_time": _format_kst_datetime(getattr(job, "next_run_time", None)),
        },
    )
    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


app = FastAPI(title="Mail Service", version="0.1.0", lifespan=lifespan)


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


@app.post("/send-verify-email", status_code=status.HTTP_202_ACCEPTED)
async def send_verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    subject = "이메일 인증을 완료해주세요"
    verify_url = f"{settings.VERIFY_BASE_URL}?email={payload.email}&token={payload.token}"
    body = _render_template(
        "verify_email.html",
        {
            "email": payload.email,
            "verify_url": verify_url,
            "service_name": settings.MAIL_FROM_NAME,
        },
    )

    try:
        await _send_html_email(
            recipient=payload.email,
            subject=subject,
            body=body,
            token=payload.token,
            db=db,
            success_event="verification_email_send_success",
            failure_event="verification_email_send_failure",
            extra={},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="메일 발송에 실패했습니다.",
        ) from exc

    return {"ok": True}


@app.post("/send-news-summary-email", status_code=status.HTTP_202_ACCEPTED)
async def send_news_summary_email(
    payload: NewsSummaryEmailRequest, db: Session = Depends(get_db)
):
    try:
        return await _send_news_summary_email_payload(
            payload=payload,
            db=db,
            batch_token=_newsletter_batch_token(datetime.now(SCHEDULER_TIMEZONE).date()),
            batch_date_kst=datetime.now(SCHEDULER_TIMEZONE).date().isoformat(),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="뉴스레터 메일 발송에 실패했습니다.",
        ) from exc


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0"
    raw_port = os.getenv("PORT", "8002")
    try:
        port = int(raw_port) if str(raw_port).strip() else 8002
    except ValueError:
        port = 8002

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_config=uvicorn_log_config(),
    )

