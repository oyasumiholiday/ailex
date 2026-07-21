from __future__ import annotations

import ast
import re
from typing import Any, Callable, Iterator


IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
NOT_EMPTY_RE = re.compile(rf"^(?:input\.)?({IDENT})\s+is\s+not\s+empty$")
EQUALS_RE = re.compile(r"^(.+?)\s+equals\s+(.+)$")
INPUT_REF_RE = re.compile(rf"^input\.({IDENT})$")
CREATED_REF_RE = re.compile(rf"^created\s+({IDENT})\.({IDENT})$")
AFFECTED_REF_RE = re.compile(rf"^affected\s+({IDENT})\.({IDENT})$")
INSERT_RE = re.compile(rf"^insert\s+({IDENT})$")
UPDATE_RE = re.compile(
    rf"^update\s+({IDENT})\s+where\s+({IDENT})\s+equals\s+(.+?)\s+set\s+(.+)$"
)
DELETE_RE = re.compile(
    rf"^delete\s+({IDENT})\s+where\s+({IDENT})\s+equals\s+(.+)$"
)
ASSIGN_RE = re.compile(rf"^({IDENT})\s*=\s*(.+)$")
EXPECT_RE = re.compile(rf"^({IDENT})\s+exists(?:\s+with\s+({IDENT})\s+(.+))?$")
NO_EXPECT_RE = re.compile(
    rf"^no\s+({IDENT})\s+exists(?:\s+with\s+({IDENT})\s+(.+))?$"
)
COUNT_EXPECT_RE = re.compile(rf"^({IDENT})\s+count\s+equals\s+([0-9]+)$")


class ExpressionError(ValueError):
    pass


def parse_requirement(expr: str) -> dict[str, Any]:
    not_empty = NOT_EMPTY_RE.match(expr)
    if not_empty:
        return {
            "kind": "not_empty",
            "target": {"kind": "input", "name": not_empty.group(1)},
        }

    equals = EQUALS_RE.match(expr)
    if equals:
        return {
            "kind": "equals",
            "left": parse_reference_or_literal(equals.group(1).strip()),
            "right": parse_reference_or_literal(equals.group(2).strip()),
        }
    raise ExpressionError(f"unsupported requirement expression: {expr}")


def parse_ensure(expr: str) -> dict[str, Any]:
    equals = EQUALS_RE.match(expr)
    if equals:
        return {
            "kind": "equals",
            "left": parse_reference_or_literal(equals.group(1).strip()),
            "right": parse_reference_or_literal(equals.group(2).strip()),
        }
    raise ExpressionError(f"unsupported ensure expression: {expr}")


def parse_effect(expr: str) -> dict[str, Any]:
    insert = INSERT_RE.match(expr)
    if insert:
        return {"op": "insert", "entity": insert.group(1)}

    update = UPDATE_RE.match(expr)
    if update:
        entity, where_field, where_value, assignments = update.groups()
        return {
            "op": "update",
            "entity": entity,
            "where": field_equals(entity, where_field, where_value),
            "set": parse_assignments(assignments),
        }

    delete = DELETE_RE.match(expr)
    if delete:
        entity, where_field, where_value = delete.groups()
        return {
            "op": "delete",
            "entity": entity,
            "where": field_equals(entity, where_field, where_value),
        }
    raise ExpressionError(f"unsupported effect expression: {expr}")


def field_equals(entity: str, field: str, value: str) -> dict[str, Any]:
    return {
        "kind": "equals",
        "left": {"kind": "entity_field", "entity": entity, "field": field},
        "right": parse_reference_or_literal(value.strip()),
    }


def parse_assignments(source: str) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for item in split_top_level(source):
        match = ASSIGN_RE.match(item.strip())
        if not match:
            raise ExpressionError(f"invalid update assignment: {item.strip()}")
        assignments.append(
            {
                "field": match.group(1),
                "value": parse_reference_or_literal(match.group(2).strip()),
            }
        )
    if not assignments:
        raise ExpressionError("update requires at least one assignment")
    return assignments


def split_top_level(source: str) -> list[str]:
    parts: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    depth = 0
    for index, char in enumerate(source):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote:
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(source[start:index])
            start = index + 1
    if quote or depth != 0:
        raise ExpressionError(f"unbalanced update assignment: {source}")
    parts.append(source[start:])
    return [part for part in parts if part.strip()]


def parse_call(expr: str) -> dict[str, Any]:
    try:
        parsed = ast.parse(expr, mode="eval").body
    except SyntaxError as error:
        raise ExpressionError(f"invalid action call: {expr}") from error

    if not isinstance(parsed, ast.Call) or not isinstance(parsed.func, ast.Name):
        raise ExpressionError(f"invalid action call: {expr}")
    if parsed.args:
        raise ExpressionError("action calls only accept named inputs")

    args: list[dict[str, Any]] = []
    for keyword in parsed.keywords:
        if keyword.arg is None:
            raise ExpressionError("expanded keyword arguments are not supported")
        args.append({"name": keyword.arg, "value": literal_from_ast(keyword.value)})

    return {
        "kind": "call",
        "action": parsed.func.id,
        "args": sorted(args, key=lambda item: item["name"]),
    }


def parse_expectation(expr: str) -> dict[str, Any]:
    count = COUNT_EXPECT_RE.match(expr)
    if count:
        return {
            "kind": "entity_count",
            "entity": count.group(1),
            "count": int(count.group(2)),
        }

    absent = NO_EXPECT_RE.match(expr)
    if absent:
        entity, field, raw_value = absent.groups()
        expectation = build_exists_expectation(entity, field, raw_value)
        expectation["kind"] = "entity_not_exists"
        return expectation

    present = EXPECT_RE.match(expr)
    if present:
        return build_exists_expectation(*present.groups())
    raise ExpressionError(f"unsupported expectation expression: {expr}")


def build_exists_expectation(
    entity: str,
    field: str | None,
    raw_value: str | None,
) -> dict[str, Any]:
    expectation: dict[str, Any] = {"kind": "entity_exists", "entity": entity}
    if field is not None and raw_value is not None:
        expectation["where"] = field_equals(entity, field, raw_value)
    return expectation


def parse_reference_or_literal(expr: str) -> dict[str, Any]:
    try:
        return parse_reference(expr)
    except ExpressionError:
        pass
    try:
        return parse_literal(expr)
    except ExpressionError:
        # Imported lazily because the pure-expression parser reuses parse_literal.
        from intentir.pure import parse_pure_expression

        return parse_pure_expression(expr)


def parse_reference(expr: str) -> dict[str, str]:
    input_ref = INPUT_REF_RE.match(expr)
    if input_ref:
        return {"kind": "input", "name": input_ref.group(1)}

    created_ref = CREATED_REF_RE.match(expr)
    if created_ref:
        return {
            "kind": "created_field",
            "entity": created_ref.group(1),
            "field": created_ref.group(2),
        }

    affected_ref = AFFECTED_REF_RE.match(expr)
    if affected_ref:
        return {
            "kind": "affected_field",
            "entity": affected_ref.group(1),
            "field": affected_ref.group(2),
        }
    raise ExpressionError(f"unsupported reference expression: {expr}")


def parse_literal(expr: str) -> dict[str, Any]:
    text = expr.strip()
    if text == "true":
        value: Any = True
    elif text == "false":
        value = False
    elif text == "null":
        value = None
    else:
        try:
            value = ast.literal_eval(text)
        except (SyntaxError, ValueError) as error:
            raise ExpressionError(f"unsupported literal: {expr}") from error

    if value is None:
        type_name = "Null"
    elif isinstance(value, bool):
        type_name = "Boolean"
    elif isinstance(value, int):
        type_name = "Integer"
    elif isinstance(value, float):
        type_name = "Number"
    elif isinstance(value, str):
        type_name = "Text"
    else:
        raise ExpressionError(f"unsupported literal: {expr}")
    return {"kind": "literal", "type": type_name, "value": value}


def literal_from_ast(node: ast.AST) -> dict[str, Any]:
    if isinstance(node, ast.Name) and node.id in {"true", "false", "null"}:
        return parse_literal(node.id)
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError) as error:
        raise ExpressionError("action inputs must be scalar literals") from error
    return parse_literal(repr(value))


def literal_value(literal: dict[str, Any]) -> Any:
    if literal.get("kind") != "literal":
        raise ExpressionError("expected a literal value")
    return literal.get("value")


def referenced_inputs(expression: dict[str, Any]) -> Iterator[str]:
    if expression.get("kind") == "input":
        yield expression["name"]
        return
    yield from walk_nested(expression, referenced_inputs)


def referenced_created_fields(expression: dict[str, Any]) -> Iterator[tuple[str, str]]:
    if expression.get("kind") == "created_field":
        yield expression["entity"], expression["field"]
        return
    yield from walk_nested(expression, referenced_created_fields)


def referenced_affected_fields(expression: dict[str, Any]) -> Iterator[tuple[str, str]]:
    if expression.get("kind") == "affected_field":
        yield expression["entity"], expression["field"]
        return
    yield from walk_nested(expression, referenced_affected_fields)


def referenced_entity_fields(expression: dict[str, Any]) -> Iterator[tuple[str, str]]:
    if expression.get("kind") == "entity_field":
        yield expression["entity"], expression["field"]
        return
    yield from walk_nested(expression, referenced_entity_fields)


def walk_nested(
    expression: dict[str, Any],
    visitor: Callable[[dict[str, Any]], Iterator[Any]],
) -> Iterator[Any]:
    for value in expression.values():
        if isinstance(value, dict):
            yield from visitor(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield from visitor(item)
