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
from intentir.pure import (
    function_references,
    parse_function_example,
    parse_pure_expression,
)


SCHEMA_VERSION = "0.13.0"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type_name: str
    required: bool = False
    default: str | None = None
    key: bool = False
    unique: bool = False
    reference_entity: str | None = None
    reference_field: str | None = None

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
        if self.reference_entity and self.reference_field:
            data["references"] = {
                "entity": self.reference_entity,
                "field": self.reference_field,
            }
        return data


@dataclass(frozen=True)
class CapabilityOperationSpec:
    name: str
    return_type: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "returnType": self.return_type}


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    operations: list[CapabilityOperationSpec] = field(default_factory=list)
    defined_in: str = ""


@dataclass(frozen=True)
class CapabilityUseSpec:
    capability: str
    operation: str
    binding: str


@dataclass(frozen=True)
class CapabilityValueSpec:
    capability: str
    operation: str
    value: str


@dataclass(frozen=True)
class EntitySpec:
    name: str
    fields: list[FieldSpec] = field(default_factory=list)
    defined_in: str = ""


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    inputs: list[FieldSpec] = field(default_factory=list)
    return_type: str = ""
    body: str = ""
    examples: list[str] = field(default_factory=list)
    defined_in: str = ""


@dataclass(frozen=True)
class ActionSpec:
    name: str
    inputs: list[FieldSpec] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    effects: list[str] = field(default_factory=list)
    ensures: list[str] = field(default_factory=list)
    uses: list[CapabilityUseSpec] = field(default_factory=list)
    defined_in: str = ""


@dataclass(frozen=True)
class TestSpec:
    name: str
    whens: list[str] = field(default_factory=list)
    expects: list[str] = field(default_factory=list)
    givens: list[CapabilityValueSpec] = field(default_factory=list)
    defined_in: str = ""

    @property
    def when(self) -> str:
        return self.whens[0] if self.whens else ""


@dataclass(frozen=True)
class ImportSpec:
    path: str


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    imports: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProgramSpec:
    module: str
    capabilities: list[CapabilitySpec] = field(default_factory=list)
    entities: list[EntitySpec] = field(default_factory=list)
    functions: list[FunctionSpec] = field(default_factory=list)
    actions: list[ActionSpec] = field(default_factory=list)
    tests: list[TestSpec] = field(default_factory=list)
    imports: list[ImportSpec] = field(default_factory=list)
    modules: list[ModuleSpec] = field(default_factory=list)


def build_ir(program: ProgramSpec) -> dict[str, Any]:
    capability_index = {capability.name: capability for capability in program.capabilities}
    definition_nodes = [
        *[
            build_capability_node(capability, program.module)
            for capability in program.capabilities
        ],
        *[build_entity_node(entity, program.module) for entity in program.entities],
        *[
            build_function_node(function, program.module)
            for function in program.functions
        ],
        *[
            build_action_node(action, capability_index, program.module)
            for action in program.actions
        ],
        *[build_test_node(test, program.module) for test in program.tests],
    ]
    modules = program.modules or [ModuleSpec(name=program.module)]
    nodes = [*definition_nodes, *build_module_nodes(modules, definition_nodes)]
    nodes.sort(key=lambda node: node["symbol"])
    symbols = {node["symbol"]: node["id"] for node in nodes}

    edges = build_edges(nodes, symbols)
    obligations = build_obligations(nodes)
    module_id = symbols[f"module:{program.module}"]

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


def build_capability_node(
    capability: CapabilitySpec, default_module: str
) -> dict[str, Any]:
    payload = {
        "kind": "capability",
        "name": capability.name,
        "definedIn": capability.defined_in or default_module,
        "operations": sorted(
            (operation.to_dict() for operation in capability.operations),
            key=lambda item: item["name"],
        ),
    }
    return addressed_node(f"capability:{capability.name}", payload)


def build_entity_node(entity: EntitySpec, default_module: str) -> dict[str, Any]:
    payload = {
        "kind": "entity",
        "name": entity.name,
        "definedIn": entity.defined_in or default_module,
        "fields": sorted(
            (field_spec.to_dict() for field_spec in entity.fields),
            key=lambda item: item["name"],
        ),
    }
    return addressed_node(f"entity:{entity.name}", payload)


def build_function_node(
    function: FunctionSpec, default_module: str
) -> dict[str, Any]:
    expression = parse_pure_expression(function.body)
    body_payload = {"kind": "function_body", "expression": expression}
    body = {
        "id": content_address(body_payload),
        "source": function.body,
        **body_payload,
    }
    examples = [
        build_function_example(source) for source in function.examples
    ]
    payload = {
        "kind": "function",
        "name": function.name,
        "definedIn": function.defined_in or default_module,
        "inputs": [input_spec.to_dict() for input_spec in function.inputs],
        "returnType": function.return_type,
        "body": body,
        "examples": sorted(examples, key=lambda item: item["id"]),
        "capabilities": [],
    }
    return addressed_node(f"function:{function.name}", payload)


def build_function_example(source: str) -> dict[str, Any]:
    example = parse_function_example(source)
    payload = {
        "kind": "function_example",
        "call": example["call"],
        "expected": example["expected"],
    }
    return {"id": content_address(payload), "source": source, **payload}


def build_action_node(
    action: ActionSpec,
    capability_specs: dict[str, CapabilitySpec],
    default_module: str,
) -> dict[str, Any]:
    requires = [
        addressed_expression("precondition", expr, parse_requirement(expr))
        for expr in action.requires
    ]
    effects = [
        addressed_expression("effect", expr, parse_effect(expr))
        for expr in action.effects
    ]
    repository_capabilities = build_repository_capabilities(effects)
    ensures = [
        addressed_expression("postcondition", expr, parse_ensure(expr))
        for expr in action.ensures
    ]
    uses = [build_capability_use(use, capability_specs) for use in action.uses]
    payload = {
        "kind": "action",
        "name": action.name,
        "definedIn": action.defined_in or default_module,
        "inputs": sorted(
            (input_spec.to_dict() for input_spec in action.inputs),
            key=lambda item: item["name"],
        ),
        "requires": sorted(requires, key=lambda item: item["id"]),
        "effects": effects,
        "capabilities": repository_capabilities,
        "uses": sorted(uses, key=lambda item: item["binding"]),
        "ensures": sorted(ensures, key=lambda item: item["id"]),
    }
    return addressed_node(f"action:{action.name}", payload)


def build_capability_use(
    use: CapabilityUseSpec, capabilities: dict[str, CapabilitySpec]
) -> dict[str, Any]:
    capability = capabilities[use.capability]
    operation = next(
        item for item in capability.operations if item.name == use.operation
    )
    payload = {
        "kind": "capability_binding",
        "capability": use.capability,
        "operation": use.operation,
        "binding": use.binding,
        "type": operation.return_type,
    }
    return {"id": content_address(payload), **payload}


def build_test_node(test: TestSpec, default_module: str) -> dict[str, Any]:
    steps = [parse_call(when) for when in test.whens]
    expects = [
        addressed_expression("expectation", expr, parse_expectation(expr))
        for expr in test.expects
    ]
    givens = [build_capability_value(given) for given in test.givens]
    payload = {
        "kind": "test",
        "name": test.name,
        "definedIn": test.defined_in or default_module,
        "steps": steps,
        "givens": sorted(
            givens, key=lambda item: (item["capability"], item["operation"])
        ),
        "expects": sorted(expects, key=lambda item: item["id"]),
    }
    return addressed_node(f"test:{slug(test.name)}", payload)


def build_capability_value(given: CapabilityValueSpec) -> dict[str, Any]:
    payload = {
        "kind": "capability_stub",
        "capability": given.capability,
        "operation": given.operation,
        "value": literal_value(parse_literal(given.value)),
    }
    return {"id": content_address(payload), **payload}


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


def build_module_nodes(
    modules: list[ModuleSpec], definition_nodes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    modules_by_name = {module.name: module for module in modules}
    members_by_module: dict[str, list[dict[str, str]]] = {
        module.name: [] for module in modules
    }
    for node in definition_nodes:
        members_by_module.setdefault(node["definedIn"], []).append(
            {"symbol": node["symbol"], "memberId": node["id"]}
        )

    built: dict[str, dict[str, Any]] = {}
    building: set[str] = set()

    def build(module_name: str) -> dict[str, Any]:
        if module_name in built:
            return built[module_name]
        if module_name in building:
            raise ValueError(f"module cycle reached while building IR: {module_name}")
        module = modules_by_name.get(module_name)
        if module is None:
            raise ValueError(f"unknown linked module: {module_name}")

        building.add(module_name)
        dependencies = [build(name) for name in module.imports]
        payload = {
            "kind": "module",
            "name": module.name,
            "imports": sorted(
                (
                    {
                        "symbol": dependency["symbol"],
                        "moduleId": dependency["id"],
                    }
                    for dependency in dependencies
                ),
                key=lambda item: item["symbol"],
            ),
            "members": sorted(
                members_by_module.get(module.name, []),
                key=lambda item: item["symbol"],
            ),
        }
        node = addressed_node(f"module:{module.name}", payload)
        building.remove(module_name)
        built[module_name] = node
        return node

    for module in modules:
        build(module.name)
    return sorted(built.values(), key=lambda node: node["symbol"])


def build_edges(nodes: list[dict[str, Any]], symbols: dict[str, str]) -> list[dict[str, Any]]:
    symbolic_edges: list[tuple[str, str, str]] = []
    for node in nodes:
        if node["kind"] == "module":
            for dependency in node["imports"]:
                symbolic_edges.append(
                    (node["symbol"], dependency["symbol"], "imports")
                )
            for member in node["members"]:
                symbolic_edges.append(
                    (node["symbol"], member["symbol"], "defines")
                )
        elif node["kind"] == "entity":
            for field in node["fields"]:
                reference = field.get("references")
                if reference:
                    symbolic_edges.append(
                        (
                            node["symbol"],
                            f"entity:{reference['entity']}",
                            "references",
                        )
                    )
        elif node["kind"] == "function":
            for function_name in function_references(node["body"]["expression"]):
                target = f"function:{function_name}"
                symbolic_edges.append((node["symbol"], target, "calls"))
        elif node["kind"] == "action":
            for use in node["uses"]:
                symbolic_edges.append(
                    (
                        node["symbol"],
                        f"capability:{use['capability']}",
                        "uses",
                    )
                )
            for requirement in node["requires"]:
                for function_name in function_references(requirement["condition"]):
                    symbolic_edges.append(
                        (node["symbol"], f"function:{function_name}", "calls")
                    )
            for effect in node["effects"]:
                target = f"entity:{effect['effect']['entity']}"
                symbolic_edges.append((node["symbol"], target, "writes"))
                for function_name in function_references(effect["effect"]):
                    symbolic_edges.append(
                        (node["symbol"], f"function:{function_name}", "calls")
                    )
            for ensure in node["ensures"]:
                for function_name in function_references(ensure["condition"]):
                    symbolic_edges.append(
                        (node["symbol"], f"function:{function_name}", "calls")
                    )
        elif node["kind"] == "test":
            for given in node["givens"]:
                symbolic_edges.append(
                    (
                        node["symbol"],
                        f"capability:{given['capability']}",
                        "stubs",
                    )
                )
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
        if node["kind"] == "function":
            for example in node["examples"]:
                payload = {
                    "kind": "function_example",
                    "owner": node["id"],
                    "ownerSymbol": node["symbol"],
                    "call": example["call"],
                    "expected": example["expected"],
                }
                obligations.append({"id": content_address(payload), **payload})
        elif node["kind"] == "action":
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
