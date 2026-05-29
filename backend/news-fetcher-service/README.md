# news-fetcher-service

## Install dependencies

```bash
cd backend/news-fetcher-service
pip install -r requirements.txt
```

(Or use repo CI bundle: `backend/requirements.txt`)

## Run locally

```bash
cd backend/news-fetcher-service
uvicorn main:app --host 0.0.0.0 --port 8003
```

## RSS → S3 snapshot (2.5)

Before calling summarizer `/summarize`, the fetcher pipeline uploads a JSON RSS snapshot to S3 (when configured).

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AWS_REGION` | When S3 enabled | e.g. `ap-northeast-2` |
| `S3_BUCKET` | Optional | If unset, snapshot upload is skipped (no-op) |
| `S3_PREFIX` | Optional | e.g. `dev` or `prod` — prepended to object keys |

Object key pattern:

`{S3_PREFIX}/rss_snapshots/{batch_date_kst}/{category_slug}/{sha256(link)[:16]}.json`

### Infrastructure (for CI/CD owner)

- Terraform apply path: `terraform/database/S3`
- **Phase 2.5:** grant the fetcher runtime IAM role **PutObject** on the RSS snapshot bucket only.
- **GetObject** is not required for this phase (summarizer receives `rss_description` over HTTP).
- Recommended **Lifecycle rule:** expire objects **30 days** after creation.

## Tests

```bash
cd backend/news-fetcher-service
pytest tests/ -v
```

Tests mock `boto3.client('s3')` — no real AWS credentials required.
