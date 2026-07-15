from __future__ import annotations

import ast
import re
from dataclasses import replace

from intentir.ir import (
    ActionSpec,
    EntitySpec,
    FieldSpec,
    FunctionSpec,
    ImportSpec,
    ProgramSpec,
    TestSpec,
)


class ParseError(ValueError):
    pass


FIELD_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<type>[A-Za-z_][A-Za-z0-9_]*)(?P<rest>.*)$"
)
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_source(source: str) -> ProgramSpec:
    lines = logical_lines(source)
    if not lines:
        raise ParseError("empty source")

    module_line = lines[0]
    if module_line.indent != 0 or not module_line.text.startswith("module "):
        raise ParseError("first statement must be: module <Name>")
    module = module_line.text.removeprefix("module ").strip()
    if not module:
        raise ParseError("module name is required")
    if not IDENTIFIER_RE.fullmatch(module):
        raise ParseError(f"invalid module name on line {module_line.number}: {module}")

    entities: list[EntitySpec] = []
    functions: list[FunctionSpec] = []
    actions: list[ActionSpec] = []
    tests: list[TestSpec] = []
    imports: list[ImportSpec] = []
    seen_definition = False

    index = 1
    while index < len(lines):
        line = lines[index]
        if line.indent != 0:
            raise ParseError(f"unexpected indentation on line {line.number}")

        if line.text.startswith("import "):
            if seen_definition:
                raise ParseError(
                    f"imports must appear before definitions on line {line.number}"
                )
            import_spec = parse_import(line)
            if import_spec.path in {item.path for item in imports}:
                raise ParseError(
                    f"duplicate import on line {line.number}: {import_spec.path}"
                )
            imports.append(import_spec)
            index += 1
        elif line.text.startswith("entity ") and line.text.endswith(":"):
            seen_definition = True
            entity, index = parse_entity(lines, index)
            entities.append(entity)
        elif line.text.startswith("function ") and line.text.endswith(":"):
            seen_definition = True
            function, index = parse_function(lines, index)
            functions.append(function)
        elif line.text.startswith("action ") and line.text.endswith(":"):
            seen_definition = True
            action, index = parse_action(lines, index)
            actions.append(action)
        elif line.text.startswith("test ") and line.text.endswith(":"):
            seen_definition = True
            test, index = parse_test(lines, index)
            tests.append(test)
        else:
            raise ParseError(f"unknown top-level statement on line {line.number}: {line.text}")

    return ProgramSpec(
        module=module,
        entities=[replace(entity, defined_in=module) for entity in entities],
        functions=[replace(function, defined_in=module) for function in functions],
        actions=[replace(action, defined_in=module) for action in actions],
        tests=[replace(test, defined_in=module) for test in tests],
        imports=imports,
    )


def parse_import(line: "Line") -> ImportSpec:
    source = line.text.removeprefix("import ").strip()
    try:
        path = ast.literal_eval(source)
    except (SyntaxError, ValueError) as error:
        raise ParseError(
            f"import path must be a quoted string on line {line.number}"
        ) from error
    if not isinstance(path, str) or not path:
        raise ParseError(f"import path is required on line {line.number}")
    return ImportSpec(path=path)


def parse_entity(lines: list["Line"], index: int) -> tuple[EntitySpec, int]:
    name = identifier_block_name(lines[index], "entity")
    fields: list[FieldSpec] = []
    index += 1
    while index < len(lines) and lines[index].indent > 0:
        line = lines[index]
        if line.indent != 2:
            raise ParseError(f"entity fields must be indented by two spaces on line {line.number}")
        fields.append(parse_field(line.text, line.number))
        index += 1
    return EntitySpec(name=name, fields=fields), index


def parse_function(lines: list["Line"], index: int) -> tuple[FunctionSpec, int]:
    name = identifier_block_name(lines[index], "function")
    inputs: list[FieldSpec] = []
    return_type: str | None = None
    body: str | None = None
    examples: list[str] = []

    index += 1
    while index < len(lines) and lines[index].indent > 0:
        section = lines[index]
        if section.indent != 2:
            raise ParseError(
                f"function entries must be indented by two spaces on line {section.number}"
            )
        if section.text.startswith("returns:"):
            if return_type is not None:
                raise ParseError(f"duplicate function returns on line {section.number}")
            return_type = section.text.removeprefix("returns:").strip()
            if not IDENTIFIER_RE.fullmatch(return_type):
                raise ParseError(f"invalid return type on line {section.number}")
            index += 1
            continue
        if section.text.startswith("body:"):
            if body is not None:
                raise ParseError(f"duplicate function body on line {section.number}")
            body = section.text.removeprefix("body:").strip()
            if not body:
                raise ParseError(f"function body is required on line {section.number}")
            index += 1
            continue
        if section.text not in {"input:", "examples:"}:
            raise ParseError(
                f"unknown function section on line {section.number}: {section.text}"
            )

        section_name = section.text[:-1]
        index += 1
        values: list[tuple[str, int]] = []
        while index < len(lines) and lines[index].indent > 2:
            item = lines[index]
            if item.indent != 4:
                raise ParseError(
                    f"function section entries must be indented by four spaces on line {item.number}"
                )
            values.append((item.text, item.number))
            index += 1
        if section_name == "input":
            inputs.extend(parse_field(value, number) for value, number in values)
        else:
            examples.extend(value for value, _number in values)

    if return_type is None:
        raise ParseError(f"function {name} is missing returns")
    if body is None:
        raise ParseError(f"function {name} is missing body")
    return FunctionSpec(name, inputs, return_type, body, examples), index


def parse_action(lines: list["Line"], index: int) -> tuple[ActionSpec, int]:
    name = identifier_block_name(lines[index], "action")
    inputs: list[FieldSpec] = []
    requires: list[str] = []
    effects: list[str] = []
    ensures: list[str] = []

    index += 1
    while index < len(lines) and lines[index].indent > 0:
        section = lines[index]
        if section.indent != 2 or not section.text.endswith(":"):
            raise ParseError(f"action section expected on line {section.number}")
        section_name = section.text[:-1]
        index += 1

        values: list[str] = []
        while index < len(lines) and lines[index].indent > 2:
            item = lines[index]
            if item.indent != 4:
                raise ParseError(f"action section entries must be indented by four spaces on line {item.number}")
            values.append(item.text)
            index += 1

        if section_name == "input":
            inputs.extend(parse_field(value, section.number) for value in values)
        elif section_name == "requires":
            requires.extend(values)
        elif section_name == "effects":
            effects.extend(values)
        elif section_name == "ensures":
            ensures.extend(values)
        else:
            raise ParseError(f"unknown action section on line {section.number}: {section_name}")

    return ActionSpec(name=name, inputs=inputs, requires=requires, effects=effects, ensures=ensures), index


def parse_test(lines: list["Line"], index: int) -> tuple[TestSpec, int]:
    raw_name = block_name(lines[index], "test")
    if raw_name.startswith('"'):
        try:
            name = ast.literal_eval(raw_name)
        except (SyntaxError, ValueError) as error:
            raise ParseError(f"invalid test name on line {lines[index].number}: {raw_name}") from error
        if not isinstance(name, str) or not name:
            raise ParseError(f"test name is required on line {lines[index].number}")
    else:
        name = raw_name
    whens: list[str] = []
    expects: list[str] = []

    index += 1
    while index < len(lines) and lines[index].indent > 0:
        line = lines[index]
        if line.indent != 2:
            raise ParseError(f"test entries must be indented by two spaces on line {line.number}")
        if line.text.startswith("when "):
            whens.append(line.text.removeprefix("when ").strip())
        elif line.text.startswith("expect "):
            expects.append(line.text.removeprefix("expect ").strip())
        else:
            raise ParseError(f"unknown test entry on line {line.number}: {line.text}")
        index += 1

    if not whens:
        raise ParseError(f"test {name!r} is missing a when entry")
    return TestSpec(name=name, whens=whens, expects=expects), index


def parse_field(text: str, line_number: int) -> FieldSpec:
    match = FIELD_RE.match(text)
    if not match:
        raise ParseError(f"invalid field declaration on line {line_number}: {text}")

    rest = match.group("rest").strip()
    required = False
    default: str | None = None
    key = False
    unique = False
    reference_entity: str | None = None
    reference_field: str | None = None

    if rest:
        tokens = rest.split()
        cursor = 0
        while cursor < len(tokens):
            token = tokens[cursor]
            if token == "required":
                required = True
                cursor += 1
            elif token == "key":
                key = True
                cursor += 1
            elif token == "unique":
                unique = True
                cursor += 1
            elif token == "ref":
                if cursor + 1 >= len(tokens):
                    raise ParseError(f"reference target missing on line {line_number}")
                target = tokens[cursor + 1]
                parts = target.split(".")
                if (
                    len(parts) != 2
                    or not IDENTIFIER_RE.fullmatch(parts[0])
                    or not IDENTIFIER_RE.fullmatch(parts[1])
                ):
                    raise ParseError(
                        f"invalid reference target on line {line_number}: {target}"
                    )
                if reference_entity is not None:
                    raise ParseError(f"duplicate reference on line {line_number}")
                reference_entity, reference_field = parts
                cursor += 2
            elif token == "default":
                if cursor + 1 >= len(tokens):
                    raise ParseError(f"default value missing on line {line_number}")
                default = " ".join(tokens[cursor + 1 :])
                break
            else:
                raise ParseError(f"unknown field modifier on line {line_number}: {token}")

    return FieldSpec(
        name=match.group("name"),
        type_name=match.group("type"),
        required=required,
        default=default,
        key=key,
        unique=unique,
        reference_entity=reference_entity,
        reference_field=reference_field,
    )


def block_name(line: "Line", keyword: str) -> str:
    name = line.text.removeprefix(keyword).strip()
    if name.endswith(":"):
        name = name[:-1].strip()
    if not name:
        raise ParseError(f"{keyword} name is required on line {line.number}")
    return name


def identifier_block_name(line: "Line", keyword: str) -> str:
    name = block_name(line, keyword)
    if not IDENTIFIER_RE.fullmatch(name):
        raise ParseError(f"invalid {keyword} name on line {line.number}: {name}")
    return name


def logical_lines(source: str) -> list["Line"]:
    result: list[Line] = []
    for number, raw in enumerate(source.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        leading = raw[: len(raw) - len(raw.lstrip())]
        if "\t" in leading:
            raise ParseError(f"tabs are not allowed for indentation on line {number}")
        indent = len(leading)
        result.append(Line(number=number, indent=indent, text=raw.strip()))
    return result


class Line:
    def __init__(self, number: int, indent: int, text: str) -> None:
        self.number = number
        self.indent = indent
        self.text = text
