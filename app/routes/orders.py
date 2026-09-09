"""Translate order business outcomes into HTTP responses."""

from fastapi import APIRouter, HTTPException, Request, status

from app.models import Order, OrderCreate
from app.services.order_service import CustomerNotFound, InvalidOrder, create_order

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=Order, status_code=status.HTTP_201_CREATED)
def post_order(order: OrderCreate, request: Request) -> Order:
    # A sync handler keeps blocking SQLite work off the async event loop.
    try:
        return create_order(order, request.app.state.database_path)
    except InvalidOrder as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CustomerNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
