"""User retrieval backed by seeded SQLite records."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request

from app.database import connect
from app.models import User

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[User])
def list_users(request: Request) -> list[User]:
    with connect(request.app.state.database_path) as connection:
        rows = connection.cursor().execute(
            "SELECT id, name, email FROM users ORDER BY id"
        ).fetchall()
    return [User(**dict(row)) for row in rows]


@router.get("/{id}", response_model=User)
def get_user(
    id: Annotated[int, Path(gt=0, le=9223372036854775807)], request: Request
) -> User:
    with connect(request.app.state.database_path) as connection:
        row = connection.cursor().execute(
            "SELECT id, name, email FROM users WHERE id = ?", (id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return User(**dict(row))
