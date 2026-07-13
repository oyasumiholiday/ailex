from __future__ import annotations

from intentir.ir import build_ir
from intentir.parser import parse_source
from intentir.validator import validate_program


def compile_source(source: str) -> dict:
    program = parse_source(source)
    validate_program(program)
    return build_ir(program)
