from __future__ import annotations

from typing import Any

from intentir.canonical import content_address


SQLITE_PROJECTION_VERSION = "1.0.0"
RELATIONAL_STORAGE_FORMAT = "relational-v1"


def sqlite_projection(
    module: str, schema: dict[str, Any]
) -> dict[str, Any]:
    if schema.get("kind") != "storage-schema":
        raise ValueError("invalid storage schema")

    entities = [
        project_entity(module, entity)
        for entity in sorted(schema.get("entities", []), key=lambda item: item["name"])
    ]
    payload: dict[str, Any] = {
        "schemaVersion": SQLITE_PROJECTION_VERSION,
        "kind": "sqlite-projection",
        "storageFormat": RELATIONAL_STORAGE_FORMAT,
        "module": module,
        "entities": entities,
    }
    payload["id"] = content_address(payload)
    return payload


def project_entity(module: str, entity: dict[str, Any]) -> dict[str, Any]:
    fields = sorted(entity.get("fields", []), key=lambda item: item["name"])
    order_column = internal_order_column({field["name"] for field in fields})
    columns = [project_field(module, field) for field in fields]
    payload = {
        "kind": "sqlite-entity",
        "entity": entity["name"],
        "table": physical_name("entity", module, entity["name"]),
        "orderColumn": order_column,
        "columns": columns,
    }
    return {"id": content_address(payload), **payload}


def project_field(module: str, field: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "field": field["name"],
        "column": field["name"],
        "type": field["type"],
        "sqliteType": sqlite_type(field["type"]),
        "nullable": not field.get("required", False),
        "unique": bool(field.get("unique", False)),
        "key": bool(field.get("key", False)),
    }
    if "default" in field:
        payload["default"] = field["default"]
    if "references" in field:
        reference = field["references"]
        payload["references"] = {
            "entity": reference["entity"],
            "field": reference["field"],
            "table": physical_name("entity", module, reference["entity"]),
            "column": reference["field"],
        }
    return {"id": content_address(payload), **payload}


def render_sqlite_ddl(module: str, schema: dict[str, Any]) -> str:
    projection = sqlite_projection(module, schema)
    lines = [
        f"-- IntentIR SQLite projection {projection['id']}",
        f"-- module: {module}",
    ]
    for entity in order_projection_entities(projection["entities"]):
        lines.extend(
            ("", f"-- entity: {entity['entity']}", render_create_table(entity) + ";")
        )
    return "\n".join(lines) + "\n"


def render_create_table(entity: dict[str, Any]) -> str:
    definitions = [
        f"  {quote_identifier(entity['orderColumn'])} INTEGER PRIMARY KEY"
    ]
    for column in entity["columns"]:
        definitions.append("  " + render_column(column))
    body = ",\n".join(definitions)
    return f"CREATE TABLE {quote_identifier(entity['table'])} (\n{body}\n)"


def render_column(column: dict[str, Any]) -> str:
    name = quote_identifier(column["column"])
    parts = [name, column["sqliteType"]]
    if not column["nullable"]:
        parts.append("NOT NULL")
    if "default" in column:
        parts.append(f"DEFAULT {sqlite_literal(column['default'])}")
    if column["unique"]:
        parts.append("UNIQUE")
    parts.append(sqlite_type_check(name, column["type"]))
    if "references" in column:
        reference = column["references"]
        parts.extend(
            [
                "REFERENCES",
                quote_identifier(reference["table"]),
                f"({quote_identifier(reference['column'])})",
                "ON UPDATE RESTRICT",
                "ON DELETE RESTRICT",
            ]
        )
    return " ".join(parts)


def order_projection_entities(
    entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_name = {entity["entity"]: entity for entity in entities}
    dependencies = {
        name: {
            column["references"]["entity"]
            for column in entity["columns"]
            if "references" in column
            and column["references"]["entity"] in by_name
        }
        for name, entity in by_name.items()
    }
    ordered: list[dict[str, Any]] = []
    completed: set[str] = set()
    while len(completed) < len(by_name):
        ready = sorted(
            name
            for name, targets in dependencies.items()
            if name not in completed and targets <= completed
        )
        if not ready:
            unresolved = ", ".join(sorted(set(by_name) - completed))
            raise ValueError(f"cyclic SQLite entity references: {unresolved}")
        for name in ready:
            ordered.append(by_name[name])
            completed.add(name)
    return ordered


def sqlite_type(type_name: str) -> str:
    if type_name in {"Text", "UUID"}:
        return "TEXT"
    if type_name in {"Boolean", "Integer"}:
        return "INTEGER"
    if type_name == "Number":
        return "NUMERIC"
    raise ValueError(f"unsupported SQLite field type: {type_name}")


def sqlite_type_check(column: str, type_name: str) -> str:
    if type_name in {"Text", "UUID"}:
        predicate = f"typeof({column}) = 'text'"
    elif type_name == "Boolean":
        predicate = f"typeof({column}) = 'integer' AND {column} IN (0, 1)"
    elif type_name == "Integer":
        predicate = f"typeof({column}) = 'integer'"
    elif type_name == "Number":
        predicate = f"typeof({column}) IN ('integer', 'real')"
    else:
        raise ValueError(f"unsupported SQLite field type: {type_name}")
    return f"CHECK ({column} IS NULL OR ({predicate}))"


def sqlite_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise ValueError(f"unsupported SQLite default: {value!r}")


def physical_name(kind: str, module: str, name: str) -> str:
    digest = content_address(
        {"kind": f"sqlite-{kind}", "module": module, "name": name}
    ).removeprefix("sha256:")
    return f"intentir_{kind}_{digest}"


def internal_order_column(field_names: set[str]) -> str:
    candidate = "__intentir_order__"
    while candidate in field_names:
        candidate = "_" + candidate
    return candidate


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
