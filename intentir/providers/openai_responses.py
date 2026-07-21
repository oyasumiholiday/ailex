from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from intentir import __version__
from intentir.canonical import content_address
from intentir.model_adapter import (
    MODEL_ADAPTER_SCHEMA_VERSION,
    ModelAdapterError,
    validate_model_request,
    validate_model_response,
)


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
PROMPT_VERSION = "intentir-openai-responses-v1"
MAX_PROVIDER_REQUEST_BYTES = 4_000_000
MAX_PROVIDER_RESPONSE_BYTES = 4_000_000
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")

DEVELOPER_INSTRUCTIONS = """You generate exactly one candidate for an IntentBench-Evolve checkpoint.
Use only the visible instruction, current source, content-addressed context, and output contract in the input.
Do not explain the answer and do not use Markdown fences.
Place the complete candidate text in the candidate field. The candidate must follow the selected output contract exactly."""

CANDIDATE_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidate"],
    "properties": {
        "candidate": {
            "type": "string",
            "minLength": 1,
        }
    },
}


class OpenAIProviderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class OpenAIResponsesConfig:
    model: str
    reasoning_effort: str | None = None
    max_output_tokens: int = 16_000
    request_timeout_seconds: int = 90
    organization: str | None = None
    project: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model:
            raise OpenAIProviderError(
                "invalid_openai_model",
                "an explicit non-empty OpenAI model is required",
            )
        if self.reasoning_effort not in (None, *REASONING_EFFORTS):
            raise OpenAIProviderError(
                "invalid_openai_reasoning_effort",
                "unsupported OpenAI reasoning effort",
            )
        if (
            not isinstance(self.max_output_tokens, int)
            or isinstance(self.max_output_tokens, bool)
            or not 1 <= self.max_output_tokens <= 200_000
        ):
            raise OpenAIProviderError(
                "invalid_openai_output_limit",
                "max output tokens must be between 1 and 200000",
            )
        if (
            not isinstance(self.request_timeout_seconds, int)
            or isinstance(self.request_timeout_seconds, bool)
            or not 1 <= self.request_timeout_seconds <= 600
        ):
            raise OpenAIProviderError(
                "invalid_openai_timeout",
                "request timeout must be between 1 and 600 seconds",
            )


ProviderSender = Callable[
    [dict[str, Any], str, OpenAIResponsesConfig],
    dict[str, Any],
]


def generate_adapter_response(
    request: dict[str, Any],
    config: OpenAIResponsesConfig,
    api_key: str,
    *,
    sender: ProviderSender | None = None,
) -> dict[str, Any]:
    validate_model_request(request)
    if not isinstance(api_key, str) or not api_key:
        raise OpenAIProviderError(
            "missing_openai_api_key",
            "OPENAI_API_KEY is required",
        )
    payload, prompt_id, configuration_id = build_api_payload(request, config)
    send = sender or _post_openai_response
    provider_response = send(payload, api_key, config)
    candidate = _extract_candidate(provider_response)
    usage = provider_response.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    response_id = provider_response.get("id")
    response_model = provider_response.get("model")
    if not isinstance(response_id, str) or not response_id:
        raise OpenAIProviderError(
            "invalid_openai_response_id",
            "OpenAI response did not include an id",
        )
    if not isinstance(response_model, str) or not response_model:
        raise OpenAIProviderError(
            "invalid_openai_response_model",
            "OpenAI response did not identify the model",
        )
    adapter_response = {
        "schemaVersion": MODEL_ADAPTER_SCHEMA_VERSION,
        "requestId": request["requestId"],
        "model": response_model,
        "candidate": candidate,
        "usage": {
            "inputTokens": _optional_non_negative_integer(usage.get("input_tokens")),
            "outputTokens": _optional_non_negative_integer(
                usage.get("output_tokens")
            ),
        },
        "provenance": {
            "provider": "openai-responses",
            "responseId": response_id,
            "requestedModel": config.model,
            "promptId": prompt_id,
            "configurationId": configuration_id,
            "reasoningEffort": config.reasoning_effort,
            "maxOutputTokens": config.max_output_tokens,
        },
    }
    validate_model_response(adapter_response, request["requestId"])
    return adapter_response


def build_api_payload(
    request: dict[str, Any],
    config: OpenAIResponsesConfig,
) -> tuple[dict[str, Any], str, str]:
    validate_model_request(request)
    prompt_id = content_address(
        {
            "kind": "openai_responses_prompt",
            "version": PROMPT_VERSION,
            "instructions": DEVELOPER_INSTRUCTIONS,
            "responseSchema": CANDIDATE_RESPONSE_SCHEMA,
        }
    )
    configuration_id = content_address(
        {
            "kind": "openai_responses_configuration",
            "model": config.model,
            "reasoningEffort": config.reasoning_effort,
            "maxOutputTokens": config.max_output_tokens,
            "store": False,
            "promptId": prompt_id,
        }
    )
    model_input = json.dumps(
        {
            "requestId": request["requestId"],
            "suite": request["suite"],
            "application": request["application"],
            "checkpoint": request["checkpoint"],
            "checkpointId": request["checkpointId"],
            "condition": request["condition"],
            "instruction": request["instruction"],
            "currentSource": request["source"],
            "context": request["context"],
            "outputContract": request["outputContract"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload: dict[str, Any] = {
        "model": config.model,
        "instructions": DEVELOPER_INSTRUCTIONS,
        "input": model_input,
        "max_output_tokens": config.max_output_tokens,
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "intentir_candidate",
                "description": "One candidate matching the requested editing interface.",
                "strict": True,
                "schema": CANDIDATE_RESPONSE_SCHEMA,
            }
        },
        "metadata": {
            "intentir_request_id": request["requestId"],
            "intentir_prompt_id": prompt_id,
        },
    }
    if config.reasoning_effort is not None:
        payload["reasoning"] = {"effort": config.reasoning_effort}
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_PROVIDER_REQUEST_BYTES:
        raise OpenAIProviderError(
            "openai_request_too_large",
            "OpenAI request exceeded the provider request limit",
        )
    return payload, prompt_id, configuration_id


def _post_openai_response(
    payload: dict[str, Any],
    api_key: str,
    config: OpenAIResponsesConfig,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": f"intentir-openai-adapter/{__version__}",
    }
    if config.organization:
        headers["OpenAI-Organization"] = config.organization
    if config.project:
        headers["OpenAI-Project"] = config.project
    http_request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            http_request,
            timeout=config.request_timeout_seconds,
        ) as response:
            raw = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise OpenAIProviderError(
            "openai_http_error",
            f"OpenAI API returned HTTP {error.code}",
        ) from error
    except urllib.error.URLError as error:
        raise OpenAIProviderError(
            "openai_network_error",
            "OpenAI API request failed",
        ) from error
    except TimeoutError as error:
        raise OpenAIProviderError(
            "openai_timeout",
            "OpenAI API request timed out",
        ) from error
    if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
        raise OpenAIProviderError(
            "openai_response_too_large",
            "OpenAI response exceeded the provider response limit",
        )
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OpenAIProviderError(
            "invalid_openai_response_json",
            "OpenAI response was not valid UTF-8 JSON",
        ) from error
    if not isinstance(parsed, dict):
        raise OpenAIProviderError(
            "invalid_openai_response",
            "OpenAI response must be a JSON object",
        )
    return parsed


def _extract_candidate(response: dict[str, Any]) -> str:
    if response.get("status") != "completed":
        raise OpenAIProviderError(
            "incomplete_openai_response",
            "OpenAI response did not complete",
        )
    texts = []
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "output_text"
                    and isinstance(part.get("text"), str)
                ):
                    texts.append(part["text"])
    if not texts:
        raise OpenAIProviderError(
            "missing_openai_output_text",
            "OpenAI response did not contain output text",
        )
    try:
        structured = json.loads("".join(texts))
    except json.JSONDecodeError as error:
        raise OpenAIProviderError(
            "invalid_openai_structured_output",
            "OpenAI structured output was not valid JSON",
        ) from error
    if (
        not isinstance(structured, dict)
        or set(structured) != {"candidate"}
        or not isinstance(structured["candidate"], str)
        or not structured["candidate"]
    ):
        raise OpenAIProviderError(
            "invalid_openai_candidate",
            "OpenAI structured output did not contain one candidate string",
        )
    return structured["candidate"]


def _optional_non_negative_integer(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intentir-openai-adapter",
        description="Bridge IntentBench-Evolve requests to the OpenAI Responses API.",
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--reasoning-effort", choices=REASONING_EFFORTS)
    parser.add_argument("--max-output-tokens", type=int, default=16_000)
    parser.add_argument("--request-timeout", type=int, default=90)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        request = json.load(sys.stdin)
        config = OpenAIResponsesConfig(
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            max_output_tokens=args.max_output_tokens,
            request_timeout_seconds=args.request_timeout,
            organization=os.environ.get("OPENAI_ORGANIZATION"),
            project=os.environ.get("OPENAI_PROJECT"),
        )
        response = generate_adapter_response(
            request,
            config,
            os.environ.get("OPENAI_API_KEY", ""),
        )
    except json.JSONDecodeError:
        print("[invalid_model_request_json] stdin was not valid JSON", file=sys.stderr)
        raise SystemExit(1)
    except (ModelAdapterError, OpenAIProviderError) as error:
        code = getattr(error, "code", "openai_adapter_error")
        print(f"[{code}] {error}", file=sys.stderr)
        raise SystemExit(1) from error
    json.dump(response, sys.stdout, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
