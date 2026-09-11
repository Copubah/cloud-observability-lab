"""Order processing with a separate span for each business step."""

import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from opentelemetry import trace

from app.database import connect
from app.models import Order, OrderCreate, User
from app.telemetry import orders_created

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)


class InvalidOrder(ValueError):
    """An order violates a business rule."""


class CustomerNotFound(LookupError):
    """An order references an unknown customer."""


@tracer.start_as_current_span("validate_order")
def validate_order(order: OrderCreate) -> None:
    # Schema validation handles shape and types; this is a business limit.
    if order.quantity > 1000:
        logger.warning("Order rejected: quantity exceeds 1000")
        raise InvalidOrder("Quantity must not exceed 1000")
    logger.info("Order validated")


@tracer.start_as_current_span("lookup_customer")
def lookup_customer(customer_id: int, path: Path) -> User:
    with connect(path) as connection:
        row = connection.cursor().execute(
            "SELECT id, name, email FROM users WHERE id = ?", (customer_id,)
        ).fetchone()
    if row is None:
        logger.warning("Order rejected: customer not found")
        raise CustomerNotFound("Customer not found")
    logger.info("Customer found")
    return User(**dict(row))


@tracer.start_as_current_span("calculate_total")
def calculate_total(order: OrderCreate) -> Decimal:
    total = (order.price * order.quantity).quantize(Decimal("0.01"))
    logger.info("Order total calculated")
    return total


@tracer.start_as_current_span("save_order")
def save_order(order: OrderCreate, total: Decimal, path: Path) -> Order:
    span = trace.get_current_span()
    if os.getenv("SIMULATE_DB_LATENCY", "false").lower() == "true":
        span.set_attribute("lab.simulation.db_latency", True)
        logger.warning("Simulating database latency")
        # Delay inside save_order so the waterfall locates the bottleneck.
        # This synchronous handler runs in FastAPI's worker thread pool.
        time.sleep(2.3)
    if os.getenv("SIMULATE_ERRORS", "false").lower() == "true":
        span.set_attribute("lab.simulation.error", True)
        logger.error("Simulating order persistence failure")
        # Fail before opening a transaction: no order or success metric is written.
        raise RuntimeError("Simulated order persistence failure")
    created_at = datetime.now(timezone.utc)
    with connect(path) as connection:
        cursor = connection.cursor().execute(
            """INSERT INTO orders
               (customer_id, product, quantity, price_cents, total_cents, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                order.customer_id,
                order.product,
                order.quantity,
                int(order.price * 100),
                int(total * 100),
                created_at.isoformat(),
            ),
        )
        result = Order(
            id=cursor.lastrowid,
            customer_id=order.customer_id,
            product=order.product,
            quantity=order.quantity,
            price=order.price.quantize(Decimal("0.01")),
            total=total,
            created_at=created_at,
        )
    # Only report success after the transaction has committed.
    orders_created.add(1)
    logger.info("Order saved", extra={"order_id": result.id})
    return result


def create_order(order: OrderCreate, path: Path) -> Order:
    validate_order(order)
    lookup_customer(order.customer_id, path)
    total = calculate_total(order)
    return save_order(order, total, path)
