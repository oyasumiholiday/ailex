from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol

from intentir.canonical import canonical_json, content_address, semantic_projection


class StorageError(ValueError):
    pass


class StateRepository(Protocol):
    def load(self, ir: dict[str, Any]) -> dict[str, Any] | None: ...

    def save(self, ir: dict[str, Any], state: dict[str, Any]) -> None: ...


class SQLiteStateRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS intentir_state (
                module TEXT PRIMARY KEY,
                schema_hash TEXT NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    @contextmanager
    def transaction(self) -> Iterator["SQLiteStateRepository"]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    def load(self, ir: dict[str, Any]) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT schema_hash, state_json FROM intentir_state WHERE module = ?",
            (ir["module"],),
        ).fetchone()
        if row is None:
            return None

        stored_hash, state_json = row
        expected_hash = storage_schema_hash(ir)
        if stored_hash != expected_hash:
            raise StorageError(
                f"database schema mismatch for module {ir['module']}: "
                f"stored {stored_hash}, expected {expected_hash}"
            )
        try:
            state = json.loads(state_json)
        except json.JSONDecodeError as error:
            raise StorageError(
                f"database state for module {ir['module']} is not valid JSON"
            ) from error
        if not isinstance(state, dict):
            raise StorageError(
                f"database state for module {ir['module']} must be an object"
            )
        return state

    def save(self, ir: dict[str, Any], state: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT INTO intentir_state(module, schema_hash, state_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(module) DO UPDATE SET
                schema_hash = excluded.schema_hash,
                state_json = excluded.state_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                ir["module"],
                storage_schema_hash(ir),
                canonical_json(state),
            ),
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteStateRepository":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def storage_schema_hash(ir: dict[str, Any]) -> str:
    entities = sorted(
        (
            semantic_projection(node)
            for node in ir["nodes"]
            if node["kind"] == "entity"
        ),
        key=lambda entity: entity["name"],
    )
    return content_address({"kind": "storage-schema", "entities": entities})
