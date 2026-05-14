from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine, get_db
from json_logging import (
    SCHEDULER_TIMEZONE,
    register_scheduler_logging,
    setup_service_logging,
    uvicorn_log_config,
)
from models import Subscription
from schemas import SubscribeCreate, SubscribeResponse

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
    Base.metadata.create_all(bind=engine)
    interval_minutes = _configure_scheduler_jobs()
    if not scheduler.running:
        scheduler.start()
    logger.info(
        "User service started and DB initialized",
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


@app.get("/health")
def health_check():
    logger.info(
        "Health check requested",
        extra={"event": "health_check_requested"},
    )
    return {"status": "ok"}


def _serialize_categories(categories: list[str]) -> str:
    cleaned = [c.strip() for c in categories if c and c.strip()]
    return ",".join(cleaned)


def _deserialize_categories(category_csv: str) -> list[str]:
    if not category_csv:
        return []
    return [c.strip() for c in category_csv.split(",") if c.strip()]


def _format_categories_for_popup(categories: list[str]) -> str:
    return ", ".join(categories)


async def send_verification_email(email: str, token: str) -> None:
    logger.info(
        "Verification email dispatch started",
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
            "Verification email HTTP error",
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
            "Verification email transport error",
            extra={
                "event": "verification_email_send_failure",
                "user_email": email,
                "reason": str(exc),
            },
        )
        raise

    logger.info(
        "Verification email sent successfully",
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
        "Subscribe request received",
        extra={"event": "subscribe_request_received", "user_email": payload.email},
    )
    existing = db.query(Subscription).filter(Subscription.email == payload.email).first()
    if existing:
        logger.warning(
            "Duplicate subscription attempt",
            extra={"event": "subscribe_duplicate_email", "user_email": payload.email},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 구독된 이메일입니다.",
        )

    verification_token = secrets.token_urlsafe(32)
    logger.info(
        "Verification token generated",
        extra={
            "event": "verification_token_generated",
            "user_email": payload.email,
            "token_char_length": len(verification_token),
        },
    )

    category_csv = _serialize_categories(payload.category)
    if not category_csv:
        logger.warning(
            "Empty category in subscribe request",
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
    except Exception:
        db.rollback()
        logger.exception(
            "Failed to persist subscription",
            extra={"event": "subscription_persist_failed", "user_email": payload.email},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="구독 저장에 실패했습니다.",
        ) from None

    background_tasks.add_task(send_verification_email, payload.email, verification_token)
    logger.info(
        "Subscription created and verification email queued",
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
        "Verify request received",
        extra={"event": "verify_request_received", "user_email": email},
    )
    subscriber = db.query(Subscription).filter(Subscription.email == email).first()
    if not subscriber:
        logger.warning(
            "Verify failed - subscriber not found",
            extra={"event": "verify_subscriber_not_found", "user_email": email},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="구독자를 찾을 수 없습니다.",
        )

    if subscriber.verification_token != token:
        logger.warning(
            "Verify failed - invalid token",
            extra={"event": "verify_invalid_token", "user_email": email},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효하지 않은 인증 토큰입니다.",
        )

    if not subscriber.is_verified:
        subscriber.is_verified = True
        db.commit()
        logger.info(
            "Subscriber verified successfully",
            extra={"event": "verify_success", "user_email": email},
        )
    else:
        logger.info(
            "Verify requested for already-verified subscriber",
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
