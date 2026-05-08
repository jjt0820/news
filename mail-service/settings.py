from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()

