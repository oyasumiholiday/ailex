from __future__ import annotations

from copy import deepcopy
from typing import Any


MISSING = object()


class PureRuntimeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def verify_ir(ir: dict[str, Any]) -> dict[str, Any]:
    entities = entity_index(ir)
    actions = action_index(ir)
    functions = function_index(ir)
    tests = [node for node in ir["nodes"] if node["kind"] == "test"]

    results = [verify_test(test, entities, actions) for test in tests]
    function_examples = [
        verify_function_example(function, example, functions)
        for function in functions.values()
        for example in function["examples"]
    ]
    passed = sum(1 for result in results if result["ok"])
    examples_passed = sum(1 for result in function_examples if result["ok"])
    summary = {
        "tests": len(results),
        "passed": passed,
        "failed": len(results) - passed,
    }
    if function_examples:
        summary.update(
            {
                "functionExamples": len(function_examples),
                "functionExamplesPassed": examples_passed,
                "functionExamplesFailed": len(function_examples) - examples_passed,
            }
        )
    return {
        "ok": passed == len(results) and examples_passed == len(function_examples),
        "moduleId": ir["moduleId"],
        "canonicalHash": ir["canonicalHash"],
        "summary": summary,
        "tests": results,
        "functionExamples": function_examples,
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


def run_function(
    ir: dict[str, Any], function_name: str, inputs: dict[str, Any]
) -> dict[str, Any]:
    functions = function_index(ir)
    function = functions.get(function_name)
    if function is None:
        raise ValueError(f"unknown function: {function_name}")
    if not isinstance(inputs, dict):
        raise ValueError("function inputs must be a JSON object")

    try:
        result = invoke_function(function, [], inputs, functions, [])
    except PureRuntimeError as error:
        return {
            "ok": False,
            "module": ir["module"],
            "function": function_name,
            "result": None,
            "errors": [
                verification_error(
                    error.code,
                    str(error),
                    f"Function `{function_name}` の実行に失敗しました: {error}",
                    function["id"],
                )
            ],
        }
    return {
        "ok": True,
        "module": ir["module"],
        "function": function_name,
        "result": result,
        "errors": [],
    }


def verify_function_example(
    function: dict[str, Any],
    example: dict[str, Any],
    functions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    try:
        actual = evaluate_pure_expression(example["call"], {}, functions, [])
        expected = example["expected"]["value"]
        ok = actual == expected
        error = None
    except PureRuntimeError as runtime_error:
        actual = None
        expected = example["expected"]["value"]
        ok = False
        error = runtime_error

    errors: list[dict[str, str]] = []
    if not ok:
        code = error.code if error else "function_example_failed"
        message = str(error) if error else f"expected {expected!r}, got {actual!r}"
        errors.append(
            verification_error(
                code,
                message,
                f"Function Example `{example['source']}` が失敗しました: {message}",
                example["id"],
            )
        )
    return {
        "id": example["id"],
        "symbol": function["symbol"],
        "name": example["source"],
        "function": function["name"],
        "ok": ok,
        "actual": actual,
        "expected": expected,
        "errors": errors,
    }


def evaluate_pure_expression(
    expression: dict[str, Any],
    variables: dict[str, Any],
    functions: dict[str, dict[str, Any]],
    stack: list[str],
) -> Any:
    kind = expression.get("kind")
    if kind == "literal":
        return expression["value"]
    if kind == "variable":
        name = expression["name"]
        if name not in variables:
            raise PureRuntimeError(
                "unknown_function_variable", f"unknown function variable {name}"
            )
        return variables[name]
    if kind == "function_call":
        function = functions.get(expression["function"])
        if function is None:
            raise PureRuntimeError(
                "unknown_function", f"unknown function {expression['function']}"
            )
        positional = [
            evaluate_pure_expression(value, variables, functions, stack)
            for value in expression["args"]
        ]
        keywords = {
            item["name"]: evaluate_pure_expression(
                item["value"], variables, functions, stack
            )
            for item in expression["kwargs"]
        }
        return invoke_function(function, positional, keywords, functions, stack)
    if kind == "binary":
        left = evaluate_pure_expression(
            expression["left"], variables, functions, stack
        )
        right = evaluate_pure_expression(
            expression["right"], variables, functions, stack
        )
        try:
            return evaluate_binary(expression["op"], left, right)
        except ZeroDivisionError as error:
            raise PureRuntimeError(
                "pure_division_by_zero", "division by zero"
            ) from error
    if kind == "comparison":
        left = evaluate_pure_expression(
            expression["left"], variables, functions, stack
        )
        right = evaluate_pure_expression(
            expression["right"], variables, functions, stack
        )
        return evaluate_comparison(expression["op"], left, right)
    if kind == "boolean":
        if expression["op"] == "and":
            return all(
                evaluate_pure_expression(value, variables, functions, stack)
                for value in expression["values"]
            )
        return any(
            evaluate_pure_expression(value, variables, functions, stack)
            for value in expression["values"]
        )
    if kind == "unary":
        value = evaluate_pure_expression(
            expression["value"], variables, functions, stack
        )
        if expression["op"] == "not":
            return not value
        if expression["op"] == "negate":
            return -value
        return +value
    if kind == "conditional":
        condition = evaluate_pure_expression(
            expression["condition"], variables, functions, stack
        )
        branch = expression["then"] if condition else expression["else"]
        return evaluate_pure_expression(branch, variables, functions, stack)
    raise PureRuntimeError(
        "unknown_pure_expression", f"unknown pure expression kind {kind}"
    )


def invoke_function(
    function: dict[str, Any],
    positional: list[Any],
    keywords: dict[str, Any],
    functions: dict[str, dict[str, Any]],
    stack: list[str],
) -> Any:
    name = function["name"]
    if name in stack or len(stack) >= 100:
        raise PureRuntimeError(
            "recursive_function_cycle", f"recursive function call detected: {name}"
        )
    inputs = function["inputs"]
    if len(positional) > len(inputs):
        raise PureRuntimeError(
            "too_many_function_arguments",
            f"function {name} received too many positional arguments",
        )

    values = {
        field["name"]: value for field, value in zip(inputs, positional)
    }
    input_map = {field["name"]: field for field in inputs}
    for input_name, value in keywords.items():
        if input_name not in input_map:
            raise PureRuntimeError(
                "unknown_function_argument",
                f"function {name} has no input {input_name}",
            )
        if input_name in values:
            raise PureRuntimeError(
                "duplicate_function_argument",
                f"function {name} input {input_name} is passed more than once",
            )
        values[input_name] = value

    for field in inputs:
        input_name = field["name"]
        if input_name not in values and "default" in field:
            values[input_name] = deepcopy(field["default"])
        if input_name not in values:
            raise PureRuntimeError(
                "missing_function_argument",
                f"function {name} requires input {input_name}",
            )
        if not value_matches_type(values[input_name], field["type"]):
            raise PureRuntimeError(
                "function_argument_type_mismatch",
                f"function {name} input {input_name} must be {field['type']}",
            )

    result = evaluate_pure_expression(
        function["body"]["expression"], values, functions, [*stack, name]
    )
    if not value_matches_type(result, function["returnType"]):
        raise PureRuntimeError(
            "function_return_type_mismatch",
            f"function {name} returned a value incompatible with {function['returnType']}",
        )
    return result


def evaluate_binary(operator: str, left: Any, right: Any) -> Any:
    if operator == "add":
        return left + right
    if operator == "subtract":
        return left - right
    if operator == "multiply":
        return left * right
    if operator == "divide":
        return left / right
    if operator == "floor_divide":
        return left // right
    if operator == "modulo":
        return left % right
    raise PureRuntimeError("unknown_pure_operator", f"unknown binary operator {operator}")


def evaluate_comparison(operator: str, left: Any, right: Any) -> bool:
    if operator == "equal":
        return left == right
    if operator == "not_equal":
        return left != right
    if operator == "less_than":
        return left < right
    if operator == "less_than_or_equal":
        return left <= right
    if operator == "greater_than":
        return left > right
    if operator == "greater_than_or_equal":
        return left >= right
    raise PureRuntimeError(
        "unknown_pure_operator", f"unknown comparison operator {operator}"
    )


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


def function_index(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        node["name"]: node for node in ir["nodes"] if node["kind"] == "function"
    }


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
