# mail-service

## Install dependencies

```bash
cd backend/mail-service
pip install -r requirements.txt
```

(Or use repo CI bundle: `backend/requirements.txt`)

## Local DB migration

Run commands from **backend/mail-service**:

```bash
cd backend/mail-service
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8002
```

## Troubleshooting

- If you see `no such table` or DB errors on startup, run `alembic upgrade head` in this directory first.
- Default DB file when `DATABASE_URL` is unset: `mail_db.sqlite`

## Tests

```bash
cd backend/mail-service
pytest tests/ -v
```

Tests use a temporary SQLite DB and run `alembic upgrade head` automatically via `tests/conftest.py`.
