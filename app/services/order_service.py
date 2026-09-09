"""Order processing with a separate span for each business step."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from opentelemetry import trace

from app.database import connect
from app.models import Order, OrderCreate, User

tracer = trace.get_tracer(__name__)


class InvalidOrder(ValueError):
    """An order violates a business rule."""


class CustomerNotFound(LookupError):
    """An order references an unknown customer."""


@tracer.start_as_current_span("validate_order")
def validate_order(order: OrderCreate) -> None:
    # Schema validation handles shape and types; this is a business limit.
    if order.quantity > 1000:
        raise InvalidOrder("Quantity must not exceed 1000")


@tracer.start_as_current_span("lookup_customer")
def lookup_customer(customer_id: int, path: Path) -> User:
    with connect(path) as connection:
        row = connection.cursor().execute(
            "SELECT id, name, email FROM users WHERE id = ?", (customer_id,)
        ).fetchone()
    if row is None:
        raise CustomerNotFound("Customer not found")
    return User(**dict(row))


@tracer.start_as_current_span("calculate_total")
def calculate_total(order: OrderCreate) -> Decimal:
    return (order.price * order.quantity).quantize(Decimal("0.01"))


@tracer.start_as_current_span("save_order")
def save_order(order: OrderCreate, total: Decimal, path: Path) -> Order:
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
    return result


def create_order(order: OrderCreate, path: Path) -> Order:
    validate_order(order)
    lookup_customer(order.customer_id, path)
    total = calculate_total(order)
    return save_order(order, total, path)
