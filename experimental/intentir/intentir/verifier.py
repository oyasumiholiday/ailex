from __future__ import annotations

from copy import deepcopy
from typing import Any


MISSING = object()


def verify_ir(ir: dict[str, Any]) -> dict[str, Any]:
    entities = entity_index(ir)
    actions = action_index(ir)
    tests = [node for node in ir["nodes"] if node["kind"] == "test"]

    results = [verify_test(test, entities, actions) for test in tests]
    passed = sum(1 for result in results if result["ok"])
    return {
        "ok": passed == len(results),
        "moduleId": ir["moduleId"],
        "canonicalHash": ir["canonicalHash"],
        "summary": {
            "tests": len(results),
            "passed": passed,
            "failed": len(results) - passed,
        },
        "tests": results,
    }


def run_action(
    ir: dict[str, Any],
    action_name: str,
    inputs: dict[str, Any],
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entities = entity_index(ir)
    actions = action_index(ir)
    action = actions.get(action_name)
    if not action:
        raise ValueError(f"unknown action: {action_name}")
    if not isinstance(inputs, dict):
        raise ValueError("action inputs must be a JSON object")

    store = create_store(entities, state)
    checks: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    result = execute_action(action, inputs, store, entities, checks, errors)
    return {
        "ok": result is not None and not errors,
        "module": ir["module"],
        "action": action_name,
        "checks": checks,
        "errors": errors,
        "state": store,
        "created": result["created"] if result else {},
        "affected": result["affected"] if result else {},
    }


def normalize_state(
    ir: dict[str, Any], state: dict[str, Any] | None = None
) -> dict[str, list[dict[str, Any]]]:
    return create_store(entity_index(ir), state)


def verify_test(
    test: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    actions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    store = create_store(entities)
    checks: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for step_index, call in enumerate(test["steps"]):
        action = actions[call["action"]]
        inputs = {arg["name"]: arg["value"]["value"] for arg in call["args"]}
        result = execute_action(
            action,
            inputs,
            store,
            entities,
            checks,
            errors,
            step_index=step_index,
        )
        if result is None:
            break

    if not errors:
        for expected in test["expects"]:
            ok = evaluate_expectation(expected["expectation"], store)
            checks.append(
                {
                    "id": expected["id"],
                    "kind": "expectation",
                    "source": expected["source"],
                    "ok": ok,
                }
            )
            if not ok:
                errors.append(
                    verification_error(
                        "expectation_failed",
                        f"expectation failed: {expected['source']}",
                        f"期待式を満たしませんでした: `{expected['source']}`",
                        expected["id"],
                    )
                )

    return {
        "id": test["id"],
        "symbol": test["symbol"],
        "name": test["name"],
        "ok": not errors,
        "checks": checks,
        "errors": errors,
        "finalState": store,
    }


def execute_action(
    action: dict[str, Any],
    raw_inputs: dict[str, Any],
    store: dict[str, list[dict[str, Any]]],
    entities: dict[str, dict[str, Any]],
    checks: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    step_index: int | None = None,
) -> dict[str, dict[str, dict[str, Any]]] | None:
    inputs = prepare_inputs(action, raw_inputs, errors)
    if inputs is None:
        return None

    working = deepcopy(store)
    created: dict[str, dict[str, Any]] = {}
    affected: dict[str, dict[str, Any]] = {}

    for requirement in action["requires"]:
        ok = evaluate_condition(requirement["condition"], inputs, created, affected)
        append_check(
            checks, requirement, "precondition", ok, action["name"], step_index
        )
        if not ok:
            errors.append(
                verification_error(
                    "precondition_failed",
                    f"precondition failed: {requirement['source']}",
                    f"事前条件を満たしませんでした: `{requirement['source']}`",
                    requirement["id"],
                )
            )
            return None

    for effect_node in action["effects"]:
        effect = effect_node["effect"]
        result = apply_effect(effect, inputs, working, entities)
        ok = result["ok"]
        append_check(checks, effect_node, "effect", ok, action["name"], step_index)
        if not ok:
            errors.append(
                verification_error(
                    result["code"],
                    result["message"],
                    result["messageJa"],
                    effect_node["id"],
                )
            )
            return None
        if result.get("record") is not None:
            entity_name = effect["entity"]
            affected[entity_name] = result["record"]
            if effect["op"] == "insert":
                created[entity_name] = result["record"]

    for ensure in action["ensures"]:
        ok = evaluate_condition(ensure["condition"], inputs, created, affected)
        append_check(checks, ensure, "postcondition", ok, action["name"], step_index)
        if not ok:
            errors.append(
                verification_error(
                    "postcondition_failed",
                    f"postcondition failed: {ensure['source']}",
                    f"事後条件を満たしませんでした: `{ensure['source']}`",
                    ensure["id"],
                )
            )

    if errors:
        return None
    store.clear()
    store.update(working)
    return {"created": created, "affected": affected}


def apply_effect(
    effect: dict[str, Any],
    inputs: dict[str, Any],
    store: dict[str, list[dict[str, Any]]],
    entities: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    entity_name = effect["entity"]
    if effect["op"] == "insert":
        record: dict[str, Any] = {}
        entity = entities[entity_name]
        for field in entity["fields"]:
            if field["name"] in inputs:
                record[field["name"]] = inputs[field["name"]]
            elif "default" in field:
                record[field["name"]] = deepcopy(field["default"])
            elif field["required"]:
                return effect_error(
                    "missing_effect_value",
                    f"insert {entity_name} cannot populate required field {field['name']}",
                    f"`insert {entity_name}` は必須 Field `{field['name']}` を生成できません。",
                )
        conflict = unique_conflict(entity, store[entity_name], record)
        if conflict:
            return uniqueness_error(entity_name, conflict)
        store[entity_name].append(record)
        return {"ok": True, "record": record}

    records = store[entity_name]
    matches = [
        index
        for index, record in enumerate(records)
        if evaluate_condition(effect["where"], inputs, {}, {}, record)
    ]
    if not matches:
        return effect_error(
            "effect_target_not_found",
            f"{effect['op']} {entity_name} matched no records",
            f"`{effect['op']} {entity_name}` の対象が見つかりませんでした。",
        )
    if len(matches) > 1:
        return effect_error(
            "effect_target_not_unique",
            f"{effect['op']} {entity_name} matched {len(matches)} records",
            f"`{effect['op']} {entity_name}` の対象が {len(matches)} 件あり、一意に決まりません。",
        )

    index = matches[0]
    record = records[index]
    if effect["op"] == "update":
        entity = entities[entity_name]
        fields = {field["name"]: field for field in entity["fields"]}
        updated = deepcopy(record)
        for assignment in effect["set"]:
            field_name = assignment["field"]
            value = resolve_value(
                assignment["value"], inputs, {}, {}, record
            )
            if fields[field_name].get("key") and value != record.get(field_name):
                return effect_error(
                    "key_update_not_allowed",
                    f"update {entity_name} cannot change key field {field_name}",
                    f"`update {entity_name}` はKey Field `{field_name}` を変更できません。",
                )
            updated[field_name] = value
        conflict = unique_conflict(entity, records, updated, ignore_index=index)
        if conflict:
            return uniqueness_error(entity_name, conflict)
        records[index] = updated
        return {"ok": True, "record": updated}

    deleted = records.pop(index)
    return {"ok": True, "record": deleted}


def prepare_inputs(
    action: dict[str, Any],
    raw_inputs: dict[str, Any],
    errors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    specs = {field["name"]: field for field in action["inputs"]}
    unknown = sorted(set(raw_inputs) - set(specs))
    if unknown:
        errors.append(
            verification_error(
                "unknown_runtime_input",
                f"action {action['name']} received unknown inputs: {', '.join(unknown)}",
                f"Action `{action['name']}` に未定義の Input が渡されました: `{', '.join(unknown)}`",
                action["id"],
            )
        )
        return None

    inputs = dict(raw_inputs)
    for name, spec in specs.items():
        if name not in inputs and "default" in spec:
            inputs[name] = deepcopy(spec["default"])
        if name not in inputs and spec["required"]:
            errors.append(
                verification_error(
                    "missing_runtime_input",
                    f"action {action['name']} requires input {name}",
                    f"Action `{action['name']}` に必須 Input `{name}` がありません。",
                    action["id"],
                )
            )
        elif name in inputs and not value_matches_type(inputs[name], spec["type"]):
            errors.append(
                verification_error(
                    "runtime_input_type_mismatch",
                    f"input {name} must be {spec['type']}",
                    f"Input `{name}` は `{spec['type']}` 型である必要があります。",
                    action["id"],
                )
            )
    return None if errors else inputs


def create_store(
    entities: dict[str, dict[str, Any]],
    state: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if state is None:
        return {name: [] for name in sorted(entities)}
    if not isinstance(state, dict):
        raise ValueError("state must be a JSON object")
    unknown_entities = sorted(set(state) - set(entities))
    if unknown_entities:
        raise ValueError(f"state contains unknown entities: {', '.join(unknown_entities)}")

    store: dict[str, list[dict[str, Any]]] = {}
    for entity_name, entity in sorted(entities.items()):
        records = state.get(entity_name, [])
        if not isinstance(records, list):
            raise ValueError(f"state.{entity_name} must be an array")
        fields = {field["name"]: field for field in entity["fields"]}
        normalized: list[dict[str, Any]] = []
        for index, source_record in enumerate(records):
            if not isinstance(source_record, dict):
                raise ValueError(f"state.{entity_name}[{index}] must be an object")
            unknown_fields = sorted(set(source_record) - set(fields))
            if unknown_fields:
                raise ValueError(
                    f"state.{entity_name}[{index}] contains unknown fields: "
                    f"{', '.join(unknown_fields)}"
                )
            record = deepcopy(source_record)
            for field_name, field in fields.items():
                if field_name not in record and "default" in field:
                    record[field_name] = deepcopy(field["default"])
                if field_name not in record and field["required"]:
                    raise ValueError(
                        f"state.{entity_name}[{index}] is missing required field {field_name}"
                    )
                if field_name in record and not value_matches_type(
                    record[field_name], field["type"]
                ):
                    raise ValueError(
                        f"state.{entity_name}[{index}].{field_name} must be {field['type']}"
                    )
            conflict = unique_conflict(entity, normalized, record)
            if conflict:
                raise ValueError(
                    f"state.{entity_name}[{index}].{conflict} violates a unique constraint"
                )
            normalized.append(record)
        store[entity_name] = normalized
    return store


def unique_conflict(
    entity: dict[str, Any],
    records: list[dict[str, Any]],
    candidate: dict[str, Any],
    ignore_index: int | None = None,
) -> str | None:
    for field in entity["fields"]:
        if not field.get("unique") or field["name"] not in candidate:
            continue
        field_name = field["name"]
        value = candidate[field_name]
        for index, record in enumerate(records):
            if index != ignore_index and record.get(field_name, MISSING) == value:
                return field_name
    return None


def uniqueness_error(entity_name: str, field_name: str) -> dict[str, Any]:
    return effect_error(
        "unique_constraint_violation",
        f"{entity_name}.{field_name} must be unique",
        f"Field `{entity_name}.{field_name}` の一意制約に違反しました。",
    )


def evaluate_expectation(
    expectation: dict[str, Any],
    store: dict[str, list[dict[str, Any]]],
) -> bool:
    records = store.get(expectation["entity"], [])
    kind = expectation["kind"]
    if kind == "entity_count":
        return len(records) == expectation["count"]
    where = expectation.get("where")
    matched = bool(records) if not where else any(
        evaluate_condition(where, {}, {}, {}, record) for record in records
    )
    return not matched if kind == "entity_not_exists" else matched


def evaluate_condition(
    condition: dict[str, Any],
    inputs: dict[str, Any],
    created: dict[str, dict[str, Any]],
    affected: dict[str, dict[str, Any]],
    record: dict[str, Any] | None = None,
) -> bool:
    kind = condition.get("kind")
    if kind == "not_empty":
        value = resolve_value(condition["target"], inputs, created, affected, record)
        return isinstance(value, str) and len(value) > 0
    if kind == "equals":
        left = resolve_value(condition["left"], inputs, created, affected, record)
        right = resolve_value(condition["right"], inputs, created, affected, record)
        return left is not MISSING and right is not MISSING and left == right
    return False


def resolve_value(
    expression: dict[str, Any],
    inputs: dict[str, Any],
    created: dict[str, dict[str, Any]],
    affected: dict[str, dict[str, Any]],
    record: dict[str, Any] | None,
) -> Any:
    kind = expression.get("kind")
    if kind == "literal":
        return expression.get("value")
    if kind == "input":
        return inputs.get(expression["name"], MISSING)
    if kind == "created_field":
        entity = created.get(expression["entity"])
        return entity.get(expression["field"], MISSING) if entity else MISSING
    if kind == "affected_field":
        entity = affected.get(expression["entity"])
        return entity.get(expression["field"], MISSING) if entity else MISSING
    if kind == "entity_field" and record is not None:
        return record.get(expression["field"], MISSING)
    return MISSING


def append_check(
    checks: list[dict[str, Any]],
    node: dict[str, Any],
    kind: str,
    ok: bool,
    action_name: str,
    step_index: int | None,
) -> None:
    check = {
        "id": node["id"],
        "kind": kind,
        "source": node["source"],
        "action": action_name,
        "ok": ok,
    }
    if step_index is not None:
        check["step"] = step_index
    checks.append(check)


def value_matches_type(value: Any, type_name: str) -> bool:
    if type_name in {"Text", "UUID"}:
        return isinstance(value, str)
    if type_name == "Boolean":
        return isinstance(value, bool)
    if type_name == "Integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "Number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def entity_index(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["name"]: node for node in ir["nodes"] if node["kind"] == "entity"}


def action_index(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["name"]: node for node in ir["nodes"] if node["kind"] == "action"}


def effect_error(code: str, message: str, message_ja: str) -> dict[str, Any]:
    return {"ok": False, "code": code, "message": message, "messageJa": message_ja}


def verification_error(
    code: str,
    message: str,
    message_ja: str,
    obligation_id: str,
) -> dict[str, str]:
    return {
        "code": code,
        "message": message,
        "messageJa": message_ja,
        "obligationId": obligation_id,
    }
