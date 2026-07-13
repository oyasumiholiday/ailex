from __future__ import annotations

import json
from typing import Any


TYPE_MAP = {
    "Boolean": "boolean",
    "Text": "string",
    "UUID": "string",
    "Number": "number",
    "Integer": "number",
}


def generate_typescript(ir: dict[str, Any]) -> str:
    module = ir["module"]
    entity_nodes = [node for node in ir["nodes"] if node["kind"] == "entity"]
    entities_by_name = {node["name"]: node for node in entity_nodes}
    action_nodes = [node for node in ir["nodes"] if node["kind"] == "action"]
    test_nodes = [node for node in ir["nodes"] if node["kind"] == "test"]

    lines: list[str] = [
        f"// Generated from IntentIR module {module} ({ir['canonicalHash']}).",
        "",
    ]
    for entity in entity_nodes:
        lines.extend(render_entity(entity))
        lines.append("")

    lines.extend(render_store(entity_nodes))
    lines.append("")
    for action in action_nodes:
        lines.extend(render_action(action, entities_by_name))
        lines.append("")
    lines.extend(render_test_runner(test_nodes, entities_by_name))
    return "\n".join(lines).rstrip() + "\n"


def render_entity(entity: dict[str, Any]) -> list[str]:
    lines = [f"export type {entity['name']} = {{"]
    for field in entity["fields"]:
        optional = "" if field.get("required") or "default" in field else "?"
        lines.append(f"  {field['name']}{optional}: {ts_type(field['type'])};")
    lines.append("};")
    return lines


def render_store(entities: list[dict[str, Any]]) -> list[str]:
    if not entities:
        return [
            "export type Store = Record<string, never>;",
            "export function createStore(): Store { return {}; }",
        ]
    lines = ["export type Store = {"]
    for entity in entities:
        lines.append(f"  {camel_plural(entity['name'])}: {entity['name']}[];")
    lines.extend(["};", "", "export function createStore(): Store {", "  return {"])
    for entity in entities:
        lines.append(f"    {camel_plural(entity['name'])}: [],")
    lines.extend(["  };", "}"])
    return lines


def render_action(
    action: dict[str, Any],
    entities_by_name: dict[str, dict[str, Any]],
) -> list[str]:
    input_type = f"{action['name']}Input"
    lines = [f"export type {input_type} = {{"]
    for field in action["inputs"]:
        optional = "" if field.get("required") and "default" not in field else "?"
        lines.append(f"  {field['name']}{optional}: {ts_type(field['type'])};")
    lines.extend(
        [
            "};",
            "",
            f"export function {action['name']}(store: Store, input: {input_type}): Store {{",
        ]
    )

    defaults = {
        field["name"]: field["default"]
        for field in action["inputs"]
        if "default" in field
    }
    default_entries = ", ".join(
        f"{name}: {ts_literal(value)}" for name, value in defaults.items()
    )
    prefix = f"{{ {default_entries}, ...input }}" if defaults else "{ ...input }"
    lines.append(f"  const resolvedInput = {prefix};")

    for requirement in action["requires"]:
        expression = render_condition(requirement["condition"])
        lines.extend(
            [
                f"  if (!({expression})) {{",
                f"    throw new Error({ts_literal('precondition failed: ' + requirement['source'])});",
                "  }",
            ]
        )

    lines.append("  let nextStore = store;")
    created_entities = sorted(
        {
            effect["effect"]["entity"]
            for effect in action["effects"]
            if effect["effect"]["op"] == "insert"
        }
    )
    affected_entities = sorted(
        {effect["effect"]["entity"] for effect in action["effects"]}
    )
    for entity in created_entities:
        lines.append(f"  let created{entity}: {entity} | undefined;")
    for entity in affected_entities:
        lines.append(f"  let affected{entity}: {entity} | undefined;")

    for index, effect in enumerate(action["effects"]):
        lines.extend(
            f"  {line}"
            for line in render_effect(effect["effect"], index, action, entities_by_name)
        )

    for ensure in action["ensures"]:
        expression = render_condition(ensure["condition"])
        lines.extend(
            [
                f"  if (!({expression})) {{",
                f"    throw new Error({ts_literal('postcondition failed: ' + ensure['source'])});",
                "  }",
            ]
        )

    lines.extend(["  return nextStore;", "}"])
    return lines


def render_effect(
    effect: dict[str, Any],
    index: int,
    action: dict[str, Any],
    entities_by_name: dict[str, dict[str, Any]],
) -> list[str]:
    entity = effect["entity"]
    entity_node = entities_by_name[entity]
    collection = camel_plural(entity)

    if effect["op"] == "insert":
        value_name = f"new{entity}{index}"
        field_lines = render_created_fields(entity_node["fields"], action["inputs"])
        return [
            f"const {value_name}: {entity} = {{",
            *[f"  {line}" for line in field_lines],
            "};",
            *render_unique_guards(entity_node, collection, value_name),
            f"created{entity} = {value_name};",
            f"affected{entity} = {value_name};",
            "nextStore = {",
            "  ...nextStore,",
            f"  {collection}: [...nextStore.{collection}, {value_name}],",
            "};",
        ]

    matches_name = f"matched{entity}{index}"
    target_name = f"target{entity}{index}"
    condition = render_condition(effect["where"])
    lines = [
        f"const {matches_name} = nextStore.{collection}.filter((item) => {condition});",
        f"if ({matches_name}.length !== 1) {{",
        f"  throw new Error({ts_literal(effect['op'] + ' ' + entity + ' must match exactly one record')});",
        "}",
        f"const {target_name} = {matches_name}[0];",
    ]

    if effect["op"] == "update":
        value_name = f"updated{entity}{index}"
        assignments = [
            f"{assignment['field']}: {render_value(assignment['value'])},"
            for assignment in effect["set"]
        ]
        lines.extend(
            [
                f"const {value_name}: {entity} = {{",
                f"  ...{target_name},",
                *[f"  {assignment}" for assignment in assignments],
                "};",
                *render_unique_guards(
                    entity_node, collection, value_name, ignore_name=target_name
                ),
                f"affected{entity} = {value_name};",
                "nextStore = {",
                "  ...nextStore,",
                f"  {collection}: nextStore.{collection}.map((item) => item === {target_name} ? {value_name} : item),",
                "};",
            ]
        )
        return lines

    lines.extend(
        [
            f"affected{entity} = {target_name};",
            "nextStore = {",
            "  ...nextStore,",
            f"  {collection}: nextStore.{collection}.filter((item) => item !== {target_name}),",
            "};",
        ]
    )
    return lines


def render_unique_guards(
    entity: dict[str, Any],
    collection: str,
    value_name: str,
    ignore_name: str | None = None,
) -> list[str]:
    lines: list[str] = []
    for field in entity["fields"]:
        if not field.get("unique"):
            continue
        field_name = field["name"]
        ignore = f"item !== {ignore_name} && " if ignore_name else ""
        condition = (
            f"{value_name}.{field_name} !== undefined && "
            f"nextStore.{collection}.some((item) => {ignore}"
            f"item.{field_name} === {value_name}.{field_name})"
        )
        lines.extend(
            [
                f"if ({condition}) {{",
                f"  throw new Error({ts_literal('unique constraint failed: ' + entity['name'] + '.' + field_name)});",
                "}",
            ]
        )
    return lines


def render_created_fields(
    fields: list[dict[str, Any]],
    inputs: list[dict[str, Any]],
) -> list[str]:
    input_specs = {field["name"]: field for field in inputs}
    lines: list[str] = []
    for field in fields:
        name = field["name"]
        if name in input_specs:
            assertion = "!" if field.get("required") and not input_specs[name].get("required") else ""
            lines.append(f"{name}: resolvedInput.{name}{assertion},")
        elif "default" in field:
            lines.append(f"{name}: {ts_literal(field['default'])},")
    return lines


def render_condition(condition: dict[str, Any], record_name: str = "item") -> str:
    kind = condition.get("kind")
    if kind == "not_empty":
        target = render_value(condition["target"], record_name)
        return f'typeof {target} === "string" && {target}.length > 0'
    if kind == "equals":
        left = render_value(condition["left"], record_name)
        right = render_value(condition["right"], record_name)
        return f"{left} === {right}"
    return "false"


def render_value(expression: dict[str, Any], record_name: str = "item") -> str:
    kind = expression.get("kind")
    if kind == "literal":
        return ts_literal(expression.get("value"))
    if kind == "input":
        return f"resolvedInput.{expression['name']}"
    if kind == "created_field":
        return f"created{expression['entity']}?.{expression['field']}"
    if kind == "affected_field":
        return f"affected{expression['entity']}?.{expression['field']}"
    if kind == "entity_field":
        return f"{record_name}.{expression['field']}"
    return "undefined"


def render_test_runner(
    tests: list[dict[str, Any]],
    entities_by_name: dict[str, dict[str, Any]],
) -> list[str]:
    lines = [
        "export type IntentIRTestResult = { name: string; ok: boolean; error?: string };",
        "",
        "export function runIntentIRTests(): IntentIRTestResult[] {",
        "  const results: IntentIRTestResult[] = [];",
    ]
    for index, test in enumerate(tests):
        store_name = f"store{index}"
        checks = [
            render_expectation(expected["expectation"], entities_by_name)
            for expected in test["expects"]
        ]
        expression = " && ".join(f"({check})" for check in checks) or "true"
        lines.extend(["  try {", f"    let {store_name} = createStore();"])
        for call in test["steps"]:
            args = ", ".join(
                f"{arg['name']}: {ts_literal(arg['value']['value'])}"
                for arg in call["args"]
            )
            lines.append(
                f"    {store_name} = {call['action']}({store_name}, {{ {args} }});"
            )
        lines.extend(
            [
                f"    const ok = {expression.replace('store.', store_name + '.')};",
                f"    results.push({{ name: {ts_literal(test['name'])}, ok, ...(ok ? {{}} : {{ error: \"expectation failed\" }}) }});",
                "  } catch (error) {",
                f"    results.push({{ name: {ts_literal(test['name'])}, ok: false, error: error instanceof Error ? error.message : String(error) }});",
                "  }",
            ]
        )
    lines.extend(["  return results;", "}"])
    return lines


def render_expectation(
    expectation: dict[str, Any],
    entities_by_name: dict[str, dict[str, Any]],
) -> str:
    entity = expectation["entity"]
    collection = camel_plural(entities_by_name[entity]["name"])
    if expectation["kind"] == "entity_count":
        return f"store.{collection}.length === {expectation['count']}"
    where = expectation.get("where")
    matched = (
        f"store.{collection}.length > 0"
        if not where
        else f"store.{collection}.some((item) => {render_condition(where)})"
    )
    return f"!({matched})" if expectation["kind"] == "entity_not_exists" else matched


def ts_type(type_name: str) -> str:
    return TYPE_MAP.get(type_name, "unknown")


def camel_plural(name: str) -> str:
    return name[:1].lower() + name[1:] + "s"


def ts_literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
