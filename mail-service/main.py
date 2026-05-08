from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import MailSendLog
from schemas import NewsSummaryEmailRequest, VerifyEmailRequest
from settings import settings

app = FastAPI(title="Mail Service", version="0.1.0")
TEMPLATE_DIR = Path(__file__).parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


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


def render_template(template_name: str, context: dict) -> str:
    template = jinja_env.get_template(template_name)
    return template.render(**context)


@app.post("/send-verify-email", status_code=status.HTTP_202_ACCEPTED)
async def send_verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    subject = "이메일 인증을 완료해주세요"
    verify_url = f"{settings.VERIFY_BASE_URL}?email={payload.email}&token={payload.token}"
    body = render_template(
        "verify_email.html",
        {
            "email": payload.email,
            "verify_url": verify_url,
            "service_name": settings.MAIL_FROM_NAME,
        },
    )

    message = MessageSchema(
        subject=subject,
        recipients=[payload.email],
        body=body,
        subtype=MessageType.html,
    )

    fm = FastMail(conf)
    try:
        await fm.send_message(message)
        db.add(
            MailSendLog(
                to_email=payload.email,
                token=payload.token,
                subject=subject,
                status="sent",
                error=None,
            )
        )
        db.commit()
    except Exception as e:
        db.add(
            MailSendLog(
                to_email=payload.email,
                token=payload.token,
                subject=subject,
                status="failed",
                error=str(e),
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="메일 발송에 실패했습니다.",
        ) from None

    return {"ok": True}


@app.post("/send-news-summary-email", status_code=status.HTTP_202_ACCEPTED)
async def send_news_summary_email(
    payload: NewsSummaryEmailRequest, db: Session = Depends(get_db)
):
    subject = "오늘의 큐레이션 뉴스"
    body = render_template(
        "news_summary.html",
        {
            "subtitle": payload.subtitle,
            "title": payload.title,
            "categories": payload.categories,
            "news_cards": [item.model_dump() for item in payload.news_cards],
        },
    )

    message = MessageSchema(
        subject=subject,
        recipients=[payload.email],
        body=body,
        subtype=MessageType.html,
    )

    fm = FastMail(conf)
    try:
        await fm.send_message(message)
        db.add(
            MailSendLog(
                to_email=payload.email,
                token="NEWSLETTER",
                subject=subject,
                status="sent",
                error=None,
            )
        )
        db.commit()
    except Exception as e:
        db.add(
            MailSendLog(
                to_email=payload.email,
                token="NEWSLETTER",
                subject=subject,
                status="failed",
                error=str(e),
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="뉴스레터 메일 발송에 실패했습니다.",
        ) from None

    return {
        "ok": True,
        "email": payload.email,
        "news_cards_count": len(payload.news_cards),
    }

