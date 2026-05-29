# user-service

## 의존성 설치

```bash
cd backend/user-service
pip install -r requirements.txt
```

(또는 저장소 루트 CI용 `backend/requirements.txt` 사용)

## DB 마이그레이션 (로컬)

작업 디렉터리는 **반드시** `backend/user-service` 입니다.

```bash
cd backend/user-service
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 문제 해결

- 앱 기동 후 `no such table` / DB 오류가 나면: 위 디렉터리에서 `alembic upgrade head` 를 먼저 실행했는지 확인하세요.
- 기본 DB 파일: `user_db.sqlite` (`DATABASE_URL` 미설정 시)

## 테스트

```bash
cd backend/user-service
pytest tests/ -v
```

테스트는 임시 SQLite DB에 `alembic upgrade head` 를 자동 적용한 뒤 실행됩니다.
