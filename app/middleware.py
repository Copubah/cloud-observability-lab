"""HTTP metrics and request logs that preserve trace and route context."""

import logging
from time import perf_counter

from opentelemetry import metrics
from opentelemetry.metrics import MeterProvider
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logging_config import request_scope

logger = logging.getLogger(__name__)
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"}


class HTTPMetricsMiddleware:
    def __init__(self, app: ASGIApp, meter_provider: MeterProvider) -> None:
        self.app = app
        meter = metrics.get_meter("cloud-observability-lab", meter_provider=meter_provider)
        self.requests = meter.create_counter(
            "lab.http.requests", unit="{request}", description="Requests by HTTP outcome"
        )
        self.duration = meter.create_histogram(
            "lab.http.request.duration", unit="s", description="Time through final response body send"
        )
        self.client_errors = meter.create_counter(
            "lab.http.client_errors", unit="{request}", description="HTTP 4xx responses"
        )
        self.server_errors = meter.create_counter(
            "lab.http.server_errors", unit="{request}", description="HTTP 5xx responses"
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = perf_counter()
        status = 500
        recorded = False

        def record(completed: bool) -> None:
            nonlocal recorded
            if recorded:
                return
            recorded = True
            route = getattr(scope.get("route"), "path", "<unmatched>")
            method = scope["method"] if scope["method"] in METHODS else "_OTHER"
            attributes = {
                "http.request.method": method,
                "http.route": route,
                "http.response.status_code": status,
                "outcome": "success" if completed and status < 400 else "failure",
            }
            self.requests.add(1, attributes)
            self.duration.record(perf_counter() - started, attributes)
            if 400 <= status < 500:
                self.client_errors.add(1, attributes)
            elif 500 <= status < 600:
                self.server_errors.add(1, attributes)

        async def measured_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                record(completed=True)

        try:
            await self.app(scope, receive, measured_send)
        finally:
            # Exceptions before a response still count; preserve the original exception.
            # This guard also prevents double counting after a completed response.
            record(completed=False)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = request_scope.set(scope)
        started = perf_counter()
        status = 500

        def details() -> dict[str, int | float]:
            return {"status_code": status, "duration_ms": round((perf_counter() - started) * 1000, 3)}

        async def logged_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
                logger.log(level, "Request completed", extra=details())

        try:
            await self.app(scope, receive, logged_send)
        except Exception:
            # Log while the request span and route context are still available.
            logger.exception("Request failed", extra=details())
            raise
        finally:
            # Prevent context from leaking into the next request or lifecycle logs.
            request_scope.reset(token)
