from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from intentir.benchmark import BENCHMARK_CONDITIONS, MAX_CANDIDATE_BYTES
from intentir.canonical import content_address
from intentir.patch import OPERATION_FIELDS, PATCH_KINDS


MODEL_ADAPTER_SCHEMA_VERSION = "0.1.0"
LANGUAGE_REFERENCE_VERSION = "intentir-benchmark-subset-0.1.0"
REQUEST_FIELDS = {
    "schemaVersion",
    "requestId",
    "suite",
    "application",
    "checkpoint",
    "checkpointId",
    "condition",
    "instruction",
    "source",
    "context",
    "languageReference",
    "outputContract",
}
RESPONSE_FIELDS = {
    "schemaVersion",
    "requestId",
    "model",
    "candidate",
    "usage",
    "provenance",
}
USAGE_FIELDS = {"inputTokens", "outputTokens"}
PROVENANCE_FIELDS = {
    "provider",
    "responseId",
    "requestedModel",
    "promptId",
    "configurationId",
    "reasoningEffort",
    "maxOutputTokens",
}


class ModelAdapterError(RuntimeError):
    def __init__(self, code: str, message: str, path: str = "/adapter") -> None:
        self.code = code
        self.message = message
        self.path = path
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "path": self.path}


class ModelAdapter(Protocol):
    def generate(self, request: dict[str, Any]) -> dict[str, Any]: ...


def language_reference() -> dict[str, Any]:
    return {
        "id": LANGUAGE_REFERENCE_VERSION,
        "syntax": {
            "entityField": (
                "<field>: <Type> [required] [key] [default <literal>]"
            ),
            "action": (
                "action <Name>:\n"
                "  input:\n"
                "    <field>: <Type> required\n"
                "  effects:\n"
                "    <effect>"
            ),
            "insertEffect": "insert <Entity>",
            "updateEffect": (
                "update <Entity> where <field> equals input.<field> "
                "set <field> = <value>"
            ),
        },
        "rules": [
            "Indentation is significant.",
            "Use equals, not =, in an update where clause.",
            "Refer to an action input as input.<field>.",
            "Write one update effect on one line.",
        ],
    }


@dataclass(frozen=True)
class ExternalCommandModelAdapter:
    command: tuple[str, ...]
    timeout_seconds: int = 120
    max_output_bytes: int = 2_000_000

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: int = 120,
        max_output_bytes: int = 2_000_000,
    ) -> None:
        if not command or not all(isinstance(item, str) and item for item in command):
            raise ModelAdapterError(
                "invalid_adapter_command",
                "adapter command must contain at least one non-empty argument",
            )
        if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 600:
            raise ModelAdapterError(
                "invalid_adapter_timeout",
                "adapter timeout must be between 1 and 600 seconds",
            )
        if not isinstance(max_output_bytes, int) or max_output_bytes < 1:
            raise ModelAdapterError(
                "invalid_adapter_output_limit",
                "adapter output limit must be positive",
            )
        object.__setattr__(self, "command", tuple(command))
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "max_output_bytes", max_output_bytes)

    def generate(self, request: dict[str, Any]) -> dict[str, Any]:
        validate_model_request(request)
        serialized = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        try:
            completed = subprocess.run(
                self.command,
                input=serialized,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as error:
            raise ModelAdapterError(
                "adapter_command_not_found",
                "model adapter command was not found",
            ) from error
        except subprocess.TimeoutExpired as error:
            raise ModelAdapterError(
                "adapter_timeout",
                "model adapter command exceeded its timeout",
            ) from error
        except OSError as error:
            raise ModelAdapterError(
                "adapter_process_error",
                "model adapter command could not be started",
            ) from error
        except UnicodeError as error:
            raise ModelAdapterError(
                "invalid_adapter_output_encoding",
                "model adapter output is not valid text",
            ) from error
        if completed.returncode != 0:
            raise ModelAdapterError(
                "adapter_nonzero_exit",
                "model adapter command exited unsuccessfully",
            )
        if len(completed.stdout.encode("utf-8")) > self.max_output_bytes:
            raise ModelAdapterError(
                "adapter_output_too_large",
                "model adapter response exceeded the output limit",
            )
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ModelAdapterError(
                "invalid_adapter_response_json",
                "model adapter response is not valid JSON",
            ) from error
        validate_model_response(response, request["requestId"])
        return response


def build_model_request(
    *,
    suite: str,
    application: str,
    checkpoint: int,
    checkpoint_id: str,
    condition: str,
    instruction: str,
    source: str,
    ir: dict[str, Any],
) -> dict[str, Any]:
    if condition not in BENCHMARK_CONDITIONS:
        raise ModelAdapterError(
            "unknown_model_condition",
            f"unknown model editing condition: {condition}",
            "/condition",
        )
    payload = {
        "schemaVersion": MODEL_ADAPTER_SCHEMA_VERSION,
        "suite": suite,
        "application": application,
        "checkpoint": checkpoint,
        "checkpointId": checkpoint_id,
        "condition": condition,
        "instruction": instruction,
        "source": source,
        "context": {
            "moduleId": ir["moduleId"],
            "nodes": sorted(
                (
                    {
                        "symbol": node["symbol"],
                        "kind": node["kind"],
                        "id": node["id"],
                    }
                    for node in ir["nodes"]
                    if node["kind"] != "module"
                ),
                key=lambda item: item["symbol"],
            ),
        },
        "languageReference": language_reference(),
        "outputContract": output_contract(condition),
    }
    request_id = content_address({"kind": "model_adapter_request", **payload})
    return {
        "schemaVersion": MODEL_ADAPTER_SCHEMA_VERSION,
        "requestId": request_id,
        **{key: value for key, value in payload.items() if key != "schemaVersion"},
    }


def output_contract(condition: str) -> dict[str, Any]:
    if condition == "full-file":
        return {
            "interface": condition,
            "candidate": {
                "encoding": "complete IntentIR source text",
                "completeSource": True,
                "markdownFences": False,
            },
        }
    if condition == "unified-diff":
        return {
            "interface": condition,
            "candidate": {
                "encoding": "UTF-8 unified diff",
                "requiredFileHeaders": [
                    "--- a/workspace.intent",
                    "+++ b/workspace.intent",
                ],
                "optionalGitHeader": (
                    "diff --git a/workspace.intent b/workspace.intent"
                ),
                "allowedPaths": [
                    "a/workspace.intent",
                    "b/workspace.intent",
                ],
                "markdownFences": False,
            },
        }
    if condition == "structure-edit":
        return {
            "interface": condition,
            "candidate": {
                "encoding": "JSON object",
                "allowedTopLevelFields": ["schemaVersion", "operations"],
                "requiredTopLevelFields": ["schemaVersion", "operations"],
                "schemaVersion": "0.1.0",
                "targetReferences": {
                    "existingDefinition": [
                        "context.nodes[].symbol",
                        "context.nodes[].id",
                    ],
                    "newDefinition": "<definition-kind>:<name>",
                },
                "operations": {
                    kind: sorted(OPERATION_FIELDS[kind] - {"expectedId"})
                    for kind in sorted(PATCH_KINDS)
                },
            },
        }
    return {
        "interface": "intent-patch",
        "candidate": {
            "encoding": "JSON object",
            "allowedTopLevelFields": [
                "schemaVersion",
                "baseModuleId",
                "operations",
                "requestedObligations",
            ],
            "requiredTopLevelFields": [
                "schemaVersion",
                "baseModuleId",
                "operations",
                "requestedObligations",
            ],
            "schemaVersion": "0.13.0",
            "baseModuleId": "copy context.moduleId exactly",
            "targetReferences": {
                "target": (
                    "use context.nodes[].symbol for an existing definition; "
                    "use <definition-kind>:<name> for add_definition"
                ),
                "expectedId": (
                    "copy the matching context.nodes[].id for an existing target"
                ),
            },
            "operations": {
                kind: sorted(OPERATION_FIELDS[kind])
                for kind in sorted(PATCH_KINDS)
            },
            "requestedObligations": [
                "static",
                "affected-tests",
                "all-tests",
            ],
        },
    }


def validate_model_request(request: Any) -> None:
    if not isinstance(request, dict):
        raise ModelAdapterError(
            "invalid_model_request",
            "model request must be a JSON object",
            "/",
        )
    unknown = sorted(set(request) - REQUEST_FIELDS)
    if unknown:
        raise ModelAdapterError(
            "unknown_model_request_field",
            f"unknown model request fields: {', '.join(unknown)}",
            "/",
        )
    if request.get("schemaVersion") != MODEL_ADAPTER_SCHEMA_VERSION:
        raise ModelAdapterError(
            "unsupported_model_request_schema",
            f"model request schemaVersion must be {MODEL_ADAPTER_SCHEMA_VERSION}",
            "/schemaVersion",
        )
    request_id = request.get("requestId")
    if not isinstance(request_id, str) or not request_id.startswith("sha256:"):
        raise ModelAdapterError(
            "invalid_model_request_id",
            "model requestId must be a sha256 content address",
            "/requestId",
        )
    for field in ("suite", "application", "checkpointId", "condition", "instruction", "source"):
        if not isinstance(request.get(field), str) or not request[field]:
            raise ModelAdapterError(
                "invalid_model_request_field",
                f"model request field must be a non-empty string: {field}",
                f"/{field}",
            )
    if request["condition"] not in BENCHMARK_CONDITIONS:
        raise ModelAdapterError(
            "unknown_model_condition",
            f"unknown model editing condition: {request['condition']}",
            "/condition",
        )
    checkpoint = request.get("checkpoint")
    if not isinstance(checkpoint, int) or isinstance(checkpoint, bool) or checkpoint < 1:
        raise ModelAdapterError(
            "invalid_model_checkpoint",
            "model checkpoint must be a positive integer",
            "/checkpoint",
        )
    if (
        not isinstance(request.get("context"), dict)
        or not isinstance(request.get("languageReference"), dict)
        or not isinstance(request.get("outputContract"), dict)
    ):
        raise ModelAdapterError(
            "invalid_model_request_context",
            (
                "model request context, languageReference, and "
                "outputContract must be objects"
            ),
            "/context",
        )
    reference = request["languageReference"]
    if (
        reference.get("id") != LANGUAGE_REFERENCE_VERSION
        or not isinstance(reference.get("syntax"), dict)
        or not isinstance(reference.get("rules"), list)
        or not all(isinstance(rule, str) and rule for rule in reference["rules"])
    ):
        raise ModelAdapterError(
            "invalid_model_language_reference",
            "model request languageReference is invalid",
            "/languageReference",
        )
    contract = request["outputContract"]
    if (
        contract.get("interface") != request["condition"]
        or not isinstance(contract.get("candidate"), dict)
    ):
        raise ModelAdapterError(
            "invalid_model_output_contract",
            "model outputContract must match condition and define candidate",
            "/outputContract",
        )


def validate_model_response(response: Any, expected_request_id: str) -> None:
    if not isinstance(response, dict):
        raise ModelAdapterError(
            "invalid_model_response",
            "model response must be a JSON object",
            "/response",
        )
    unknown = sorted(set(response) - RESPONSE_FIELDS)
    if unknown:
        raise ModelAdapterError(
            "unknown_model_response_field",
            f"unknown model response fields: {', '.join(unknown)}",
            "/response",
        )
    if response.get("schemaVersion") != MODEL_ADAPTER_SCHEMA_VERSION:
        raise ModelAdapterError(
            "unsupported_model_response_schema",
            f"model response schemaVersion must be {MODEL_ADAPTER_SCHEMA_VERSION}",
            "/response/schemaVersion",
        )
    if response.get("requestId") != expected_request_id:
        raise ModelAdapterError(
            "model_response_request_mismatch",
            "model response requestId does not match the request",
            "/response/requestId",
        )
    model = response.get("model")
    candidate = response.get("candidate")
    if not isinstance(model, str) or not model:
        raise ModelAdapterError(
            "invalid_model_name",
            "model response must identify a non-empty model name",
            "/response/model",
        )
    if not isinstance(candidate, str) or not candidate:
        raise ModelAdapterError(
            "invalid_model_candidate",
            "model response candidate must be a non-empty string",
            "/response/candidate",
        )
    if len(candidate.encode("utf-8")) > MAX_CANDIDATE_BYTES:
        raise ModelAdapterError(
            "model_candidate_too_large",
            f"model candidate exceeds {MAX_CANDIDATE_BYTES} bytes",
            "/response/candidate",
        )
    usage = response.get("usage")
    if not isinstance(usage, dict) or set(usage) != USAGE_FIELDS:
        raise ModelAdapterError(
            "invalid_model_usage",
            "model usage must contain inputTokens and outputTokens only",
            "/response/usage",
        )
    for field in USAGE_FIELDS:
        value = usage.get(field)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise ModelAdapterError(
                "invalid_model_usage_value",
                f"model usage value must be a non-negative integer or null: {field}",
                f"/response/usage/{field}",
            )
    provenance = response.get("provenance")
    if provenance is None:
        return
    if not isinstance(provenance, dict) or set(provenance) != PROVENANCE_FIELDS:
        raise ModelAdapterError(
            "invalid_model_provenance",
            "model provenance fields do not match the protocol",
            "/response/provenance",
        )
    for field in (
        "provider",
        "responseId",
        "requestedModel",
        "promptId",
        "configurationId",
    ):
        if not isinstance(provenance.get(field), str) or not provenance[field]:
            raise ModelAdapterError(
                "invalid_model_provenance_value",
                f"model provenance field must be a non-empty string: {field}",
                f"/response/provenance/{field}",
            )
    for field in ("promptId", "configurationId"):
        value = provenance[field]
        if (
            len(value) != 71
            or not value.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in value[7:])
        ):
            raise ModelAdapterError(
                "invalid_model_provenance_hash",
                f"model provenance field must be a sha256 content address: {field}",
                f"/response/provenance/{field}",
            )
    reasoning_effort = provenance.get("reasoningEffort")
    if reasoning_effort is not None and not isinstance(reasoning_effort, str):
        raise ModelAdapterError(
            "invalid_model_provenance_reasoning",
            "model provenance reasoningEffort must be a string or null",
            "/response/provenance/reasoningEffort",
        )
    max_output_tokens = provenance.get("maxOutputTokens")
    if (
        not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or max_output_tokens < 1
    ):
        raise ModelAdapterError(
            "invalid_model_provenance_output_limit",
            "model provenance maxOutputTokens must be a positive integer",
            "/response/provenance/maxOutputTokens",
        )
