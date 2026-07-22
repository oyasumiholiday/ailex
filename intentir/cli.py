from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

from intentir import __version__
from intentir.agent import TOOL_NAMES, AgentService
from intentir.benchmark import (
    BENCHMARK_CONDITIONS,
    BenchmarkError,
    render_benchmark_output,
    run_benchmark_file,
)
from intentir.canonical import canonical_json
from intentir.compiler import (
    compile_path as compile_program_path,
    compile_source,
    load_program,
)
from intentir.demos.concurrent_agent import (
    ConcurrentAgentDemoError,
    render_concurrent_agent_demo,
    run_concurrent_agent_demo,
)
from intentir.formatter import format_source
from intentir.generators.typescript import generate_typescript
from intentir.migration import MigrationError, apply_migration, plan_migration
from intentir.model_adapter import ExternalCommandModelAdapter, ModelAdapterError
from intentir.patch import PatchError, patch_path
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
    "patch",
    "agent",
    "demo",
    "benchmark",
    "benchmark-model",
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
        "patch": command_patch,
        "agent": command_agent,
        "demo": command_demo,
        "benchmark": command_benchmark,
        "benchmark-model": command_benchmark_model,
        "build": command_build,
        "fmt": command_fmt,
        "report": command_report,
        "ir": command_ir,
    }
    handlers[args.command](args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intentir",
        description="Compile, verify, patch, and expose IntentIR programs to agents.",
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
    run.add_argument(
        "--capabilities",
        default="{}",
        help="JSON object of Capability.operation values or @path/to/file.json",
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

    patch = commands.add_parser(
        "patch", help="validate or atomically apply a semantic patch"
    )
    patch.add_argument("source", type=Path)
    patch.add_argument("patch", type=Path)
    patch.add_argument("--apply", action="store_true", help="write the patched source")
    patch.add_argument("--json", action="store_true", help="emit structured output")

    agent = commands.add_parser(
        "agent", help="invoke one model-independent structured agent tool"
    )
    agent.add_argument("tool", choices=TOOL_NAMES)
    agent.add_argument(
        "--arguments",
        default="{}",
        help="JSON object or @path/to/arguments.json",
    )
    agent.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="project root that bounds all source access",
    )
    agent.add_argument(
        "--allow-writes",
        action="store_true",
        help="explicitly enable source-writing agent tools",
    )

    demo = commands.add_parser(
        "demo", help="run a self-contained IntentIR demonstration"
    )
    demo.add_argument("scenario", choices=("concurrent-agent",))
    demo.add_argument("--json", action="store_true", help="emit structured output")

    benchmark = commands.add_parser(
        "benchmark", help="run an IntentBench-Evolve manifest"
    )
    benchmark.add_argument("manifest", type=Path)
    benchmark.add_argument(
        "--condition",
        action="append",
        choices=BENCHMARK_CONDITIONS,
        help="run only this editing condition; may be repeated",
    )
    benchmark.add_argument(
        "--measure-time",
        action="store_true",
        help="include nondeterministic wall-clock measurements",
    )
    benchmark.add_argument(
        "--fail-on-run-failure",
        action="store_true",
        help="exit with status 1 when any candidate fails",
    )
    benchmark.add_argument("--json", action="store_true", help="emit structured output")
    benchmark.add_argument("-o", "--output", type=Path)

    benchmark_model = commands.add_parser(
        "benchmark-model",
        help="run a trajectory through an explicit external model adapter",
    )
    benchmark_model.add_argument("manifest", type=Path)
    benchmark_model.add_argument(
        "--condition",
        required=True,
        choices=BENCHMARK_CONDITIONS,
    )
    benchmark_model.add_argument("--adapter-command", required=True)
    benchmark_model.add_argument(
        "--adapter-arg",
        action="append",
        default=[],
        help="append one argument to the adapter command",
    )
    benchmark_model.add_argument("--timeout", type=int, default=120)
    benchmark_model.add_argument("--measure-time", action="store_true")
    benchmark_model.add_argument("--fail-on-run-failure", action="store_true")
    benchmark_model.add_argument("--json", action="store_true")
    benchmark_model.add_argument("-o", "--output", type=Path)

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
        capability_values = load_json_argument(args.capabilities)
        if args.db:
            if args.write_state:
                raise ValueError("--write-state cannot be combined with --db")
            with SQLiteStateRepository(args.db) as repository:
                with repository.transaction():
                    state = repository.load(ir)
                    result = run_action(
                        ir,
                        args.action,
                        inputs,
                        state,
                        capability_values,
                    )
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
            result = run_action(
                ir,
                args.action,
                inputs,
                state,
                capability_values,
            )
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


def command_patch(args: argparse.Namespace) -> None:
    try:
        envelope = load_json_file(args.patch)
        result = patch_path(args.source, envelope, apply=args.apply)
    except (ParseError, ValidationError, PatchError) as error:
        payload = error_payload(error)
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print_error(error)
        raise SystemExit(1) from error
    except (OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    print(f"Patch {result['patchId']}")
    print(f"  {result['baseModuleId']} -> {result['resultModuleId']}")
    print(f"  changed: {', '.join(result['changedSymbols'])}")
    print(f"  affected: {', '.join(result['affectedSymbols'])}")
    if result["diff"]:
        print(result["diff"], end="" if result["diff"].endswith("\n") else "\n")
    print("Applied successfully." if result["applied"] else "Validated; use --apply to write.")


def command_agent(args: argparse.Namespace) -> None:
    try:
        arguments = load_json_argument(args.arguments)
    except (OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    result = AgentService(args.root, allow_writes=args.allow_writes).invoke(
        args.tool, arguments
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["ok"]:
        raise SystemExit(1)


def command_demo(args: argparse.Namespace) -> None:
    try:
        if args.scenario == "concurrent-agent":
            result = run_concurrent_agent_demo()
        else:
            raise ConcurrentAgentDemoError(f"unknown demo scenario: {args.scenario}")
    except ConcurrentAgentDemoError as error:
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "diagnostics": [
                            {
                                "code": "concurrent_agent_demo_failed",
                                "message": str(error),
                            }
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(f"demo failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(render_concurrent_agent_demo(result), end="")


def command_benchmark(args: argparse.Namespace) -> None:
    try:
        result = run_benchmark_file(
            args.manifest,
            conditions=args.condition,
            measure_time=args.measure_time,
        )
    except BenchmarkError as error:
        payload = {"ok": False, "diagnostics": [error.to_dict()]}
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(
                f"{error.path}: [{error.code}] {error.message}",
                file=sys.stderr,
            )
        raise SystemExit(1) from error

    serialized = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        write_text(args.output, serialized)
        print(args.output)
    elif args.json:
        print(serialized, end="")
    else:
        print(render_benchmark_output(result), end="")
    if args.fail_on_run_failure and result["summary"]["failed"]:
        raise SystemExit(1)


def command_benchmark_model(args: argparse.Namespace) -> None:
    from intentir.trajectory import run_trajectory_manifest

    try:
        adapter = ExternalCommandModelAdapter(
            [args.adapter_command, *args.adapter_arg],
            timeout_seconds=args.timeout,
        )
        result = run_trajectory_manifest(
            args.manifest,
            conditions=[args.condition],
            measure_time=args.measure_time,
            adapter=adapter,
        )
    except (BenchmarkError, ModelAdapterError) as error:
        payload = {"ok": False, "diagnostics": [error.to_dict()]}
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(
                f"{error.path}: [{error.code}] {error.message}",
                file=sys.stderr,
            )
        raise SystemExit(1) from error

    serialized = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        write_text(args.output, serialized)
        print(args.output)
    elif args.json:
        print(serialized, end="")
    else:
        print(render_benchmark_output(result), end="")
    if args.fail_on_run_failure and result["summary"]["failed"]:
        raise SystemExit(1)


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


def error_payload(
    error: ParseError | ValidationError | PatchError,
) -> dict[str, Any]:
    if isinstance(error, (ValidationError, PatchError)):
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


def print_error(error: ParseError | ValidationError | PatchError) -> None:
    if isinstance(error, (ValidationError, PatchError)):
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
