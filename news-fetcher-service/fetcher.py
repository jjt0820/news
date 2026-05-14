from __future__ import annotations

import json
from typing import Dict, List

import feedparser


RSS_FEEDS: Dict[str, str] = {
    "IT/테크": "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    "경제": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "국제": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "스포츠": "https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml",
    "연예": "https://rss.nytimes.com/services/xml/rss/nyt/Movies.xml",
    "정치": "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
}

DEFAULT_NEWS_LIMIT = 3


def get_rss_url(category: str) -> str:
    """카테고리에 해당하는 RSS URL을 반환한다."""
    if category not in RSS_FEEDS:
        available = ", ".join(RSS_FEEDS.keys())
        raise ValueError(f"지원하지 않는 카테고리입니다: {category} (지원: {available})")
    return RSS_FEEDS[category]


def fetch_latest_news(category: str, *, limit: int = DEFAULT_NEWS_LIMIT) -> List[Dict[str, str]]:
    """
    지정한 카테고리의 최신 뉴스 최대 limit건(제목/링크)을 리스트로 가져온다.
    피드에 글이 없으면 빈 리스트를 반환한다.
    """
    if limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다.")

    rss_url = get_rss_url(category)
    feed = feedparser.parse(rss_url)
    entries = getattr(feed, "entries", None) or []

    items: List[Dict[str, str]] = []
    for entry in entries:
        if len(items) >= limit:
            break
        title = str(entry.get("title", "")).strip()
        link = str(entry.get("link", "")).strip()
        if not title or not link:
            continue
        items.append(
            {
                "category": category,
                "title": title,
                "link": link,
            }
        )
    return items


def fetch_latest_news_all_categories(
    *, limit: int = DEFAULT_NEWS_LIMIT
) -> Dict[str, List[Dict[str, str]]]:
    """모든 카테고리의 최신 뉴스를 각각 최대 limit건씩 가져온다."""
    return {category: fetch_latest_news(category, limit=limit) for category in RSS_FEEDS}


if __name__ == "__main__":
    from main import logger, run_pipeline

    logger.info("fetcher_cli_start", extra={"event": "fetcher_cli_start"})
    summary = run_pipeline()
    logger.info(
        "pipeline_summary",
        extra={"event": "pipeline_summary", "stats": summary, "stats_json": json.dumps(summary, ensure_ascii=False)},
    )
