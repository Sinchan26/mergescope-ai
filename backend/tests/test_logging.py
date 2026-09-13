import json
import logging
from uuid import UUID

from mergescope.core.logging import JsonFormatter, bind_correlation_id, normalize_correlation_id


def test_json_logs_include_correlation_and_only_curated_context() -> None:
    record = logging.LogRecord(
        name="mergescope.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Request completed.",
        args=(),
        exc_info=None,
    )
    record.event = "test_event"
    record.status_code = 200
    record.operator_token = "must-not-appear"

    with bind_correlation_id("request-123"):
        payload = json.loads(JsonFormatter().format(record))

    assert payload["correlation_id"] == "request-123"
    assert payload["event"] == "test_event"
    assert payload["status_code"] == 200
    assert "operator_token" not in payload


def test_unsafe_correlation_id_is_replaced_with_uuid() -> None:
    generated = normalize_correlation_id("unsafe request id with spaces")

    assert str(UUID(generated)) == generated
