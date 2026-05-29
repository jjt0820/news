"""Frontend/API slug ↔ stored Korean category labels."""

from __future__ import annotations

from constants import ALLOWED_CATEGORIES

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


def normalize_category_slugs(raw: list[str]) -> list[str]:
    cleaned = [c.strip() for c in raw if c and c.strip()]
    if not cleaned:
        raise ValueError("category는 최소 1개 이상의 값이 필요합니다.")

    labels: list[str] = []
    invalid: list[str] = []
    for item in cleaned:
        label = resolve_category_slug(item)
        if label is None:
            invalid.append(item)
            continue
        if label not in labels:
            labels.append(label)

    if invalid:
        allowed = ", ".join(sorted(SLUG_TO_LABEL.keys()))
        raise ValueError(
            f"허용되지 않은 카테고리입니다: {', '.join(invalid)}. 허용 slug: {allowed}"
        )
    if not labels:
        raise ValueError("category는 최소 1개 이상의 값이 필요합니다.")
    return labels
