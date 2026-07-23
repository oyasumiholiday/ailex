from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from intentir.compiler import compile_source
from intentir.parser import ParseError
from intentir.patch import (
    OPERATION_FIELDS,
    PATCH_KINDS,
    PatchError,
    changed_symbols,
    plan_patch_source,
)
from intentir.validator import ValidationError
from intentir.verifier import verify_ir


BENCHMARK_SCHEMA_VERSION = "0.1.0"
BENCHMARK_CONDITIONS = (
    "full-file",
    "unified-diff",
    "structure-edit",
    "intent-patch",
)
MAX_CANDIDATE_BYTES = 1_000_000

ROOT_FIELDS = {"schemaVersion", "suite", "description", "conditions", "tasks"}
TASK_FIELDS = {
    "id",
    "application",
    "checkpoint",
    "instruction",
    "baseSource",
    "hiddenTests",
    "expectedChangedSymbols",
    "candidates",
}
STRUCTURE_EDIT_FIELDS = {"schemaVersion", "operations"}


class BenchmarkError(ValueError):
    def __init__(self, code: str, message: str, path: str) -> None:
        self.code = code
        self.message = message
        self.path = path
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True)
class CandidateEvaluation:
    result: dict[str, Any]
    source: str | None


def classify_benchmark_failure(
    diagnostics: Iterable[dict[str, Any]],
    *,
    default_stage: str = "candidate",
) -> dict[str, Any]:
    codes = sorted(
        {
            diagnostic.get("code", "unknown_failure")
            for diagnostic in diagnostics
            if isinstance(diagnostic, dict)
        }
    )
    if any(code.startswith("stale_") for code in codes):
        stage = "precondition"
    elif "benchmark_verification_failed" in codes:
        stage = "verification"
    elif set(codes) & {"baseline_test_removed", "unexpected_semantic_change"}:
        stage = "semantic-scope"
    else:
        stage = default_stage
    return {"stage": stage, "codes": codes or ["unknown_failure"]}


def benchmark_failure_counts(runs: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in runs:
        for code in run.get("failure", {}).get("codes", []):
            counts[code] = counts.get(code, 0) + 1
    return {code: counts[code] for code in sorted(counts)}


def run_benchmark_manifest(
    manifest: Path | str,
    *,
    conditions: Iterable[str] | None = None,
    measure_time: bool = False,
) -> dict[str, Any]:
    manifest_path = Path(manifest).expanduser().resolve()
    suite = _load_manifest(manifest_path)
    selected = _select_conditions(suite["conditions"], conditions)
    runs: list[dict[str, Any]] = []

    for task in suite["tasks"]:
        base_source = _read_text(task["baseSource"], f"/tasks/{task['index']}/baseSource")
        hidden_tests = _read_text(
            task["hiddenTests"], f"/tasks/{task['index']}/hiddenTests"
        )
        try:
            base_ir = compile_source(base_source)
        except (ParseError, ValidationError) as error:
            raise BenchmarkError(
                "invalid_benchmark_base_source",
                f"benchmark base source is invalid: {_error_codes(error)}",
                f"/tasks/{task['index']}/baseSource",
            ) from error

        for condition in selected:
            candidate_path = task["candidates"][condition]
            candidate_text = _read_candidate(
                candidate_path,
                f"/tasks/{task['index']}/candidates/{condition}",
            )
            started = time.perf_counter() if measure_time else None
            evaluation = evaluate_benchmark_candidate(
                task,
                condition,
                base_source,
                base_ir,
                hidden_tests,
                candidate_text,
            )
            run = evaluation.result
            if started is not None:
                run["metrics"]["elapsedMs"] = round(
                    (time.perf_counter() - started) * 1000,
                    3,
                )
            runs.append(run)

    condition_summary = {}
    for condition in selected:
        condition_runs = [run for run in runs if run["condition"] == condition]
        condition_summary[condition] = {
            "runs": len(condition_runs),
            "passed": sum(1 for run in condition_runs if run["ok"]),
            "failed": sum(1 for run in condition_runs if not run["ok"]),
        }
    passed = sum(1 for run in runs if run["ok"])
    return {
        "ok": passed == len(runs),
        "schemaVersion": BENCHMARK_SCHEMA_VERSION,
        "mode": "independent",
        "suite": suite["suite"],
        "description": suite["description"],
        "conditions": selected,
        "summary": {
            "tasks": len(suite["tasks"]),
            "runs": len(runs),
            "passed": passed,
            "failed": len(runs) - passed,
            "failuresByCode": benchmark_failure_counts(runs),
            "byCondition": condition_summary,
        },
        "runs": runs,
    }


def render_benchmark_result(result: dict[str, Any]) -> str:
    lines = [
        f"IntentBench-Evolve: {result['suite']}",
        "",
    ]
    for run in result["runs"]:
        verification = run.get("verification", {})
        summary = verification.get("summary", {})
        tests = (
            f"{summary.get('passed', 0)}/{summary.get('tests', 0)} tests"
            if summary
            else "not verified"
        )
        lines.append(
            f"{'PASS' if run['ok'] else 'FAIL'}  {run['taskId']}  "
            f"{run['condition']}  {tests}"
        )
        for diagnostic in run["diagnostics"]:
            lines.append(f"      [{diagnostic['code']}] {diagnostic['message']}")
    summary = result["summary"]
    lines.extend(
        [
            "",
            f"{summary['passed']} passed, {summary['failed']} failed, "
            f"{summary['runs']} runs",
            "",
        ]
    )
    return "\n".join(lines)


def run_benchmark_file(
    manifest: Path | str,
    *,
    conditions: Iterable[str] | None = None,
    measure_time: bool = False,
) -> dict[str, Any]:
    manifest_path = Path(manifest).expanduser().resolve()
    data = _parse_json(
        _read_text(manifest_path, "/manifest"),
        "invalid_benchmark_manifest",
        "/",
    )
    if isinstance(data, dict) and "applications" in data:
        from intentir.trajectory import run_trajectory_manifest

        return run_trajectory_manifest(
            manifest_path,
            conditions=conditions,
            measure_time=measure_time,
        )
    return run_benchmark_manifest(
        manifest_path,
        conditions=conditions,
        measure_time=measure_time,
    )


def render_benchmark_output(result: dict[str, Any]) -> str:
    if result.get("mode") == "trajectory":
        from intentir.trajectory import render_trajectory_result

        return render_trajectory_result(result)
    return render_benchmark_result(result)


def evaluate_benchmark_candidate(
    task: dict[str, Any],
    condition: str,
    base_source: str,
    base_ir: dict[str, Any],
    hidden_tests: str,
    candidate_text: str,
) -> CandidateEvaluation:
    metrics = {
        "candidateBytes": len(candidate_text.encode("utf-8")),
        "candidateLines": len(candidate_text.splitlines()),
    }
    result: dict[str, Any] = {
        "ok": False,
        "taskId": task["id"],
        "application": task["application"],
        "checkpoint": task["checkpoint"],
        "condition": condition,
        "candidateSha256": "sha256:"
        + hashlib.sha256(candidate_text.encode("utf-8")).hexdigest(),
        "metrics": metrics,
        "diagnostics": [],
    }
    candidate_source: str | None = None
    try:
        candidate_source, application = materialize_benchmark_candidate(
            condition,
            base_source,
            base_ir,
            candidate_text,
        )
        candidate_ir = compile_source(candidate_source)
        base_tests = _test_symbols(base_ir)
        candidate_tests = _test_symbols(candidate_ir)
        removed_tests = sorted(base_tests - candidate_tests)
        changed = changed_symbols(base_ir, candidate_ir)
        expected = set(task["expectedChangedSymbols"])
        unexpected = sorted(set(changed) - expected)

        evaluation_source = (
            candidate_source.rstrip() + "\n\n" + hidden_tests.strip() + "\n"
        )
        evaluation_ir = compile_source(evaluation_source)
        verification = verify_ir(evaluation_ir)
        diagnostics: list[dict[str, Any]] = []
        if removed_tests:
            diagnostics.append(
                {
                    "code": "baseline_test_removed",
                    "message": "candidate removed baseline tests",
                    "scope": removed_tests,
                }
            )
        if unexpected:
            diagnostics.append(
                {
                    "code": "unexpected_semantic_change",
                    "message": "candidate changed symbols outside the expected scope",
                    "scope": unexpected,
                }
            )
        failed_checks = [
            test["name"] for test in verification["tests"] if not test["ok"]
        ]
        failed_checks.extend(
            example["name"]
            for example in verification["functionExamples"]
            if not example["ok"]
        )
        if failed_checks:
            diagnostics.append(
                {
                    "code": "benchmark_verification_failed",
                    "message": "candidate failed tests or function examples",
                    "scope": failed_checks,
                }
            )

        diff = list(
            difflib.unified_diff(
                base_source.splitlines(),
                candidate_source.splitlines(),
            )
        )
        metrics.update(
            {
                "resultSourceBytes": len(candidate_source.encode("utf-8")),
                "resultSourceLines": len(candidate_source.splitlines()),
                "changedLines": sum(
                    1
                    for line in diff
                    if (line.startswith("+") or line.startswith("-"))
                    and not line.startswith(("+++", "---"))
                ),
            }
        )
        result.update(
            {
                "ok": verification["ok"] and not diagnostics,
                "resultModuleId": candidate_ir["moduleId"],
                "changedSymbols": changed,
                "expectedChangedSymbols": sorted(expected),
                "unexpectedChangedSymbols": unexpected,
                "baselineTestsPreserved": not removed_tests,
                "applicationResult": application,
                "verification": {
                    "summary": verification["summary"],
                    "visibleTests": len(candidate_tests),
                    "hiddenTests": len(_test_symbols(evaluation_ir) - candidate_tests),
                },
                "diagnostics": diagnostics,
            }
        )
        if not result["ok"]:
            result["failure"] = classify_benchmark_failure(diagnostics)
    except (BenchmarkError, ParseError, ValidationError, PatchError) as error:
        result["diagnostics"] = _diagnostics(error)
        result["failure"] = classify_benchmark_failure(result["diagnostics"])
        candidate_source = None
    return CandidateEvaluation(result=result, source=candidate_source)


def materialize_benchmark_candidate(
    condition: str,
    base_source: str,
    base_ir: dict[str, Any],
    candidate_text: str,
) -> tuple[str, dict[str, Any]]:
    if condition == "full-file":
        return candidate_text, {"kind": condition}
    if condition == "unified-diff":
        return _apply_unified_diff(base_source, candidate_text), {"kind": condition}
    if condition == "structure-edit":
        candidate = _parse_json(candidate_text, "invalid_structure_edit_json")
        envelope = _structure_edit_envelope(candidate, base_ir)
        plan = plan_patch_source(base_source, envelope, source_name="workspace.intent")
        return plan.source, {
            "kind": condition,
            "patchId": plan.result["patchId"],
        }
    if condition == "intent-patch":
        candidate = _parse_json(candidate_text, "invalid_intent_patch_json")
        plan = plan_patch_source(base_source, candidate, source_name="workspace.intent")
        return plan.source, {
            "kind": condition,
            "patchId": plan.result["patchId"],
        }
    raise BenchmarkError(
        "unknown_benchmark_condition",
        f"unknown benchmark condition: {condition}",
        "/conditions",
    )


def _structure_edit_envelope(
    candidate: Any,
    base_ir: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise BenchmarkError(
            "invalid_structure_edit",
            "structure edit must be a JSON object",
            "/candidate",
        )
    _reject_unknown(candidate, STRUCTURE_EDIT_FIELDS, "/candidate")
    if candidate.get("schemaVersion") != BENCHMARK_SCHEMA_VERSION:
        raise BenchmarkError(
            "unsupported_structure_edit_schema",
            f"structure edit schemaVersion must be {BENCHMARK_SCHEMA_VERSION}",
            "/candidate/schemaVersion",
        )
    operations = candidate.get("operations")
    if not isinstance(operations, list) or not operations:
        raise BenchmarkError(
            "empty_structure_edit",
            "structure edit operations must be a non-empty array",
            "/candidate/operations",
        )
    nodes = {
        reference: node
        for node in base_ir["nodes"]
        for reference in (node["symbol"], node["id"])
    }
    normalized = []
    for index, operation in enumerate(operations):
        path = f"/candidate/operations/{index}"
        if not isinstance(operation, dict):
            raise BenchmarkError(
                "invalid_structure_operation",
                "structure operation must be a JSON object",
                path,
            )
        kind = operation.get("kind")
        if kind not in PATCH_KINDS:
            raise BenchmarkError(
                "unknown_structure_operation",
                f"unknown structure operation: {kind}",
                f"{path}/kind",
            )
        allowed = OPERATION_FIELDS[kind] - {"expectedId"}
        _reject_unknown(operation, allowed, path)
        item = dict(operation)
        if kind != "add_definition":
            target = operation.get("target")
            node = nodes.get(target)
            if node is None:
                raise BenchmarkError(
                    "unknown_structure_target",
                    f"unknown structure edit target: {target}",
                    f"{path}/target",
                )
            item["target"] = node["symbol"]
            item["expectedId"] = node["id"]
        normalized.append(item)
    return {
        "schemaVersion": "0.13.0",
        "baseModuleId": base_ir["moduleId"],
        "operations": normalized,
        "requestedObligations": ["static", "affected-tests"],
    }


def _apply_unified_diff(base_source: str, diff: str) -> str:
    headers = []
    git_headers = []
    forbidden = (
        "rename from ",
        "rename to ",
        "new file mode ",
        "deleted file mode ",
        "GIT binary patch",
    )
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            git_headers.append(line)
        if line.startswith(("--- ", "+++ ")):
            headers.append(line.split("\t", 1)[0])
        if line.startswith(forbidden):
            raise BenchmarkError(
                "unsafe_unified_diff",
                "benchmark diff may only modify workspace.intent",
                "/candidate",
            )
    allowed_git_headers = (
        [],
        ["diff --git a/workspace.intent b/workspace.intent"],
    )
    if git_headers not in allowed_git_headers or headers != [
        "--- a/workspace.intent",
        "+++ b/workspace.intent",
    ]:
        raise BenchmarkError(
            "unsafe_unified_diff",
            "benchmark diff must modify only a/workspace.intent",
            "/candidate",
        )

    with tempfile.TemporaryDirectory(prefix="intentbench-diff-") as directory:
        root = Path(directory)
        workspace = root / "workspace.intent"
        patch = root / "candidate.diff"
        workspace.write_text(base_source, encoding="utf-8")
        patch.write_text(diff, encoding="utf-8")
        command = [
            "git",
            "apply",
            "--no-index",
            "--whitespace=nowarn",
            "candidate.diff",
        ]
        try:
            checked = subprocess.run(
                [*command[:2], "--check", *command[2:]],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if checked.returncode != 0:
                raise BenchmarkError(
                    "unified_diff_apply_failed",
                    "unified diff did not apply to the benchmark base source",
                    "/candidate",
                )
            applied = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError as error:
            raise BenchmarkError(
                "unified_diff_tool_missing",
                "git is required for the unified-diff benchmark condition",
                "/candidate",
            ) from error
        except OSError as error:
            raise BenchmarkError(
                "unified_diff_process_error",
                "git could not be started for unified diff application",
                "/candidate",
            ) from error
        except subprocess.TimeoutExpired as error:
            raise BenchmarkError(
                "unified_diff_timeout",
                "unified diff application exceeded 10 seconds",
                "/candidate",
            ) from error
        if applied.returncode != 0:
            raise BenchmarkError(
                "unified_diff_apply_failed",
                "unified diff could not be applied",
                "/candidate",
            )
        return workspace.read_text(encoding="utf-8")


def _load_manifest(path: Path) -> dict[str, Any]:
    data = _parse_json(
        _read_text(path, "/manifest"),
        "invalid_benchmark_manifest",
        "/",
    )
    if not isinstance(data, dict):
        raise BenchmarkError(
            "invalid_benchmark_manifest",
            "benchmark manifest must be a JSON object",
            "/",
        )
    _reject_unknown(data, ROOT_FIELDS, "/")
    if data.get("schemaVersion") != BENCHMARK_SCHEMA_VERSION:
        raise BenchmarkError(
            "unsupported_benchmark_schema",
            f"benchmark schemaVersion must be {BENCHMARK_SCHEMA_VERSION}",
            "/schemaVersion",
        )
    suite = data.get("suite")
    if not isinstance(suite, str) or not suite:
        raise BenchmarkError("invalid_benchmark_suite", "suite is required", "/suite")
    description = data.get("description", "")
    if not isinstance(description, str):
        raise BenchmarkError(
            "invalid_benchmark_description",
            "description must be a string",
            "/description",
        )
    conditions = data.get("conditions")
    if (
        not isinstance(conditions, list)
        or not conditions
        or not all(isinstance(item, str) for item in conditions)
        or len(set(conditions)) != len(conditions)
        or set(conditions) - set(BENCHMARK_CONDITIONS)
    ):
        raise BenchmarkError(
            "invalid_benchmark_conditions",
            "conditions must be unique supported editing conditions",
            "/conditions",
        )
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise BenchmarkError(
            "empty_benchmark_tasks",
            "benchmark manifest must contain at least one task",
            "/tasks",
        )

    normalized_tasks = []
    ids = set()
    root = path.parent
    for index, task in enumerate(tasks):
        task_path = f"/tasks/{index}"
        if not isinstance(task, dict):
            raise BenchmarkError(
                "invalid_benchmark_task",
                "benchmark task must be a JSON object",
                task_path,
            )
        _reject_unknown(task, TASK_FIELDS, task_path)
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id or task_id in ids:
            raise BenchmarkError(
                "invalid_benchmark_task_id",
                "task id must be a unique non-empty string",
                f"{task_path}/id",
            )
        ids.add(task_id)
        application = task.get("application")
        instruction = task.get("instruction")
        checkpoint = task.get("checkpoint")
        if not isinstance(application, str) or not application:
            raise BenchmarkError(
                "invalid_benchmark_application",
                "application must be a non-empty string",
                f"{task_path}/application",
            )
        if not isinstance(instruction, str) or not instruction:
            raise BenchmarkError(
                "invalid_benchmark_instruction",
                "instruction must be a non-empty string",
                f"{task_path}/instruction",
            )
        if (
            not isinstance(checkpoint, int)
            or isinstance(checkpoint, bool)
            or checkpoint < 1
        ):
            raise BenchmarkError(
                "invalid_benchmark_checkpoint",
                "checkpoint must be a positive integer",
                f"{task_path}/checkpoint",
            )
        expected = task.get("expectedChangedSymbols")
        if not isinstance(expected, list) or not all(
            isinstance(item, str) for item in expected
        ):
            raise BenchmarkError(
                "invalid_expected_changed_symbols",
                "expectedChangedSymbols must be an array of strings",
                f"{task_path}/expectedChangedSymbols",
            )
        candidates = task.get("candidates")
        if not isinstance(candidates, dict) or set(candidates) != set(conditions):
            raise BenchmarkError(
                "invalid_benchmark_candidates",
                "candidate keys must exactly match manifest conditions",
                f"{task_path}/candidates",
            )
        normalized_tasks.append(
            {
                "index": index,
                "id": task_id,
                "application": application,
                "checkpoint": checkpoint,
                "instruction": instruction,
                "expectedChangedSymbols": expected,
                "baseSource": _resolve_reference(
                    root, task.get("baseSource"), f"{task_path}/baseSource"
                ),
                "hiddenTests": _resolve_reference(
                    root, task.get("hiddenTests"), f"{task_path}/hiddenTests"
                ),
                "candidates": {
                    condition: _resolve_reference(
                        root,
                        candidates[condition],
                        f"{task_path}/candidates/{condition}",
                    )
                    for condition in conditions
                },
            }
        )
    return {
        "suite": suite,
        "description": description,
        "conditions": conditions,
        "tasks": normalized_tasks,
    }


def _select_conditions(
    available: list[str], requested: Iterable[str] | None
) -> list[str]:
    if requested is None:
        return list(available)
    selected = list(dict.fromkeys(requested))
    if not selected:
        raise BenchmarkError(
            "empty_benchmark_condition_selection",
            "at least one benchmark condition must be selected",
            "/conditions",
        )
    unavailable = sorted(set(selected) - set(available))
    if unavailable:
        raise BenchmarkError(
            "unavailable_benchmark_condition",
            f"conditions are not present in the manifest: {', '.join(unavailable)}",
            "/conditions",
        )
    return [condition for condition in available if condition in selected]


def _resolve_reference(root: Path, value: Any, path: str) -> Path:
    if not isinstance(value, str) or not value:
        raise BenchmarkError(
            "invalid_benchmark_file_reference",
            "benchmark file reference must be a non-empty string",
            path,
        )
    resolved = (root / value).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise BenchmarkError(
            "benchmark_path_outside_suite",
            "benchmark file reference leaves the manifest directory",
            path,
        ) from error
    if not resolved.is_file():
        raise BenchmarkError(
            "benchmark_file_not_found",
            "benchmark file reference does not exist",
            path,
        )
    return resolved


def _read_candidate(path: Path, diagnostic_path: str) -> str:
    if path.stat().st_size > MAX_CANDIDATE_BYTES:
        raise BenchmarkError(
            "benchmark_candidate_too_large",
            f"candidate exceeds {MAX_CANDIDATE_BYTES} bytes",
            diagnostic_path,
        )
    return _read_text(path, diagnostic_path)


def _read_text(path: Path, diagnostic_path: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise BenchmarkError(
            "benchmark_file_read_error",
            "benchmark file could not be read as UTF-8",
            diagnostic_path,
        ) from error


def _parse_json(source: str, code: str, path: str = "/candidate") -> Any:
    try:
        return json.loads(source)
    except json.JSONDecodeError as error:
        raise BenchmarkError(code, "input is not valid JSON", path) from error


def _reject_unknown(value: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise BenchmarkError(
            "unknown_benchmark_field",
            f"unknown fields: {', '.join(unknown)}",
            path,
        )


def _test_symbols(ir: dict[str, Any]) -> set[str]:
    return {
        node["symbol"] for node in ir["nodes"] if node["kind"] == "test"
    }


def _diagnostics(error: Exception) -> list[dict[str, Any]]:
    if isinstance(error, BenchmarkError):
        return [error.to_dict()]
    if isinstance(error, (PatchError, ValidationError)):
        return [item.to_dict() for item in error.diagnostics]
    if isinstance(error, ParseError):
        return [
            {
                "code": "candidate_parse_error",
                "message": "candidate source did not parse",
                "path": "/candidate",
            }
        ]
    return [
        {
            "code": getattr(error, "code", "parse_error"),
            "message": str(error),
            "path": getattr(error, "path", "/candidate"),
        }
    ]


def _error_codes(error: Exception) -> str:
    return ", ".join(item.get("code", "unknown") for item in _diagnostics(error))
