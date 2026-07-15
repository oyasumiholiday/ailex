from __future__ import annotations

import ast
import keyword
from typing import Any, Iterator

from intentir.expressions import ExpressionError, parse_literal


BINARY_OPERATORS = {
    ast.Add: "add",
    ast.Sub: "subtract",
    ast.Mult: "multiply",
    ast.Div: "divide",
    ast.FloorDiv: "floor_divide",
    ast.Mod: "modulo",
}
COMPARISON_OPERATORS = {
    ast.Eq: "equal",
    ast.NotEq: "not_equal",
    ast.Lt: "less_than",
    ast.LtE: "less_than_or_equal",
    ast.Gt: "greater_than",
    ast.GtE: "greater_than_or_equal",
}
BOOLEAN_OPERATORS = {ast.And: "and", ast.Or: "or"}
UNARY_OPERATORS = {ast.Not: "not", ast.USub: "negate", ast.UAdd: "positive"}
PURE_RESERVED_NAMES = {"true", "false", "null", *keyword.kwlist}


def parse_pure_expression(source: str) -> dict[str, Any]:
    try:
        parsed = ast.parse(source, mode="eval").body
    except SyntaxError as error:
        raise ExpressionError(f"invalid pure expression: {source}") from error
    return lower_expression(parsed)


def parse_function_example(source: str) -> dict[str, Any]:
    if " equals " not in source:
        raise ExpressionError(f"function example must contain equals: {source}")
    call_source, expected_source = source.rsplit(" equals ", 1)
    expression = parse_pure_expression(call_source.strip())
    if expression.get("kind") != "function_call":
        raise ExpressionError(f"function example must call a function: {source}")
    return {
        "kind": "function_example",
        "call": expression,
        "expected": parse_literal(expected_source.strip()),
    }


def lower_expression(node: ast.AST) -> dict[str, Any]:
    if isinstance(node, ast.Constant):
        return literal_from_value(node.value)

    if isinstance(node, ast.Name):
        if node.id in {"true", "false", "null"}:
            return parse_literal(node.id)
        return {"kind": "variable", "name": node.id}

    if isinstance(node, ast.BinOp):
        operator = operator_name(node.op, BINARY_OPERATORS, "binary")
        return {
            "kind": "binary",
            "op": operator,
            "left": lower_expression(node.left),
            "right": lower_expression(node.right),
        }

    if isinstance(node, ast.BoolOp):
        operator = operator_name(node.op, BOOLEAN_OPERATORS, "boolean")
        return {
            "kind": "boolean",
            "op": operator,
            "values": [lower_expression(value) for value in node.values],
        }

    if isinstance(node, ast.UnaryOp):
        operator = operator_name(node.op, UNARY_OPERATORS, "unary")
        return {
            "kind": "unary",
            "op": operator,
            "value": lower_expression(node.operand),
        }

    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ExpressionError("chained comparisons are not supported")
        operator = operator_name(node.ops[0], COMPARISON_OPERATORS, "comparison")
        return {
            "kind": "comparison",
            "op": operator,
            "left": lower_expression(node.left),
            "right": lower_expression(node.comparators[0]),
        }

    if isinstance(node, ast.IfExp):
        return {
            "kind": "conditional",
            "condition": lower_expression(node.test),
            "then": lower_expression(node.body),
            "else": lower_expression(node.orelse),
        }

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ExpressionError("function calls require a direct function name")
        keywords: list[dict[str, Any]] = []
        for keyword in node.keywords:
            if keyword.arg is None:
                raise ExpressionError("expanded function arguments are not supported")
            keywords.append(
                {"name": keyword.arg, "value": lower_expression(keyword.value)}
            )
        keywords.sort(key=lambda item: item["name"])
        return {
            "kind": "function_call",
            "function": node.func.id,
            "args": [lower_expression(argument) for argument in node.args],
            "kwargs": keywords,
        }

    raise ExpressionError(
        f"unsupported pure expression node: {node.__class__.__name__}"
    )


def function_references(expression: dict[str, Any]) -> Iterator[str]:
    if expression.get("kind") == "function_call":
        yield expression["function"]
    for value in expression.values():
        if isinstance(value, dict):
            yield from function_references(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield from function_references(item)


def literal_from_value(value: Any) -> dict[str, Any]:
    if isinstance(value, (bool, int, float, str)) or value is None:
        return parse_literal(repr(value))
    raise ExpressionError(f"unsupported pure literal: {value!r}")


def operator_name(
    operator: ast.AST, mapping: dict[type[ast.AST], str], kind: str
) -> str:
    for operator_type, name in mapping.items():
        if isinstance(operator, operator_type):
            return name
    raise ExpressionError(
        f"unsupported {kind} operator: {operator.__class__.__name__}"
    )
