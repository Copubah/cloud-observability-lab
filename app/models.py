"""API contracts; monetary values are serialized as decimal strings."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    id: int
    name: str
    email: str


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    customer_id: int = Field(gt=0, le=9223372036854775807, strict=True)
    product: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0, strict=True)
    price: Decimal = Field(gt=0, max_digits=8, decimal_places=2)


class Order(BaseModel):
    id: int
    customer_id: int
    product: str
    quantity: int
    price: Decimal
    total: Decimal
    created_at: datetime
