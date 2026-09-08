import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import uuid4

CORRELATION_ID = ContextVar[str | None]("correlation_id", default=None)
SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
LOG_FIELDS = (
    "event",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "job_id",
    "repository",
    "pr_number",
    "evaluation_run_id",
    "case_id",
)


def correlation_id() -> str | None:
    return CORRELATION_ID.get()


def normalize_correlation_id(value: str | None) -> str:
    return value if value and SAFE_CORRELATION_ID.fullmatch(value) else str(uuid4())


@contextmanager
def bind_correlation_id(value: str | None) -> Iterator[str]:
    resolved = normalize_correlation_id(value)
    token = CORRELATION_ID.set(resolved)
    try:
        yield resolved
    finally:
        CORRELATION_ID.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id(),
        }
        for field in LOG_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(level: str, *, json_logs: bool) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter() if json_logs else logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        framework_logger = logging.getLogger(logger_name)
        framework_logger.handlers.clear()
        framework_logger.propagate = True
