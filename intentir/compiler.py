from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from intentir.ir import ModuleSpec, ProgramSpec, build_ir
from intentir.parser import ParseError, parse_source
from intentir.validator import validate_program


class ImportResolutionError(ParseError):
    def __init__(self, code: str, message: str, path: str) -> None:
        self.code = code
        self.path = path
        super().__init__(message)


def compile_source(source: str) -> dict:
    program = parse_source(source)
    if program.imports:
        raise ParseError("imports require a source path; use compile_path")
    program = replace(
        program,
        modules=[ModuleSpec(name=program.module)],
    )
    validate_program(program)
    return build_ir(program)


def compile_path(path: Path | str) -> dict:
    program = load_program(path)
    validate_program(program)
    return build_ir(program)


def compile_path_source(path: Path | str, source: str) -> dict:
    """Compile an in-memory replacement for the root file with normal imports."""
    program = load_program(path, root_source=source)
    validate_program(program)
    return build_ir(program)


def load_program(path: Path | str, *, root_source: str | None = None) -> ProgramSpec:
    root_path = Path(path).expanduser().resolve()
    programs: dict[Path, ProgramSpec] = {}
    module_paths: dict[str, Path] = {}
    resolved_imports: dict[Path, list[str]] = {}
    loading: list[Path] = []
    order: list[Path] = []

    def visit(source_path: Path, imported_from: Path | None = None) -> ProgramSpec:
        resolved = source_path.expanduser().resolve()
        if resolved in loading:
            start = loading.index(resolved)
            cycle_paths = [*loading[start:], resolved]
            cycle = " -> ".join(
                programs[item].module if item in programs else item.name
                for item in cycle_paths
            )
            owner = programs[resolved].module if resolved in programs else resolved.name
            raise ImportResolutionError(
                "import_cycle",
                f"import cycle: {cycle}",
                f"/modules/{owner}/imports",
            )
        if resolved in resolved_imports:
            return programs[resolved]

        if resolved == root_path and root_source is not None:
            source = root_source
        else:
            try:
                source = resolved.read_text(encoding="utf-8")
            except OSError as error:
                if imported_from is None:
                    message = f"cannot read module {resolved}: {error}"
                    code = "source_read_error"
                    error_path = "/"
                else:
                    message = (
                        f"cannot read import {resolved} from {imported_from}: {error}"
                    )
                    code = "missing_import"
                    owner = programs[imported_from].module
                    error_path = f"/modules/{owner}/imports"
                raise ImportResolutionError(code, message, error_path) from error

        program = parse_source(source)
        existing_path = module_paths.get(program.module)
        if existing_path is not None and existing_path != resolved:
            raise ImportResolutionError(
                "duplicate_module",
                f"duplicate module name {program.module}: "
                f"{existing_path} and {resolved}",
                f"/modules/{program.module}",
            )
        programs[resolved] = program
        module_paths[program.module] = resolved
        loading.append(resolved)

        direct_imports: list[str] = []
        imported_paths: set[Path] = set()
        for import_spec in program.imports:
            import_path = Path(import_spec.path)
            if import_path.is_absolute():
                raise ImportResolutionError(
                    "absolute_import",
                    f"module {program.module} import must be relative: "
                    f"{import_spec.path}",
                    f"/modules/{program.module}/imports",
                )
            target = (resolved.parent / import_path).resolve()
            if target in imported_paths:
                raise ImportResolutionError(
                    "duplicate_import",
                    f"module {program.module} imports {target} more than once",
                    f"/modules/{program.module}/imports",
                )
            imported_paths.add(target)
            dependency = visit(target, resolved)
            direct_imports.append(dependency.module)

        loading.pop()
        resolved_imports[resolved] = direct_imports
        order.append(resolved)
        return program

    root = visit(root_path)
    return ProgramSpec(
        module=root.module,
        capabilities=[
            capability
            for source_path in order
            for capability in programs[source_path].capabilities
        ],
        entities=[
            entity for source_path in order for entity in programs[source_path].entities
        ],
        functions=[
            function
            for source_path in order
            for function in programs[source_path].functions
        ],
        actions=[
            action for source_path in order for action in programs[source_path].actions
        ],
        tests=[test for source_path in order for test in programs[source_path].tests],
        imports=root.imports,
        modules=[
            ModuleSpec(
                name=programs[source_path].module,
                imports=resolved_imports[source_path],
            )
            for source_path in order
        ],
    )
