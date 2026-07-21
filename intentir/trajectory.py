from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable

from intentir.benchmark import (
    BENCHMARK_CONDITIONS,
    BENCHMARK_SCHEMA_VERSION,
    BenchmarkError,
    _parse_json,
    _read_candidate,
    _read_text,
    _reject_unknown,
    _resolve_reference,
    _select_conditions,
    benchmark_failure_counts,
    classify_benchmark_failure,
    evaluate_benchmark_candidate,
)
from intentir.compiler import compile_source
from intentir.model_adapter import ModelAdapter, ModelAdapterError, build_model_request
from intentir.parser import ParseError
from intentir.validator import ValidationError


TRAJECTORY_ROOT_FIELDS = {
    "schemaVersion",
    "suite",
    "description",
    "conditions",
    "applications",
}
APPLICATION_FIELDS = {"id", "baseSource", "checkpoints"}
CHECKPOINT_FIELDS = {
    "id",
    "checkpoint",
    "instruction",
    "hiddenTests",
    "expectedChangedSymbols",
    "candidates",
}


def run_trajectory_manifest(
    manifest: Path | str,
    *,
    conditions: Iterable[str] | None = None,
    measure_time: bool = False,
    adapter: ModelAdapter | None = None,
) -> dict[str, Any]:
    manifest_path = Path(manifest).expanduser().resolve()
    suite = _load_trajectory_manifest(
        manifest_path,
        require_candidates=adapter is None,
    )
    selected = _select_conditions(suite["conditions"], conditions)
    trajectories = []

    for application in suite["applications"]:
        initial_source = _read_text(
            application["baseSource"],
            f"/applications/{application['index']}/baseSource",
        )
        try:
            initial_ir = compile_source(initial_source)
        except (ParseError, ValidationError) as error:
            raise BenchmarkError(
                "invalid_trajectory_base_source",
                "trajectory base source is invalid",
                f"/applications/{application['index']}/baseSource",
            ) from error

        for condition in selected:
            current_source = initial_source
            cumulative_hidden: list[str] = []
            checkpoint_runs = []
            for checkpoint in application["checkpoints"]:
                cumulative_hidden.append(
                    _read_text(
                        checkpoint["hiddenTests"],
                        (
                            f"/applications/{application['index']}/checkpoints/"
                            f"{checkpoint['index']}/hiddenTests"
                        ),
                    ).strip()
                )
                current_ir = compile_source(current_source)
                task = {
                    "id": f"{application['id']}/{checkpoint['id']}",
                    "application": application["id"],
                    "checkpoint": checkpoint["checkpoint"],
                    "expectedChangedSymbols": checkpoint["expectedChangedSymbols"],
                }
                started = time.perf_counter() if measure_time else None
                model_record = None
                if adapter is None:
                    candidate = _read_candidate(
                        checkpoint["candidates"][condition],
                        (
                            f"/applications/{application['index']}/checkpoints/"
                            f"{checkpoint['index']}/candidates/{condition}"
                        ),
                    )
                else:
                    request = build_model_request(
                        suite=suite["suite"],
                        application=application["id"],
                        checkpoint=checkpoint["checkpoint"],
                        checkpoint_id=checkpoint["id"],
                        condition=condition,
                        instruction=checkpoint["instruction"],
                        source=current_source,
                        ir=current_ir,
                    )
                    try:
                        response = adapter.generate(request)
                    except ModelAdapterError as error:
                        metrics = {}
                        if started is not None:
                            metrics["elapsedMs"] = round(
                                (time.perf_counter() - started) * 1000,
                                3,
                            )
                        run = {
                            "ok": False,
                            "taskId": task["id"],
                            "application": application["id"],
                            "checkpoint": checkpoint["checkpoint"],
                            "checkpointId": checkpoint["id"],
                            "condition": condition,
                            "modelRequestId": request["requestId"],
                            "metrics": metrics,
                            "diagnostics": [error.to_dict()],
                        }
                        run["failure"] = classify_benchmark_failure(
                            run["diagnostics"],
                            default_stage="generation",
                        )
                        checkpoint_runs.append(run)
                        break
                    candidate = response["candidate"]
                    model_record = {
                        "requestId": request["requestId"],
                        "model": response["model"],
                        "usage": response["usage"],
                    }
                    if "provenance" in response:
                        model_record["provenance"] = response["provenance"]
                evaluation = evaluate_benchmark_candidate(
                    task,
                    condition,
                    current_source,
                    current_ir,
                    "\n\n".join(cumulative_hidden),
                    candidate,
                )
                run = evaluation.result
                run["checkpointId"] = checkpoint["id"]
                if model_record is not None:
                    run["model"] = model_record
                if started is not None:
                    run["metrics"]["elapsedMs"] = round(
                        (time.perf_counter() - started) * 1000,
                        3,
                    )
                checkpoint_runs.append(run)
                if not run["ok"] or evaluation.source is None:
                    break
                current_source = evaluation.source

            completed = sum(1 for run in checkpoint_runs if run["ok"])
            trajectory_ok = completed == len(application["checkpoints"])
            final_ir = compile_source(current_source)
            trajectories.append(
                {
                    "ok": trajectory_ok,
                    "application": application["id"],
                    "condition": condition,
                    "initialModuleId": initial_ir["moduleId"],
                    "finalModuleId": final_ir["moduleId"],
                    "completedCheckpoints": completed,
                    "totalCheckpoints": len(application["checkpoints"]),
                    "checkpoints": checkpoint_runs,
                }
            )

    checkpoint_runs = [
        run for trajectory in trajectories for run in trajectory["checkpoints"]
    ]
    passed_runs = sum(1 for run in checkpoint_runs if run["ok"])
    passed_trajectories = sum(1 for item in trajectories if item["ok"])
    by_condition = {}
    for condition in selected:
        items = [item for item in trajectories if item["condition"] == condition]
        runs = [run for item in items for run in item["checkpoints"]]
        by_condition[condition] = {
            "trajectories": len(items),
            "passedTrajectories": sum(1 for item in items if item["ok"]),
            "failedTrajectories": sum(1 for item in items if not item["ok"]),
            "checkpointRuns": len(runs),
            "passed": sum(1 for run in runs if run["ok"]),
            "failed": sum(1 for run in runs if not run["ok"]),
            "failuresByCode": benchmark_failure_counts(runs),
        }
    return {
        "ok": passed_trajectories == len(trajectories),
        "schemaVersion": BENCHMARK_SCHEMA_VERSION,
        "mode": "trajectory",
        "adapter": {
            "kind": "external-command" if adapter is not None else "fixture-files"
        },
        "suite": suite["suite"],
        "description": suite["description"],
        "conditions": selected,
        "summary": {
            "applications": len(suite["applications"]),
            "trajectories": len(trajectories),
            "passedTrajectories": passed_trajectories,
            "failedTrajectories": len(trajectories) - passed_trajectories,
            "runs": len(checkpoint_runs),
            "passed": passed_runs,
            "failed": len(checkpoint_runs) - passed_runs,
            "failuresByCode": benchmark_failure_counts(checkpoint_runs),
            "byCondition": by_condition,
        },
        "trajectories": trajectories,
    }


def render_trajectory_result(result: dict[str, Any]) -> str:
    lines = [f"IntentBench-Evolve trajectory: {result['suite']}", ""]
    for trajectory in result["trajectories"]:
        lines.append(
            f"{'PASS' if trajectory['ok'] else 'FAIL'}  "
            f"{trajectory['application']}  {trajectory['condition']}  "
            f"{trajectory['completedCheckpoints']}/{trajectory['totalCheckpoints']} checkpoints"
        )
        for run in trajectory["checkpoints"]:
            summary = run.get("verification", {}).get("summary", {})
            tests = (
                f"{summary.get('passed', 0)}/{summary.get('tests', 0)} tests"
                if summary
                else "not verified"
            )
            lines.append(
                f"      {'PASS' if run['ok'] else 'FAIL'}  "
                f"{run['checkpointId']}  {tests}"
            )
            for diagnostic in run["diagnostics"]:
                lines.append(
                    f"            [{diagnostic['code']}] {diagnostic['message']}"
                )
    summary = result["summary"]
    lines.extend(
        [
            "",
            f"{summary['passedTrajectories']} trajectories passed, "
            f"{summary['failedTrajectories']} failed; "
            f"{summary['passed']}/{summary['runs']} checkpoint runs passed",
            "",
        ]
    )
    return "\n".join(lines)


def _load_trajectory_manifest(
    path: Path,
    *,
    require_candidates: bool = True,
) -> dict[str, Any]:
    data = _parse_json(
        _read_text(path, "/manifest"),
        "invalid_trajectory_manifest",
        "/",
    )
    if not isinstance(data, dict):
        raise BenchmarkError(
            "invalid_trajectory_manifest",
            "trajectory manifest must be a JSON object",
            "/",
        )
    _reject_unknown(data, TRAJECTORY_ROOT_FIELDS, "/")
    if data.get("schemaVersion") != BENCHMARK_SCHEMA_VERSION:
        raise BenchmarkError(
            "unsupported_trajectory_schema",
            f"trajectory schemaVersion must be {BENCHMARK_SCHEMA_VERSION}",
            "/schemaVersion",
        )
    suite = data.get("suite")
    description = data.get("description", "")
    conditions = data.get("conditions")
    applications = data.get("applications")
    if not isinstance(suite, str) or not suite:
        raise BenchmarkError("invalid_trajectory_suite", "suite is required", "/suite")
    if not isinstance(description, str):
        raise BenchmarkError(
            "invalid_trajectory_description",
            "description must be a string",
            "/description",
        )
    if (
        not isinstance(conditions, list)
        or not conditions
        or not all(isinstance(item, str) for item in conditions)
        or len(set(conditions)) != len(conditions)
        or set(conditions) - set(BENCHMARK_CONDITIONS)
    ):
        raise BenchmarkError(
            "invalid_trajectory_conditions",
            "conditions must be unique supported editing conditions",
            "/conditions",
        )
    if not isinstance(applications, list) or not applications:
        raise BenchmarkError(
            "empty_trajectory_applications",
            "trajectory manifest must contain at least one application",
            "/applications",
        )

    root = path.parent
    normalized_applications = []
    application_ids = set()
    for app_index, application in enumerate(applications):
        app_path = f"/applications/{app_index}"
        if not isinstance(application, dict):
            raise BenchmarkError(
                "invalid_trajectory_application",
                "application must be a JSON object",
                app_path,
            )
        _reject_unknown(application, APPLICATION_FIELDS, app_path)
        app_id = application.get("id")
        checkpoints = application.get("checkpoints")
        if not isinstance(app_id, str) or not app_id or app_id in application_ids:
            raise BenchmarkError(
                "invalid_trajectory_application_id",
                "application id must be a unique non-empty string",
                f"{app_path}/id",
            )
        application_ids.add(app_id)
        if not isinstance(checkpoints, list) or not checkpoints:
            raise BenchmarkError(
                "empty_trajectory_checkpoints",
                "application must contain at least one checkpoint",
                f"{app_path}/checkpoints",
            )
        normalized_checkpoints = []
        checkpoint_ids = set()
        for checkpoint_index, checkpoint in enumerate(checkpoints):
            checkpoint_path = f"{app_path}/checkpoints/{checkpoint_index}"
            if not isinstance(checkpoint, dict):
                raise BenchmarkError(
                    "invalid_trajectory_checkpoint",
                    "checkpoint must be a JSON object",
                    checkpoint_path,
                )
            _reject_unknown(checkpoint, CHECKPOINT_FIELDS, checkpoint_path)
            checkpoint_id = checkpoint.get("id")
            number = checkpoint.get("checkpoint")
            instruction = checkpoint.get("instruction")
            expected = checkpoint.get("expectedChangedSymbols")
            candidates = checkpoint.get("candidates")
            if (
                not isinstance(checkpoint_id, str)
                or not checkpoint_id
                or checkpoint_id in checkpoint_ids
            ):
                raise BenchmarkError(
                    "invalid_trajectory_checkpoint_id",
                    "checkpoint id must be a unique non-empty string",
                    f"{checkpoint_path}/id",
                )
            checkpoint_ids.add(checkpoint_id)
            if number != checkpoint_index + 1:
                raise BenchmarkError(
                    "nonsequential_trajectory_checkpoint",
                    "checkpoint numbers must start at 1 and be sequential",
                    f"{checkpoint_path}/checkpoint",
                )
            if not isinstance(instruction, str) or not instruction:
                raise BenchmarkError(
                    "invalid_trajectory_instruction",
                    "instruction must be a non-empty string",
                    f"{checkpoint_path}/instruction",
                )
            if not isinstance(expected, list) or not all(
                isinstance(item, str) for item in expected
            ):
                raise BenchmarkError(
                    "invalid_trajectory_changed_symbols",
                    "expectedChangedSymbols must be an array of strings",
                    f"{checkpoint_path}/expectedChangedSymbols",
                )
            if candidates is None and require_candidates:
                raise BenchmarkError(
                    "invalid_trajectory_candidates",
                    "candidates are required when no model adapter is configured",
                    f"{checkpoint_path}/candidates",
                )
            if candidates is not None and (
                not isinstance(candidates, dict)
                or set(candidates) != set(conditions)
            ):
                raise BenchmarkError(
                    "invalid_trajectory_candidates",
                    "candidate keys must exactly match trajectory conditions",
                    f"{checkpoint_path}/candidates",
                )
            normalized_checkpoints.append(
                {
                    "index": checkpoint_index,
                    "id": checkpoint_id,
                    "checkpoint": number,
                    "instruction": instruction,
                    "expectedChangedSymbols": expected,
                    "hiddenTests": _resolve_reference(
                        root,
                        checkpoint.get("hiddenTests"),
                        f"{checkpoint_path}/hiddenTests",
                    ),
                    "candidates": (
                        {
                            condition: _resolve_reference(
                                root,
                                candidates[condition],
                                f"{checkpoint_path}/candidates/{condition}",
                            )
                            for condition in conditions
                        }
                        if candidates is not None
                        else {}
                    ),
                }
            )
        normalized_applications.append(
            {
                "index": app_index,
                "id": app_id,
                "baseSource": _resolve_reference(
                    root,
                    application.get("baseSource"),
                    f"{app_path}/baseSource",
                ),
                "checkpoints": normalized_checkpoints,
            }
        )
    return {
        "suite": suite,
        "description": description,
        "conditions": conditions,
        "applications": normalized_applications,
    }
