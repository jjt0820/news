from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class MailSendLog(Base):
    __tablename__ = "mail_send_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    to_email: Mapped[s= mapped_column(String(128), index=True)
    subject: Mapped[str] = mapped_column(String(255), index=True)
    token: Mapped[str] tr] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), index=True)  # sent | failed
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

