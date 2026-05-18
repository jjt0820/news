from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

# LogRecord 기본 필드 — 나머지는 extra로 간주해 JSON에 합친다.
_SKIP = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "exc_info",
        "exc_text",
        "stack_info",
        "getMessage",
        "message",
        "taskName",
    }
)

_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id",
    default=None,
)
_service_name_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "service_name",
    default=None,
)

_SENSITIVE_KEY_RE = re.compile(
    r'(?i)(("?(?:password|token|authorization|secret|api[_-]?key)"?\s*[:=]\s*")([^"]+)("))'
)
_SENSITIVE_INLINE_RE = re.compile(
    r"(?i)\b(password|token|authorization|secret|api[_-]?key)\b(\s*[:=]\s*)([^\s,}\]]+)"
)


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


def _mask_sensitive_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(word in lowered for word in ("password", "token", "authorization", "secret", "api_key", "apikey")):
        return "***"
    if isinstance(value, dict):
        return {str(k): _mask_sensitive_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_sensitive_value(key, item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        service_name = _service_name_var.get() or getattr(record, "service", None) or record.name
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = _trace_id_var.get()
        if trace_id:
            payload["trace_id"] = trace_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info).rstrip()
        for key, value in record.__dict__.items():
            if key in _SKIP or key in {"service", "trace_id"} or key.startswith("_"):
                continue
            payload[key] = _mask_sensitive_value(str(key), value)
        return _mask_sensitive_text(json.dumps(payload, ensure_ascii=False, default=str))


SCHEDULER_TIMEZONE = ZoneInfo("Asia/Seoul")


def setup_service_logging(service_name: str) -> logging.Logger:
    set_service_name(service_name)
    log = logging.getLogger(service_name)
    log.handlers.clear()
    log.setLevel(logging.INFO)
    log.propagate = False
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    log.addHandler(h)
    return log


def _serialize_log_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_serialize_log_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_log_value(item) for key, item in value.items()}
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value


def _format_scheduler_datetime(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [_format_scheduler_datetime(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _format_scheduler_datetime(item) for key, item in value.items()}
    if hasattr(value, "astimezone"):
        try:
            localized = value.astimezone(SCHEDULER_TIMEZONE)
            return localized.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(value)
    return value


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

    if getattr(scheduler, "_json_scheduler_logging_registered", False):
        return

    scheduler_trace_ids: dict[str, str] = {}

    def _listener(event: Any) -> None:
        jobs = scheduler.get_jobs()
        next_run_times = {
            job.id: _format_scheduler_datetime(getattr(job, "next_run_time", None))
            for job in jobs
        }
        next_run_time = next(
            (run_time for run_time in next_run_times.values() if run_time is not None),
            None,
        )
        base_extra = {
            "timezone": str(getattr(scheduler, "timezone", SCHEDULER_TIMEZONE)),
            "scheduler_timezone": str(getattr(scheduler, "timezone", SCHEDULER_TIMEZONE)),
            "next_run_time": next_run_time,
            "next_run_times": next_run_times,
        }

        if event.code == EVENT_SCHEDULER_STARTED:
            logger.info(
                "scheduler_started",
                extra={
                    "event": "scheduler_started",
                    "job_count": len(jobs),
                    **base_extra,
                },
            )
            return

        if event.code == EVENT_SCHEDULER_SHUTDOWN:
            logger.info(
                "scheduler_shutdown",
                extra={"event": "scheduler_shutdown", **base_extra},
            )
            return

        if event.code == EVENT_JOB_SUBMITTED:
            job_id = str(getattr(event, "job_id", "unknown"))
            trace_id = f"cron-{uuid.uuid4().hex[:12]}"
            scheduler_trace_ids[job_id] = trace_id
            set_trace_id(trace_id)
            logger.info(
                "scheduler_job_start",
                extra={
                    "event": "scheduler_job_start",
                    "job_id": job_id,
                    "scheduled_run_times": _format_scheduler_datetime(
                        getattr(event, "scheduled_run_times", None)
                    ),
                    **base_extra,
                },
            )
            return

        if event.code == EVENT_JOB_EXECUTED:
            job_id = str(getattr(event, "job_id", "unknown"))
            set_trace_id(scheduler_trace_ids.pop(job_id, None))
            try:
                logger.info(
                    "scheduler_job_success",
                    extra={
                        "event": "scheduler_job_success",
                        "job_id": job_id,
                        "scheduled_run_time": _format_scheduler_datetime(
                            getattr(event, "scheduled_run_time", None)
                        ),
                        "job_result": _serialize_log_value(getattr(event, "retval", None)),
                        **base_extra,
                    },
                )
            finally:
                set_trace_id(None)
            return

        if event.code == EVENT_JOB_ERROR:
            job_id = str(getattr(event, "job_id", "unknown"))
            set_trace_id(scheduler_trace_ids.pop(job_id, None))
            exception = getattr(event, "exception", None)
            exception_name = type(exception).__name__ if exception is not None else ""
            log_method = (
                logger.critical
                if "OperationalError" in exception_name or "DatabaseError" in exception_name
                else logger.error
            )
            try:
                log_method(
                    "scheduler_job_failure",
                    extra={
                        "event": "scheduler_job_failure",
                        "job_id": job_id,
                        "scheduled_run_time": _format_scheduler_datetime(
                            getattr(event, "scheduled_run_time", None)
                        ),
                        "error": str(exception or ""),
                        "error_type": exception_name,
                        "traceback": getattr(event, "traceback", None),
                        **base_extra,
                    },
                )
            finally:
                set_trace_id(None)

    scheduler.add_listener(
        _listener,
        EVENT_SCHEDULER_STARTED
        | EVENT_SCHEDULER_SHUTDOWN
        | EVENT_JOB_SUBMITTED
        | EVENT_JOB_EXECUTED
        | EVENT_JOB_ERROR,
    )
    setattr(scheduler, "_json_scheduler_logging_registered", True)
