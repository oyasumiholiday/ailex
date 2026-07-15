from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

from intentir import __version__
from intentir.canonical import canonical_json
from intentir.compiler import (
    compile_path as compile_program_path,
    compile_source,
    load_program,
)
from intentir.formatter import format_source
from intentir.generators.typescript import generate_typescript
from intentir.migration import MigrationError, apply_migration, plan_migration
from intentir.parser import ParseError
from intentir.reports import (
    generate_parse_error_report,
    generate_program_validation_report,
)
from intentir.storage import (
    SQLiteStateRepository,
    StorageError,
    empty_storage_schema,
    storage_schema,
    storage_schema_hash,
)
from intentir.sqlite_projection import render_sqlite_ddl
from intentir.validator import ValidationError
from intentir.verifier import normalize_state, run_action, run_function, verify_ir


COMMANDS = {
    "check",
    "test",
    "call",
    "run",
    "migrate",
    "build",
    "fmt",
    "report",
    "ir",
}


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] not in COMMANDS and arguments[0] not in {
        "-h",
        "--help",
        "--version",
    }:
        legacy_main(arguments)
        return

    parser = build_parser()
    args = parser.parse_args(arguments)
    if not args.command:
        parser.print_help()
        return

    handlers = {
        "check": command_check,
        "test": command_test,
        "call": command_call,
        "run": command_run,
        "migrate": command_migrate,
        "build": command_build,
        "fmt": command_fmt,
        "report": command_report,
        "ir": command_ir,
    }
    handlers[args.command](args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intentir",
        description="Compile, check, call, run, and format IntentIR programs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")

    check = commands.add_parser("check", help="statically validate a program")
    check.add_argument("source", type=Path)
    check.add_argument("--json", action="store_true", help="emit structured output")

    test = commands.add_parser("test", help="run executable IntentIR tests")
    test.add_argument("source", type=Path)
    test.add_argument("--json", action="store_true", help="emit structured output")

    call = commands.add_parser("call", help="evaluate one pure function")
    call.add_argument("source", type=Path)
    call.add_argument("function")
    call.add_argument(
        "--input",
        default="{}",
        help="JSON object or @path/to/input.json",
    )

    run = commands.add_parser("run", help="execute one action against a JSON store")
    run.add_argument("source", type=Path)
    run.add_argument("action")
    run.add_argument(
        "--input",
        default="{}",
        help="JSON object or @path/to/input.json",
    )
    state_source = run.add_mutually_exclusive_group()
    state_source.add_argument("--state", type=Path, help="JSON state file")
    state_source.add_argument("--db", type=Path, help="persistent SQLite database")
    run.add_argument("--write-state", type=Path, help="write resulting JSON state")

    migrate = commands.add_parser("migrate", help="plan or apply a SQLite schema migration")
    migrate.add_argument("source", type=Path)
    migrate.add_argument("--db", type=Path, required=True)
    migrate.add_argument("--apply", action="store_true", help="apply the migration")
    migrate.add_argument(
        "--allow-destructive",
        action="store_true",
        help="allow entity or field removal",
    )
    migrate.add_argument("--json", action="store_true", help="emit structured output")

    build = commands.add_parser("build", help="compile a program")
    build.add_argument("source", type=Path)
    build.add_argument(
        "--target", choices=("typescript", "ir", "sqlite"), default="typescript"
    )
    build.add_argument("-o", "--output", type=Path)

    fmt = commands.add_parser("fmt", help="format IntentIR source")
    fmt.add_argument("source", type=Path)
    fmt_mode = fmt.add_mutually_exclusive_group()
    fmt_mode.add_argument("-w", "--write", action="store_true")
    fmt_mode.add_argument("--check", action="store_true")

    report = commands.add_parser("report", help="generate a Japanese validation report")
    report.add_argument("source", type=Path)
    report.add_argument("-o", "--output", type=Path)

    ir = commands.add_parser("ir", help="emit semantic IR as JSON")
    ir.add_argument("source", type=Path)
    ir.add_argument("--canonical", action="store_true")
    return parser


def command_check(args: argparse.Namespace) -> None:
    try:
        ir = compile_program_path(args.source)
    except (ParseError, ValidationError) as error:
        if args.json:
            print(json.dumps(error_payload(error), indent=2, ensure_ascii=False))
        else:
            print_error(error)
        raise SystemExit(1) from error

    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "module": ir["module"],
                    "schemaVersion": ir["schemaVersion"],
                    "canonicalHash": ir["canonicalHash"],
                    "diagnostics": [],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"OK: {ir['module']} ({ir['canonicalHash']})")


def command_test(args: argparse.Namespace) -> None:
    ir = compile_path(args.source)
    result = verify_ir(ir)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        for test in result["tests"]:
            print(f"{'ok' if test['ok'] else 'FAIL'}  {test['name']}")
            for error in test["errors"]:
                print(f"      {error['messageJa']}")
        summary = result["summary"]
        print(
            f"{summary['passed']} passed, {summary['failed']} failed, "
            f"{summary['tests']} total"
        )
        for example in result["functionExamples"]:
            print(f"{'ok' if example['ok'] else 'FAIL'}  {example['name']}")
            for error in example["errors"]:
                print(f"      {error['messageJa']}")
        if result["functionExamples"]:
            print(
                f"{summary['functionExamplesPassed']} function examples passed, "
                f"{summary['functionExamplesFailed']} failed, "
                f"{summary['functionExamples']} total"
            )
    if not result["ok"]:
        raise SystemExit(1)


def command_call(args: argparse.Namespace) -> None:
    ir = compile_path(args.source)
    try:
        inputs = load_json_argument(args.input)
        result = run_function(ir, args.function, inputs)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["ok"]:
        raise SystemExit(1)


def command_run(args: argparse.Namespace) -> None:
    ir = compile_path(args.source)
    try:
        inputs = load_json_argument(args.input)
        if args.db:
            if args.write_state:
                raise ValueError("--write-state cannot be combined with --db")
            with SQLiteStateRepository(args.db) as repository:
                with repository.transaction():
                    state = repository.load(ir)
                    result = run_action(ir, args.action, inputs, state)
                    write_mode = None
                    if result["ok"]:
                        if state is None:
                            repository.save(ir, result["state"])
                            write_mode = "replace"
                        else:
                            write_mode = repository.save_changes(
                                ir,
                                state,
                                result["state"],
                                set(result["affected"]),
                            )
                    stored = repository.inspect(ir["module"])
            result["storage"] = {
                "kind": "sqlite",
                "format": stored["storageFormat"] if stored else None,
                "path": str(args.db),
                "writeMode": write_mode,
            }
        else:
            state = load_json_file(args.state) if args.state else None
            result = run_action(ir, args.action, inputs, state)
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["ok"] and args.write_state:
        write_text(
            args.write_state,
            json.dumps(result["state"], indent=2, ensure_ascii=False) + "\n",
        )
    if not result["ok"]:
        raise SystemExit(1)


def command_migrate(args: argparse.Namespace) -> None:
    ir = compile_path(args.source)
    try:
        with SQLiteStateRepository(args.db) as repository:
            with repository.transaction():
                stored = repository.inspect(ir["module"])
                if stored is None:
                    source_schema = empty_storage_schema()
                    state: dict[str, Any] = {}
                    source_present = False
                else:
                    source_schema = stored["schema"]
                    state = stored["state"]
                    source_present = True
                    if source_schema is None:
                        if stored["schemaHash"] != storage_schema_hash(ir):
                            raise StorageError(
                                "legacy database has no schema snapshot; "
                                "migrate through the matching v0.5 source first"
                            )
                        source_schema = storage_schema(ir)

                plan = plan_migration(
                    source_schema,
                    ir,
                    source_present=source_present,
                )
                applied = False
                normalized = state
                if args.apply:
                    migrated = apply_migration(
                        state,
                        plan,
                        allow_destructive=args.allow_destructive,
                    )
                    normalized = normalize_state(ir, migrated)
                    repository.save(ir, normalized)
                    applied = True
        result = {
            "ok": True,
            "applied": applied,
            "database": str(args.db),
            "plan": plan,
            "records": {
                entity: len(records) for entity, records in sorted(normalized.items())
            },
        }
    except (OSError, ValueError, MigrationError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(render_migration_result(result))


def command_build(args: argparse.Namespace) -> None:
    ir = compile_path(args.source)
    if args.target == "typescript":
        content = generate_typescript(ir)
        suffix = ".ts"
    elif args.target == "sqlite":
        content = render_sqlite_ddl(ir["module"], storage_schema(ir))
        suffix = ".sql"
    else:
        content = json.dumps(ir, indent=2, ensure_ascii=False) + "\n"
        suffix = ".ir.json"
    output = args.output or args.source.with_suffix(suffix)
    write_text(output, content)
    print(output)


def command_fmt(args: argparse.Namespace) -> None:
    source = read_source(args.source)
    try:
        formatted = format_source(source)
    except ParseError as error:
        print_error(error)
        raise SystemExit(1) from error
    if args.check:
        if formatted != source:
            print(f"needs formatting: {args.source}", file=sys.stderr)
            raise SystemExit(1)
        print(f"formatted: {args.source}")
    elif args.write:
        write_text(args.source, formatted)
    else:
        print(formatted, end="")


def command_report(args: argparse.Namespace) -> None:
    try:
        program = load_program(args.source)
    except ParseError as error:
        report = generate_parse_error_report(error, str(args.source))
    else:
        report = generate_program_validation_report(program, str(args.source))
    if args.output:
        write_text(args.output, report)
        print(args.output)
    else:
        print(report, end="")


def command_ir(args: argparse.Namespace) -> None:
    ir = compile_path(args.source)
    print(canonical_json(ir) if args.canonical else json.dumps(ir, indent=2, ensure_ascii=False))


def render_migration_result(result: dict[str, Any]) -> str:
    plan = result["plan"]
    lines = [
        f"Migration {plan['id']}",
        f"  {plan['fromSchemaHash'] or '(new database)'} -> {plan['toSchemaHash']}",
    ]
    if plan["operations"]:
        for operation in plan["operations"]:
            lines.append(
                f"  [{operation['safety']}] {operation['descriptionJa']}"
            )
    else:
        lines.append("  no schema changes")
    summary = plan["summary"]
    lines.append(
        f"  safe={summary['safe']} destructive={summary['destructive']} "
        f"manual={summary['manual']}"
    )
    if result["applied"]:
        lines.append("Applied successfully.")
    elif not plan["applicable"]:
        lines.append("Not applicable automatically: manual values are required.")
    elif plan["requiresDestructiveApproval"]:
        lines.append("Review the plan, then use --apply --allow-destructive.")
    else:
        lines.append("Review the plan, then use --apply.")
    return "\n".join(lines)


def legacy_main(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Compile IntentIR specs.")
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--emit",
        choices=("ir", "canonical", "typescript", "verify", "report"),
        default="ir",
    )
    args = parser.parse_args(arguments)
    if args.emit == "report":
        try:
            program = load_program(args.source)
        except ParseError as error:
            report = generate_parse_error_report(error, str(args.source))
        else:
            report = generate_program_validation_report(program, str(args.source))
        print(report, end="")
        return

    ir = compile_path(args.source)
    if args.emit == "ir":
        print(json.dumps(ir, indent=2, ensure_ascii=False))
    elif args.emit == "canonical":
        print(canonical_json(ir))
    elif args.emit == "typescript":
        print(generate_typescript(ir), end="")
    else:
        result = verify_ir(ir)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not result["ok"]:
            raise SystemExit(1)


def compile_path(path: Path) -> dict[str, Any]:
    try:
        return compile_program_path(path)
    except (ParseError, ValidationError) as error:
        print_error(error)
        raise SystemExit(1) from error


def compile_text(source: str) -> dict[str, Any]:
    try:
        return compile_source(source)
    except (ParseError, ValidationError) as error:
        print_error(error)
        raise SystemExit(1) from error


def error_payload(error: ParseError | ValidationError) -> dict[str, Any]:
    if isinstance(error, ValidationError):
        diagnostics = [diagnostic.to_dict() for diagnostic in error.diagnostics]
    else:
        code = getattr(error, "code", "parse_error")
        path = getattr(error, "path", "/")
        diagnostics = [
            {
                "code": code,
                "severity": "error",
                "message": str(error),
                "messageJa": (
                    f"Import解決エラー: {error}"
                    if code != "parse_error"
                    else f"構文エラー: {error}"
                ),
                "path": path,
                "scope": [],
            }
        ]
    return {"ok": False, "diagnostics": diagnostics}


def print_error(error: ParseError | ValidationError) -> None:
    if isinstance(error, ValidationError):
        for diagnostic in error.diagnostics:
            print(
                f"{diagnostic.path}: [{diagnostic.code}] {diagnostic.message_ja}",
                file=sys.stderr,
            )
    else:
        code = getattr(error, "code", None)
        prefix = f"[{code}] Import解決エラー" if code else "構文エラー"
        print(f"{prefix}: {error}", file=sys.stderr)


def read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def load_json_argument(source: str) -> Any:
    if source.startswith("@"):
        return load_json_file(Path(source[1:]))
    return json.loads(source)


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
