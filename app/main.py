"""HTTP entry point for Cloud Observability Lab."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.database import database_path, initialize_database
from app.middleware import HTTPMetricsMiddleware, RequestLoggingMiddleware
from app.routes import orders, users
from app.telemetry import (
    configure_metrics,
    configure_logging,
    configure_tracing,
    flush_metrics,
    flush_logs,
    flush_traces,
    instrument_app,
)

tracer_provider = configure_tracing()
meter_provider = configure_metrics()
logger_provider = configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    try:
        path = database_path()
        # Group startup SQL separately from request traces.
        tracer = tracer_provider.get_tracer(__name__)
        with tracer.start_as_current_span("database.initialize"):
            await run_in_threadpool(initialize_database, path)
            logger.info("Database initialized")
        application.state.database_path = path
        yield
    finally:
        # Flush on app shutdown; the process-wide SDK shuts down at process exit.
        await run_in_threadpool(flush_traces, tracer_provider)
        await run_in_threadpool(flush_metrics, meter_provider)
        await run_in_threadpool(flush_logs, logger_provider)


app = FastAPI(
    title="Cloud Observability Lab",
    description="A production-style API for learning logs, metrics, and traces.",
    version="0.8.0",
    lifespan=lifespan,
)
app.include_router(users.router)
app.include_router(orders.router)
app.add_middleware(HTTPMetricsMiddleware, meter_provider=meter_provider)
app.add_middleware(RequestLoggingMiddleware)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Check process liveness without depending on a database or exporter."""
    return {"status": "healthy"}


@app.get("/slow", tags=["diagnostics"])
async def deliberate_latency() -> dict[str, str]:
    """Demonstrate latency without blocking the event loop."""
    await asyncio.sleep(2.3)
    return {"status": "slow", "delay_seconds": "2.3"}


@app.get("/error", tags=["diagnostics"])
async def deliberate_error() -> None:
    """Exercise exception correlation without changing application data."""
    raise RuntimeError("Deliberate error for observability demonstration")


instrument_app(app, tracer_provider)
