from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from intentir.expressions import (
    ExpressionError,
    parse_call,
    parse_effect,
    parse_ensure,
    parse_expectation,
    parse_literal,
    parse_requirement,
    referenced_affected_fields,
    referenced_created_fields,
    referenced_entity_fields,
    referenced_inputs,
)
from intentir.ir import ActionSpec, EntitySpec, FieldSpec, ProgramSpec, TestSpec, slug


BUILTIN_TYPES = {"Boolean", "Integer", "Number", "Text", "UUID"}
T = TypeVar("T", bound="NamedSpec")


class NamedSpec(Protocol):
    name: str


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    message_ja: str
    path: str
    scope: tuple[str, ...] = ()
    hint: str | None = None
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "messageJa": self.message_ja,
            "path": self.path,
            "scope": list(self.scope),
        }
        if self.hint:
            data["hint"] = self.hint
        return data


class ValidationError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__("\n".join(diagnostic.message for diagnostic in diagnostics))


def validate_program(program: ProgramSpec) -> None:
    diagnostics = collect_diagnostics(program)
    if diagnostics:
        raise ValidationError(diagnostics)


def collect_diagnostics(program: ProgramSpec) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    entities = index_named(program.entities, "entity", "/entities", diagnostics)
    actions = index_named(program.actions, "action", "/actions", diagnostics)
    index_named(program.tests, "test", "/tests", diagnostics)
    validate_test_symbols(program.tests, diagnostics)

    for entity in program.entities:
        validate_entity(entity, diagnostics)
    for action in program.actions:
        validate_action(action, entities, diagnostics)
    for test in program.tests:
        validate_test(test, actions, entities, diagnostics)
    return diagnostics


def validate_entity(entity: EntitySpec, diagnostics: list[Diagnostic]) -> None:
    field_names: set[str] = set()
    key_fields: list[str] = []
    for field in entity.fields:
        path = f"/entities/{entity.name}/fields/{field.name}"
        if field.name in field_names:
            diagnostics.append(
                make_diagnostic(
                    "duplicate_field",
                    f"entity {entity.name} defines field {field.name} more than once",
                    f"Entity `{entity.name}` の Field `{field.name}` が重複しています。",
                    path,
                    field_names,
                    "Remove or rename one of the fields.",
                )
            )
        field_names.add(field.name)
        validate_type(field.type_name, path, diagnostics)
        validate_default(field, path, diagnostics)
        if field.key:
            key_fields.append(field.name)
            if not field.required:
                diagnostics.append(
                    make_diagnostic(
                        "key_requires_required",
                        f"key field {entity.name}.{field.name} must be required",
                        f"Key Field `{entity.name}.{field.name}` は `required` である必要があります。",
                        path,
                        ("required",),
                        "Add the `required` modifier.",
                    )
                )
            if field.default is not None:
                diagnostics.append(
                    make_diagnostic(
                        "key_default_not_allowed",
                        f"key field {entity.name}.{field.name} cannot have a default",
                        f"Key Field `{entity.name}.{field.name}` にデフォルト値は指定できません。",
                        path,
                        (),
                        "Remove the default and provide the key explicitly.",
                    )
                )
    if len(key_fields) > 1:
        diagnostics.append(
            make_diagnostic(
                "multiple_entity_keys",
                f"entity {entity.name} defines multiple key fields",
                f"Entity `{entity.name}` に複数のKey Fieldがあります。",
                f"/entities/{entity.name}/fields",
                key_fields,
                "Keep one key field and mark additional identifiers as unique.",
            )
        )


def validate_action(
    action: ActionSpec,
    entities: dict[str, EntitySpec],
    diagnostics: list[Diagnostic],
) -> None:
    path = f"/actions/{action.name}"
    inputs = index_fields(action.inputs, action.name, diagnostics)
    for input_spec in action.inputs:
        input_path = f"{path}/inputs/{input_spec.name}"
        validate_type(input_spec.type_name, input_path, diagnostics)
        validate_default(input_spec, input_path, diagnostics)
        if input_spec.key or input_spec.unique:
            diagnostics.append(
                make_diagnostic(
                    "input_constraint_not_allowed",
                    f"action input {action.name}.{input_spec.name} cannot be key or unique",
                    f"Action Input `{action.name}.{input_spec.name}` に `key` または `unique` は指定できません。",
                    input_path,
                    (),
                    "Move identity constraints to an entity field.",
                )
            )

    parsed_requirements: list[dict[str, Any]] = []
    parsed_effects: list[dict[str, Any]] = []
    for index, requirement in enumerate(action.requires):
        condition = parse_or_diagnose(
            parse_requirement,
            requirement,
            "unsupported_requirement",
            f"{path}/requires/{index}",
            action.name,
            diagnostics,
        )
        if condition:
            parsed_requirements.append(condition)
            validate_condition(action, condition, inputs, entities, "requires", diagnostics)

    guaranteed_inputs = {
        condition["target"]["name"]
        for condition in parsed_requirements
        if condition.get("kind") == "not_empty"
        and condition.get("target", {}).get("kind") == "input"
    }

    for index, effect_source in enumerate(action.effects):
        effect = parse_or_diagnose(
            parse_effect,
            effect_source,
            "unsupported_effect",
            f"{path}/effects/{index}",
            action.name,
            diagnostics,
        )
        if effect:
            parsed_effects.append(effect)
            validate_effect(
                action,
                effect,
                inputs,
                guaranteed_inputs,
                entities,
                index,
                diagnostics,
            )

    inserted = [effect["entity"] for effect in parsed_effects if effect["op"] == "insert"]
    affected = [effect["entity"] for effect in parsed_effects]
    for index, ensure in enumerate(action.ensures):
        condition = parse_or_diagnose(
            parse_ensure,
            ensure,
            "unsupported_ensure",
            f"{path}/ensures/{index}",
            action.name,
            diagnostics,
        )
        if condition:
            validate_condition(action, condition, inputs, entities, "ensures", diagnostics)
            for entity_name, _ in referenced_created_fields(condition):
                count = inserted.count(entity_name)
                if count == 0:
                    diagnostics.append(
                        make_diagnostic(
                            "unbound_created_entity",
                            f"action {action.name} references created {entity_name} but does not insert it",
                            f"Action `{action.name}` は `{entity_name}` を生成していないため `created {entity_name}` を参照できません。",
                            f"{path}/ensures/{index}",
                            inserted,
                            f"Add `insert {entity_name}` or change the postcondition.",
                        )
                    )
                elif count > 1:
                    diagnostics.append(
                        make_diagnostic(
                            "ambiguous_created_entity",
                            f"action {action.name} creates {entity_name} more than once",
                            f"Action `{action.name}` は `{entity_name}` を複数生成するため参照先が曖昧です。",
                            f"{path}/ensures/{index}",
                            inserted,
                            "Create each entity type at most once per action.",
                        )
                    )
            for entity_name, _ in referenced_affected_fields(condition):
                count = affected.count(entity_name)
                if count == 0:
                    diagnostics.append(
                        make_diagnostic(
                            "unbound_affected_entity",
                            f"action {action.name} references affected {entity_name} but has no effect on it",
                            f"Action `{action.name}` は `{entity_name}` を変更していないため `affected {entity_name}` を参照できません。",
                            f"{path}/ensures/{index}",
                            affected,
                            f"Add an effect for `{entity_name}` or change the postcondition.",
                        )
                    )
                elif count > 1:
                    diagnostics.append(
                        make_diagnostic(
                            "ambiguous_affected_entity",
                            f"action {action.name} affects {entity_name} more than once",
                            f"Action `{action.name}` は `{entity_name}` を複数回変更するため参照先が曖昧です。",
                            f"{path}/ensures/{index}",
                            affected,
                            "Use at most one effect per referenced entity type.",
                        )
                    )


def validate_test(
    test: TestSpec,
    actions: dict[str, ActionSpec],
    entities: dict[str, EntitySpec],
    diagnostics: list[Diagnostic],
) -> None:
    path = f"/tests/{test.name}"
    for step_index, source in enumerate(test.whens):
        validate_test_step(test, source, step_index, actions, diagnostics)

    validate_test_expectations(test, entities, diagnostics)


def validate_test_step(
    test: TestSpec,
    source: str,
    step_index: int,
    actions: dict[str, ActionSpec],
    diagnostics: list[Diagnostic],
) -> None:
    path = f"/tests/{test.name}/steps/{step_index}"
    try:
        call = parse_call(source)
    except ExpressionError as error:
        diagnostics.append(
            make_diagnostic(
                "invalid_test_call",
                f"test {test.name} has invalid when expression: {error}",
                f"Test `{test.name}` の `when` 式が不正です: {error}",
                path,
                actions,
                "Use ActionName(input=value) with named scalar inputs.",
            )
        )
        return

    action_name = call["action"]
    action = actions.get(action_name)
    if not action:
        diagnostics.append(
            make_diagnostic(
                "unknown_action",
                f"test {test.name} calls unknown action {action_name}",
                f"Test `{test.name}` が未定義の Action `{action_name}` を呼び出しています。",
                f"{path}/action",
                actions,
                "Choose an action from scope.",
            )
        )
        return

    inputs = {input_spec.name: input_spec for input_spec in action.inputs}
    seen: set[str] = set()
    for arg in call["args"]:
        name = arg["name"]
        if name in seen:
            diagnostics.append(
                make_diagnostic(
                    "duplicate_test_input",
                    f"test {test.name} passes input {name} more than once",
                    f"Test `{test.name}` が Input `{name}` を重複指定しています。",
                    f"{path}/args/{name}",
                    inputs,
                    "Pass each named input once.",
                )
            )
        seen.add(name)
        input_spec = inputs.get(name)
        if not input_spec:
            diagnostics.append(
                make_diagnostic(
                    "unknown_test_input",
                    f"test {test.name} passes unknown input {name} to action {action_name}",
                    f"Test `{test.name}` が Action `{action_name}` に未定義の Input `{name}` を渡しています。",
                    f"{path}/args/{name}",
                    inputs,
                    "Choose an input from scope.",
                )
            )
        elif not literal_matches_type(arg["value"], input_spec.type_name):
            add_literal_type_mismatch(
                diagnostics,
                arg["value"],
                input_spec.type_name,
                f"{path}/args/{name}",
            )

    for input_spec in action.inputs:
        if input_spec.required and input_spec.name not in seen and input_spec.default is None:
            diagnostics.append(
                make_diagnostic(
                    "missing_test_input",
                    f"test {test.name} omits required input {input_spec.name}",
                    f"Test `{test.name}` に必須 Input `{input_spec.name}` がありません。",
                    f"{path}/args",
                    inputs,
                    f"Pass `{input_spec.name}=...`.",
                )
            )


def validate_test_expectations(
    test: TestSpec,
    entities: dict[str, EntitySpec],
    diagnostics: list[Diagnostic],
) -> None:
    path = f"/tests/{test.name}"
    if not test.expects:
        diagnostics.append(
            make_diagnostic(
                "empty_test",
                f"test {test.name} has no expectations",
                f"Test `{test.name}` に期待値がありません。",
                f"{path}/expects",
                (),
                "Add at least one `expect` entry.",
            )
        )
    for index, expected_source in enumerate(test.expects):
        try:
            expected = parse_expectation(expected_source)
        except ExpressionError as error:
            diagnostics.append(
                make_diagnostic(
                    "unsupported_expectation",
                    f"test {test.name} has {error}",
                    f"Test `{test.name}` の期待式には対応していません: `{expected_source}`",
                    f"{path}/expects/{index}",
                    entities,
                    "Use `Entity exists`, `no Entity exists`, or `Entity count equals N`.",
                )
            )
            continue
        validate_expectation(test, expected, entities, index, diagnostics)


def validate_condition(
    action: ActionSpec,
    condition: dict[str, Any],
    inputs: dict[str, FieldSpec],
    entities: dict[str, EntitySpec],
    section: str,
    diagnostics: list[Diagnostic],
) -> None:
    path = f"/actions/{action.name}/{section}"
    for input_name in referenced_inputs(condition):
        if input_name not in inputs:
            diagnostics.append(
                make_diagnostic(
                    "unknown_input",
                    f"action {action.name} {section} unknown input {input_name}",
                    f"Action `{action.name}` の `{section}` が未定義の Input `{input_name}` を参照しています。",
                    path,
                    inputs,
                    "Choose an input from scope.",
                )
            )

    for entity_name, field_name in referenced_created_fields(condition):
        validate_entity_field_reference(
            action, entity_name, field_name, entities, path, diagnostics
        )
    for entity_name, field_name in referenced_affected_fields(condition):
        validate_entity_field_reference(
            action, entity_name, field_name, entities, path, diagnostics
        )
    for entity_name, field_name in referenced_entity_fields(condition):
        validate_entity_field_reference(
            action, entity_name, field_name, entities, path, diagnostics
        )

    if condition.get("kind") == "not_empty":
        target_name = condition["target"]["name"]
        target = inputs.get(target_name)
        if target and target.type_name not in {"Text", "UUID"}:
            diagnostics.append(
                make_diagnostic(
                    "condition_type_mismatch",
                    f"not_empty expects Text but {target_name} is {target.type_name}",
                    f"`not empty` は Text/UUID 用ですが `{target_name}` は `{target.type_name}` です。",
                    path,
                    ("Text", "UUID"),
                    "Use a text input or another condition.",
                )
            )
    elif condition.get("kind") == "equals":
        left_type = expression_type(condition["left"], inputs, entities)
        right_type = expression_type(condition["right"], inputs, entities)
        if left_type and right_type and not compatible_types(left_type, right_type):
            diagnostics.append(
                make_diagnostic(
                    "condition_type_mismatch",
                    f"equals compares incompatible types {left_type} and {right_type}",
                    f"`equals` が互換性のない型 `{left_type}` と `{right_type}` を比較しています。",
                    path,
                    (left_type, right_type),
                    "Compare values with compatible types.",
                )
            )


def validate_effect(
    action: ActionSpec,
    effect: dict[str, Any],
    inputs: dict[str, FieldSpec],
    guaranteed_inputs: set[str],
    entities: dict[str, EntitySpec],
    index: int,
    diagnostics: list[Diagnostic],
) -> None:
    path = f"/actions/{action.name}/effects/{index}"
    entity_name = effect["entity"]
    entity = entities.get(entity_name)
    if not entity:
        diagnostics.append(
            make_diagnostic(
                "unknown_effect_entity",
                f"action {action.name} effect references unknown entity {entity_name}",
                f"Action `{action.name}` の Effect が未定義の Entity `{entity_name}` を参照しています。",
                path,
                entities,
                "Choose an entity from scope.",
            )
        )
        return
    if effect["op"] in {"update", "delete"}:
        validate_condition(
            action,
            effect["where"],
            inputs,
            entities,
            f"effects/{index}/where",
            diagnostics,
        )
        where_value = effect["where"]["right"]
        if where_value.get("kind") not in {"input", "literal"}:
            add_unsupported_effect_value(action, where_value, path, diagnostics)
        selector_name = effect["where"]["left"]["field"]
        selector = next(
            (field for field in entity.fields if field.name == selector_name), None
        )
        if selector and not (selector.key or selector.unique):
            diagnostics.append(
                make_diagnostic(
                    "non_unique_effect_selector",
                    f"action {action.name} {effect['op']} selector {entity_name}.{selector_name} is not unique",
                    f"Action `{action.name}` の `{effect['op']}` は一意でない Field `{entity_name}.{selector_name}` を対象にしています。",
                    f"{path}/where",
                    tuple(
                        field.name
                        for field in entity.fields
                        if field.key or field.unique
                    ),
                    "Select by a key or unique field.",
                )
            )

        if effect["op"] == "update":
            validate_update_assignments(
                action, effect, entity, inputs, entities, path, diagnostics
            )
        return

    for field in entity.fields:
        input_spec = inputs.get(field.name)
        if input_spec and input_spec.type_name != field.type_name:
            diagnostics.append(
                make_diagnostic(
                    "effect_binding_type_mismatch",
                    f"action {action.name} input {field.name} is {input_spec.type_name} but {entity_name}.{field.name} is {field.type_name}",
                    f"Input `{field.name}` の型 `{input_spec.type_name}` は Field `{entity_name}.{field.name}` の型 `{field.type_name}` と一致しません。",
                    path,
                    (field.type_name,),
                    "Use the same type for the input and entity field.",
                )
            )
        if field.required and field.default is None and input_spec is None:
            diagnostics.append(
                make_diagnostic(
                    "missing_effect_binding",
                    f"action {action.name} cannot populate required field {entity_name}.{field.name}",
                    f"Action `{action.name}` は必須 Field `{entity_name}.{field.name}` の値を生成できません。",
                    path,
                    inputs,
                    f"Add input `{field.name}: {field.type_name}` or a field default.",
                )
            )
        elif (
            field.required
            and input_spec
            and not input_spec.required
            and input_spec.default is None
            and input_spec.name not in guaranteed_inputs
        ):
            diagnostics.append(
                make_diagnostic(
                    "optional_effect_binding",
                    f"action {action.name} may omit required field {entity_name}.{field.name}",
                    f"任意 Input `{field.name}` から必須 Field `{entity_name}.{field.name}` を生成するため、値が欠ける可能性があります。",
                    path,
                    guaranteed_inputs,
                    f"Mark input `{field.name}` required, give it a default, or add a not-empty precondition.",
                )
            )


def validate_update_assignments(
    action: ActionSpec,
    effect: dict[str, Any],
    entity: EntitySpec,
    inputs: dict[str, FieldSpec],
    entities: dict[str, EntitySpec],
    path: str,
    diagnostics: list[Diagnostic],
) -> None:
    fields = {field.name: field for field in entity.fields}
    seen: set[str] = set()
    for assignment in effect["set"]:
        field_name = assignment["field"]
        value = assignment["value"]
        assignment_path = f"{path}/set/{field_name}"
        if field_name in seen:
            diagnostics.append(
                make_diagnostic(
                    "duplicate_effect_assignment",
                    f"action {action.name} assigns {entity.name}.{field_name} more than once",
                    f"Action `{action.name}` が Field `{entity.name}.{field_name}` を重複更新しています。",
                    assignment_path,
                    fields,
                    "Assign each field at most once per update.",
                )
            )
        seen.add(field_name)

        field = fields.get(field_name)
        if not field:
            diagnostics.append(
                make_diagnostic(
                    "unknown_effect_field",
                    f"action {action.name} updates unknown field {entity.name}.{field_name}",
                    f"Action `{action.name}` が未定義の Field `{entity.name}.{field_name}` を更新しています。",
                    assignment_path,
                    fields,
                    "Choose a field from scope.",
                )
            )
            continue

        if field.key:
            diagnostics.append(
                make_diagnostic(
                    "key_update_not_allowed",
                    f"action {action.name} updates key field {entity.name}.{field_name}",
                    f"Action `{action.name}` はKey Field `{entity.name}.{field_name}` を更新できません。",
                    assignment_path,
                    (),
                    "Keep keys immutable or create a new entity.",
                )
            )

        for input_name in referenced_inputs(value):
            if input_name not in inputs:
                diagnostics.append(
                    make_diagnostic(
                        "unknown_input",
                        f"action {action.name} effect references unknown input {input_name}",
                        f"Action `{action.name}` の Effect が未定義の Input `{input_name}` を参照しています。",
                        assignment_path,
                        inputs,
                        "Choose an input from scope.",
                    )
                )
        if value.get("kind") not in {"input", "literal"}:
            add_unsupported_effect_value(action, value, assignment_path, diagnostics)
            continue
        value_type = expression_type(value, inputs, entities)
        if value_type and not compatible_types(field.type_name, value_type):
            diagnostics.append(
                make_diagnostic(
                    "effect_assignment_type_mismatch",
                    f"action {action.name} assigns {value_type} to {entity.name}.{field_name} ({field.type_name})",
                    f"Action `{action.name}` は `{field.type_name}` 型の `{entity.name}.{field_name}` に `{value_type}` を代入しています。",
                    assignment_path,
                    (field.type_name,),
                    "Assign a value with a compatible type.",
                )
            )


def add_unsupported_effect_value(
    action: ActionSpec,
    value: dict[str, Any],
    path: str,
    diagnostics: list[Diagnostic],
) -> None:
    diagnostics.append(
        make_diagnostic(
            "unsupported_effect_value",
            f"action {action.name} uses unsupported {value.get('kind')} value in an effect",
            f"Action `{action.name}` の Effect では `{value.get('kind')}` 値を使用できません。",
            path,
            ("input", "literal"),
            "Use an input reference or scalar literal.",
        )
    )


def validate_entity_field_reference(
    action: ActionSpec,
    entity_name: str,
    field_name: str,
    entities: dict[str, EntitySpec],
    path: str,
    diagnostics: list[Diagnostic],
) -> None:
    entity = entities.get(entity_name)
    if not entity:
        diagnostics.append(
            make_diagnostic(
                "unknown_entity",
                f"action {action.name} references unknown entity {entity_name}",
                f"Action `{action.name}` が未定義の Entity `{entity_name}` を参照しています。",
                path,
                entities,
                "Choose an entity from scope.",
            )
        )
        return
    fields = {field.name for field in entity.fields}
    if field_name not in fields:
        diagnostics.append(
            make_diagnostic(
                "unknown_field",
                f"action {action.name} references unknown field {entity_name}.{field_name}",
                f"Action `{action.name}` が未定義の Field `{entity_name}.{field_name}` を参照しています。",
                path,
                fields,
                "Choose a field from scope.",
            )
        )


def validate_expectation(
    test: TestSpec,
    expectation: dict[str, Any],
    entities: dict[str, EntitySpec],
    index: int,
    diagnostics: list[Diagnostic],
) -> None:
    path = f"/tests/{test.name}/expects/{index}"
    entity_name = expectation["entity"]
    entity = entities.get(entity_name)
    if not entity:
        diagnostics.append(
            make_diagnostic(
                "unknown_expected_entity",
                f"test {test.name} expects unknown entity {entity_name}",
                f"Test `{test.name}` が未定義の Entity `{entity_name}` を期待しています。",
                path,
                entities,
                "Choose an entity from scope.",
            )
        )
        return
    where = expectation.get("where")
    if not where:
        return
    field_name = where["left"]["field"]
    fields = {field.name: field for field in entity.fields}
    field = fields.get(field_name)
    if not field:
        diagnostics.append(
            make_diagnostic(
                "unknown_expected_field",
                f"test {test.name} expects unknown field {entity_name}.{field_name}",
                f"Test `{test.name}` が未定義の Field `{entity_name}.{field_name}` を期待しています。",
                path,
                fields,
                "Choose a field from scope.",
            )
        )
    elif not literal_matches_type(where["right"], field.type_name):
        add_literal_type_mismatch(diagnostics, where["right"], field.type_name, path)


def parse_or_diagnose(
    parser: Any,
    source: str,
    code: str,
    path: str,
    action_name: str,
    diagnostics: list[Diagnostic],
) -> dict[str, Any] | None:
    try:
        return parser(source)
    except ExpressionError as error:
        diagnostics.append(
            make_diagnostic(
                code,
                f"action {action_name} has {error}",
                f"Action `{action_name}` の式には対応していません: `{source}`",
                path,
                (),
                "Use a supported structured expression.",
            )
        )
        return None


def validate_type(type_name: str, path: str, diagnostics: list[Diagnostic]) -> None:
    if type_name not in BUILTIN_TYPES:
        diagnostics.append(
            make_diagnostic(
                "unknown_type",
                f"{path} uses unknown type {type_name}",
                f"`{path}` が未定義の型 `{type_name}` を使用しています。",
                path,
                BUILTIN_TYPES,
                "Choose a type from scope.",
            )
        )


def validate_default(field: FieldSpec, path: str, diagnostics: list[Diagnostic]) -> None:
    if field.default is None:
        return
    try:
        literal = parse_literal(field.default)
    except ExpressionError:
        diagnostics.append(
            make_diagnostic(
                "invalid_default",
                f"{path} has invalid default {field.default}",
                f"`{path}` のデフォルト値 `{field.default}` は不正です。",
                path,
                (),
                "Use a scalar literal compatible with the field type.",
            )
        )
        return
    if not literal_matches_type(literal, field.type_name):
        add_literal_type_mismatch(diagnostics, literal, field.type_name, path)


def expression_type(
    expression: dict[str, Any],
    inputs: dict[str, FieldSpec],
    entities: dict[str, EntitySpec],
) -> str | None:
    kind = expression.get("kind")
    if kind == "literal":
        return expression["type"]
    if kind == "input":
        field = inputs.get(expression["name"])
        return field.type_name if field else None
    if kind in {"created_field", "affected_field", "entity_field"}:
        entity = entities.get(expression["entity"])
        if entity:
            field = next((field for field in entity.fields if field.name == expression["field"]), None)
            return field.type_name if field else None
    return None


def literal_matches_type(literal: dict[str, Any], type_name: str) -> bool:
    literal_type = literal.get("type")
    if type_name in {"Text", "UUID"}:
        return literal_type == "Text"
    if type_name == "Number":
        return literal_type in {"Integer", "Number"}
    return literal_type == type_name


def compatible_types(left: str, right: str) -> bool:
    if left == right:
        return True
    return {left, right} <= {"Integer", "Number"} or {left, right} <= {
        "Text",
        "UUID",
    }


def add_literal_type_mismatch(
    diagnostics: list[Diagnostic],
    literal: dict[str, Any],
    expected: str,
    path: str,
) -> None:
    actual = literal.get("type", "Unknown")
    diagnostics.append(
        make_diagnostic(
            "literal_type_mismatch",
            f"{path} expects {expected} but literal is {actual}",
            f"`{path}` は `{expected}` を期待していますが、値は `{actual}` です。",
            path,
            (expected,),
            "Use a literal compatible with the declared type.",
        )
    )


def index_fields(
    fields: list[FieldSpec],
    action_name: str,
    diagnostics: list[Diagnostic],
) -> dict[str, FieldSpec]:
    result: dict[str, FieldSpec] = {}
    for field in fields:
        if field.name in result:
            diagnostics.append(
                make_diagnostic(
                    "duplicate_input",
                    f"action {action_name} defines input {field.name} more than once",
                    f"Action `{action_name}` の Input `{field.name}` が重複しています。",
                    f"/actions/{action_name}/inputs/{field.name}",
                    result,
                    "Remove or rename one of the inputs.",
                )
            )
        result[field.name] = field
    return result


def index_named(
    items: list[T],
    kind: str,
    path: str,
    diagnostics: list[Diagnostic],
) -> dict[str, T]:
    result: dict[str, T] = {}
    for item in items:
        if item.name in result:
            diagnostics.append(
                make_diagnostic(
                    f"duplicate_{kind}",
                    f"{kind} {item.name} is defined more than once",
                    f"{kind.title()} `{item.name}` が重複定義されています。",
                    f"{path}/{item.name}",
                    result,
                    f"Remove or rename one of the {kind}s.",
                )
            )
        result[item.name] = item
    return result


def validate_test_symbols(tests: list[TestSpec], diagnostics: list[Diagnostic]) -> None:
    symbols: dict[str, str] = {}
    for test in tests:
        symbol = slug(test.name)
        previous = symbols.get(symbol)
        if previous and previous != test.name:
            diagnostics.append(
                make_diagnostic(
                    "test_symbol_collision",
                    f"tests {previous} and {test.name} have the same symbol {symbol}",
                    f"Test `{previous}` と `{test.name}` の正規化後シンボル `{symbol}` が衝突します。",
                    f"/tests/{test.name}",
                    symbols,
                    "Rename one test so their slugs differ.",
                )
            )
        symbols[symbol] = test.name


def make_diagnostic(
    code: str,
    message: str,
    message_ja: str,
    path: str,
    scope: Any,
    hint: str | None,
) -> Diagnostic:
    if isinstance(scope, dict):
        values = tuple(sorted(str(key) for key in scope))
    else:
        values = tuple(sorted(str(value) for value in scope))
    return Diagnostic(code, message, message_ja, path, values, hint)
