"""Frontend/API slug ↔ stored Korean category labels."""

from __future__ import annotations

ALLOWED_CATEGORIES = ["IT/테크", "경제", "국제", "스포츠", "연예", "정치"]

SLUG_TO_LABEL: dict[str, str] = {
    "tech": "IT/테크",
    "it-tech": "IT/테크",
    "economy": "경제",
    "world": "국제",
    "sports": "스포츠",
    "entertainment": "연예",
    "politics": "정치",
}


def resolve_category_slug(slug: str) -> str | None:
    raw = (slug or "").strip()
    if not raw:
        return None
    label = SLUG_TO_LABEL.get(raw.lower())
    if label:
        return label
    if raw in ALLOWED_CATEGORIES:
        return raw
    return None
