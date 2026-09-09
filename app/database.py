"""SQLite storage for a single-instance local lab."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "lab.db"


def database_path() -> Path:
    configured = os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH)).strip()
    if not configured or configured == ":memory:":
        raise ValueError("DATABASE_PATH must be a non-empty SQLite file path")
    return Path(configured).expanduser().resolve()


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    # Create and close in the same worker thread; never share a global connection.
    connection = sqlite3.connect(path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        # OTel's SQLite integration traces cursor calls, not connection shortcuts.
        connection.cursor().execute("PRAGMA foreign_keys = ON")
        # The transaction context commits on success and rolls back on failure.
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as connection:
        # WAL lets readers continue while a writer commits; writes remain serial.
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE
            )"""
        )
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES users(id),
                product TEXT NOT NULL CHECK(length(trim(product)) BETWEEN 1 AND 100),
                quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 1000),
                price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 1 AND 99999999),
                total_cents INTEGER NOT NULL CHECK(total_cents = quantity * price_cents),
                created_at TEXT NOT NULL
            )"""
        )
        cursor.executemany(
            """INSERT INTO users (id, name, email) VALUES (?, ?, ?)
               ON CONFLICT(id) DO NOTHING""",
            [
                (1, "Amina Hassan", "amina@example.com"),
                (2, "Daniel Otieno", "daniel@example.com"),
                (3, "Grace Wanjiku", "grace@example.com"),
            ],
        )
