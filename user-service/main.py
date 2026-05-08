import os
import secrets
import logging
from typing import List

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import Subscription
from schemas import SubscribeCreate, SubscribeResponse

MAIL_SERVICE_URL = os.environ.get("MAIL_SERVICE_URL", "http://localhost:8002").rstrip("/")
LOG_DIR = "logs"
LOG_PATH = os.path.join(LOG_DIR, "user_service.log")

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
logger = logging.getLogger("user-service")

app = FastAPI(title="User Service", version="0.1.0")


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    logger.info("User service started and DB initialized")


@app.get("/health")
def health_check():
    logger.info("Health check requested")
    return {"status": "ok"}

def _serialize_categories(categories: List[str]) -> str:
    cleaned = [c.strip() for c in categories if c and c.strip()]
    return ",".join(cleaned)


def _deserialize_categories(category_csv: str) -> List[str]:
    if not category_csv:
        return []
    return [c.strip() for c in category_csv.split(",") if c.strip()]


def _format_categories_for_popup(categories: List[str]) -> str:
    return ", ".join(categories)


async def send_verification_email(email: str, token: str) -> None:
    logger.info("Sending verification email requested: email=%s", email)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{MAIL_SERVICE_URL}/send-verify-email",
            json={"email": email, "token": token},
        )
        response.raise_for_status()
    logger.info("Verification email request completed: email=%s", email)


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
    logger.info("Subscribe request received: email=%s", payload.email)
    existing = db.query(Subscription).filter(Subscription.email == payload.email).first()
    if existing:
        logger.warning("Duplicate subscription attempt: email=%s", payload.email)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 구독된 이메일입니다.",
        )

    verification_token = secrets.token_urlsafe(32)
    category_csv = _serialize_categories(payload.category)
    if not category_csv:
        logger.warning("Empty category in subscribe request: email=%s", payload.email)
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
        logger.exception("Failed to persist subscription: email=%s", payload.email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="구독 저장에 실패했습니다.",
        ) from None

    background_tasks.add_task(send_verification_email, payload.email, verification_token)
    logger.info("Subscription created and verification queued: email=%s", payload.email)

    return SubscribeResponse(
        message="구독 완료!",
        email=row.email,
        category=_format_categories_for_popup(_deserialize_categories(row.category)),
    )


@app.get("/verify")
def verify_subscription(email: str, token: str, db: Session = Depends(get_db)):
    logger.info("Verify request received: email=%s", email)
    subscriber = db.query(Subscription).filter(Subscription.email == email).first()
    if not subscriber:
        logger.warning("Verify failed - subscriber not found: email=%s", email)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="구독자를 찾을 수 없습니다.",
        )

    if subscriber.verification_token != token:
        logger.warning("Verify failed - invalid token: email=%s", email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효하지 않은 인증 토큰입니다.",
        )

    if not subscriber.is_verified:
        subscriber.is_verified = True
        db.commit()
        logger.info("Subscriber verified: email=%s", email)
    else:
        logger.info("Verify requested for already-verified subscriber: email=%s", email)

    return {"message": "인증이 완료되었습니다"}
