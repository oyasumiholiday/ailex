from __future__ import annotations

from copy import deepcopy
from typing import Any

from intentir.canonical import content_address
from intentir.storage import storage_schema, storage_schema_hash


MIGRATION_SCHEMA_VERSION = "0.1.0"


class MigrationError(ValueError):
    pass


def plan_migration(
    source_schema: dict[str, Any],
    target_ir: dict[str, Any],
    *,
    source_present: bool = True,
) -> dict[str, Any]:
    target_schema = storage_schema(target_ir)
    source_entities = entity_map(source_schema)
    target_entities = entity_map(target_schema)
    operations: list[dict[str, Any]] = []

    for entity_name in sorted(set(source_entities) - set(target_entities)):
        operations.append(
            migration_operation(
                "remove_entity",
                entity_name,
                safety="destructive",
                before=source_entities[entity_name],
                description=f"Remove entity {entity_name} and all stored records.",
                description_ja=f"Entity `{entity_name}` と保存済みレコードを削除します。",
            )
        )

    for entity_name in sorted(set(target_entities) - set(source_entities)):
        operations.append(
            migration_operation(
                "add_entity",
                entity_name,
                safety="safe",
                after=target_entities[entity_name],
                description=f"Add empty entity collection {entity_name}.",
                description_ja=f"空のEntity Collection `{entity_name}` を追加します。",
            )
        )

    for entity_name in sorted(set(source_entities) & set(target_entities)):
        source_fields = field_map(source_entities[entity_name])
        target_fields = field_map(target_entities[entity_name])
        for field_name in sorted(set(source_fields) - set(target_fields)):
            operations.append(
                migration_operation(
                    "remove_field",
                    entity_name,
                    field=field_name,
                    safety="destructive",
                    before=source_fields[field_name],
                    description=f"Remove field {entity_name}.{field_name} from all records.",
                    description_ja=f"全レコードからField `{entity_name}.{field_name}` を削除します。",
                )
            )
        for field_name in sorted(set(target_fields) - set(source_fields)):
            field = target_fields[field_name]
            safety = (
                "manual"
                if field.get("required") and "default" not in field
                else "safe"
            )
            operations.append(
                migration_operation(
                    "add_field",
                    entity_name,
                    field=field_name,
                    safety=safety,
                    after=field,
                    description=add_field_description(entity_name, field),
                    description_ja=add_field_description_ja(entity_name, field),
                )
            )
        for field_name in sorted(set(source_fields) & set(target_fields)):
            before = source_fields[field_name]
            after = target_fields[field_name]
            if before == after:
                continue
            safety = classify_field_change(before, after)
            operations.append(
                migration_operation(
                    "alter_field",
                    entity_name,
                    field=field_name,
                    safety=safety,
                    before=before,
                    after=after,
                    description=f"Change field definition {entity_name}.{field_name}.",
                    description_ja=f"Field `{entity_name}.{field_name}` の定義を変更します。",
                )
            )

    summary = {
        safety: sum(1 for operation in operations if operation["safety"] == safety)
        for safety in ("safe", "destructive", "manual")
    }
    payload: dict[str, Any] = {
        "schemaVersion": MIGRATION_SCHEMA_VERSION,
        "kind": "migration_plan",
        "module": target_ir["module"],
        "fromSchemaHash": content_address(source_schema) if source_present else None,
        "toSchemaHash": storage_schema_hash(target_ir),
        "operations": operations,
        "summary": summary,
        "applicable": summary["manual"] == 0,
        "requiresDestructiveApproval": summary["destructive"] > 0,
    }
    payload["id"] = content_address(payload)
    return payload


def apply_migration(
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    allow_destructive: bool = False,
) -> dict[str, Any]:
    manual = [
        operation for operation in plan["operations"] if operation["safety"] == "manual"
    ]
    if manual:
        paths = ", ".join(operation_path(operation) for operation in manual)
        raise MigrationError(f"migration requires manual values for: {paths}")
    destructive = [
        operation
        for operation in plan["operations"]
        if operation["safety"] == "destructive"
    ]
    if destructive and not allow_destructive:
        paths = ", ".join(operation_path(operation) for operation in destructive)
        raise MigrationError(
            f"migration contains destructive operations for: {paths}; "
            "pass --allow-destructive to apply"
        )

    migrated = deepcopy(state)
    for operation in plan["operations"]:
        entity_name = operation["entity"]
        op = operation["op"]
        if op == "add_entity":
            migrated.setdefault(entity_name, [])
        elif op == "remove_entity":
            migrated.pop(entity_name, None)
        elif op == "add_field":
            add_field(migrated, operation)
        elif op == "remove_field":
            for record in migrated.get(entity_name, []):
                record.pop(operation["field"], None)
        elif op == "alter_field":
            add_default_to_missing_values(migrated, operation)
        else:
            raise MigrationError(f"unsupported migration operation: {op}")
    return migrated


def entity_map(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if schema.get("kind") != "storage-schema":
        raise MigrationError("invalid storage schema")
    return {entity["name"]: entity for entity in schema.get("entities", [])}


def field_map(entity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {field["name"]: field for field in entity.get("fields", [])}


def migration_operation(
    op: str,
    entity: str,
    *,
    safety: str,
    description: str,
    description_ja: str,
    field: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "op": op,
        "entity": entity,
        "safety": safety,
        "description": description,
        "descriptionJa": description_ja,
    }
    if field is not None:
        payload["field"] = field
    if before is not None:
        payload["before"] = before
    if after is not None:
        payload["after"] = after
    return {"id": content_address(payload), **payload}


def classify_field_change(before: dict[str, Any], after: dict[str, Any]) -> str:
    if before.get("type") != after.get("type"):
        return "manual"
    if not before.get("required") and after.get("required") and "default" not in after:
        return "manual"
    return "safe"


def add_field_description(entity_name: str, field: dict[str, Any]) -> str:
    path = f"{entity_name}.{field['name']}"
    if "default" in field:
        return f"Add field {path} and fill existing records with its default."
    if field.get("required"):
        return f"Add required field {path}; existing records need explicit values."
    return f"Add optional field {path}."


def add_field_description_ja(entity_name: str, field: dict[str, Any]) -> str:
    path = f"{entity_name}.{field['name']}"
    if "default" in field:
        return f"Field `{path}` を追加し、既存レコードをdefaultで補完します。"
    if field.get("required"):
        return f"必須Field `{path}` の追加には既存レコードの値が必要です。"
    return f"任意Field `{path}` を追加します。"


def add_field(state: dict[str, Any], operation: dict[str, Any]) -> None:
    field = operation["after"]
    if field.get("required") and "default" not in field:
        raise MigrationError(
            f"field {operation_path(operation)} requires explicit values"
        )
    if "default" in field:
        for record in state.get(operation["entity"], []):
            record.setdefault(operation["field"], deepcopy(field["default"]))


def add_default_to_missing_values(
    state: dict[str, Any], operation: dict[str, Any]
) -> None:
    field = operation["after"]
    if "default" not in field:
        return
    for record in state.get(operation["entity"], []):
        record.setdefault(operation["field"], deepcopy(field["default"]))


def operation_path(operation: dict[str, Any]) -> str:
    if "field" in operation:
        return f"{operation['entity']}.{operation['field']}"
    return operation["entity"]
