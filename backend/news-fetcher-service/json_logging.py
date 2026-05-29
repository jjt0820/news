from __future__ import annotations

import contextvars
import logging
import re
import sys
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id",
    default=None,
)
_service_name_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "service_name",
    default=None,
)

_DB_ERROR_NAMES = frozenset({"OperationalError", "DatabaseError"})
_DB_EVENTS = frozenset({"database_connection_failed"})
_CRON_EVENT_PREFIXES = (
    "scheduler_",
    "newsletter_batch",
    "pipeline_",
    "category_batch",
    "category_no_items",
    "category_fetch_stats",
    "category_pipeline_failed",
    "rss_snapshot_",
)

_SENSITIVE_KEY_RE = re.compile(
    r'(?i)(("?(?:password|token|authorization|secret|api[_-]?key)"?\s*[:=]\s*")([^"]+)("))'
)
_SENSITIVE_INLINE_RE = re.compile(
    r"(?i)\b(password|token|authorization|secret|api[_-]?key)\b(\s*[:=]\s*)([^\s,}\]]+)"
)

SCHEDULER_TIMEZONE = ZoneInfo("Asia/Seoul")

_SCHEDULER_MESSAGES = {
    "scheduler_started": "스케줄러가 시작되었습니다",
    "scheduler_shutdown": "스케줄러가 종료되었습니다",
    "scheduler_job_start": "배치 작업이 시작되었습니다",
    "scheduler_job_success": "배치 작업이 완료되었습니다",
    "scheduler_job_failure": "배치 작업이 실패했습니다",
}


def resolve_request_trace_id(header_value: str | None) -> str:
    raw = (header_value or "").strip()
    if raw:
        return raw
    return f"req-{uuid.uuid4().hex[:12]}"


def set_trace_id(trace_id: str | None) -> contextvars.Token[str | None]:
    return _trace_id_var.set(trace_id)


def reset_trace_id(token: contextvars.Token[str | None]) -> None:
    _trace_id_var.reset(token)


def set_service_name(service_name: str | None) -> contextvars.Token[str | None]:
    return _service_name_var.set(service_name)


def reset_service_name(token: contextvars.Token[str | None]) -> None:
    _service_name_var.reset(token)


def _mask_sensitive_text(text: str) -> str:
    text = _SENSITIVE_KEY_RE.sub(lambda m: f"{m.group(2)}***{m.group(4)}", text)
    return _SENSITIVE_INLINE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)


def _is_db_related(record: logging.LogRecord) -> bool:
    event = getattr(record, "event", "")
    if event in _DB_EVENTS:
        return True
    error_type = getattr(record, "error_type", "")
    if error_type in _DB_ERROR_NAMES:
        return True
    if record.exc_info and record.exc_info[0] is not None:
        if record.exc_info[0].__name__ in _DB_ERROR_NAMES:
            return True
    return False


def _is_cron_related(record: logging.LogRecord) -> bool:
    if getattr(record, "actor_type", None) == "SYSTEM-CRON":
        return True
    event = getattr(record, "event", "")
    if not isinstance(event, str):
        return False
    if event.startswith("scheduler_"):
        return True
    return any(event.startswith(prefix) for prefix in _CRON_EVENT_PREFIXES)


def _resolve_context(record: logging.LogRecord) -> str:
    user_email = getattr(record, "user_email", None)
    if user_email:
        return f"User: {user_email}"

    if _is_cron_related(record):
        return "SYSTEM-CRON"

    if _is_db_related(record):
        return "SYSTEM-DB"

    trace_id = _trace_id_var.get()
    if trace_id:
        return trace_id
    return "req-unknown"


class BracketFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(
            fmt="[%(asctime)s] [%(context)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=SCHEDULER_TIMEZONE)
        return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        record.context = _resolve_context(record)
        message = _mask_sensitive_text(record.getMessage())
        record.msg = message
        record.args = ()
        line = super().format(record)
        line = _mask_sensitive_text(line)
        if record.exc_info:
            exc_text = self.formatException(record.exc_info).rstrip()
            if exc_text:
                line = f"{line}\n{_mask_sensitive_text(exc_text)}"
        return line


def setup_service_logging(service_name: str) -> logging.Logger:
    set_service_name(service_name)
    log = logging.getLogger(service_name)
    log.handlers.clear()
    log.setLevel(logging.INFO)
    log.propagate = False
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(BracketFormatter())
    log.addHandler(handler)
    return log


def register_scheduler_logging(
    scheduler: Any,
    logger: logging.Logger,
    *,
    service_name: str,
) -> None:
    from apscheduler.events import (
        EVENT_JOB_ERROR,
        EVENT_JOB_EXECUTED,
        EVENT_JOB_SUBMITTED,
        EVENT_SCHEDULER_SHUTDOWN,
        EVENT_SCHEDULER_STARTED,
    )

    if getattr(scheduler, "_bracket_scheduler_logging_registered", False):
        return

    def _cron_extra(job_id: str, event: str, **fields: Any) -> dict[str, Any]:
        extra: dict[str, Any] = {
            "actor_type": "SYSTEM-CRON",
            "job_id": job_id,
            "event": event,
        }
        extra.update(fields)
        return extra

    def _listener(event: Any) -> None:
        if event.code == EVENT_SCHEDULER_STARTED:
            logger.info(
                _SCHEDULER_MESSAGES["scheduler_started"],
                extra=_cron_extra("-", "scheduler_started"),
            )
            return

        if event.code == EVENT_SCHEDULER_SHUTDOWN:
            logger.info(
                _SCHEDULER_MESSAGES["scheduler_shutdown"],
                extra=_cron_extra("-", "scheduler_shutdown"),
            )
            return

        job_id = str(getattr(event, "job_id", "unknown"))

        if event.code == EVENT_JOB_SUBMITTED:
            logger.info(
                _SCHEDULER_MESSAGES["scheduler_job_start"],
                extra=_cron_extra(job_id, "scheduler_job_start"),
            )
            return

        if event.code == EVENT_JOB_EXECUTED:
            logger.info(
                _SCHEDULER_MESSAGES["scheduler_job_success"],
                extra=_cron_extra(job_id, "scheduler_job_success"),
            )
            return

        if event.code == EVENT_JOB_ERROR:
            exception = getattr(event, "exception", None)
            exception_name = type(exception).__name__ if exception is not None else ""
            log_method = logger.critical if exception_name in _DB_ERROR_NAMES else logger.error
            message = _SCHEDULER_MESSAGES["scheduler_job_failure"]
            if exception_name:
                message = f"{message} ({exception_name})"
            log_method(
                message,
                extra=_cron_extra(
                    job_id,
                    "scheduler_job_failure",
                    error=str(exception or ""),
                    error_type=exception_name,
                ),
            )

    scheduler.add_listener(
        _listener,
        EVENT_SCHEDULER_STARTED
        | EVENT_SCHEDULER_SHUTDOWN
        | EVENT_JOB_SUBMITTED
        | EVENT_JOB_EXECUTED
        | EVENT_JOB_ERROR,
    )
    setattr(scheduler, "_bracket_scheduler_logging_registered", True)


def uvicorn_log_config() -> dict[str, Any]:
    """uvicorn.run(log_config=...) — 앱과 동일한 3브래킷 평문 포맷."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "bracket": {"()": "json_logging.BracketFormatter"},
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "bracket",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
        },
    }
