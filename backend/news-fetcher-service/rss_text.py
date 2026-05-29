"""RSS description extraction and HTML cleanup."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self._parts.append(text)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def strip_html_tags(raw: str) -> str:
    """Remove HTML tags from RSS description text."""
    text = (raw or "").strip()
    if not text:
        return ""
    if "<" not in text:
        return text
    parser = _HTMLTextExtractor()
    parser.feed(text)
    parser.close()
    return parser.get_text()


def extract_rss_description(entry: Any) -> str:
    """Try summary then description fields from a feedparser entry."""
    for key in ("summary", "description"):
        raw = entry.get(key)
        if raw is None:
            continue
        cleaned = strip_html_tags(str(raw))
        if cleaned:
            return cleaned
    return ""


def extract_pub_date_utc(entry: Any) -> str:
    published = entry.get("published") or entry.get("updated") or ""
    return str(published).strip()


def extract_author(entry: Any) -> str:
    author = entry.get("author") or ""
    if author:
        return str(author).strip()
    authors = entry.get("authors") or []
    if authors and isinstance(authors, list):
        first = authors[0]
        if isinstance(first, dict):
            return str(first.get("name") or first.get("email") or "").strip()
        return str(first).strip()
    return ""
