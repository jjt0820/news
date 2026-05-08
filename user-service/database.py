"""DB 연결. SQLite(`user_db`) 기본값 — MySQL 전환 시 `DATABASE_URL`만 바꾸면 됩니다."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# SQLite: 로컬 파일 ./user_db.sqlite
# MySQL 예: mysql+pymysql://user:pass@host:3306/dbname
SQLALCHEMY_DATABASE_URL = "sqlite:///./user_db.sqlite"

# SQLite는 단일 스레드 체크 완화(필요 시 조정)
connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith(
    "sqlite"
) else {}

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
