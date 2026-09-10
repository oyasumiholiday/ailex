from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from intentir.benchmark import BENCHMARK_CONDITIONS, BenchmarkError
from intentir.canonical import content_address
from intentir.model_adapter import ModelAdapterError
from intentir.providers.openai_responses import (
    OPENAI_INPUT_TOKENS_URL,
    PROMPT_VERSION,
    InputTokenCounter,
    OpenAIProviderError,
    OpenAIResponsesConfig,
    ProviderSender,
    _generate_adapter_response_from_prepared,
    build_api_payload,
    build_input_token_count_payload,
    count_response_input_tokens,
)
from intentir.trajectory import _load_trajectory_manifest, run_trajectory_manifest


PILOT_SCHEMA_VERSION = "0.1.0"
PROTOCOL_FIELDS = {
    "schemaVersion",
    "id",
    "manifest",
    "conditions",
    "provider",
    "promptVersion",
    "model",
    "reasoningEffort",
    "maxOutputTokens",
    "requestTimeoutSeconds",
    "trials",
    "budgetUsd",
    "maxRequestBytesPerCall",
    "reservedInputTokensPerCall",
    "pricing",
}
PRICING_FIELDS = {
    "currency",
    "inputPerMillionTokens",
    "outputPerMillionTokens",
    "observedAt",
    "sourceUrl",
}
SNAPSHOT_RE = re.compile(r".*-\d{4}-\d{2}-\d{2}$")
DECIMAL_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PILOT_REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh")
MILLION = Decimal(1_000_000)
BUDGET_GUARD_VERSION = "intentir-pilot-budget-guard-v1"


class PilotError(ValueError):
    def __init__(self, code: str, message: str, path: str = "/") -> None:
        self.code = code
        self.message = message
        self.path = path
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "path": self.path}


class PilotGuardError(ModelAdapterError):
    abort_batch = True


def load_pilot_protocol(path: Path | str) -> dict[str, Any]:
    protocol_path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(protocol_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise PilotError(
            "pilot_protocol_read_error",
            "pilot protocol could not be read",
            "/protocol",
        ) from error
    except json.JSONDecodeError as error:
        raise PilotError(
            "invalid_pilot_protocol_json",
            "pilot protocol is not valid JSON",
            "/protocol",
        ) from error
    if not isinstance(raw, dict):
        raise PilotError(
            "invalid_pilot_protocol",
            "pilot protocol must be a JSON object",
        )
    _reject_unknown(raw, PROTOCOL_FIELDS, "/")
    if raw.get("schemaVersion") != PILOT_SCHEMA_VERSION:
        raise PilotError(
            "unsupported_pilot_schema",
            f"pilot schemaVersion must be {PILOT_SCHEMA_VERSION}",
            "/schemaVersion",
        )
    protocol_id = _non_empty_string(raw, "id")
    provider = _non_empty_string(raw, "provider")
    if provider != "openai-responses":
        raise PilotError(
            "unsupported_pilot_provider",
            "pilot provider must be openai-responses",
            "/provider",
        )
    prompt_version = None
    if "promptVersion" in raw:
        prompt_version = _non_empty_string(raw, "promptVersion")
        if prompt_version != PROMPT_VERSION:
            raise PilotError(
                "pilot_prompt_version_mismatch",
                (
                    "pilot promptVersion must match the installed provider "
                    f"prompt: {PROMPT_VERSION}"
                ),
                "/promptVersion",
            )
    model = _non_empty_string(raw, "model")
    if not SNAPSHOT_RE.fullmatch(model):
        raise PilotError(
            "pilot_model_not_snapshot",
            "pilot model must be a date-pinned snapshot",
            "/model",
        )
    reasoning_effort = raw.get("reasoningEffort")
    if reasoning_effort not in PILOT_REASONING_EFFORTS:
        raise PilotError(
            "invalid_pilot_reasoning_effort",
            "pilot reasoningEffort is unsupported",
            "/reasoningEffort",
        )
    max_output_tokens = _positive_int(raw, "maxOutputTokens", maximum=200_000)
    timeout = _positive_int(raw, "requestTimeoutSeconds", maximum=600)
    trials = _positive_int(raw, "trials", maximum=20)
    max_request_bytes = _positive_int(
        raw,
        "maxRequestBytesPerCall",
        maximum=4_000_000,
    )
    reserved_input_tokens = _positive_int(
        raw,
        "reservedInputTokensPerCall",
        maximum=1_000_000,
    )
    budget = _positive_decimal(raw.get("budgetUsd"), "/budgetUsd")

    conditions = raw.get("conditions")
    if (
        not isinstance(conditions, list)
        or not conditions
        or not all(isinstance(item, str) for item in conditions)
        or len(set(conditions)) != len(conditions)
        or set(conditions) - set(BENCHMARK_CONDITIONS)
    ):
        raise PilotError(
            "invalid_pilot_conditions",
            "conditions must be unique supported benchmark conditions",
            "/conditions",
        )

    manifest_reference = _non_empty_string(raw, "manifest")
    manifest_path = (protocol_path.parent / manifest_reference).resolve()
    try:
        manifest_path.relative_to(protocol_path.parent)
    except ValueError as error:
        raise PilotError(
            "pilot_manifest_outside_protocol_root",
            "pilot manifest must remain inside the protocol directory",
            "/manifest",
        ) from error
    try:
        suite = _load_trajectory_manifest(manifest_path, require_candidates=False)
    except BenchmarkError as error:
        raise PilotError(error.code, error.message, f"/manifest{error.path}") from error
    unavailable = sorted(set(conditions) - set(suite["conditions"]))
    if unavailable:
        raise PilotError(
            "pilot_condition_not_in_manifest",
            f"pilot conditions are absent from the manifest: {', '.join(unavailable)}",
            "/conditions",
        )

    pricing = raw.get("pricing")
    if not isinstance(pricing, dict):
        raise PilotError(
            "invalid_pilot_pricing",
            "pricing must be a JSON object",
            "/pricing",
        )
    _reject_unknown(pricing, PRICING_FIELDS, "/pricing")
    if pricing.get("currency") != "USD":
        raise PilotError(
            "invalid_pilot_currency",
            "pilot pricing currency must be USD",
            "/pricing/currency",
        )
    input_price = _positive_decimal(
        pricing.get("inputPerMillionTokens"),
        "/pricing/inputPerMillionTokens",
    )
    output_price = _positive_decimal(
        pricing.get("outputPerMillionTokens"),
        "/pricing/outputPerMillionTokens",
    )
    observed_at = _non_empty_string(pricing, "observedAt", prefix="/pricing")
    if not DATE_RE.fullmatch(observed_at):
        raise PilotError(
            "invalid_pilot_pricing_date",
            "pricing observedAt must use YYYY-MM-DD",
            "/pricing/observedAt",
        )
    source_url = _non_empty_string(pricing, "sourceUrl", prefix="/pricing")
    if not source_url.startswith("https://developers.openai.com/"):
        raise PilotError(
            "invalid_pilot_pricing_source",
            "pricing source must be an official OpenAI developer URL",
            "/pricing/sourceUrl",
        )

    checkpoints_per_trial = sum(
        len(application["checkpoints"]) for application in suite["applications"]
    )
    maximum_calls = checkpoints_per_trial * len(conditions) * trials
    reservation_per_call = _token_cost(
        reserved_input_tokens,
        max_output_tokens,
        input_price,
        output_price,
    )
    maximum_reserved_cost = reservation_per_call * maximum_calls
    if maximum_reserved_cost > budget:
        raise PilotError(
            "pilot_budget_does_not_cover_reservation",
            "budgetUsd is lower than the maximum reserved pilot cost",
            "/budgetUsd",
        )

    normalized = {
        "schemaVersion": PILOT_SCHEMA_VERSION,
        "id": protocol_id,
        "manifest": manifest_reference,
        "conditions": list(conditions),
        "provider": provider,
        "model": model,
        "reasoningEffort": reasoning_effort,
        "maxOutputTokens": max_output_tokens,
        "requestTimeoutSeconds": timeout,
        "trials": trials,
        "budgetUsd": _decimal_text(budget),
        "maxRequestBytesPerCall": max_request_bytes,
        "reservedInputTokensPerCall": reserved_input_tokens,
        "pricing": {
            "currency": "USD",
            "inputPerMillionTokens": _decimal_text(input_price),
            "outputPerMillionTokens": _decimal_text(output_price),
            "observedAt": observed_at,
            "sourceUrl": source_url,
        },
    }
    if prompt_version is not None:
        normalized["promptVersion"] = prompt_version
    return {
        "path": protocol_path,
        "manifestPath": manifest_path,
        "suite": suite,
        "protocol": normalized,
        "protocolHash": content_address(
            {"kind": "intentbench_pilot_protocol", **normalized}
        ),
        "budget": budget,
        "inputPrice": input_price,
        "outputPrice": output_price,
        "reservationPerCall": reservation_per_call,
        "maximumCalls": maximum_calls,
        "maximumReservedCost": maximum_reserved_cost,
    }


def preflight_pilot(path: Path | str) -> dict[str, Any]:
    loaded = load_pilot_protocol(path)
    protocol = loaded["protocol"]
    return {
        "ok": True,
        "mode": "pilot-preflight",
        "willCallProvider": False,
        "budgetGuardVersion": BUDGET_GUARD_VERSION,
        "protocolId": protocol["id"],
        "protocolHash": loaded["protocolHash"],
        "manifest": protocol["manifest"],
        "conditions": protocol["conditions"],
        "model": protocol["model"],
        "promptVersion": protocol.get("promptVersion"),
        "reasoningEffort": protocol["reasoningEffort"],
        "trials": protocol["trials"],
        "maximumCalls": loaded["maximumCalls"],
        "providerRequestPlan": {
            "maximumGenerationRequests": loaded["maximumCalls"],
            "maximumInputTokenCountRequests": loaded["maximumCalls"],
            "inputTokenCountRequestsAreAdditional": True,
            "inputTokenCountEndpoint": OPENAI_INPUT_TOKENS_URL,
        },
        "budget": {
            "currency": "USD",
            "limitUsd": protocol["budgetUsd"],
            "reservedPerCallUsd": _decimal_text(loaded["reservationPerCall"]),
            "maximumReservedCostUsd": _decimal_text(
                loaded["maximumReservedCost"]
            ),
            "pricingObservedAt": protocol["pricing"]["observedAt"],
            "accountingBasis": "fixed-protocol-token-prices",
            "actualAccountBillGuaranteed": False,
            "inputTokenCountRequestCostsIncluded": False,
        },
        "executionGuards": [
            "--execute is required",
            "--confirm-budget-usd must exactly match budgetUsd",
            "OPENAI_API_KEY must be present",
            "the output directory must not already exist",
            "provider retries are disabled",
            "each generation requires a successful input-token count request",
            "input-token count requests are additional provider transmissions",
        ],
    }


class BudgetedOpenAIAdapter:
    def __init__(
        self,
        loaded: dict[str, Any],
        api_key: str,
        record_directory: Path,
        *,
        sender: ProviderSender | None = None,
        counter: InputTokenCounter | None = None,
    ) -> None:
        protocol = loaded["protocol"]
        self.loaded = loaded
        self.api_key = api_key
        self.record_directory = record_directory
        self.sender = sender
        self.counter = counter
        self.config = OpenAIResponsesConfig(
            model=protocol["model"],
            reasoning_effort=protocol["reasoningEffort"],
            max_output_tokens=protocol["maxOutputTokens"],
            request_timeout_seconds=protocol["requestTimeoutSeconds"],
        )
        self.accounted_cost = Decimal(0)
        self.provider_calls = 0
        self.token_count_calls = 0
        self.records: list[dict[str, Any]] = []
        self.trial = 0

    def generate(self, request: dict[str, Any]) -> dict[str, Any]:
        protocol = self.loaded["protocol"]
        prepared_payload = build_api_payload(request, self.config)
        payload, prompt_id, configuration_id = prepared_payload
        request_bytes = len(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        reservation = self.loaded["reservationPerCall"]
        sequence = len(self.records) + 1
        record: dict[str, Any] = {
            "schemaVersion": PILOT_SCHEMA_VERSION,
            "budgetGuardVersion": BUDGET_GUARD_VERSION,
            "sequence": sequence,
            "trial": self.trial,
            "status": "guard-started",
            "requestBytes": request_bytes,
            "reservedCostUsd": _decimal_text(reservation),
            "reservedInputTokens": protocol["reservedInputTokensPerCall"],
            "reservedOutputTokens": protocol["maxOutputTokens"],
            "promptId": prompt_id,
            "configurationId": configuration_id,
            "request": request,
            "providerPayload": payload,
            "inputTokenCountDispatched": False,
            "generationDispatched": False,
        }
        record_path = self.record_directory / f"{sequence:04d}.json"
        _write_json(record_path, record)

        if self.provider_calls >= self.loaded["maximumCalls"]:
            self._reject_guard(
                record,
                "maximum-calls-rejected",
                "pilot_maximum_calls_exceeded",
                "maximumCalls was reached before generation dispatch",
                "/pilot/maximumCalls",
            )
        if request_bytes > protocol["maxRequestBytesPerCall"]:
            self._reject_guard(
                record,
                "request-size-rejected",
                "pilot_request_too_large",
                "provider request exceeded maxRequestBytesPerCall",
                "/pilot/maxRequestBytesPerCall",
            )
        if self.accounted_cost + reservation > self.loaded["budget"]:
            self._reject_guard(
                record,
                "budget-reservation-rejected",
                "pilot_budget_exhausted",
                "the next reserved call would exceed budgetUsd",
                "/pilot/budgetUsd",
            )
        if self.sender is not None and self.counter is None:
            self._reject_guard(
                record,
                "input-token-counter-required",
                "pilot_input_token_counter_required",
                "an injected sender requires an explicit input-token counter",
                "/pilot/inputTokenCounter",
            )

        count_payload = build_input_token_count_payload(payload)
        count_payload_hash = content_address(
            {
                "kind": "openai_responses_input_token_count_payload",
                "payload": count_payload,
            }
        )
        record["inputTokenCount"] = {
            "endpoint": OPENAI_INPUT_TOKENS_URL,
            "payload": count_payload,
            "payloadHash": count_payload_hash,
        }
        record["status"] = "input-token-count-started"
        record["inputTokenCountDispatched"] = True
        self.token_count_calls += 1
        _write_json(record_path, record)
        try:
            input_tokens, sent_count_payload = count_response_input_tokens(
                payload,
                self.config,
                self.api_key,
                counter=self.counter,
            )
        except OpenAIProviderError as error:
            record.update(
                {
                    "status": "input-token-count-error",
                    "diagnostic": {"code": error.code, "message": error.message},
                }
            )
            self._record(record)
            raise PilotGuardError(
                error.code,
                error.message,
                "/provider/inputTokens",
            ) from error
        if sent_count_payload != count_payload:
            self._reject_guard(
                record,
                "input-token-payload-mismatch",
                "pilot_input_token_payload_mismatch",
                "count payload did not match the prepared generation payload",
                "/pilot/inputTokenCount",
            )
        record["inputTokenCount"]["inputTokens"] = input_tokens
        if input_tokens > protocol["reservedInputTokensPerCall"]:
            self._reject_guard(
                record,
                "input-token-reservation-rejected",
                "pilot_input_token_reservation_exceeded",
                "counted input tokens exceeded reservedInputTokensPerCall",
                "/pilot/reservedInputTokensPerCall",
            )
        if build_input_token_count_payload(payload) != count_payload:
            self._reject_guard(
                record,
                "input-token-payload-mismatch",
                "pilot_input_token_payload_mismatch",
                "prepared generation payload changed after input-token counting",
                "/pilot/inputTokenCount",
            )

        self.accounted_cost += reservation
        self.provider_calls += 1
        record.update(
            {
                "status": "generation-started",
                "generationDispatched": True,
                "accountingMode": "reserved-before-dispatch",
                "accountedCostUsd": _decimal_text(reservation),
                "cumulativeAccountedCostUsd": _decimal_text(self.accounted_cost),
            }
        )
        _write_json(record_path, record)
        try:
            response = _generate_adapter_response_from_prepared(
                request,
                self.config,
                self.api_key,
                prepared_payload,
                sender=self.sender,
            )
        except OpenAIProviderError as error:
            record.update(
                {
                    "status": "provider-error",
                    "diagnostic": {"code": error.code, "message": error.message},
                    "accountingMode": "reserved-upper-bound",
                    "accountedCostUsd": _decimal_text(reservation),
                    "cumulativeAccountedCostUsd": _decimal_text(
                        self.accounted_cost
                    ),
                }
            )
            self._record(record)
            raise ModelAdapterError(error.code, error.message, "/provider") from error

        usage = response["usage"]
        input_tokens = usage["inputTokens"]
        output_tokens = usage["outputTokens"]
        usage_violation = (
            input_tokens is not None
            and input_tokens > protocol["reservedInputTokensPerCall"]
        ) or (
            output_tokens is not None
            and output_tokens > protocol["maxOutputTokens"]
        )
        if input_tokens is not None and output_tokens is not None:
            provider_usage_cost = _token_cost(
                input_tokens,
                output_tokens,
                self.loaded["inputPrice"],
                self.loaded["outputPrice"],
            )
            call_cost = (
                max(reservation, provider_usage_cost)
                if usage_violation
                else provider_usage_cost
            )
            accounting_mode = "provider-usage"
        else:
            partial_usage_upper_bound = _token_cost(
                (
                    input_tokens
                    if input_tokens is not None
                    else protocol["reservedInputTokensPerCall"]
                ),
                (
                    output_tokens
                    if output_tokens is not None
                    else protocol["maxOutputTokens"]
                ),
                self.loaded["inputPrice"],
                self.loaded["outputPrice"],
            )
            call_cost = max(reservation, partial_usage_upper_bound)
            accounting_mode = "reserved-bounds-partial-usage-estimate"
        self.accounted_cost += call_cost - reservation
        record.update(
            {
                "status": "completed",
                "accountingMode": accounting_mode,
                "accountedCostUsd": _decimal_text(call_cost),
                "cumulativeAccountedCostUsd": _decimal_text(self.accounted_cost),
                "response": response,
            }
        )
        if usage_violation:
            record["status"] = "usage-reservation-violation"
            record["diagnostic"] = {
                "code": "pilot_usage_reservation_exceeded",
                "message": "provider usage exceeded reserved token bounds",
            }
            self._record(record)
            raise PilotGuardError(
                "pilot_usage_reservation_exceeded",
                "provider usage exceeded reserved token bounds",
                "/response/usage",
            )
        if response["model"] != protocol["model"]:
            record["status"] = "model-mismatch"
            record["diagnostic"] = {
                "code": "pilot_model_mismatch",
                "message": "provider response model did not match the pinned snapshot",
            }
            self._record(record)
            raise PilotGuardError(
                "pilot_model_mismatch",
                "provider response model did not match the pinned snapshot",
                "/response/model",
            )
        if self.accounted_cost > self.loaded["budget"]:
            record["status"] = "budget-exceeded"
            self._record(record)
            raise PilotGuardError(
                "pilot_budget_exceeded",
                "provider usage exceeded the fixed pilot budget",
                "/pilot/budgetUsd",
            )
        self._record(record)
        return response

    def _reject_guard(
        self,
        record: dict[str, Any],
        status: str,
        code: str,
        message: str,
        path: str,
    ) -> None:
        record["status"] = status
        record["diagnostic"] = {"code": code, "message": message}
        self._record(record)
        raise PilotGuardError(code, message, path)

    def _record(self, record: dict[str, Any]) -> None:
        self.records.append(record)
        _write_json(
            self.record_directory / f"{record['sequence']:04d}.json",
            record,
        )


def run_pilot(
    path: Path | str,
    output_directory: Path | str,
    *,
    confirm_budget_usd: str | None,
    api_key: str,
    sender: ProviderSender | None = None,
    counter: InputTokenCounter | None = None,
) -> dict[str, Any]:
    loaded = load_pilot_protocol(path)
    try:
        confirmation = Decimal(confirm_budget_usd or "")
    except InvalidOperation as error:
        raise PilotError(
            "pilot_budget_confirmation_required",
            "confirm-budget-usd must exactly match budgetUsd",
            "/confirmation",
        ) from error
    if confirmation != loaded["budget"]:
        raise PilotError(
            "pilot_budget_confirmation_mismatch",
            "confirm-budget-usd must exactly match budgetUsd",
            "/confirmation",
        )
    if not isinstance(api_key, str) or not api_key:
        raise PilotError(
            "missing_openai_api_key",
            "OPENAI_API_KEY is required only for an executed pilot",
            "/environment/OPENAI_API_KEY",
        )
    if sender is not None and counter is None:
        raise PilotError(
            "pilot_input_token_counter_required",
            "an injected sender requires an explicit offline input-token counter",
            "/inputTokenCounter",
        )

    output_path = Path(output_directory).expanduser().resolve()
    if output_path.exists():
        raise PilotError(
            "pilot_output_already_exists",
            "pilot output directory must not already exist",
            "/outputDirectory",
        )
    output_path.mkdir(parents=True)
    calls_path = output_path / "calls"
    calls_path.mkdir()
    preflight = preflight_pilot(path)
    _write_json(output_path / "protocol.snapshot.json", loaded["protocol"])
    _write_json(output_path / "preflight.json", preflight)

    adapter = BudgetedOpenAIAdapter(
        loaded,
        api_key,
        calls_path,
        sender=sender,
        counter=counter,
    )
    trial_results = []
    for trial in range(1, loaded["protocol"]["trials"] + 1):
        adapter.trial = trial
        result = run_trajectory_manifest(
            loaded["manifestPath"],
            conditions=loaded["protocol"]["conditions"],
            measure_time=True,
            adapter=adapter,
        )
        result["trial"] = trial
        trial_results.append(result)
        _write_json(output_path / f"trial_{trial:02d}.result.json", result)
        if not result["ok"]:
            break

    result = {
        "ok": (
            len(trial_results) == loaded["protocol"]["trials"]
            and all(item["ok"] for item in trial_results)
        ),
        "schemaVersion": PILOT_SCHEMA_VERSION,
        "mode": "pilot-execution",
        "protocolId": loaded["protocol"]["id"],
        "protocolHash": loaded["protocolHash"],
        "model": loaded["protocol"]["model"],
        "reasoningEffort": loaded["protocol"]["reasoningEffort"],
        "conditions": loaded["protocol"]["conditions"],
        "trialsPlanned": loaded["protocol"]["trials"],
        "trialsCompleted": len(trial_results),
        "providerCalls": adapter.provider_calls,
        "tokenCountCalls": adapter.token_count_calls,
        "provenance": {
            "budgetGuardVersion": BUDGET_GUARD_VERSION,
            "inputTokenCountEndpoint": OPENAI_INPUT_TOKENS_URL,
            "inputTokenCountCompatibility": "live-unverified",
            "inputTokenCountRequestsAreAdditional": True,
            "budgetAccountingBasis": "fixed-protocol-token-prices",
            "partialUsageAccounting": (
                "estimated-from-reserved-bounds-conditional-on-service-caps"
            ),
            "inputTokenCountRequestCostsIncluded": False,
            "actualAccountBillGuaranteed": False,
        },
        "budget": {
            "currency": "USD",
            "limitUsd": loaded["protocol"]["budgetUsd"],
            "accountedCostUsd": _decimal_text(adapter.accounted_cost),
        },
        "outputDirectory": str(output_path),
        "trials": trial_results,
    }
    _write_json(output_path / "summary.json", result)
    return result


def render_pilot_result(result: dict[str, Any]) -> str:
    budget = result["budget"]
    if result["mode"] == "pilot-preflight":
        return "\n".join(
            [
                f"IntentBench pilot preflight: {result['protocolId']}",
                f"  model: {result['model']} ({result['reasoningEffort']})",
                f"  maximum calls: {result['maximumCalls']}",
                (
                    "  maximum input-token count calls: "
                    f"{result['providerRequestPlan']['maximumInputTokenCountRequests']} "
                    "(additional)"
                ),
                (
                    "  budget: USD "
                    f"{budget['maximumReservedCostUsd']} reserved / "
                    f"{budget['limitUsd']} limit"
                ),
                "  provider calls: disabled (use --execute with exact budget confirmation)",
                "",
            ]
        )
    return "\n".join(
        [
            f"IntentBench pilot: {'PASS' if result['ok'] else 'FAIL'}",
            f"  model: {result['model']} ({result['reasoningEffort']})",
            f"  provider calls: {result['providerCalls']}",
            f"  input-token count calls: {result['tokenCountCalls']}",
            f"  accounted cost: USD {budget['accountedCostUsd']} / {budget['limitUsd']}",
            f"  output: {result['outputDirectory']}",
            "",
        ]
    )


def _token_cost(
    input_tokens: int,
    output_tokens: int,
    input_price: Decimal,
    output_price: Decimal,
) -> Decimal:
    return (
        Decimal(input_tokens) * input_price
        + Decimal(output_tokens) * output_price
    ) / MILLION


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")


def _positive_decimal(value: Any, path: str) -> Decimal:
    if not isinstance(value, str) or not DECIMAL_RE.fullmatch(value):
        raise PilotError(
            "invalid_pilot_decimal",
            "decimal money and pricing values must be plain decimal strings",
            path,
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise PilotError("invalid_pilot_decimal", "invalid decimal value", path) from error
    if not parsed.is_finite() or parsed <= 0:
        raise PilotError(
            "invalid_pilot_decimal",
            "decimal value must be finite and positive",
            path,
        )
    return parsed


def _positive_int(
    value: dict[str, Any],
    field: str,
    *,
    maximum: int,
) -> int:
    item = value.get(field)
    if (
        not isinstance(item, int)
        or isinstance(item, bool)
        or not 1 <= item <= maximum
    ):
        raise PilotError(
            "invalid_pilot_integer",
            f"{field} must be an integer between 1 and {maximum}",
            f"/{field}",
        )
    return item


def _non_empty_string(
    value: dict[str, Any],
    field: str,
    *,
    prefix: str = "",
) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise PilotError(
            "invalid_pilot_string",
            f"{field} must be a non-empty string",
            f"{prefix}/{field}",
        )
    return item


def _reject_unknown(value: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PilotError(
            "unknown_pilot_field",
            f"unknown pilot fields: {', '.join(unknown)}",
            path,
        )


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
