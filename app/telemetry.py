"""Process-wide, vendor-neutral tracing with console or OTLP/HTTP export."""

import logging
import os
from functools import lru_cache
from urllib.parse import urlparse

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

logger = logging.getLogger(__name__)


def otlp_exporter() -> OTLPSpanExporter:
    protocol = os.getenv(
        "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
        os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"),
    )
    if protocol != "http/protobuf":
        raise ValueError("This lab uses OTLP http/protobuf, normally on port 4318")
    endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"),
    )
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("The OTLP endpoint must be an absolute http:// or https:// URL")
    # Let the exporter interpret standard endpoint, headers, timeout and TLS env vars.
    # A generic endpoint gains /v1/traces; a traces-specific endpoint is used as-is.
    return OTLPSpanExporter()


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

    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "cloud-observability-lab"),
            "service.version": "0.3.0",
        }
    )
    # The SDK reads OTEL_TRACES_SAMPLER / OTEL_TRACES_SAMPLER_ARG and registers
    # shutdown at process exit. Parent-based sampling preserves upstream decisions.
    provider = TracerProvider(resource=resource)
    if exporter is not None:
        # Batch export keeps network I/O off request threads.
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    SQLite3Instrumentor().instrument(tracer_provider=provider)
    return provider


def instrument_app(application: FastAPI, provider: TracerProvider) -> None:
    FastAPIInstrumentor.instrument_app(
        application,
        tracer_provider=provider,
        # Keep server and business spans visible without ASGI transport noise.
        exclude_spans=["receive", "send"],
    )


def flush_traces(provider: TracerProvider) -> None:
    if not provider.force_flush(timeout_millis=5000):
        logger.warning("Trace flush did not finish within five seconds")
