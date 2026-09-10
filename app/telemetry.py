"""Vendor-neutral traces, metrics, and correlated logs."""

import logging
import os
import sys
from functools import lru_cache
from urllib.parse import urlparse

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from app.logging_config import CorrelationFilter, JSONFormatter, capture_trace_ids

logger = logging.getLogger(__name__)
orders_created = metrics.get_meter("cloud-observability-lab").create_counter(
    "lab.orders.created", unit="{order}", description="Orders successfully committed to SQLite"
)


def validate_otlp_configuration(signal: str) -> None:
    protocol = os.getenv(
        f"OTEL_EXPORTER_OTLP_{signal}_PROTOCOL",
        os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"),
    )
    if protocol != "http/protobuf":
        raise ValueError("This lab uses OTLP http/protobuf, normally on port 4318")
    endpoint = os.getenv(
        f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT",
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"),
    )
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("The OTLP endpoint must be an absolute http:// or https:// URL")


def otlp_exporter() -> OTLPSpanExporter:
    validate_otlp_configuration("TRACES")
    # Generic endpoints gain the signal path; signal-specific endpoints are used as-is.
    return OTLPSpanExporter()


@lru_cache(maxsize=1)
def service_resource() -> Resource:
    return Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "cloud-observability-lab"),
            "service.version": "0.5.0",
        }
    )


@lru_cache(maxsize=1)
def configure_tracing() -> TracerProvider:
    # A global provider can be registered only once. Environment changes need restart.
    mode = os.getenv("OTEL_TRACES_EXPORTER", "console").strip().lower()
    if mode not in {"console", "otlp", "none"}:
        raise ValueError("OTEL_TRACES_EXPORTER must be console, otlp, or none")
    exporter = None
    if mode == "console":
        exporter = ConsoleSpanExporter()
    elif mode == "otlp":
        exporter = otlp_exporter()

    # The SDK reads OTEL_TRACES_SAMPLER / OTEL_TRACES_SAMPLER_ARG and registers
    # shutdown at process exit. Parent-based sampling preserves upstream decisions.
    provider = TracerProvider(resource=service_resource())
    if exporter is not None:
        # Batch export keeps network I/O off request threads.
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    SQLite3Instrumentor().instrument(tracer_provider=provider)
    return provider


@lru_cache(maxsize=1)
def configure_metrics() -> MeterProvider:
    mode = os.getenv("OTEL_METRICS_EXPORTER", "console").strip().lower()
    if mode not in {"console", "otlp", "none"}:
        raise ValueError("OTEL_METRICS_EXPORTER must be console, otlp, or none")
    readers = []
    if mode != "none":
        if mode == "otlp":
            validate_otlp_configuration("METRICS")
            exporter = OTLPMetricExporter()
        else:
            exporter = ConsoleMetricExporter()
        # The reader honors OTEL_METRIC_EXPORT_INTERVAL and OTEL_METRIC_EXPORT_TIMEOUT.
        readers.append(PeriodicExportingMetricReader(exporter))
    provider = MeterProvider(
        resource=service_resource(),
        metric_readers=readers,
        views=[
            View(
                instrument_name="lab.http.request.duration",
                aggregation=ExplicitBucketHistogramAggregation(
                    boundaries=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 2.5, 3, 5, 10)
                ),
            )
        ],
    )
    metrics.set_meter_provider(provider)
    return provider


@lru_cache(maxsize=1)
def configure_logging() -> LoggerProvider:
    mode = os.getenv("OTEL_LOGS_EXPORTER", "console").strip().lower()
    if mode not in {"console", "otlp", "none"}:
        raise ValueError("OTEL_LOGS_EXPORTER must be console, otlp, or none")
    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if level_name not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    level = getattr(logging, level_name)
    exporter = None
    if mode == "otlp":
        validate_otlp_configuration("LOGS")
        exporter = OTLPLogExporter()
    provider = LoggerProvider(resource=service_resource())
    if exporter is not None:
        provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(provider)
    # In the pinned instrumentation, the hook captures IDs without installing
    # its text formatter or a second, automatic root OTLP handler.
    LoggingInstrumentor().instrument(
        set_logging_format=False,
        enable_log_auto_instrumentation=False,
        log_hook=capture_trace_ids,
    )
    correlation = CorrelationFilter(str(service_resource().attributes["service.name"]))
    root = logging.getLogger()
    root.setLevel(level)
    console = logging.StreamHandler(sys.stdout) if mode != "none" else logging.NullHandler()
    console.setLevel(level)
    console.addFilter(correlation)
    console.setFormatter(JSONFormatter())
    root.handlers[:] = [console]

    application_logger = logging.getLogger("app")
    application_logger.handlers.clear()
    application_logger.setLevel(level)
    application_logger.propagate = True
    if exporter is not None:
        handler = LoggingHandler(level=level, logger_provider=provider)
        handler.addFilter(correlation)
        # Only application logs go to OTLP. Exporter diagnostics stay on stdout,
        # avoiding recursive export when the Collector is unavailable.
        application_logger.addHandler(handler)

    for name in ("uvicorn", "uvicorn.error"):
        server_logger = logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True
    # Our middleware emits a correlated request summary instead of an access line.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers[:] = [logging.NullHandler()]
    access_logger.propagate = False
    return provider


def instrument_app(application: FastAPI, provider: TracerProvider) -> None:
    FastAPIInstrumentor.instrument_app(
        application,
        tracer_provider=provider,
        # Our middleware owns HTTP metrics; avoid overlapping automatic instruments.
        meter_provider=NoOpMeterProvider(),
        # Keep server and business spans visible without ASGI transport noise.
        exclude_spans=["receive", "send"],
    )


def flush_traces(provider: TracerProvider) -> None:
    if not provider.force_flush(timeout_millis=5000):
        logger.warning("Trace flush did not finish within five seconds")


def flush_metrics(provider: MeterProvider) -> None:
    try:
        if not provider.force_flush(timeout_millis=5000):
            logger.warning("Metric flush did not finish within five seconds")
    except Exception:
        # Export failure must not replace an application startup/shutdown error.
        logger.exception("Metric flush failed")


def flush_logs(provider: LoggerProvider) -> None:
    try:
        if not provider.force_flush(timeout_millis=5000):
            logger.warning("Log flush did not finish within five seconds")
    except Exception:
        logger.exception("Log flush failed")
