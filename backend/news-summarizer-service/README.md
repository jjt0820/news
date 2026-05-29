# news-summarizer-service

## Install dependencies

```bash
cd backend/news-summarizer-service
pip install -r requirements.txt
```

(Or use repo CI bundle: `backend/requirements.txt`)

## Local DB migration

Run commands from **backend/news-summarizer-service**:

```bash
cd backend/news-summarizer-service
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8004
```

## Troubleshooting

- If you see `no such table` or DB errors on startup, run `alembic upgrade head` in this directory first.
- If you have an **old** `news.db` from before Alembic (e.g. only `create_all` / runtime ALTER), **delete it** and run `alembic upgrade head` again so the schema matches the current migration.
- Default DB file when `DATABASE_URL` is unset: `news.db` (see `database.py` / `NEWS_DB_PATH`).

## Tests

```bash
cd backend/news-summarizer-service
pytest tests/ -v
```

Tests use a temporary SQLite DB and run `alembic upgrade head` automatically via `tests/conftest.py`.

## S3 snapshot key (stored in DB)

The fetcher may store an RSS snapshot object key in `summarized_news.s3_key` when uploading to S3.  
`GET /news` does **not** expose `s3_key` (mail service unchanged).

### Related AWS env (fetcher-side)

See `backend/news-fetcher-service/README.md` for `AWS_REGION`, `S3_BUCKET`, `S3_PREFIX`.

Infrastructure: Terraform apply path `terraform/database/S3`; fetcher IAM needs **PutObject**; lifecycle expire after 30 days recommended.
