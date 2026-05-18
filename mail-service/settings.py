from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from json_logging import setup_service_logging

logger = setup_service_logging("mail-service")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    SMTP_HOST: str
    SMTP_PORT: int = 587
    SMTP_USER: str
    SMTP_PASS: str
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False

    MAIL_FROM: str
    MAIL_FROM_NAME: str = "Project1"

    # 메일 본문에 넣을 인증 링크(선택)
    VERIFY_BASE_URL: str = "http://localhost:8000/verify"
    USER_SERVICE_URL: str = "http://localhost:8000"
    NEWS_DATA_SERVICE_URL: str = "http://localhost:8004"


try:
    settings = Settings()
except ValidationError as exc:
    missing = [
        ".".join(str(part) for part in error.get("loc", ()))
        for error in exc.errors()
        if error.get("type") == "missing"
    ]
    logger.critical(
        "required_environment_missing",
        extra={
            "event": "required_environment_missing",
            "missing_env_vars": missing,
            "error": str(exc),
        },
    )
    raise

