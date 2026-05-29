from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from sqlalchemy import func
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
from models import Subscription
from schemas import InternalSubscriberOut, SubscribeCreate, SubscribeResponse

MAIL_SERVICE_URL = os.environ.get("MAIL_SERVICE_URL", "http://localhost:8002").rstrip("/")
DEFAULT_SCHEDULER_HEARTBEAT_MINUTES = 60

logger = setup_service_logging("user-service")
scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
register_scheduler_logging(scheduler, logger, service_name="user-service")

def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _subscription_snapshot_job() -> dict[str, int]:
    with SessionLocal() as db:
        total = int(db.query(func.count(Subscription.id)).scalar() or 0)
        verified = int(
            db.query(func.count(Subscription.id))
            .filter(Subscription.is_verified.is_(True))
            .scalar()
            or 0
        )
    return {
        "subscription_total": total,
        "verified_total": verified,
        "pending_verification_total": max(total - verified, 0),
    }


def _configure_scheduler_jobs() -> int:
    interval_minutes = max(
        1,
        _env_int("SCHEDULER_HEARTBEAT_MINUTES", DEFAULT_SCHEDULER_HEARTBEAT_MINUTES),
    )
    scheduler.add_job(
        _subscription_snapshot_job,
        trigger="interval",
        minutes=interval_minutes,
        id="user-service-subscription-snapshot",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=max(60, interval_minutes * 60),
        next_run_time=datetime.now(SCHEDULER_TIMEZONE),
    )
    return interval_minutes


@asynccontextmanager
async def lifespan(_app: FastAPI):
    interval_minutes = _configure_scheduler_jobs()
    if not scheduler.running:
        scheduler.start()
    logger.info(
        "유저 서비스가 시작되었습니다",
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


app = FastAPI(title="User Service", version="0.1.0", lifespan=lifespan)


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


def _serialize_categories(categories: list[str]) -> str:
    cleaned = [c.strip() for c in categories if c and c.strip()]
    return ",".join(cleaned)


def _deserialize_categories(category_csv: str) -> list[str]:
    if not category_csv:
        return []
    return [c.strip() for c in category_csv.split(",") if c.strip()]


@app.get("/health")
def health_check():
    logger.info(
        "헬스체크 정상",
        extra={"event": "health_check_requested"},
    )
    return {"status": "ok"}


@app.get("/internal/subscribers", response_model=list[InternalSubscriberOut])
def internal_subscribers(db: Session = Depends(get_db)):
    """인증 완료 구독자 목록 (mail-service 뉴스레터 등 내부 연동용)."""
    try:
        rows = (
            db.query(Subscription)
            .filter(Subscription.is_verified.is_(True))
            .order_by(Subscription.id.asc())
            .all()
        )
    except OperationalError as exc:
        logger.critical(
            "DB 조회에 실패했습니다",
            extra={
                "event": "database_connection_failed",
                "operation": "internal_subscribers",
                "error": str(exc),
                "error_type": "OperationalError",
            },
        )
        raise
    return [
        InternalSubscriberOut(
            email=r.email,
            interest_categories=_deserialize_categories(r.category or ""),
        )
        for r in rows
    ]


def _format_categories_for_popup(categories: list[str]) -> str:
    return ", ".join(categories)


async def send_verification_email(email: str, token: str) -> None:
    logger.info(
        "인증 메일 발송을 시작합니다",
        extra={"event": "verification_email_send_attempt", "user_email": email},
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{MAIL_SERVICE_URL}/send-verify-email",
                json={"email": email, "token": token},
            )
            response.raise_for_status()
            status_code = response.status_code
    except httpx.HTTPStatusError as exc:
        sc = exc.response.status_code if exc.response is not None else None
        logger.error(
            "인증 메일 발송 HTTP 오류",
            extra={
                "event": "verification_email_send_failure",
                "user_email": email,
                "http_status": sc,
                "reason": str(exc),
            },
        )
        raise
    except httpx.RequestError as exc:
        logger.error(
            "인증 메일 발송 네트워크 오류",
            extra={
                "event": "verification_email_send_failure",
                "user_email": email,
                "reason": str(exc),
            },
        )
        raise

    logger.info(
        "인증 메일 발송 성공",
        extra={
            "event": "verification_email_send_success",
            "user_email": email,
            "http_status": status_code,
        },
    )


@app.post(
    "/subscribe",
    response_model=SubscribeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def subscribe(
    payload: SubscribeCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    logger.info(
        "구독 요청을 받았습니다",
        extra={"event": "subscribe_request_received", "user_email": payload.email},
    )
    try:
        existing = db.query(Subscription).filter(Subscription.email == payload.email).first()
    except OperationalError as exc:
        logger.critical(
            "DB 조회에 실패했습니다",
            extra={
                "event": "database_connection_failed",
                "operation": "subscribe_lookup",
                "error": str(exc),
                "error_type": "OperationalError",
            },
        )
        raise
    if existing:
        logger.warning(
            "이미 구독된 이메일입니다",
            extra={"event": "subscribe_duplicate_email", "user_email": payload.email},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 구독된 이메일입니다.",
        )

    verification_token = secrets.token_urlsafe(32)
    logger.info(
        "인증 토큰이 생성되었습니다",
        extra={
            "event": "verification_token_generated",
            "user_email": payload.email,
            "token_char_length": len(verification_token),
        },
    )

    category_csv = _serialize_categories(payload.category)
    if not category_csv:
        logger.warning(
            "구독 카테고리가 비어 있습니다",
            extra={"event": "subscribe_empty_category", "user_email": payload.email},
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="category는 최소 1개 이상의 값이 필요합니다.",
        )
    row = Subscription(
        email=payload.email,
        category=category_csv,
        is_verified=False,
        verification_token=verification_token,
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
    except OperationalError as exc:
        db.rollback()
        logger.critical(
            "DB 저장에 실패했습니다",
            extra={
                "event": "database_connection_failed",
                "operation": "subscribe_commit",
                "error": str(exc),
                "error_type": "OperationalError",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DB 연결에 실패했습니다.",
        ) from exc
    except Exception:
        db.rollback()
        logger.exception(
            "구독 정보 저장에 실패했습니다",
            extra={"event": "subscription_persist_failed", "user_email": payload.email},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="구독 저장에 실패했습니다.",
        ) from None

    background_tasks.add_task(send_verification_email, payload.email, verification_token)
    logger.info(
        "구독이 완료되었고 인증 메일이 대기열에 등록되었습니다",
        extra={
            "event": "subscription_created_verification_queued",
            "user_email": payload.email,
            "category_count": len(_deserialize_categories(category_csv)),
        },
    )

    return SubscribeResponse(
        message="구독 완료!",
        email=row.email,
        category=_format_categories_for_popup(_deserialize_categories(row.category)),
    )


@app.get("/verify")
def verify_subscription(email: str, token: str, db: Session = Depends(get_db)):
    logger.info(
        "이메일 인증 요청을 받았습니다",
        extra={"event": "verify_request_received", "user_email": email},
    )
    try:
        subscriber = db.query(Subscription).filter(Subscription.email == email).first()
    except OperationalError as exc:
        logger.critical(
            "DB 조회에 실패했습니다",
            extra={
                "event": "database_connection_failed",
                "operation": "verify_lookup",
                "error": str(exc),
                "error_type": "OperationalError",
            },
        )
        raise
    if not subscriber:
        logger.warning(
            "구독자를 찾을 수 없습니다",
            extra={"event": "verify_subscriber_not_found", "user_email": email},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="구독자를 찾을 수 없습니다.",
        )

    if subscriber.verification_token != token:
        logger.warning(
            "유효하지 않은 인증 토큰입니다",
            extra={"event": "verify_invalid_token", "user_email": email},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효하지 않은 인증 토큰입니다.",
        )

    if not subscriber.is_verified:
        subscriber.is_verified = True
        try:
            db.commit()
        except OperationalError as exc:
            db.rollback()
            logger.critical(
                "DB 저장에 실패했습니다",
                extra={
                    "event": "database_connection_failed",
                    "operation": "verify_commit",
                    "error": str(exc),
                    "error_type": "OperationalError",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DB 연결에 실패했습니다.",
            ) from exc
        logger.info(
            "이메일 인증이 완료되었습니다",
            extra={"event": "verify_success", "user_email": email},
        )
    else:
        logger.info(
            "이미 인증된 구독자입니다",
            extra={"event": "verify_already_verified", "user_email": email},
        )

    return {"message": "인증이 완료되었습니다"}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0"
    raw_port = os.getenv("PORT", "8000")
    try:
        port = int(raw_port) if str(raw_port).strip() else 8000
    except ValueError:
        port = 8000

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_config=uvicorn_log_config(),
    )
