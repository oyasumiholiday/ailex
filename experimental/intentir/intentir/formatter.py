from __future__ import annotations

import json

from intentir.ir import (
    ActionSpec,
    EntitySpec,
    FieldSpec,
    FunctionSpec,
    ProgramSpec,
    TestSpec,
)
from intentir.parser import parse_source


def format_source(source: str) -> str:
    formatted = format_program(parse_source(source))
    return restore_comments(source, formatted)


def format_program(program: ProgramSpec) -> str:
    blocks = [f"module {program.module}"]
    blocks.extend(format_entity(entity) for entity in program.entities)
    blocks.extend(format_function(function) for function in program.functions)
    blocks.extend(format_action(action) for action in program.actions)
    blocks.extend(format_test(test) for test in program.tests)
    return "\n\n".join(blocks) + "\n"


def format_entity(entity: EntitySpec) -> str:
    lines = [f"entity {entity.name}:"]
    lines.extend(f"  {format_field(field)}" for field in entity.fields)
    return "\n".join(lines)


def format_function(function: FunctionSpec) -> str:
    lines = [f"function {function.name}:"]
    append_section(lines, "input", [format_field(field) for field in function.inputs])
    lines.append(f"  returns: {function.return_type}")
    lines.append(f"  body: {function.body}")
    append_section(lines, "examples", function.examples)
    return "\n".join(lines)


def format_action(action: ActionSpec) -> str:
    lines = [f"action {action.name}:"]
    append_section(lines, "input", [format_field(field) for field in action.inputs])
    append_section(lines, "requires", action.requires)
    append_section(lines, "effects", action.effects)
    append_section(lines, "ensures", action.ensures)
    return "\n".join(lines)


def format_test(test: TestSpec) -> str:
    name = json.dumps(test.name, ensure_ascii=False)
    lines = [f"test {name}:"]
    lines.extend(f"  when {when}" for when in test.whens)
    lines.extend(f"  expect {expect}" for expect in test.expects)
    return "\n".join(lines)


def format_field(field: FieldSpec) -> str:
    modifiers: list[str] = []
    if field.required:
        modifiers.append("required")
    if field.key:
        modifiers.append("key")
    elif field.unique:
        modifiers.append("unique")
    if field.default is not None:
        modifiers.extend(["default", field.default])
    suffix = f" {' '.join(modifiers)}" if modifiers else ""
    return f"{field.name}: {field.type_name}{suffix}"


def append_section(lines: list[str], name: str, values: list[str]) -> None:
    if not values:
        return
    lines.append(f"  {name}:")
    lines.extend(f"    {value}" for value in values)


def restore_comments(source: str, formatted: str) -> str:
    comments: dict[int, list[str]] = {}
    source_statements = 0
    for raw in source.splitlines():
        if raw.lstrip().startswith("#"):
            comments.setdefault(source_statements, []).append(raw.rstrip())
        elif raw.strip():
            source_statements += 1
    if not comments:
        return formatted

    formatted_lines = formatted.rstrip("\n").splitlines()
    formatted_statements = sum(1 for line in formatted_lines if line.strip())
    if source_statements != formatted_statements:
        return source if source.endswith("\n") else source + "\n"

    result: list[str] = []
    statement_index = 0
    for line in formatted_lines:
        if line.strip():
            result.extend(comments.get(statement_index, []))
            statement_index += 1
        result.append(line)
    result.extend(comments.get(statement_index, []))
    return "\n".join(result) + "\n"
