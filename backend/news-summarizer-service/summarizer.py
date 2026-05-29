from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path, encoding="utf-8-sig")
load_dotenv(encoding="utf-8-sig")

_DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_DEFAULT_DELAY_SECONDS = _env_float("SUMMARY_DELAY_SECONDS", 1.25)
_DEFAULT_MAX_RETRIES = _env_int("SUMMARY_MAX_RETRIES", 5)

log = logging.getLogger("news-summarizer")


def _require_api_key() -> str:
    raw = os.getenv("GEMINI_API_KEY")
    if not raw:
        log.critical(
            "required_environment_missing",
            extra={"event": "required_environment_missing", "env_var": "GEMINI_API_KEY"},
        )
        raise RuntimeError(
            "GEMINI_API_KEY가 설정되어 있지 않습니다. "
            "news-summarizer-service/.env 파일에 GEMINI_API_KEY=... 형태로 추가하세요."
        )
    # BOM·앞뒤 공백·따옴표(에디터 자동 삽입) 제거
    api_key = raw.strip().strip("\ufeff").strip().strip('"').strip("'")
    if not api_key:
        log.critical(
            "required_environment_empty",
            extra={"event": "required_environment_empty", "env_var": "GEMINI_API_KEY"},
        )
        raise RuntimeError("GEMINI_API_KEY가 비어 있습니다.")
    return api_key


def _extract_response_text(resp: Any) -> str:
    """generate_content 응답에서 텍스트를 안정적으로 추출한다."""
    text = (getattr(resp, "text", None) or "").strip()
    if text:
        return text

    candidates = getattr(resp, "candidates", None) or []
    if not candidates:
        prompt_fb = getattr(resp, "prompt_feedback", None)
        block = getattr(prompt_fb, "block_reason", None) if prompt_fb else None
        raise RuntimeError(
            "Gemini 응답에 텍스트가 없습니다."
            + (f" (차단 사유: {block})" if block else "")
        )

    parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
    chunks = []
    for p in parts:
        t = getattr(p, "text", None)
        if t:
            chunks.append(t)
    out = "".join(chunks).strip()
    if not out:
        finish = getattr(candidates[0], "finish_reason", None)
        raise RuntimeError(
            "Gemini 응답에서 본문을 읽을 수 없습니다."
            + (f" (finish_reason: {finish})" if finish else "")
        )
    return out


def _is_retryable_rate_limit(exc: BaseException) -> bool:
    try:
        from google.api_core import exceptions as gexc

        if isinstance(exc, gexc.ResourceExhausted):
            return True
    except Exception:
        pass

    name = type(exc).__name__
    if name in ("ResourceExhausted", "TooManyRequests"):
        return True

    s = str(exc).lower()
    return (
        "429" in s
        or "resource exhausted" in s
        or "quota" in s
        or "rate limit" in s
        or "too many requests" in s
    )


def _is_timeout_or_5xx(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return (
        "timeout" in name
        or "deadline" in name
        or "timeout" in message
        or "deadline exceeded" in message
        or "500" in message
        or "502" in message
        or "503" in message
        or "504" in message
    )


def _summarize_with_client(
    client: Any,
    news: Dict[str, Any],
    *,
    timeout_seconds: Optional[int],
) -> str:
    title = str(news.get("title", "")).strip()
    link = str(news.get("link", "")).strip()
    category = str(news.get("category", "")).strip()
    rss_description = str(news.get("rss_description", "")).strip()

    if not title or not link:
        raise ValueError("news 입력에는 최소한 'title'과 'link'가 필요합니다.")

    if rss_description:
        prompt = f"""
You are a professional Korean news summarizer for a daily newsletter.

Input (RSS title and description — use ONLY facts present below):
- category: {category}
- title: {title}
- rss_description: {rss_description}

Write the summary in Korean ONLY, using EXACTLY this format:

[오늘의 한 줄]: <핵심 요약 1줄>

[주요 내용]:
- <상세 내용 1>
- <상세 내용 2>
- <상세 내용 3>

[알아두면 좋은 점]: <배경 지식/시사점 1줄>

Important rules:
- Base your writing ONLY on the title and rss_description above. Do NOT invent facts (no hallucination).
- If the description is short, keep bullets concise without adding outside information.
- Keep each line concise and friendly for a newsletter card.
- Do NOT include any extra sections.
- Do NOT include URLs or the original link anywhere inside the summary body.
- Do NOT add markdown code blocks.
""".strip()
    else:
        prompt = f"""
You are a professional Korean news summarizer for a daily newsletter.

Input (RSS title only — description was empty):
- category: {category}
- title: {title}

The rss_description is empty. Write a brief Korean newsletter card using ONLY what the title states.
Do NOT invent specific facts beyond what the title clearly implies.

Write the summary in Korean ONLY, using EXACTLY this format:

[오늘의 한 줄]: <제목 기반 핵심 1줄>

[주요 내용]:
- <제목에서 알 수 있는 내용 1줄>

Important rules:
- Keep it short because only the title is available.
- Do NOT include URLs or the original link anywhere inside the summary body.
- Do NOT add markdown code blocks.
""".strip()

    _ = timeout_seconds

    import google.generativeai as genai

    generation_config = genai.GenerationConfig(
        temperature=0.35,
        max_output_tokens=1024,
    )
    try:
        resp = client.generate_content(prompt, generation_config=generation_config)
    except BaseException as exc:
        if _is_timeout_or_5xx(exc):
            log.error(
                "gemini_api_failure",
                extra={
                    "event": "gemini_api_failure",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "news_link": link[:300],
                },
            )
        raise
    text = _extract_response_text(resp)
    if not text:
        raise RuntimeError("Gemini가 비어있는 요약을 반환했습니다.")

    return f"{text}\n\n🔗 원문 보기: {link}"


def summarize_news(
    news: Dict[str, Any],
    *,
    model: str = _DEFAULT_MODEL,
    timeout_seconds: Optional[int] = None,
) -> str:
    """
    뉴스 dict(title/link/category 등)를 입력받아 Gemini로 한국어 요약 텍스트를 생성한다.

    출력 포맷(한국어):
    [오늘의 한 줄]: ...
    [주요 내용]:
    - ...
    - ...
    - ...
    [알아두면 좋은 점]: ...
    🔗 원문 보기: [URL]
    """
    import google.generativeai as genai

    api_key = _require_api_key()
    genai.configure(api_key=api_key)
    client = genai.GenerativeModel(model)
    return _summarize_with_client(client, news, timeout_seconds=timeout_seconds)


def iter_summarize_news(
    news_list: List[Dict[str, Any]],
    *,
    model: str = _DEFAULT_MODEL,
    delay_seconds: float = _DEFAULT_DELAY_SECONDS,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    timeout_seconds: Optional[int] = None,
):
    """
    뉴스 리스트를 한 건씩 요약하며 (원본 dict, 요약 문자열)을 순서대로 보낸다.
    항목 사이에 지연을 두고, 할당량/속도 제한 오류에는 지수 백오프로 재시도한다.
    """
    import google.generativeai as genai

    if max_retries < 1:
        raise ValueError("max_retries는 1 이상이어야 합니다.")
    if delay_seconds < 0:
        raise ValueError("delay_seconds는 0 이상이어야 합니다.")

    if not news_list:
        return

    api_key = _require_api_key()
    genai.configure(api_key=api_key)
    client = genai.GenerativeModel(model)

    for i, news in enumerate(news_list):
        if i > 0:
            time.sleep(delay_seconds)

        summary: Optional[str] = None
        for attempt in range(max_retries):
            try:
                summary = _summarize_with_client(
                    client, news, timeout_seconds=timeout_seconds
                )
                break
            except BaseException as exc:
                if not _is_retryable_rate_limit(exc) or attempt == max_retries - 1:
                    raise
                backoff = (2**attempt) + random.uniform(0.0, 0.35)
                retrying_count = attempt + 1
                log.warning(
                    "gemini_summarize_retry_backoff",
                    extra={
                        "event": "gemini_summarize_retry_backoff",
                        "retrying_count": retrying_count,
                        "gemini_attempt_index": attempt + 1,
                        "max_retries": max_retries,
                        "list_index": i,
                        "news_link": str(news.get("link", ""))[:300],
                        "sleep_seconds": round(backoff, 4),
                        "error_type": type(exc).__name__,
                    },
                )
                time.sleep(backoff)

        if summary is None:
            raise RuntimeError("요약 생성에 실패했습니다.")

        yield news, summary


def summarize_news_list(
    news_list: List[Dict[str, Any]],
    *,
    model: str = _DEFAULT_MODEL,
    delay_seconds: float = _DEFAULT_DELAY_SECONDS,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    timeout_seconds: Optional[int] = None,
) -> List[str]:
    """
    뉴스 dict 리스트를 순서대로 요약한 문자열 리스트를 반환한다.
    (내부적으로 iter_summarize_news와 동일한 지연·재시도 정책을 사용한다.)
    """
    return [
        text
        for _, text in iter_summarize_news(
            news_list,
            model=model,
            delay_seconds=delay_seconds,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )
    ]


if __name__ == "__main__":
    from json_logging import setup_service_logging

    setup_service_logging("news-summarizer")
    samples: List[Dict[str, str]] = [
        {
            "category": "IT/테크",
            "title": "Tech Giants Report Quarterly Earnings Amid AI Spending Boom",
            "link": "https://example.com/news/sample-tech-earnings",
        },
    ]

    log.info(
        "summarizer_cli_start",
        extra={"event": "summarizer_cli_start", "sample_count": len(samples)},
    )
    summaries = summarize_news_list(samples)
    for i, summary in enumerate(summaries, start=1):
        log.info(
            "summarizer_cli_result",
            extra={"event": "summarizer_cli_result", "index": i, "summary_preview": summary[:400]},
        )
