"""Exercise real lifespan and SQLite without an external telemetry backend."""

import os

import pytest
from fastapi.testclient import TestClient

# Providers are process-wide and initialized on import. Override shell settings
# before importing the application so a test cannot export to a live backend.
for signal in ('TRACES', 'METRICS', 'LOGS'):
    os.environ[f'OTEL_{signal}_EXPORTER'] = 'none'
os.environ['OTEL_TRACES_SAMPLER'] = 'always_on'
os.environ['LOG_LEVEL'] = 'INFO'

from app.main import app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'test.db'))
    monkeypatch.setenv('SIMULATE_DB_LATENCY', 'false')
    monkeypatch.setenv('SIMULATE_ERRORS', 'false')
    # The context manager runs startup/seeding and shutdown. Return actual 500
    # responses instead of re-raising app exceptions in the test process.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def order():
    return {'customer_id': 1, 'product': 'Notebook', 'quantity': 3, 'price': '0.10'}


@pytest.fixture(scope='session')
def span_exporter():
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from app.main import tracer_provider

    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture
def spans(client, span_exporter):
    # Clear startup spans and previous requests, keeping providers process-wide.
    span_exporter.clear()
    return span_exporter
