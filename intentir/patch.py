from __future__ import annotations

import difflib
import json
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from intentir.canonical import content_address
from intentir.compiler import compile_path, compile_path_source, compile_source
from intentir.formatter import format_program
from intentir.ir import (
    ActionSpec,
    CapabilityOperationSpec,
    CapabilitySpec,
    CapabilityUseSpec,
    CapabilityValueSpec,
    EntitySpec,
    FieldSpec,
    FunctionSpec,
    ProgramSpec,
    TestSpec,
    slug,
)
from intentir.parser import (
    IDENTIFIER_RE,
    ParseError,
    parse_capability_use,
    parse_capability_value,
    parse_field,
    parse_source,
)
from intentir.validator import Diagnostic, ValidationError
from intentir.verifier import verify_ir


PATCH_SCHEMA_VERSION = "0.13.0"
PATCH_KINDS = {
    "add_definition",
    "replace_definition",
    "remove_definition",
    "rename_symbol",
    "set_member",
    "insert_member",
    "remove_member",
}
OPERATION_FIELDS = {
    "add_definition": {"kind", "target", "value"},
    "replace_definition": {"kind", "target", "expectedId", "value"},
    "remove_definition": {"kind", "target", "expectedId"},
    "rename_symbol": {"kind", "target", "expectedId", "name"},
    "set_member": {"kind", "target", "expectedId", "member", "value"},
    "insert_member": {
        "kind",
        "target",
        "expectedId",
        "member",
        "value",
        "index",
    },
    "remove_member": {"kind", "target", "expectedId", "member"},
}
REQUESTED_OBLIGATIONS = {"static", "affected-tests", "all-tests"}
DEFINITION_ATTRIBUTES = {
    "capability": "capabilities",
    "entity": "entities",
    "function": "functions",
    "action": "actions",
    "test": "tests",
}


@dataclass(frozen=True)
class PatchPlan:
    result: dict[str, Any]
    source: str
    original_source: str


class PatchError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__("\n".join(item.message for item in diagnostics))


def plan_patch_source(
    source: str,
    envelope: Any,
    *,
    source_name: str = "<memory>",
) -> PatchPlan:
    root = parse_source(source)
    current_ir = compile_source(source)
    return _plan_patch(
        root,
        source,
        current_ir,
        envelope,
        compile_source,
        source_name,
    )


def plan_patch_path(path: Path | str, envelope: Any) -> PatchPlan:
    source_path = Path(path).expanduser().resolve()
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as error:
        fail(
            "patch_source_read_error",
            f"cannot read patch target {source_path}: {error}",
            f"Patch対象 `{source_path}` を読み込めません: {error}",
            "/source",
        )
    root = parse_source(source)
    current_ir = compile_path(source_path)
    return _plan_patch(
        root,
        source,
        current_ir,
        envelope,
        lambda candidate: compile_path_source(source_path, candidate),
        str(source_path),
    )


def patch_path(
    path: Path | str,
    envelope: Any,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    source_path = Path(path).expanduser().resolve()
    plan = plan_patch_path(source_path, envelope)
    if apply:
        try:
            current_source = source_path.read_text(encoding="utf-8")
        except OSError as error:
            fail(
                "patch_source_read_error",
                f"cannot re-read patch target {source_path}: {error}",
                f"書込み前にPatch対象 `{source_path}` を再読込できません: {error}",
                "/source",
            )
        if current_source != plan.original_source:
            fail(
                "concurrent_source_change",
                "source changed after the patch was validated",
                "Patch検証後にSourceが変更されたため、書込みを中止しました。",
                "/source",
                hint="最新SourceのModule IDを取得してPatchを再生成してください。",
            )
        atomic_write_text(source_path, plan.source)
    return {**plan.result, "applied": apply}


def _plan_patch(
    root: ProgramSpec,
    original_source: str,
    current_ir: dict[str, Any],
    envelope: Any,
    compile_candidate: Callable[[str], dict[str, Any]],
    source_name: str,
) -> PatchPlan:
    patch = validate_envelope(envelope)
    if patch["baseModuleId"] != current_ir["moduleId"]:
        fail(
            "stale_base_module",
            "patch baseModuleId does not match the current module",
            "PatchのbaseModuleIdが現在のModule IDと一致しません。",
            "/baseModuleId",
            scope=(current_ir["moduleId"],),
            hint="最新のModule IDを取得してPatchを再生成してください。",
        )

    base_nodes = {node["symbol"]: node for node in current_ir["nodes"]}
    program = root
    for index, operation in enumerate(patch["operations"]):
        program = apply_operation(
            program,
            operation,
            index,
            base_nodes,
            root.module,
        )

    candidate_source = format_program(program)
    try:
        candidate_ir = compile_candidate(candidate_source)
    except ValidationError as error:
        raise PatchError(error.diagnostics) from error
    except ParseError as error:
        fail(
            "patch_result_parse_error",
            f"patched source does not parse: {error}",
            f"Patch後のSourceを構文解析できません: {error}",
            "/operations",
        )

    changed = changed_symbols(current_ir, candidate_ir)
    if not changed:
        fail(
            "patch_has_no_semantic_change",
            "patch does not change the semantic graph",
            "Patchによる意味Graphの変更がありません。",
            "/operations",
            hint="内容が変わるOperationだけを残してください。",
        )
    affected = affected_symbols(current_ir, candidate_ir, changed)
    verification, executed = execute_requested_obligations(
        candidate_ir,
        patch["requestedObligations"],
        affected,
    )
    if verification is not None and not verification["ok"]:
        failed = [
            item["name"]
            for item in [
                *verification["tests"],
                *verification["functionExamples"],
            ]
            if not item["ok"]
        ]
        fail(
            "patch_obligation_failed",
            f"patched program failed requested obligations: {', '.join(failed)}",
            "Patch後のProgramが要求された検証義務に失敗しました: "
            + ", ".join(failed),
            "/requestedObligations",
            scope=tuple(failed),
            hint="失敗したTestまたはFunction exampleを満たすようPatchを修正してください。",
        )

    normalized_patch = {
        "schemaVersion": patch["schemaVersion"],
        "baseModuleId": patch["baseModuleId"],
        "operations": patch["operations"],
        "requestedObligations": patch["requestedObligations"],
    }
    patch_id = content_address({"kind": "intent_patch", **normalized_patch})
    diff = "".join(
        difflib.unified_diff(
            original_source.splitlines(keepends=True),
            candidate_source.splitlines(keepends=True),
            fromfile=source_name,
            tofile=f"{source_name}.patched",
        )
    )
    result = {
        "ok": True,
        "schemaVersion": PATCH_SCHEMA_VERSION,
        "patchId": patch_id,
        "module": candidate_ir["module"],
        "baseModuleId": current_ir["moduleId"],
        "resultModuleId": candidate_ir["moduleId"],
        "baseCanonicalHash": current_ir["canonicalHash"],
        "resultCanonicalHash": candidate_ir["canonicalHash"],
        "changedSymbols": changed,
        "affectedSymbols": affected,
        "requestedObligations": patch["requestedObligations"],
        "executedObligations": executed,
        "diff": diff,
    }
    return PatchPlan(result=result, source=candidate_source, original_source=original_source)


def validate_envelope(envelope: Any) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        fail(
            "invalid_patch_envelope",
            "patch envelope must be a JSON object",
            "Patch EnvelopeはJSON Objectである必要があります。",
            "/",
        )
    allowed = {
        "schemaVersion",
        "baseModuleId",
        "operations",
        "requestedObligations",
    }
    unknown = sorted(set(envelope) - allowed)
    if unknown:
        fail(
            "unknown_patch_field",
            f"unknown patch fields: {', '.join(unknown)}",
            f"未知のPatch Fieldです: {', '.join(unknown)}",
            "/",
            scope=tuple(unknown),
        )
    if envelope.get("schemaVersion") != PATCH_SCHEMA_VERSION:
        fail(
            "unsupported_patch_schema",
            f"patch schemaVersion must be {PATCH_SCHEMA_VERSION}",
            f"Patch schemaVersionは `{PATCH_SCHEMA_VERSION}` である必要があります。",
            "/schemaVersion",
        )
    base_module_id = envelope.get("baseModuleId")
    if not isinstance(base_module_id, str) or not base_module_id.startswith("sha256:"):
        fail(
            "invalid_base_module_id",
            "baseModuleId must be a sha256 content address",
            "baseModuleIdにはsha256 Content Addressが必要です。",
            "/baseModuleId",
        )
    operations = envelope.get("operations")
    if not isinstance(operations, list) or not operations:
        fail(
            "empty_patch",
            "patch operations must be a non-empty array",
            "Patch operationsには1件以上のOperationが必要です。",
            "/operations",
        )
    normalized_operations: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            fail(
                "invalid_patch_operation",
                "patch operation must be a JSON object",
                "Patch OperationはJSON Objectである必要があります。",
                f"/operations/{index}",
            )
        kind = operation.get("kind")
        if kind not in PATCH_KINDS:
            fail(
                "unknown_patch_operation",
                f"unknown patch operation: {kind}",
                f"未知のPatch Operationです: {kind}",
                f"/operations/{index}/kind",
                scope=tuple(sorted(PATCH_KINDS)),
            )
        unknown_fields = sorted(set(operation) - OPERATION_FIELDS[kind])
        if unknown_fields:
            fail(
                "unknown_patch_operation_field",
                f"unknown fields for {kind}: {', '.join(unknown_fields)}",
                f"{kind}では使用できないFieldです: {', '.join(unknown_fields)}",
                f"/operations/{index}",
                scope=tuple(unknown_fields),
                hint="Operation Schemaに含まれるFieldだけを送信してください。",
            )
        normalized_operations.append(dict(operation))

    requested = envelope.get("requestedObligations", ["static"])
    if not isinstance(requested, list) or not all(
        isinstance(item, str) for item in requested
    ):
        fail(
            "invalid_requested_obligations",
            "requestedObligations must be an array of strings",
            "requestedObligationsはString配列である必要があります。",
            "/requestedObligations",
        )
    unknown_obligations = sorted(set(requested) - REQUESTED_OBLIGATIONS)
    if unknown_obligations:
        fail(
            "unknown_requested_obligation",
            f"unknown requested obligations: {', '.join(unknown_obligations)}",
            f"未知の検証義務です: {', '.join(unknown_obligations)}",
            "/requestedObligations",
            scope=tuple(sorted(REQUESTED_OBLIGATIONS)),
        )
    normalized_requested = sorted(set(["static", *requested]))
    return {
        "schemaVersion": PATCH_SCHEMA_VERSION,
        "baseModuleId": base_module_id,
        "operations": normalized_operations,
        "requestedObligations": normalized_requested,
    }


def apply_operation(
    program: ProgramSpec,
    operation: dict[str, Any],
    index: int,
    base_nodes: dict[str, dict[str, Any]],
    root_module: str,
) -> ProgramSpec:
    kind = operation["kind"]
    path = f"/operations/{index}"
    if kind == "add_definition":
        definition = parse_definition_value(operation.get("value"), root_module, path)
        symbol = definition_symbol(definition)
        target = operation.get("target")
        if target is not None and target != symbol:
            fail(
                "patch_target_mismatch",
                f"operation target {target} does not match value symbol {symbol}",
                f"Operation target `{target}` とvalueのSymbol `{symbol}` が一致しません。",
                f"{path}/target",
            )
        if symbol in base_nodes or local_definition(program, symbol) is not None:
            fail(
                "definition_already_exists",
                f"definition already exists: {symbol}",
                f"Definition `{symbol}` はすでに存在します。",
                f"{path}/target",
            )
        return append_definition(program, definition)

    target = operation.get("target")
    if not isinstance(target, str) or ":" not in target:
        fail(
            "invalid_patch_target",
            "operation target must be a definition symbol",
            "Operation targetにはDefinition Symbolが必要です。",
            f"{path}/target",
        )
    base_node = base_nodes.get(target)
    if base_node is None:
        fail(
            "unknown_patch_target",
            f"unknown patch target: {target}",
            f"Patch対象 `{target}` が見つかりません。",
            f"{path}/target",
            scope=tuple(sorted(base_nodes)),
        )
    expected_id = operation.get("expectedId")
    if expected_id != base_node["id"]:
        fail(
            "stale_target_node",
            f"expectedId does not match current node for {target}",
            f"`{target}` のexpectedIdが現在のNode IDと一致しません。",
            f"{path}/expectedId",
            scope=(base_node["id"],),
            hint="最新Node IDを取得してOperationを再生成してください。",
        )
    if base_node.get("definedIn") != root_module:
        fail(
            "imported_patch_target",
            f"target {target} is defined in imported module {base_node.get('definedIn')}",
            f"`{target}` はImport先Module `{base_node.get('definedIn')}` の定義です。",
            f"{path}/target",
            hint="定義元FileをPatch対象にしてください。",
        )
    current = local_definition(program, target)
    if current is None:
        fail(
            "conflicting_patch_operation",
            f"an earlier operation already removed or renamed {target}",
            f"先行Operationが `{target}` を削除またはRenameしています。",
            f"{path}/target",
        )

    if kind == "replace_definition":
        replacement = parse_definition_value(operation.get("value"), root_module, path)
        if definition_symbol(replacement) != target:
            fail(
                "replacement_symbol_changed",
                "replace_definition cannot change a symbol; use rename_symbol",
                "replace_definitionではSymbolを変更できません。rename_symbolを使用してください。",
                f"{path}/value",
            )
        return replace_definition(program, target, replacement)
    if kind == "remove_definition":
        return remove_definition(program, target)
    if kind == "rename_symbol":
        new_name = operation.get("name")
        return rename_definition(
            program,
            target,
            new_name,
            path,
            base_nodes,
        )
    if kind in {"set_member", "insert_member", "remove_member"}:
        member = operation.get("member")
        if not isinstance(member, str) or not member:
            fail(
                "invalid_patch_member",
                "member operation requires a member path",
                "Member Operationにはmember pathが必要です。",
                f"{path}/member",
            )
        updated = apply_member_operation(current, operation, path)
        return replace_definition(program, target, updated)
    raise AssertionError(f"unhandled patch kind: {kind}")


def parse_definition_value(value: Any, module: str, path: str) -> Any:
    source = source_value(value, f"{path}/value")
    try:
        fragment = parse_source(f"module {module}\n\n{source.strip()}\n")
    except ParseError as error:
        fail(
            "invalid_definition_value",
            f"cannot parse definition value: {error}",
            f"Definition valueを構文解析できません: {error}",
            f"{path}/value",
        )
    definitions = all_definitions(fragment)
    if fragment.imports or len(definitions) != 1:
        fail(
            "invalid_definition_value",
            "definition value must contain exactly one definition",
            "Definition valueにはDefinitionを1件だけ指定してください。",
            f"{path}/value",
        )
    return replace(definitions[0], defined_in=module)


def apply_member_operation(spec: Any, operation: dict[str, Any], path: str) -> Any:
    kind = operation["kind"]
    member = operation["member"]
    collection, separator, selector = member.partition(".")
    if not separator:
        if kind == "set_member" and isinstance(spec, FunctionSpec):
            value = source_value(operation.get("value"), f"{path}/value").strip()
            if member == "body":
                return replace(spec, body=value)
            if member == "returnType":
                if not IDENTIFIER_RE.fullmatch(value):
                    fail(
                        "invalid_member_value",
                        f"invalid return type: {value}",
                        f"不正なReturn型です: {value}",
                        f"{path}/value",
                    )
                return replace(spec, return_type=value)
        if kind != "insert_member":
            fail(
                "member_selector_required",
                f"{kind} requires a selected member such as {member}.name",
                f"{kind}には `{member}.name` のような選択済みMemberが必要です。",
                f"{path}/member",
            )
        selector = ""

    items, parser, selector_for = collection_access(spec, collection, path)
    if kind == "insert_member":
        value = parser(operation.get("value"), f"{path}/value")
        insertion_index = operation.get("index", len(items))
        if (
            not isinstance(insertion_index, int)
            or isinstance(insertion_index, bool)
            or insertion_index < 0
            or insertion_index > len(items)
        ):
            fail(
                "invalid_member_index",
                f"member insertion index is out of range: {insertion_index}",
                f"Member挿入位置が範囲外です: {insertion_index}",
                f"{path}/index",
            )
        updated_items = [*items]
        updated_items.insert(insertion_index, value)
        return replace_collection(spec, collection, updated_items)

    item_index = find_member_index(items, selector, selector_for, path)
    updated_items = [*items]
    if kind == "set_member":
        updated_items[item_index] = parser(operation.get("value"), f"{path}/value")
    else:
        del updated_items[item_index]
    return replace_collection(spec, collection, updated_items)


def collection_access(
    spec: Any, collection: str, path: str
) -> tuple[list[Any], Callable[[Any, str], Any], Callable[[Any, int], str]]:
    if isinstance(spec, CapabilitySpec) and collection == "operations":
        return [*spec.operations], parse_operation_value, lambda item, _: item.name
    if isinstance(spec, EntitySpec) and collection == "fields":
        return [*spec.fields], parse_field_value, lambda item, _: item.name
    if isinstance(spec, FunctionSpec):
        if collection == "inputs":
            return [*spec.inputs], parse_field_value, lambda item, _: item.name
        if collection == "examples":
            return [*spec.examples], parse_text_value, lambda _item, index: str(index)
    if isinstance(spec, ActionSpec):
        if collection == "inputs":
            return [*spec.inputs], parse_field_value, lambda item, _: item.name
        if collection == "uses":
            return [*spec.uses], parse_use_value, lambda item, _: item.binding
        if collection in {"requires", "effects", "ensures"}:
            return (
                [*getattr(spec, collection)],
                parse_text_value,
                lambda _item, index: str(index),
            )
    if isinstance(spec, TestSpec):
        if collection == "givens":
            return (
                [*spec.givens],
                parse_given_value,
                lambda item, _: f"{item.capability}.{item.operation}",
            )
        attribute = "whens" if collection == "whens" else collection
        if attribute in {"whens", "expects"}:
            return (
                [*getattr(spec, attribute)],
                parse_text_value,
                lambda _item, index: str(index),
            )
    fail(
        "unsupported_patch_member",
        f"member collection {collection} is not valid for {type(spec).__name__}",
        f"`{type(spec).__name__}` ではMember Collection `{collection}` を編集できません。",
        f"{path}/member",
    )


def replace_collection(spec: Any, collection: str, items: list[Any]) -> Any:
    if isinstance(spec, CapabilitySpec) and collection == "operations":
        return replace(spec, operations=items)
    if isinstance(spec, EntitySpec) and collection == "fields":
        return replace(spec, fields=items)
    if isinstance(spec, FunctionSpec):
        if collection == "inputs":
            return replace(spec, inputs=items)
        if collection == "examples":
            return replace(spec, examples=items)
    if isinstance(spec, ActionSpec):
        if collection == "inputs":
            return replace(spec, inputs=items)
        if collection == "uses":
            return replace(spec, uses=items)
        if collection == "requires":
            return replace(spec, requires=items)
        if collection == "effects":
            return replace(spec, effects=items)
        if collection == "ensures":
            return replace(spec, ensures=items)
    if isinstance(spec, TestSpec):
        if collection == "givens":
            return replace(spec, givens=items)
        if collection == "whens":
            return replace(spec, whens=items)
        if collection == "expects":
            return replace(spec, expects=items)
    raise AssertionError(f"unsupported collection replacement: {collection}")


def find_member_index(
    items: list[Any],
    selector: str,
    selector_for: Callable[[Any, int], str],
    path: str,
) -> int:
    matches = [
        index for index, item in enumerate(items) if selector_for(item, index) == selector
    ]
    if len(matches) != 1:
        available = tuple(selector_for(item, index) for index, item in enumerate(items))
        fail(
            "unknown_patch_member",
            f"member selector {selector} matched {len(matches)} members",
            f"Member `{selector}` の一致数が {len(matches)} 件でした。",
            f"{path}/member",
            scope=available,
        )
    return matches[0]


def parse_field_value(value: Any, path: str) -> FieldSpec:
    if isinstance(value, dict) and "source" not in value:
        name = value.get("name")
        type_name = value.get("type")
        if not isinstance(name, str) or not isinstance(type_name, str):
            fail(
                "invalid_member_value",
                "field value requires string name and type",
                "Field valueにはStringのnameとtypeが必要です。",
                path,
            )
        reference = value.get("references") or {}
        default = value.get("default", _MISSING)
        return FieldSpec(
            name=name,
            type_name=type_name,
            required=bool(value.get("required", False)),
            default=None if default is _MISSING else json.dumps(default, ensure_ascii=False),
            key=bool(value.get("key", False)),
            unique=bool(value.get("unique", False)),
            reference_entity=reference.get("entity"),
            reference_field=reference.get("field"),
        )
    source = source_value(value, path).strip()
    try:
        return parse_field(source, 1)
    except ParseError as error:
        fail(
            "invalid_member_value",
            f"cannot parse field: {error}",
            f"Fieldを構文解析できません: {error}",
            path,
        )


def parse_operation_value(value: Any, path: str) -> CapabilityOperationSpec:
    if isinstance(value, dict) and "source" not in value:
        name = value.get("name")
        return_type = value.get("returnType")
        if isinstance(name, str) and isinstance(return_type, str):
            return CapabilityOperationSpec(name=name, return_type=return_type)
    source = source_value(value, path).strip()
    if source.startswith("operation "):
        source = source.removeprefix("operation ")
    parts = source.split()
    if len(parts) == 3 and parts[1] == "returns":
        return CapabilityOperationSpec(name=parts[0], return_type=parts[2])
    fail(
        "invalid_member_value",
        "operation value must be: operation <name> returns <Type>",
        "Operation valueは `operation <name> returns <Type>` 形式で指定してください。",
        path,
    )


def parse_use_value(value: Any, path: str) -> CapabilityUseSpec:
    if isinstance(value, dict) and "source" not in value:
        capability = value.get("capability")
        operation = value.get("operation")
        binding = value.get("binding")
        if all(isinstance(item, str) for item in (capability, operation, binding)):
            return CapabilityUseSpec(capability, operation, binding)
    source = source_value(value, path).strip()
    try:
        return parse_capability_use(source, 1)
    except ParseError as error:
        fail(
            "invalid_member_value",
            f"cannot parse capability use: {error}",
            f"Capability Useを構文解析できません: {error}",
            path,
        )


def parse_given_value(value: Any, path: str) -> CapabilityValueSpec:
    if isinstance(value, dict) and "source" not in value:
        capability = value.get("capability")
        operation = value.get("operation")
        if isinstance(capability, str) and isinstance(operation, str) and "value" in value:
            return CapabilityValueSpec(
                capability,
                operation,
                json.dumps(value["value"], ensure_ascii=False),
            )
    source = source_value(value, path).strip()
    if source.startswith("given "):
        source = source.removeprefix("given ")
    try:
        return parse_capability_value(source, 1)
    except ParseError as error:
        fail(
            "invalid_member_value",
            f"cannot parse capability value: {error}",
            f"Capability valueを構文解析できません: {error}",
            path,
        )


def parse_text_value(value: Any, path: str) -> str:
    return source_value(value, path).strip()


def source_value(value: Any, path: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("source"), str):
        return value["source"]
    fail(
        "missing_patch_value",
        "patch value requires a source string",
        "Patch valueにはsource Stringが必要です。",
        path,
    )


def rename_definition(
    program: ProgramSpec,
    target: str,
    new_name: Any,
    path: str,
    base_nodes: dict[str, dict[str, Any]],
) -> ProgramSpec:
    kind, old_name = target.split(":", 1)
    if not isinstance(new_name, str) or not new_name:
        fail(
            "invalid_symbol_name",
            "rename_symbol requires a non-empty name",
            "rename_symbolには空でないnameが必要です。",
            f"{path}/name",
        )
    if kind != "test" and not IDENTIFIER_RE.fullmatch(new_name):
        fail(
            "invalid_symbol_name",
            f"invalid identifier: {new_name}",
            f"不正な識別子です: {new_name}",
            f"{path}/name",
        )
    new_symbol = f"test:{slug(new_name)}" if kind == "test" else f"{kind}:{new_name}"
    if new_symbol != target and new_symbol in base_nodes:
        fail(
            "symbol_already_exists",
            f"symbol already exists: {new_symbol}",
            f"Symbol `{new_symbol}` はすでに存在します。",
            f"{path}/name",
        )

    current = local_definition(program, target)
    assert current is not None
    renamed = replace(current, name=new_name)
    result = replace_definition(program, target, renamed)

    if kind == "capability":
        result = replace(
            result,
            actions=[
                replace(
                    action,
                    uses=[
                        replace(use, capability=new_name)
                        if use.capability == old_name
                        else use
                        for use in action.uses
                    ],
                )
                for action in result.actions
            ],
            tests=[
                replace(
                    test,
                    givens=[
                        replace(given, capability=new_name)
                        if given.capability == old_name
                        else given
                        for given in test.givens
                    ],
                )
                for test in result.tests
            ],
        )
    elif kind == "entity":
        result = replace(
            result,
            entities=[
                replace(
                    entity,
                    fields=[
                        replace(field, reference_entity=new_name)
                        if field.reference_entity == old_name
                        else field
                        for field in entity.fields
                    ],
                )
                for entity in result.entities
            ],
            actions=[
                replace(
                    action,
                    requires=rename_in_values(action.requires, old_name, new_name),
                    effects=rename_in_values(action.effects, old_name, new_name),
                    ensures=rename_in_values(action.ensures, old_name, new_name),
                )
                for action in result.actions
            ],
            tests=[
                replace(
                    test,
                    expects=rename_in_values(test.expects, old_name, new_name),
                )
                for test in result.tests
            ],
        )
    elif kind == "function":
        result = replace(
            result,
            functions=[
                replace(
                    function,
                    body=rename_identifier(function.body, old_name, new_name),
                    examples=rename_in_values(function.examples, old_name, new_name),
                )
                for function in result.functions
            ],
            actions=[
                replace(
                    action,
                    requires=rename_in_values(action.requires, old_name, new_name),
                    effects=rename_in_values(action.effects, old_name, new_name),
                    ensures=rename_in_values(action.ensures, old_name, new_name),
                )
                for action in result.actions
            ],
        )
    elif kind == "action":
        result = replace(
            result,
            tests=[
                replace(
                    test,
                    whens=rename_in_values(test.whens, old_name, new_name),
                )
                for test in result.tests
            ],
        )
    return result


def rename_in_values(values: list[str], old_name: str, new_name: str) -> list[str]:
    return [rename_identifier(value, old_name, new_name) for value in values]


def rename_identifier(source: str, old_name: str, new_name: str) -> str:
    result: list[str] = []
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(source):
        char = source[index]
        if quote is not None:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            result.append(char)
            index += 1
            continue
        if char.isalpha() or char == "_":
            end = index + 1
            while end < len(source) and (source[end].isalnum() or source[end] == "_"):
                end += 1
            token = source[index:end]
            result.append(new_name if token == old_name else token)
            index = end
            continue
        result.append(char)
        index += 1
    return "".join(result)


def changed_symbols(
    before: dict[str, Any], after: dict[str, Any]
) -> list[str]:
    before_nodes = {
        node["symbol"]: node["id"]
        for node in before["nodes"]
        if node["kind"] != "module"
    }
    after_nodes = {
        node["symbol"]: node["id"]
        for node in after["nodes"]
        if node["kind"] != "module"
    }
    return sorted(
        symbol
        for symbol in set(before_nodes) | set(after_nodes)
        if before_nodes.get(symbol) != after_nodes.get(symbol)
    )


def affected_symbols(
    before: dict[str, Any],
    after: dict[str, Any],
    changed: list[str],
) -> list[str]:
    reverse: dict[str, set[str]] = {}
    for edge in [*before["edges"], *after["edges"]]:
        reverse.setdefault(edge["toSymbol"], set()).add(edge["fromSymbol"])
    affected = set(changed)
    pending = [*changed]
    while pending:
        symbol = pending.pop()
        for dependent in reverse.get(symbol, set()):
            if dependent not in affected:
                affected.add(dependent)
                pending.append(dependent)
    return sorted(affected)


def execute_requested_obligations(
    ir: dict[str, Any],
    requested: list[str],
    affected: list[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    executed = ["static"]
    if "all-tests" in requested:
        verification = verify_ir(ir)
        selected_symbols = {
            node["symbol"]
            for node in ir["nodes"]
            if node["kind"] in {"function", "test", "action"}
        }
    elif "affected-tests" in requested:
        selected_symbols = {
            symbol
            for symbol in affected
            if symbol.startswith(("function:", "test:"))
        }
        verification = verify_ir(ir, selected_symbols)
    else:
        return None, executed
    executed.extend(
        obligation["id"]
        for obligation in ir["obligations"]
        if obligation["ownerSymbol"] in selected_symbols
    )
    return verification, sorted(set(executed))


def definition_symbol(definition: Any) -> str:
    if isinstance(definition, CapabilitySpec):
        return f"capability:{definition.name}"
    if isinstance(definition, EntitySpec):
        return f"entity:{definition.name}"
    if isinstance(definition, FunctionSpec):
        return f"function:{definition.name}"
    if isinstance(definition, ActionSpec):
        return f"action:{definition.name}"
    if isinstance(definition, TestSpec):
        return f"test:{slug(definition.name)}"
    raise TypeError(f"unsupported definition: {type(definition).__name__}")


def all_definitions(program: ProgramSpec) -> list[Any]:
    return [
        *program.capabilities,
        *program.entities,
        *program.functions,
        *program.actions,
        *program.tests,
    ]


def local_definition(program: ProgramSpec, symbol: str) -> Any | None:
    return next(
        (item for item in all_definitions(program) if definition_symbol(item) == symbol),
        None,
    )


def append_definition(program: ProgramSpec, definition: Any) -> ProgramSpec:
    kind = definition_symbol(definition).split(":", 1)[0]
    attribute = DEFINITION_ATTRIBUTES[kind]
    return replace(program, **{attribute: [*getattr(program, attribute), definition]})


def replace_definition(program: ProgramSpec, symbol: str, replacement: Any) -> ProgramSpec:
    kind = symbol.split(":", 1)[0]
    attribute = DEFINITION_ATTRIBUTES[kind]
    items = [
        replacement if definition_symbol(item) == symbol else item
        for item in getattr(program, attribute)
    ]
    return replace(program, **{attribute: items})


def remove_definition(program: ProgramSpec, symbol: str) -> ProgramSpec:
    kind = symbol.split(":", 1)[0]
    attribute = DEFINITION_ATTRIBUTES[kind]
    items = [
        item for item in getattr(program, attribute) if definition_symbol(item) != symbol
    ]
    return replace(program, **{attribute: items})


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def fail(
    code: str,
    message: str,
    message_ja: str,
    path: str,
    *,
    scope: tuple[str, ...] = (),
    hint: str | None = None,
) -> None:
    raise PatchError(
        [
            Diagnostic(
                code=code,
                message=message,
                message_ja=message_ja,
                path=path,
                scope=scope,
                hint=hint,
            )
        ]
    )


_MISSING = object()
