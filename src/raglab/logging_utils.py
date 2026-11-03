from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from raglab.config import Settings

# Correlation id of the HTTP request being served, set by the API middleware.
# Every log line emitted while the request runs (including threadpool work and
# streamed responses, which copy the context) carries it.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def _serialize_log_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _serialize_log_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_log_value(item) for item in value]
    return value


class JsonLogFormatter(logging.Formatter):
    def __init__(self, *, service_name: str, environment: str):
        super().__init__()
        self.service_name = service_name
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
            "environment": self.environment,
        }

        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id

        event_name = getattr(record, "event_name", None)
        if event_name:
            payload["event"] = event_name

        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict) and event_data:
            payload["context"] = _serialize_log_value(event_data)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class TextLogFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(levelname)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        request_id = request_id_var.get()
        return f"{line} request_id={request_id}" if request_id else line


def configure_logging(
    *,
    settings: Settings,
    log_level: str | None = None,
    log_json: bool | None = None,
) -> None:
    level_name = (log_level or settings.log_level).upper()
    level = getattr(logging, level_name, logging.INFO)
    use_json = log_json if log_json is not None else settings.log_format.lower() == "json"

    handler = logging.StreamHandler()
    if use_json:
        handler.setFormatter(
            JsonLogFormatter(
                service_name=settings.app_name,
                environment=settings.environment,
            )
        )
    else:
        handler.setFormatter(TextLogFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    logger.log(
        level,
        event,
        extra={
            "event_name": event,
            "event_data": fields,
        },
    )
