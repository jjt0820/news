from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Set

from dotenv import load_dotenv

_SERVICE_DIR = Path(__file__).resolve().parent
load_dotenv(_SERVICE_DIR / ".env")
load_dotenv()


def _db_path() -> Path:
    raw = os.getenv("NEWS_DB_PATH", "").strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_absolute():
            return p
        return Path(__file__).resolve().parent / p
    return Path(__file__).resolve().parent / "news.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS summarized_news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            link TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        )
        """
    )
    existing_columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(summarized_news)").fetchall()
    }
    optional_columns = {
        "batch_date_kst": "TEXT",
        "scheduled_run_time_kst": "TEXT",
        "collected_at_kst": "TEXT",
    }
    for column_name, column_type in optional_columns.items():
        if column_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE summarized_news ADD COLUMN {column_name} {column_type}"
            )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_summarized_news_batch_date_kst
        ON summarized_news (batch_date_kst, category)
        """
    )
    conn.commit()


def save_news(news_data: Dict[str, Any]) -> bool:
    """
    요약 뉴스 1건을 저장한다.
    link가 이미 있으면 INSERT OR IGNORE로 무시하고 False를 반환한다.
    새로 삽입되면 True를 반환한다.
    """
    required = ("category", "title", "summary", "link")
    for key in required:
        if key not in news_data:
            raise KeyError(f"news_data에 '{key}' 키가 필요합니다.")

    category = str(news_data["category"])
    title = str(news_data["title"])
    summary = str(news_data["summary"])
    link = str(news_data["link"])
    batch_date_kst = news_data.get("batch_date_kst")
    scheduled_run_time_kst = news_data.get("scheduled_run_time_kst")
    collected_at_kst = news_data.get("collected_at_kst")

    conn = _connect()
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO summarized_news (
                category,
                title,
                summary,
                link,
                batch_date_kst,
                scheduled_run_time_kst,
                collected_at_kst
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                category,
                title,
                summary,
                link,
                batch_date_kst,
                scheduled_run_time_kst,
                collected_at_kst,
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_recent_news(category: str, limit: int = 3) -> List[Dict[str, Any]]:
    """특정 카테고리의 최신 뉴스를 최대 limit건 반환한다 (created_at 내림차순)."""
    if limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다.")

    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT id, category, title, summary, link, created_at
            FROM summarized_news
            WHERE category = ?
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (category, limit),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_existing_links(links: List[str]) -> Set[str]:
    """입력 링크 목록 중 DB에 이미 저장된 링크 집합을 반환한다."""
    clean_links = [str(link).strip() for link in links if str(link).strip()]
    if not clean_links:
        return set()

    placeholders = ",".join("?" for _ in clean_links)
    conn = _connect()
    try:
        cur = conn.execute(
            f"""
            SELECT link
            FROM summarized_news
            WHERE link IN ({placeholders})
            """,
            clean_links,
        )
        return {str(row["link"]) for row in cur.fetchall()}
    finally:
        conn.close()


if __name__ == "__main__":
    from json_logging import setup_service_logging

    log = setup_service_logging("news-fetcher.database")

    sample = {
        "category": "IT/테크",
        "title": "Sample headline for DB test",
        "summary": "[오늘의 한 줄]: 테스트 요약\n[주요 내용]:\n- 항목1\n- 항목2\n- 항목3\n[알아두면 좋은 점]: 테스트",
        "link": "https://example.com/news/db-test-unique-link",
    }

    inserted = save_news(sample)
    log.info(
        "db_test_first_insert",
        extra={"event": "db_test_first_insert", "inserted": inserted},
    )

    duplicate_inserted = save_news(sample)
    log.info(
        "db_test_duplicate_insert",
        extra={"event": "db_test_duplicate_insert", "inserted": duplicate_inserted},
    )

    rows = get_recent_news("IT/테크", limit=3)
    log.info(
        "db_test_recent_news",
        extra={"event": "db_test_recent_news", "row_count": len(rows), "rows": [dict(row) for row in rows]},
    )
