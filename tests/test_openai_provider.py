import json
import os
import ssl
import unittest
import urllib.error
from unittest import mock

from intentir.compiler import compile_source
from intentir.demos.concurrent_agent import DEMO_SOURCE
from intentir.model_adapter import build_model_request
from intentir.providers.openai_responses import (
    CANDIDATE_RESPONSE_SCHEMA,
    OpenAIProviderError,
    OpenAIResponsesConfig,
    _openai_ssl_context,
    _post_openai_response,
    build_api_payload,
    build_parser,
    generate_adapter_response,
)


class OpenAIResponsesProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.request = build_model_request(
            suite="openai-provider-test",
            application="work-item",
            checkpoint=1,
            checkpoint_id="add-priority",
            condition="intent-patch",
            instruction="Add an Integer priority field with default 0.",
            source=DEMO_SOURCE,
            ir=compile_source(DEMO_SOURCE),
        )
        self.config = OpenAIResponsesConfig(
            model="gpt-test-2026-01-01",
            reasoning_effort="low",
            max_output_tokens=4096,
        )

    def test_payload_is_deterministic_structured_and_secret_free(self) -> None:
        first = build_api_payload(self.request, self.config)
        second = build_api_payload(self.request, self.config)

        self.assertEqual(first, second)
        payload, prompt_id, configuration_id = first
        self.assertFalse(payload["store"])
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertEqual(
            payload["text"]["format"]["schema"],
            CANDIDATE_RESPONSE_SCHEMA,
        )
        self.assertEqual(payload["reasoning"], {"effort": "low"})
        model_input = json.loads(payload["input"])
        self.assertEqual(
            model_input["languageReference"]["id"],
            "intentir-benchmark-subset-0.1.0",
        )
        self.assertEqual(
            model_input["outputContract"]["interface"],
            "intent-patch",
        )
        self.assertTrue(prompt_id.startswith("sha256:"))
        self.assertTrue(configuration_id.startswith("sha256:"))
        changed_config = OpenAIResponsesConfig(
            model=self.config.model,
            reasoning_effort="medium",
            max_output_tokens=self.config.max_output_tokens,
        )
        self.assertNotEqual(
            configuration_id,
            build_api_payload(self.request, changed_config)[2],
        )
        option_strings = {
            option
            for action in build_parser()._actions
            for option in action.option_strings
        }
        self.assertNotIn("--api-key", option_strings)
        serialized = json.dumps(payload)
        self.assertNotIn("test-secret", serialized)
        self.assertNotIn("item-hidden", serialized)

    def test_response_is_converted_to_adapter_protocol_with_provenance(self) -> None:
        candidate = '{"schemaVersion":"0.13.0","baseModuleId":"sha256:test"}'

        def fake_sender(payload, api_key, config):
            self.assertEqual(api_key, "test-secret")
            self.assertEqual(payload["model"], config.model)
            return {
                "id": "resp_test_123",
                "status": "completed",
                "model": "gpt-test-2026-01-01",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"candidate": candidate}),
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 321, "output_tokens": 45},
            }

        response = generate_adapter_response(
            self.request,
            self.config,
            "test-secret",
            sender=fake_sender,
        )

        self.assertEqual(response["candidate"], candidate)
        self.assertEqual(response["usage"], {"inputTokens": 321, "outputTokens": 45})
        self.assertEqual(response["provenance"]["provider"], "openai-responses")
        self.assertEqual(response["provenance"]["responseId"], "resp_test_123")
        self.assertEqual(response["provenance"]["reasoningEffort"], "low")
        self.assertNotIn("test-secret", json.dumps(response))

    def test_incomplete_response_is_rejected_without_echoing_provider_body(self) -> None:
        def fake_sender(payload, api_key, config):
            return {
                "id": "resp_incomplete",
                "status": "incomplete",
                "model": config.model,
                "output": [],
                "private": "do-not-echo",
            }

        with self.assertRaises(OpenAIProviderError) as context:
            generate_adapter_response(
                self.request,
                self.config,
                "test-secret",
                sender=fake_sender,
            )
        self.assertEqual(context.exception.code, "incomplete_openai_response")
        self.assertNotIn("do-not-echo", str(context.exception))

    def test_explicit_ca_bundle_has_priority(self) -> None:
        expected_context = object()
        with (
            mock.patch.dict(
                os.environ,
                {"SSL_CERT_FILE": "/tmp/intentir-test-ca.pem"},
            ),
            mock.patch(
                "intentir.providers.openai_responses.ssl.create_default_context",
                return_value=expected_context,
            ) as create_context,
        ):
            context = _openai_ssl_context()

        self.assertIs(context, expected_context)
        create_context.assert_called_once_with(
            cafile="/tmp/intentir-test-ca.pem",
        )

    def test_tls_verification_failure_has_specific_diagnostic(self) -> None:
        tls_error = ssl.SSLCertVerificationError(
            1,
            "unable to get local issuer certificate",
        )
        with mock.patch(
            "intentir.providers.openai_responses.urllib.request.urlopen",
            side_effect=urllib.error.URLError(tls_error),
        ):
            with self.assertRaises(OpenAIProviderError) as context:
                _post_openai_response(
                    {"model": self.config.model},
                    "test-secret",
                    self.config,
                )

        self.assertEqual(context.exception.code, "openai_tls_error")
        self.assertNotIn("test-secret", str(context.exception))


if __name__ == "__main__":
    unittest.main()
