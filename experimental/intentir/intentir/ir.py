from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from intentir.canonical import content_address, semantic_projection
from intentir.expressions import (
    literal_value,
    parse_call,
    parse_effect,
    parse_ensure,
    parse_expectation,
    parse_literal,
    parse_requirement,
)


SCHEMA_VERSION = "0.7.0"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type_name: str
    required: bool = False
    default: str | None = None
    key: bool = False
    unique: bool = False

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "type": self.type_name,
            "required": self.required,
        }
        if self.default is not None:
            data["default"] = literal_value(parse_literal(self.default))
        if self.key:
            data["key"] = True
            data["unique"] = True
        elif self.unique:
            data["unique"] = True
        return data


@dataclass(frozen=True)
class EntitySpec:
    name: str
    fields: list[FieldSpec] = field(default_factory=list)


@dataclass(frozen=True)
class ActionSpec:
    name: str
    inputs: list[FieldSpec] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    effects: list[str] = field(default_factory=list)
    ensures: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TestSpec:
    name: str
    whens: list[str] = field(default_factory=list)
    expects: list[str] = field(default_factory=list)

    @property
    def when(self) -> str:
        return self.whens[0] if self.whens else ""


@dataclass(frozen=True)
class ProgramSpec:
    module: str
    entities: list[EntitySpec] = field(default_factory=list)
    actions: list[ActionSpec] = field(default_factory=list)
    tests: list[TestSpec] = field(default_factory=list)


def build_ir(program: ProgramSpec) -> dict[str, Any]:
    nodes = [
        *[build_entity_node(entity) for entity in program.entities],
        *[build_action_node(action) for action in program.actions],
        *[build_test_node(test) for test in program.tests],
    ]
    nodes.sort(key=lambda node: node["symbol"])
    symbols = {node["symbol"]: node["id"] for node in nodes}

    edges = build_edges(nodes, symbols)
    obligations = build_obligations(nodes)
    module_id = content_address(
        {
            "kind": "module",
            "name": program.module,
            "members": sorted(symbols.items()),
        }
    )

    ir: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "hashAlgorithm": "sha256",
        "module": program.module,
        "moduleId": module_id,
        "symbols": symbols,
        "nodes": nodes,
        "edges": edges,
        "obligations": obligations,
    }
    ir["canonicalHash"] = content_address(semantic_projection(ir))
    return ir


def build_entity_node(entity: EntitySpec) -> dict[str, Any]:
    payload = {
        "kind": "entity",
        "name": entity.name,
        "fields": sorted(
            (field_spec.to_dict() for field_spec in entity.fields),
            key=lambda item: item["name"],
        ),
    }
    return addressed_node(f"entity:{entity.name}", payload)


def build_action_node(action: ActionSpec) -> dict[str, Any]:
    requires = [
        addressed_expression("precondition", expr, parse_requirement(expr))
        for expr in action.requires
    ]
    effects = [
        addressed_expression("effect", expr, parse_effect(expr))
        for expr in action.effects
    ]
    capabilities = build_repository_capabilities(effects)
    ensures = [
        addressed_expression("postcondition", expr, parse_ensure(expr))
        for expr in action.ensures
    ]
    payload = {
        "kind": "action",
        "name": action.name,
        "inputs": sorted(
            (input_spec.to_dict() for input_spec in action.inputs),
            key=lambda item: item["name"],
        ),
        "requires": sorted(requires, key=lambda item: item["id"]),
        "effects": effects,
        "capabilities": capabilities,
        "ensures": sorted(ensures, key=lambda item: item["id"]),
    }
    return addressed_node(f"action:{action.name}", payload)


def build_test_node(test: TestSpec) -> dict[str, Any]:
    steps = [parse_call(when) for when in test.whens]
    expects = [
        addressed_expression("expectation", expr, parse_expectation(expr))
        for expr in test.expects
    ]
    payload = {
        "kind": "test",
        "name": test.name,
        "steps": steps,
        "expects": sorted(expects, key=lambda item: item["id"]),
    }
    return addressed_node(f"test:{slug(test.name)}", payload)


def addressed_node(symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
    semantic = {"symbol": symbol, **semantic_projection(payload)}
    return {"id": content_address(semantic), "symbol": symbol, **payload}


def addressed_expression(kind: str, source: str, value: dict[str, Any]) -> dict[str, Any]:
    key = "condition" if kind in {"precondition", "postcondition"} else kind
    payload = {"kind": kind, key: value}
    return {"id": content_address(payload), "source": source, **payload}


def build_repository_capabilities(
    effects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    operations: dict[str, set[str]] = {}
    for effect_node in effects:
        effect = effect_node["effect"]
        operations.setdefault(effect["entity"], set()).add(effect["op"])

    capabilities: list[dict[str, Any]] = []
    for entity, entity_operations in sorted(operations.items()):
        payload = {
            "kind": "repository",
            "entity": entity,
            "operations": sorted(entity_operations),
        }
        capabilities.append({"id": content_address(payload), **payload})
    return capabilities


def build_edges(nodes: list[dict[str, Any]], symbols: dict[str, str]) -> list[dict[str, Any]]:
    symbolic_edges: list[tuple[str, str, str]] = []
    for node in nodes:
        if node["kind"] == "action":
            for effect in node["effects"]:
                target = f"entity:{effect['effect']['entity']}"
                symbolic_edges.append((node["symbol"], target, "writes"))
        elif node["kind"] == "test":
            for step in node["steps"]:
                symbolic_edges.append(
                    (node["symbol"], f"action:{step['action']}", "exercises")
                )
            for expected in node["expects"]:
                target = f"entity:{expected['expectation']['entity']}"
                symbolic_edges.append((node["symbol"], target, "asserts"))

    edges: list[dict[str, Any]] = []
    for source_symbol, target_symbol, kind in sorted(set(symbolic_edges)):
        payload = {
            "from": symbols[source_symbol],
            "to": symbols[target_symbol],
            "fromSymbol": source_symbol,
            "toSymbol": target_symbol,
            "kind": kind,
        }
        edges.append({"id": content_address(payload), **payload})
    return edges


def build_obligations(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    obligations: list[dict[str, Any]] = []
    for node in nodes:
        if node["kind"] == "action":
            for ensure in node["ensures"]:
                payload = {
                    "kind": "postcondition",
                    "owner": node["id"],
                    "ownerSymbol": node["symbol"],
                    "condition": ensure["condition"],
                }
                obligations.append({"id": content_address(payload), **payload})
        elif node["kind"] == "test":
            for expected in node["expects"]:
                payload = {
                    "kind": "example",
                    "owner": node["id"],
                    "ownerSymbol": node["symbol"],
                    "expectation": expected["expectation"],
                }
                obligations.append({"id": content_address(payload), **payload})
    return sorted(obligations, key=lambda item: item["id"])


def slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
