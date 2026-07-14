from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol

from intentir.canonical import canonical_json, content_address, semantic_projection
from intentir.sqlite_projection import (
    RELATIONAL_STORAGE_FORMAT,
    physical_name,
    quote_identifier,
    render_create_table,
    sqlite_projection,
)
from intentir.verifier import normalize_state


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
                schema_json TEXT,
                state_json TEXT NOT NULL,
                storage_format TEXT NOT NULL DEFAULT 'json-v1',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {
            row[1]
            for row in self.connection.execute("PRAGMA table_info(intentir_state)")
        }
        if "schema_json" not in columns:
            self.connection.execute(
                "ALTER TABLE intentir_state ADD COLUMN schema_json TEXT"
            )
        if "storage_format" not in columns:
            self.connection.execute(
                "ALTER TABLE intentir_state ADD COLUMN storage_format TEXT "
                "NOT NULL DEFAULT 'json-v1'"
            )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS intentir_relations (
                module TEXT NOT NULL,
                entity TEXT NOT NULL,
                table_name TEXT NOT NULL UNIQUE,
                projection_id TEXT NOT NULL,
                PRIMARY KEY(module, entity)
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
        stored = self.inspect(ir["module"])
        if stored is None:
            return None

        stored_hash = stored["schemaHash"]
        expected_hash = storage_schema_hash(ir)
        if stored_hash != expected_hash:
            raise StorageError(
                f"database schema mismatch for module {ir['module']}: "
                f"stored {stored_hash}, expected {expected_hash}"
            )
        return stored["state"]

    def inspect(self, module: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT schema_hash, schema_json, state_json, storage_format "
            "FROM intentir_state WHERE module = ?",
            (module,),
        ).fetchone()
        if row is None:
            return None

        stored_hash, schema_json, state_json, storage_format = row
        schema = parse_stored_json(schema_json, module, "schema") if schema_json else None
        if schema is not None and not isinstance(schema, dict):
            raise StorageError(f"database schema for module {module} must be an object")
        if storage_format == RELATIONAL_STORAGE_FORMAT:
            if schema is None:
                raise StorageError(
                    f"relational database schema for module {module} is missing"
                )
            state = self.load_relational_state(module, schema)
        elif storage_format == "json-v1":
            state = parse_stored_json(state_json, module, "state")
        else:
            raise StorageError(
                f"unsupported storage format for module {module}: {storage_format}"
            )
        if not isinstance(state, dict):
            raise StorageError(f"database state for module {module} must be an object")
        return {
            "schemaHash": stored_hash,
            "schema": schema,
            "state": state,
            "storageFormat": storage_format,
        }

    def save(self, ir: dict[str, Any], state: dict[str, Any]) -> None:
        if self.connection.in_transaction:
            self._save(ir, state)
        else:
            with self.transaction():
                self._save(ir, state)

    def _save(self, ir: dict[str, Any], state: dict[str, Any]) -> None:
        schema = storage_schema(ir)
        normalized = normalize_state(ir, state)
        projection = sqlite_projection(ir["module"], schema)
        self.replace_relational_state(ir["module"], projection, normalized)
        self.connection.execute(
            """
            INSERT INTO intentir_state(
                module, schema_hash, schema_json, state_json, storage_format, updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(module) DO UPDATE SET
                schema_hash = excluded.schema_hash,
                schema_json = excluded.schema_json,
                state_json = excluded.state_json,
                storage_format = excluded.storage_format,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                ir["module"],
                storage_schema_hash(ir),
                canonical_json(schema),
                canonical_json({}),
                RELATIONAL_STORAGE_FORMAT,
            ),
        )

    def replace_relational_state(
        self,
        module: str,
        projection: dict[str, Any],
        state: dict[str, list[dict[str, Any]]],
    ) -> None:
        old_relations = [
            {"entity": row[0], "table": row[1]}
            for row in self.connection.execute(
                "SELECT entity, table_name FROM intentir_relations WHERE module = ?",
                (module,),
            )
        ]
        for relation in old_relations:
            expected = physical_name("entity", module, relation["entity"])
            if relation["table"] != expected:
                raise StorageError(
                    f"unsafe relational table metadata for "
                    f"{module}.{relation['entity']}"
                )
            self.connection.execute(
                f"DROP TABLE {quote_identifier(relation['table'])}"
            )
        self.connection.execute(
            "DELETE FROM intentir_relations WHERE module = ?", (module,)
        )

        for entity in projection["entities"]:
            table_name = entity["table"]
            self.connection.execute(
                f"DROP TABLE IF EXISTS {quote_identifier(table_name)}"
            )
            self.connection.execute(render_create_table(entity))
            self.connection.execute(
                "INSERT INTO intentir_relations("
                "module, entity, table_name, projection_id) VALUES (?, ?, ?, ?)",
                (module, entity["entity"], table_name, entity["id"]),
            )
            self.insert_records(entity, state[entity["entity"]])

    def insert_records(
        self, entity: dict[str, Any], records: list[dict[str, Any]]
    ) -> None:
        columns = entity["columns"]
        if not columns:
            statement = (
                f"INSERT INTO {quote_identifier(entity['table'])} DEFAULT VALUES"
            )
            for _record in records:
                self.connection.execute(statement)
            return

        column_sql = ", ".join(
            quote_identifier(column["column"]) for column in columns
        )
        placeholders = ", ".join("?" for _column in columns)
        statement = (
            f"INSERT INTO {quote_identifier(entity['table'])} ({column_sql}) "
            f"VALUES ({placeholders})"
        )
        for record in records:
            values = [
                encode_sqlite_value(record.get(column["field"]), column["type"])
                for column in columns
            ]
            self.connection.execute(statement, values)

    def load_relational_state(
        self, module: str, schema: dict[str, Any]
    ) -> dict[str, list[dict[str, Any]]]:
        projection = sqlite_projection(module, schema)
        stored_relations = {
            row[0]: {"table": row[1], "projectionId": row[2]}
            for row in self.connection.execute(
                "SELECT entity, table_name, projection_id "
                "FROM intentir_relations WHERE module = ?",
                (module,),
            )
        }
        expected_entities = {entity["entity"] for entity in projection["entities"]}
        if set(stored_relations) != expected_entities:
            raise StorageError(
                f"relational metadata mismatch for module {module}"
            )

        state: dict[str, list[dict[str, Any]]] = {}
        for entity in projection["entities"]:
            metadata = stored_relations[entity["entity"]]
            if metadata != {
                "table": entity["table"],
                "projectionId": entity["id"],
            }:
                raise StorageError(
                    f"relational projection mismatch for {module}.{entity['entity']}"
                )
            state[entity["entity"]] = self.select_records(entity)
        return state

    def select_records(self, entity: dict[str, Any]) -> list[dict[str, Any]]:
        columns = entity["columns"]
        if columns:
            selected = ", ".join(
                quote_identifier(column["column"]) for column in columns
            )
        else:
            selected = quote_identifier(entity["orderColumn"])
        statement = (
            f"SELECT {selected} FROM {quote_identifier(entity['table'])} "
            f"ORDER BY {quote_identifier(entity['orderColumn'])}"
        )
        records: list[dict[str, Any]] = []
        for row in self.connection.execute(statement):
            record = {
                column["field"]: decode_sqlite_value(value, column["type"])
                for column, value in zip(columns, row)
                if value is not None
            }
            records.append(record)
        return records

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteStateRepository":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def storage_schema_hash(ir: dict[str, Any]) -> str:
    return content_address(storage_schema(ir))


def storage_schema(ir: dict[str, Any]) -> dict[str, Any]:
    entities = sorted(
        (
            semantic_projection(node)
            for node in ir["nodes"]
            if node["kind"] == "entity"
        ),
        key=lambda entity: entity["name"],
    )
    return {"kind": "storage-schema", "entities": entities}


def empty_storage_schema() -> dict[str, Any]:
    return {"kind": "storage-schema", "entities": []}


def parse_stored_json(source: str, module: str, kind: str) -> Any:
    try:
        return json.loads(source)
    except json.JSONDecodeError as error:
        raise StorageError(
            f"database {kind} for module {module} is not valid JSON"
        ) from error


def encode_sqlite_value(value: Any, type_name: str) -> Any:
    if value is None:
        return None
    if type_name == "Boolean":
        return int(value)
    return value


def decode_sqlite_value(value: Any, type_name: str) -> Any:
    if type_name == "Boolean":
        return bool(value)
    return value
