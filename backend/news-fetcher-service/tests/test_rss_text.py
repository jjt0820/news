"""Unit tests for RSS text helpers."""

from __future__ import annotations

from rss_text import extract_rss_description, strip_html_tags


def test_strip_html_tags_removes_tags() -> None:
    raw = "<p>Hello <b>world</b></p>"
    assert strip_html_tags(raw) == "Hello world"


def test_extract_rss_description_prefers_summary() -> None:
    entry = {"summary": "<p>First summary</p>", "description": "Second"}
    assert extract_rss_description(entry) == "First summary"


def test_extract_rss_description_falls_back_to_description() -> None:
    entry = {"description": "Plain description"}
    assert extract_rss_description(entry) == "Plain description"
