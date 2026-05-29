"""Tests for category slug normalization."""

from __future__ import annotations

import pytest

from category_slugs import normalize_category_slugs, resolve_category_slug


def test_resolve_category_slug_accepts_frontend_slug() -> None:
    assert resolve_category_slug("tech") == "IT/테크"


def test_resolve_category_slug_accepts_korean_label() -> None:
    assert resolve_category_slug("경제") == "경제"


def test_normalize_category_slugs_maps_multiple_slugs() -> None:
    assert normalize_category_slugs(["tech", "economy"]) == ["IT/테크", "경제"]


def test_normalize_category_slugs_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="허용되지 않은"):
        normalize_category_slugs(["unknown-slug"])
