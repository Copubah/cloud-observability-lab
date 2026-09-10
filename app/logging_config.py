"""JSON formatting and request context shared by console and OTLP handlers."""

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

from opentelemetry.trace import Span
from starlette.types import Scope

# Store the scope itself: routing fills its template before worker-thread logs run.
request_scope: ContextVar[Scope | None] = ContextVar("request_scope", default=None)


def capture_trace_ids(span: Span, record: logging.LogRecord) -> None:
    context = span.get_span_context()
    record.otelTraceID = format(context.trace_id, "032x")
    record.otelSpanID = format(context.span_id, "016x")


class CorrelationFilter(logging.Filter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        scope = request_scope.get()
        record.timestamp = datetime.fromtimestamp(record.created, timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        record.service_name = self.service_name
        record.route = getattr(scope.get("route"), "path", "<unmatched>") if scope else "-"
        # LoggingInstrumentor captures IDs when the record is created, before export.
        record.trace_id = str(getattr(record, "otelTraceID", "0")).zfill(32)
        record.span_id = str(getattr(record, "otelSpanID", "0")).zfill(16)
        return True


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        document = {
            "timestamp": record.timestamp,
            "level": record.levelname,
            "service_name": record.service_name,
            "route": record.route,
            "message": record.getMessage(),
            "trace_id": record.trace_id,
            "span_id": record.span_id,
            "logger": record.name,
        }
        for name in ("status_code", "duration_ms", "order_id"):
            if hasattr(record, name):
                document[name] = getattr(record, name)
        if record.exc_info:
            document["exception"] = self.formatException(record.exc_info)
        # JSON escapes stack-trace newlines so each record occupies one physical line.
        return json.dumps(document, ensure_ascii=False)
