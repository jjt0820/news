from __future__ import annotations

import json
import logging
import sys
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


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info).rstrip()
        for key, value in record.__dict__.items():
            if key in _SKIP or key.startswith("_"):
                continue
            payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


SCHEDULER_TIMEZONE = ZoneInfo("Asia/Seoul")


def setup_service_logging(service_name: str) -> logging.Logger:
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
            "service": service_name,
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
            logger.info(
                "scheduler_job_start",
                extra={
                    "event": "scheduler_job_start",
                    "job_id": getattr(event, "job_id", None),
                    "scheduled_run_times": _format_scheduler_datetime(
                        getattr(event, "scheduled_run_times", None)
                    ),
                    **base_extra,
                },
            )
            return

        if event.code == EVENT_JOB_EXECUTED:
            logger.info(
                "scheduler_job_success",
                extra={
                    "event": "scheduler_job_success",
                    "job_id": getattr(event, "job_id", None),
                    "scheduled_run_time": _format_scheduler_datetime(
                        getattr(event, "scheduled_run_time", None)
                    ),
                    "job_result": _serialize_log_value(getattr(event, "retval", None)),
                    **base_extra,
                },
            )
            return

        if event.code == EVENT_JOB_ERROR:
            logger.error(
                "scheduler_job_failure",
                extra={
                    "event": "scheduler_job_failure",
                    "job_id": getattr(event, "job_id", None),
                    "scheduled_run_time": _format_scheduler_datetime(
                        getattr(event, "scheduled_run_time", None)
                    ),
                    "error": str(getattr(event, "exception", "")),
                    "traceback": getattr(event, "traceback", None),
                    **base_extra,
                },
            )

    scheduler.add_listener(
        _listener,
        EVENT_SCHEDULER_STARTED
        | EVENT_SCHEDULER_SHUTDOWN
        | EVENT_JOB_SUBMITTED
        | EVENT_JOB_EXECUTED
        | EVENT_JOB_ERROR,
    )
    setattr(scheduler, "_json_scheduler_logging_registered", True)


def uvicorn_log_config() -> dict[str, Any]:
    """uvicorn.run(log_config=...)용 — 앱과 동일한 JSON 한 줄 포맷."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {"()": "json_logging.JsonFormatter"},
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
        },
    }
