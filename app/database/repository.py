"""SQLite-backed repository used by all pharmacy tools.

The previous demo kept a process-local dictionary of fabricated records.  This
repository deliberately starts empty and persists real application records in
SQLite.  It retains the small mapping interface used by the existing tools so
the tool contracts remain stable while every mutation is durable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Iterator


_COLLECTIONS = (
    "users", "products", "pharmacies", "inventory", "carts", "cart_items",
    "orders", "doctors", "appointments", "prescriptions", "household_members",
    "pharmacists", "merchants", "merchant_products", "merchant_inventory",
    "merchant_orders",
)


class SQLiteRepository(MutableMapping[str, list[dict[str, Any]]]):
    """Durable JSON-row collections backed by SQLite.

    This is intentionally a compatibility repository while the existing tools
    are incrementally moved to query-specific methods.  Unlike the retired
    mock data module, there is no fixture data or in-memory source of truth.
    """

    def __init__(self, database_url: str | None = None) -> None:
        database_url = database_url or os.getenv("DATABASE_URL", "sqlite:///./data/pharmacy.db")
        if not database_url.startswith("sqlite:///"):
            raise RuntimeError("Only sqlite:/// DATABASE_URL values are supported by this build")
        self.path = Path(database_url.removeprefix("sqlite:///"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS application_collections ("
            "name TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        self._connection.commit()
        self._data = {name: self._load(name) for name in _COLLECTIONS}

    def _load(self, name: str) -> list[dict[str, Any]]:
        row = self._connection.execute(
            "SELECT payload FROM application_collections WHERE name = ?", (name,)
        ).fetchone()
        return json.loads(row[0]) if row else []

    def save(self) -> None:
        """Atomically persist all collections after a tool mutation."""
        with self._lock, self._connection:
            self._connection.executemany(
                "INSERT INTO application_collections(name, payload, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP",
                [(name, json.dumps(rows, separators=(",", ":"))) for name, rows in self._data.items()],
            )

    def __getitem__(self, key: str) -> list[dict[str, Any]]:
        return self._data[key]

    def __setitem__(self, key: str, value: list[dict[str, Any]]) -> None:
        self._data[key] = value
        self.save()

    def __delitem__(self, key: str) -> None:
        raise TypeError("Application collections cannot be deleted")

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


database = SQLiteRepository()
