"""Bounded notation experiments over IntentIR's existing pure-expression semantics.

This module deliberately supports only Integer literals and inputs, ``+``, ``-``,
``*``, and unary ``+``/``-``.  It is a hand-designed baseline for comparing
interchangeable notations, not an autonomous language-evolution mechanism.

Graph JSON has the exact top-level shape::

    {"version": 1, "inputs": {name: "Integer"}, "nodes": [...], "root": id}

Each node has ``id``, ``type: "Integer"``, and one of these exact shapes:
``input(name)``, ``const(value)``, ``add(left,right)``,
``subtract(left,right)``, ``multiply(left,right)``, ``negate(value)``, or
``positive(value)``. References must point backward in the node list.

Rows JSON is the compact exact shape ``{"v":1,"i":[[name,type]],
"n":[rows],"r":id}``. A row is ``[id,type,op,arg]`` for leaves/unary
nodes and ``[id,type,op,left,right]`` for binary nodes. Node IDs survive codec
round-trips and replacements, but re-lowering source may assign different IDs.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import keyword
import os
from pathlib import Path
import stat
import sys
from typing import Any, NoReturn, Sequence

from intentir.canonical import canonical_json, content_address
from intentir.expressions import ExpressionError
from intentir.pure import PURE_RESERVED_NAMES, parse_pure_expression
from intentir.validator import Diagnostic, infer_pure_type
from intentir.verifier import PureRuntimeError, evaluate_pure_expression


GRAPH_VERSION = 1
INTEGER_TYPE = "Integer"
MAX_SOURCE_BYTES = 16_384
MAX_NODES = 256
MAX_DEPTH = 64
MAX_INTEGER_BITS = 256
MAX_OUTPUT_INTEGER_BITS = 256
MAX_EXPANDED_NODES = 4_096
MAX_NODE_ID_BYTES = 128

BINARY_OPS = {"add", "subtract", "multiply"}
UNARY_OPS = {"negate", "positive"}
NODE_OPS = {"input", "const", *BINARY_OPS, *UNARY_OPS}
TOP_LEVEL_FIELDS = {"version", "inputs", "nodes", "root"}
ROWS_FIELDS = {"v", "i", "n", "r"}


class NotationError(ValueError):
    """A stable, user-facing failure at a notation boundary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def _fail(code: str, message: str) -> NoReturn:
    raise NotationError(code, message)


def _utf8_size(value: str, label: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise NotationError("invalid_text", f"{label} must be valid UTF-8") from error


def _check_source_size(source: Any, label: str = "source") -> str:
    if not isinstance(source, str):
        _fail("invalid_source", f"{label} must be text")
    if _utf8_size(source, label) > MAX_SOURCE_BYTES:
        _fail(
            "source_limit",
            f"{label} exceeds the {MAX_SOURCE_BYTES}-byte limit",
        )
    return source


def _is_integer(value: Any) -> bool:
    return type(value) is int


def _check_integer(value: Any, label: str) -> int:
    if not _is_integer(value):
        _fail("integer_required", f"{label} must be an Integer (booleans are not integers)")
    if value.bit_length() > MAX_INTEGER_BITS:
        _fail(
            "integer_limit",
            f"{label} exceeds the {MAX_INTEGER_BITS}-bit integer limit",
        )
    return value


def _valid_identifier(name: Any) -> bool:
    return (
        isinstance(name, str)
        and name.isidentifier()
        and not keyword.iskeyword(name)
        and name not in PURE_RESERVED_NAMES
    )


def _validate_input_declarations(inputs: Any) -> dict[str, str]:
    if not isinstance(inputs, dict):
        _fail("invalid_inputs", "inputs must be an object mapping names to Integer")
    result: dict[str, str] = {}
    for name, type_name in inputs.items():
        if not _valid_identifier(name):
            _fail("invalid_input_name", f"invalid input identifier: {name!r}")
        if type_name != INTEGER_TYPE:
            _fail("type_mismatch", f"input {name} must have type Integer")
        result[name] = INTEGER_TYPE
    return result


def _validate_expression(
    expression: Any,
    inputs: dict[str, str],
    *,
    depth: int = 1,
    counter: list[int] | None = None,
) -> None:
    if counter is None:
        counter = [0]
    if depth > MAX_DEPTH:
        _fail("depth_limit", f"expression exceeds the depth limit of {MAX_DEPTH}")
    counter[0] += 1
    if counter[0] > MAX_NODES:
        _fail("node_limit", f"expression exceeds the node limit of {MAX_NODES}")
    if not isinstance(expression, dict):
        _fail("unsupported_expression", "pure expression node must be an object")

    kind = expression.get("kind")
    if kind == "literal":
        if set(expression) != {"kind", "type", "value"}:
            _fail("unsupported_expression", "Integer literals must use the exact pure AST shape")
        if expression.get("type") != INTEGER_TYPE:
            _fail("unsupported_expression", "only Integer literals are supported")
        _check_integer(expression.get("value"), "literal")
        return
    if kind == "variable":
        if set(expression) != {"kind", "name"}:
            _fail("unsupported_expression", "variables must use the exact pure AST shape")
        name = expression.get("name")
        if name not in inputs:
            _fail("unknown_input", f"unknown Integer input: {name!r}")
        return
    if kind == "binary" and expression.get("op") in BINARY_OPS:
        if set(expression) != {"kind", "op", "left", "right"}:
            _fail("unsupported_expression", "binary expressions must use the exact pure AST shape")
        _validate_expression(expression["left"], inputs, depth=depth + 1, counter=counter)
        _validate_expression(expression["right"], inputs, depth=depth + 1, counter=counter)
        return
    if kind == "unary" and expression.get("op") in UNARY_OPS:
        if set(expression) != {"kind", "op", "value"}:
            _fail("unsupported_expression", "unary expressions must use the exact pure AST shape")
        _validate_expression(expression["value"], inputs, depth=depth + 1, counter=counter)
        return
    _fail(
        "unsupported_expression",
        "only Integer inputs/literals, add, subtract, multiply, negate, and positive are supported",
    )


def _typecheck_expression(expression: dict[str, Any], inputs: dict[str, str]) -> None:
    diagnostics: list[Diagnostic] = []
    inferred = infer_pure_type(expression, inputs, {}, diagnostics, "/expression")
    if diagnostics or inferred != INTEGER_TYPE:
        detail = diagnostics[0].message if diagnostics else f"inferred {inferred!r}"
        _fail("type_mismatch", f"expression must have type Integer: {detail}")


def expression_to_graph(source: str, inputs: dict[str, str]) -> dict[str, Any]:
    """Parse and deterministically lower a bounded Integer expression to a DAG."""

    source = _check_source_size(source, "expression source")
    declarations = _validate_input_declarations(inputs)
    try:
        expression = parse_pure_expression(source)
    except (ExpressionError, SyntaxError, RecursionError) as error:
        raise NotationError("invalid_expression", str(error)) from error
    _validate_expression(expression, declarations)
    _typecheck_expression(expression, declarations)

    nodes: list[dict[str, Any]] = []
    interned: dict[str, str] = {}

    def emit(node: dict[str, Any]) -> str:
        key = canonical_json(node)
        existing = interned.get(key)
        if existing is not None:
            return existing
        kind = node["kind"]
        node_id = f"n{len(nodes)}"
        if kind == "literal":
            graph_node = {
                "id": node_id,
                "type": INTEGER_TYPE,
                "op": "const",
                "value": node["value"],
            }
        elif kind == "variable":
            graph_node = {
                "id": node_id,
                "type": INTEGER_TYPE,
                "op": "input",
                "name": node["name"],
            }
        elif kind == "binary":
            left = emit(node["left"])
            right = emit(node["right"])
            node_id = f"n{len(nodes)}"
            graph_node = {
                "id": node_id,
                "type": INTEGER_TYPE,
                "op": node["op"],
                "left": left,
                "right": right,
            }
        else:
            value = emit(node["value"])
            node_id = f"n{len(nodes)}"
            graph_node = {
                "id": node_id,
                "type": INTEGER_TYPE,
                "op": node["op"],
                "value": value,
            }
        nodes.append(graph_node)
        interned[key] = node_id
        return node_id

    graph = {
        "version": GRAPH_VERSION,
        "inputs": dict(sorted(declarations.items())),
        "nodes": nodes,
        "root": emit(expression),
    }
    validate_graph(graph)
    return graph


lower_expression_to_graph = expression_to_graph


def _expected_node_fields(op: str) -> set[str]:
    if op == "input":
        return {"id", "type", "op", "name"}
    if op == "const":
        return {"id", "type", "op", "value"}
    if op in BINARY_OPS:
        return {"id", "type", "op", "left", "right"}
    if op in UNARY_OPS:
        return {"id", "type", "op", "value"}
    _fail("unknown_operator", f"unsupported graph operator: {op!r}")


def _node_references(node: dict[str, Any]) -> tuple[Any, ...]:
    op = node["op"]
    if op in BINARY_OPS:
        return (node["left"], node["right"])
    if op in UNARY_OPS:
        return (node["value"],)
    return ()


def validate_graph(graph: Any) -> dict[str, Any]:
    """Validate the strict graph schema and all topology/reachability bounds."""

    if not isinstance(graph, dict):
        _fail("invalid_graph", "graph must be a JSON object")
    if set(graph) != TOP_LEVEL_FIELDS:
        _fail("invalid_graph", "graph must contain exactly version, inputs, nodes, and root")
    if not _is_integer(graph["version"]) or graph["version"] != GRAPH_VERSION:
        _fail("unsupported_version", "graph version must be integer 1")
    inputs = _validate_input_declarations(graph["inputs"])
    nodes = graph["nodes"]
    if not isinstance(nodes, list):
        _fail("invalid_graph", "nodes must be a list")
    if not nodes:
        _fail("invalid_graph", "graph must contain at least one node")
    if len(nodes) > MAX_NODES:
        _fail("node_limit", f"graph exceeds the node limit of {MAX_NODES}")

    by_id: dict[str, dict[str, Any]] = {}
    depths: dict[str, int] = {}
    refs_by_id: dict[str, tuple[str, ...]] = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            _fail("invalid_node", f"node {index} must be an object")
        op = node.get("op")
        if not isinstance(op, str) or op not in NODE_OPS:
            _fail("unknown_operator", f"node {index} has unsupported operator {op!r}")
        expected = _expected_node_fields(op)
        if set(node) != expected:
            _fail("invalid_node", f"node {index} with op {op} has invalid fields")
        node_id = node["id"]
        if not isinstance(node_id, str) or not node_id:
            _fail("invalid_node_id", f"node {index} id must be a nonempty string")
        if _utf8_size(node_id, f"node {index} id") > MAX_NODE_ID_BYTES:
            _fail("invalid_node_id", f"node {index} id exceeds {MAX_NODE_ID_BYTES} bytes")
        if node_id in by_id:
            _fail("duplicate_node_id", f"duplicate node id: {node_id}")
        if node["type"] != INTEGER_TYPE:
            _fail("type_mismatch", f"node {node_id} must have type Integer")

        if op == "input":
            name = node["name"]
            if not isinstance(name, str) or name not in inputs:
                _fail("unknown_input", f"node {node_id} references undeclared input {name!r}")
        elif op == "const":
            _check_integer(node["value"], f"node {node_id} constant")

        raw_refs = _node_references(node)
        refs: list[str] = []
        for ref in raw_refs:
            if not isinstance(ref, str) or ref not in by_id:
                _fail(
                    "non_topological_reference",
                    f"node {node_id} reference {ref!r} must name an earlier node",
                )
            refs.append(ref)
        depth = 1 + max((depths[ref] for ref in refs), default=0)
        if depth > MAX_DEPTH:
            _fail("depth_limit", f"graph exceeds the depth limit of {MAX_DEPTH}")
        by_id[node_id] = node
        depths[node_id] = depth
        refs_by_id[node_id] = tuple(refs)

    root = graph["root"]
    if not isinstance(root, str) or root not in by_id:
        _fail("unknown_root", "root must name a graph node")
    reachable: set[str] = set()
    pending = [root]
    while pending:
        node_id = pending.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        pending.extend(refs_by_id[node_id])
    if reachable != set(by_id):
        unused = sorted(set(by_id) - reachable)
        _fail("unreachable_node", f"all nodes must be reachable from root; unused: {unused}")
    return graph


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_json_key", f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    _fail("non_finite_json", f"non-finite JSON number is not allowed: {value}")


def _parse_json_integer(source: str) -> int:
    digits = source.removeprefix("-")
    maximum_decimal_digits = (MAX_INTEGER_BITS * 30_103) // 100_000 + 2
    if len(digits) > maximum_decimal_digits:
        _fail(
            "integer_limit",
            f"JSON integer exceeds the {MAX_INTEGER_BITS}-bit integer limit",
        )
    return _check_integer(int(source), "JSON integer")


def _decode_json(source: str, label: str) -> Any:
    source = _check_source_size(source, label)
    try:
        return json.loads(
            source,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
            parse_int=_parse_json_integer,
        )
    except NotationError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise NotationError("invalid_json", f"invalid {label}: {error}") from error


def encode_graph_json(graph: dict[str, Any]) -> str:
    validate_graph(graph)
    encoded = canonical_json(graph)
    _check_source_size(encoded, "graph JSON")
    return encoded


def decode_graph_json(source: str) -> dict[str, Any]:
    value = _decode_json(source, "graph JSON")
    validate_graph(value)
    return value


graph_to_json = encode_graph_json
graph_from_json = decode_graph_json


def graph_to_rows(graph: dict[str, Any]) -> dict[str, Any]:
    validate_graph(graph)
    rows: list[list[Any]] = []
    for node in graph["nodes"]:
        op = node["op"]
        prefix: list[Any] = [node["id"], node["type"], op]
        if op == "input":
            rows.append([*prefix, node["name"]])
        elif op == "const" or op in UNARY_OPS:
            rows.append([*prefix, node["value"]])
        else:
            rows.append([*prefix, node["left"], node["right"]])
    return {
        "v": GRAPH_VERSION,
        "i": [[name, type_name] for name, type_name in sorted(graph["inputs"].items())],
        "n": rows,
        "r": graph["root"],
    }


def rows_to_graph(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, dict) or set(rows) != ROWS_FIELDS:
        _fail("invalid_rows", "rows must contain exactly v, i, n, and r")
    compact_inputs = rows["i"]
    compact_nodes = rows["n"]
    if not isinstance(compact_inputs, list):
        _fail("invalid_rows", "rows i must be a list")
    if not isinstance(compact_nodes, list):
        _fail("invalid_rows", "rows n must be a list")
    inputs: dict[str, str] = {}
    for index, item in enumerate(compact_inputs):
        if not isinstance(item, list) or len(item) != 2:
            _fail("invalid_rows", f"input row {index} must have two items")
        name, type_name = item
        if not isinstance(name, str):
            _fail("invalid_rows", f"input row {index} name must be text")
        if name in inputs:
            _fail("duplicate_input", f"duplicate input declaration: {name}")
        inputs[name] = type_name

    nodes: list[dict[str, Any]] = []
    for index, row in enumerate(compact_nodes):
        if not isinstance(row, list) or len(row) < 3:
            _fail("invalid_rows", f"node row {index} must be a list with an operator")
        node_id, type_name, op = row[:3]
        if not isinstance(op, str) or op not in NODE_OPS:
            _fail("unknown_operator", f"node row {index} has unsupported operator {op!r}")
        if op == "input":
            if len(row) != 4:
                _fail("invalid_rows", f"input node row {index} must have four items")
            node = {"id": node_id, "type": type_name, "op": op, "name": row[3]}
        elif op == "const" or op in UNARY_OPS:
            if len(row) != 4:
                _fail("invalid_rows", f"node row {index} with op {op} must have four items")
            node = {"id": node_id, "type": type_name, "op": op, "value": row[3]}
        else:
            if len(row) != 5:
                _fail("invalid_rows", f"node row {index} with op {op} must have five items")
            node = {
                "id": node_id,
                "type": type_name,
                "op": op,
                "left": row[3],
                "right": row[4],
            }
        nodes.append(node)
    graph = {"version": rows["v"], "inputs": inputs, "nodes": nodes, "root": rows["r"]}
    validate_graph(graph)
    return graph


def encode_rows_json(graph: dict[str, Any]) -> str:
    encoded = canonical_json(graph_to_rows(graph))
    _check_source_size(encoded, "rows JSON")
    return encoded


def decode_rows_json(source: str) -> dict[str, Any]:
    return rows_to_graph(_decode_json(source, "rows JSON"))


rows_to_json = encode_rows_json
rows_from_json = decode_rows_json


def graph_to_pure_expression(graph: dict[str, Any]) -> dict[str, Any]:
    """Expand a validated graph into the existing pure AST within a hard budget."""

    validate_graph(graph)
    by_id = {node["id"]: node for node in graph["nodes"]}
    emitted = 0

    def expand(node_id: str) -> dict[str, Any]:
        nonlocal emitted
        emitted += 1
        if emitted > MAX_EXPANDED_NODES:
            _fail(
                "expansion_limit",
                f"graph expansion exceeds {MAX_EXPANDED_NODES} pure AST nodes",
            )
        node = by_id[node_id]
        op = node["op"]
        if op == "input":
            return {"kind": "variable", "name": node["name"]}
        if op == "const":
            return {"kind": "literal", "type": INTEGER_TYPE, "value": node["value"]}
        if op in BINARY_OPS:
            return {
                "kind": "binary",
                "op": op,
                "left": expand(node["left"]),
                "right": expand(node["right"]),
            }
        return {"kind": "unary", "op": op, "value": expand(node["value"])}

    expression = expand(graph["root"])
    _typecheck_expression(expression, graph["inputs"])
    return expression


def _validate_runtime_inputs(
    declarations: dict[str, str], values: Any
) -> dict[str, int]:
    if not isinstance(values, dict):
        _fail("invalid_inputs", "runtime inputs must be a JSON object")
    expected = set(declarations)
    actual = set(values)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected, key=repr)
        _fail("input_mismatch", f"runtime input keys differ; missing={missing}, extra={extra}")
    result: dict[str, int] = {}
    for name in declarations:
        result[name] = _check_integer(values[name], f"input {name}")
    return result


def _check_evaluation_growth(graph: dict[str, Any], inputs: dict[str, int]) -> None:
    """Reject conservatively large intermediates before invoking the evaluator.

    This is intentionally a magnitude bound, not symbolic simplification. An
    expression such as ``x - x`` can therefore be rejected at the bit limit even
    though its final mathematical value would be zero.
    """

    bounds: dict[str, int] = {}
    for node in graph["nodes"]:
        op = node["op"]
        if op == "input":
            bound = inputs[node["name"]].bit_length()
        elif op == "const":
            bound = node["value"].bit_length()
        elif op in {"add", "subtract"}:
            bound = max(bounds[node["left"]], bounds[node["right"]]) + 1
        elif op == "multiply":
            bound = bounds[node["left"]] + bounds[node["right"]]
        else:
            bound = bounds[node["value"]]
        if bound > MAX_OUTPUT_INTEGER_BITS:
            _fail(
                "output_limit",
                f"node {node['id']} may exceed the {MAX_OUTPUT_INTEGER_BITS}-bit output limit",
            )
        bounds[node["id"]] = bound


def evaluate_graph(graph: dict[str, Any], inputs: dict[str, Any]) -> int:
    """Evaluate through IntentIR's existing pure evaluator after strict validation."""

    validate_graph(graph)
    values = _validate_runtime_inputs(graph["inputs"], inputs)
    _check_evaluation_growth(graph, values)
    expression = graph_to_pure_expression(graph)
    try:
        result = evaluate_pure_expression(expression, values, {}, [])
    except PureRuntimeError as error:
        raise NotationError("evaluation_error", str(error)) from error
    if not _is_integer(result):
        _fail("type_mismatch", "evaluator returned a non-Integer result")
    if result.bit_length() > MAX_OUTPUT_INTEGER_BITS:
        _fail(
            "output_limit",
            f"result exceeds the {MAX_OUTPUT_INTEGER_BITS}-bit output limit",
        )
    return result


def evaluate_expression(source: str, inputs: dict[str, Any]) -> int:
    """Evaluate expression notation, inferring Integer declarations from input keys."""

    if not isinstance(inputs, dict):
        _fail("invalid_inputs", "runtime inputs must be a JSON object")
    for name, value in inputs.items():
        if not _valid_identifier(name):
            _fail("invalid_input_name", f"invalid input identifier: {name!r}")
        _check_integer(value, f"input {name}")
    declarations = {name: INTEGER_TYPE for name in sorted(inputs)}
    return evaluate_graph(expression_to_graph(source, declarations), inputs)


def graph_hash(graph: dict[str, Any]) -> str:
    """Return the canonical representation hash used as the exact patch base."""

    validate_graph(graph)
    return content_address(graph)


def replace_node(
    graph: dict[str, Any],
    node_id: str,
    replacement: dict[str, Any],
    expected_hash: str,
) -> dict[str, Any]:
    """Return a fully revalidated copy with one node replaced under a hash guard.

    The hash guards the canonical graph representation. It does not assert semantic
    equivalence. Neither successful nor failed replacements mutate ``graph``.
    """

    validate_graph(graph)
    actual_hash = graph_hash(graph)
    if expected_hash != actual_hash:
        _fail("stale_base", f"expected graph hash {expected_hash!r}, current hash is {actual_hash}")
    if not isinstance(node_id, str) or not any(node["id"] == node_id for node in graph["nodes"]):
        _fail("unknown_node", f"unknown graph node: {node_id!r}")
    if not isinstance(replacement, dict):
        _fail("invalid_replacement", "replacement must be an object")
    candidate = deepcopy(graph)
    replacement_copy = deepcopy(replacement)
    replacement_id = replacement_copy.get("id", node_id)
    if replacement_id != node_id:
        _fail("node_id_mismatch", "replacement must omit id or preserve the target id")
    replacement_copy["id"] = node_id
    for index, node in enumerate(candidate["nodes"]):
        if node["id"] == node_id:
            candidate["nodes"][index] = replacement_copy
            break
    validate_graph(candidate)
    return candidate


def _read_source(path_value: str) -> str:
    path = Path(path_value)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_BINARY", 0),
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            _fail("source_read_error", f"source must be a regular file: {path}")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            raw = handle.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            _fail("source_limit", f"source file exceeds the {MAX_SOURCE_BYTES}-byte limit")
        return raw.decode("utf-8")
    except NotationError:
        raise
    except (OSError, UnicodeError) as error:
        raise NotationError("source_read_error", f"cannot read source {path}: {error}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def demo_result() -> dict[str, Any]:
    source = "price * quantity + fee"
    inputs = {"price": 120, "quantity": 3, "fee": 20}
    declarations = {name: INTEGER_TYPE for name in inputs}
    graph = expression_to_graph(source, declarations)
    graph_json = encode_graph_json(graph)
    rows_json = encode_rows_json(graph)
    expression_result = evaluate_expression(source, inputs)
    graph_result = evaluate_graph(decode_graph_json(graph_json), inputs)
    rows_result = evaluate_graph(decode_rows_json(rows_json), inputs)
    fee_node = next(
        node["id"]
        for node in graph["nodes"]
        if node["op"] == "input" and node["name"] == "fee"
    )
    base_hash = graph_hash(graph)
    patched = replace_node(
        graph,
        fee_node,
        {"type": INTEGER_TYPE, "op": "const", "value": 30},
        base_hash,
    )
    return {
        "ok": True,
        "inputs": inputs,
        "representations": {
            "expression": {"source": source, "result": expression_result},
            "graph-json": {"source": graph_json, "result": graph_result},
            "rows-json": {"source": rows_json, "result": rows_result},
        },
        "equivalent": expression_result == graph_result == rows_result == 380,
        "patch": {
            "targetNode": fee_node,
            "baseHash": base_hash,
            "patchedHash": graph_hash(patched),
            "replacement": {"type": INTEGER_TYPE, "op": "const", "value": 30},
            "result": evaluate_graph(patched, inputs),
            "inputDeclarationsRemain": sorted(patched["inputs"]),
        },
    }


class _JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise NotationError("invalid_arguments", message)


def build_parser() -> argparse.ArgumentParser:
    parser = _JSONArgumentParser(description="Run the bounded IntentIR notation lab.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("demo", help="print the deterministic notation comparison")
    run_parser = subparsers.add_parser("run", help="evaluate one notation source")
    run_parser.add_argument(
        "--format",
        required=True,
        choices=("expression", "graph-json", "rows-json"),
    )
    run_parser.add_argument("--source", required=True, help="path to the notation source")
    run_parser.add_argument("--inputs", required=True, help="strict JSON object of Integer inputs")
    return parser


def _run_command(args: argparse.Namespace) -> dict[str, Any]:
    source = _read_source(args.source)
    inputs = _decode_json(args.inputs, "inputs JSON")
    if args.format == "expression":
        result = evaluate_expression(source, inputs)
        return {
            "ok": True,
            "format": args.format,
            "result": result,
            "inputTypesInferred": INTEGER_TYPE,
        }
    graph = decode_graph_json(source) if args.format == "graph-json" else decode_rows_json(source)
    return {
        "ok": True,
        "format": args.format,
        "graphHash": graph_hash(graph),
        "result": evaluate_graph(graph, inputs),
    }


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = demo_result() if args.command == "demo" else _run_command(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except NotationError as error:
        print(
            json.dumps({"ok": False, "error": error.to_dict()}, ensure_ascii=False, sort_keys=True),
            file=sys.stdout,
        )
        return 1


__all__ = [
    "GRAPH_VERSION",
    "INTEGER_TYPE",
    "MAX_DEPTH",
    "MAX_EXPANDED_NODES",
    "MAX_INTEGER_BITS",
    "MAX_NODES",
    "MAX_OUTPUT_INTEGER_BITS",
    "MAX_SOURCE_BYTES",
    "NotationError",
    "decode_graph_json",
    "decode_rows_json",
    "demo_result",
    "encode_graph_json",
    "encode_rows_json",
    "evaluate_expression",
    "evaluate_graph",
    "expression_to_graph",
    "graph_from_json",
    "graph_hash",
    "graph_to_json",
    "graph_to_pure_expression",
    "graph_to_rows",
    "lower_expression_to_graph",
    "replace_node",
    "rows_from_json",
    "rows_to_graph",
    "rows_to_json",
    "validate_graph",
]


if __name__ == "__main__":
    raise SystemExit(main())
