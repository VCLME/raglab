import json
import logging

from raglab.config import Settings
from raglab.logging_utils import JsonLogFormatter, configure_logging, log_event


def test_json_log_formatter_serializes_event_context(tmp_path):
    formatter = JsonLogFormatter(service_name="raglab", environment="test")
    record = logging.LogRecord(
        name="raglab.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ingestion.completed",
        args=(),
        exc_info=None,
    )
    record.event_name = "ingestion.completed"
    record.event_data = {
        "folder": tmp_path,
        "count": 2,
    }

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "ingestion.completed"
    assert payload["service"] == "raglab"
    assert payload["environment"] == "test"
    assert payload["context"]["folder"] == str(tmp_path)
    assert payload["context"]["count"] == 2


def test_log_event_sets_structured_fields():
    logger = logging.getLogger("raglab.test")
    records: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = CaptureHandler()
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_event(logger, logging.INFO, "query.completed", top_k=5)

    assert len(records) == 1
    assert records[0].event_name == "query.completed"
    assert records[0].event_data == {"top_k": 5}


def test_configure_logging_uses_json_formatter():
    settings = Settings(app_name="raglab", environment="test", log_format="json")
    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level

    try:
        configure_logging(settings=settings, log_json=None)
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonLogFormatter)
    finally:
        root.handlers.clear()
        root.handlers.extend(previous_handlers)
        root.setLevel(previous_level)
