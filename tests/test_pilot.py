import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from intentir.compiler import compile_source
from intentir.demos.concurrent_agent import DEMO_SOURCE
from intentir.model_adapter import ModelAdapterError, build_model_request
from intentir.pilot import (
    BUDGET_GUARD_VERSION,
    BudgetedOpenAIAdapter,
    PilotError,
    load_pilot_protocol,
    preflight_pilot,
    run_pilot,
)
from intentir.providers.openai_responses import OpenAIProviderError, PROMPT_VERSION


class PilotExperimentTest(unittest.TestCase):
    def test_preflight_guards_and_offline_execution_archive_every_call(self) -> None:
        root = Path(__file__).resolve().parents[1]
        suite = root / "benchmarks" / "intentbench_evolve"
        protocol = suite / "openai_pilot_protocol.json"

        with mock.patch(
            "intentir.providers.openai_responses.urllib.request.urlopen",
            side_effect=AssertionError("preflight must remain network-free"),
        ):
            preflight = preflight_pilot(protocol)
        self.assertTrue(preflight["ok"])
        self.assertFalse(preflight["willCallProvider"])
        self.assertEqual(preflight["budgetGuardVersion"], BUDGET_GUARD_VERSION)
        self.assertEqual(preflight["maximumCalls"], 16)
        self.assertEqual(
            preflight["providerRequestPlan"]["maximumInputTokenCountRequests"],
            16,
        )
        self.assertTrue(
            preflight["providerRequestPlan"][
                "inputTokenCountRequestsAreAdditional"
            ]
        )
        self.assertEqual(preflight["model"], "gpt-5.4-mini-2026-03-17")
        self.assertEqual(preflight["budget"]["limitUsd"], "1.000000")
        self.assertLessEqual(
            float(preflight["budget"]["maximumReservedCostUsd"]),
            1.0,
        )

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "intentir",
                "pilot",
                str(protocol),
                "--json",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        cli_preflight = json.loads(completed.stdout)
        self.assertFalse(cli_preflight["willCallProvider"])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pilot-output"
            with self.assertRaises(PilotError) as confirmation_context:
                run_pilot(
                    protocol,
                    output,
                    confirm_budget_usd="0.99",
                    api_key="offline-test-key",
                )
            self.assertEqual(
                confirmation_context.exception.code,
                "pilot_budget_confirmation_mismatch",
            )
            self.assertFalse(output.exists())

            counted_payloads = []

            def fake_counter(payload, _api_key, _config):
                counted_payloads.append(payload)
                return {
                    "object": "response.input_tokens",
                    "input_tokens": 100,
                }

            def fake_sender(payload, _api_key, config):
                self.assertEqual(
                    counted_payloads[-1],
                    {
                        field: payload[field]
                        for field in (
                            "model",
                            "input",
                            "instructions",
                            "reasoning",
                            "text",
                        )
                    },
                )
                request = json.loads(payload["input"])
                checkpoint = request["checkpoint"]
                condition = request["condition"]
                suffixes = {
                    "full-file": "full_file.intent",
                    "unified-diff": "unified.diff",
                    "structure-edit": "structure_edit.json",
                    "intent-patch": "intent_patch.json",
                }
                candidate = (
                    suite
                    / "candidates"
                    / "work_item"
                    / f"checkpoint_{checkpoint:02d}"
                    / suffixes[condition]
                ).read_text(encoding="utf-8")
                return {
                    "id": f"resp-{condition}-{checkpoint}",
                    "model": config.model,
                    "status": "completed",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
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
                }

            result = run_pilot(
                protocol,
                output,
                confirm_budget_usd="1.00",
                api_key="offline-test-key",
                sender=fake_sender,
                counter=fake_counter,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["providerCalls"], 16)
            self.assertEqual(result["tokenCountCalls"], 16)
            self.assertEqual(result["budget"]["accountedCostUsd"], "0.004800")
            self.assertEqual(
                result["provenance"]["budgetGuardVersion"],
                BUDGET_GUARD_VERSION,
            )
            self.assertFalse(
                result["provenance"]["actualAccountBillGuaranteed"]
            )
            records = sorted((output / "calls").glob("*.json"))
            self.assertEqual(len(records), 16)
            first_record = json.loads(records[0].read_text(encoding="utf-8"))
            self.assertEqual(first_record["status"], "completed")
            self.assertTrue(first_record["inputTokenCountDispatched"])
            self.assertTrue(first_record["generationDispatched"])
            self.assertEqual(first_record["inputTokenCount"]["inputTokens"], 100)
            self.assertIn("candidate", first_record["response"])
            serialized_output = "".join(
                item.read_text(encoding="utf-8")
                for item in output.rglob("*.json")
            )
            self.assertNotIn("offline-test-key", serialized_output)

    def test_injected_sender_without_counter_fails_closed(self) -> None:
        protocol = self._protocol_path()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pilot-output"
            with self.assertRaises(PilotError) as context:
                run_pilot(
                    protocol,
                    output,
                    confirm_budget_usd="1.00",
                    api_key="offline-test-key",
                    sender=lambda *_args: {},
                )

            self.assertEqual(
                context.exception.code,
                "pilot_input_token_counter_required",
            )
            self.assertFalse(output.exists())

    def test_count_failure_and_oversized_count_stop_without_generation(self) -> None:
        cases = (
            (
                "count-error",
                lambda *_args: (_ for _ in ()).throw(
                    OpenAIProviderError("openai_network_error", "count failed")
                ),
                "input-token-count-error",
            ),
            (
                "count-over-reservation",
                lambda *_args: {
                    "object": "response.input_tokens",
                    "input_tokens": 32_001,
                },
                "input-token-reservation-rejected",
            ),
        )
        for name, counter, expected_status in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                generation_calls = []
                output = Path(directory) / "pilot-output"
                result = run_pilot(
                    self._protocol_path(),
                    output,
                    confirm_budget_usd="1.00",
                    api_key="offline-test-key",
                    sender=lambda *_args: generation_calls.append(True),
                    counter=counter,
                )

                self.assertFalse(result["ok"])
                self.assertEqual(result["tokenCountCalls"], 1)
                self.assertEqual(result["providerCalls"], 0)
                self.assertEqual(generation_calls, [])
                self.assertEqual(len(result["trials"][0]["trajectories"]), 1)
                record = json.loads(
                    (output / "calls" / "0001.json").read_text(encoding="utf-8")
                )
                self.assertEqual(record["status"], expected_status)
                self.assertFalse(record["generationDispatched"])

    def test_partial_usage_and_mismatch_overruns_are_terminal(self) -> None:
        cases = (
            (
                "input-only-overrun",
                {"input_tokens": 32_001},
                "gpt-5.4-mini-2026-03-17",
                "usage-reservation-violation",
                "0.042433",
            ),
            (
                "output-only-overrun",
                {"output_tokens": 4_097},
                "gpt-5.4-mini-2026-03-17",
                "usage-reservation-violation",
                "0.042436",
            ),
            (
                "mismatch-and-overrun",
                {"input_tokens": 32_001, "output_tokens": 1},
                "gpt-other-2026-03-17",
                "usage-reservation-violation",
                "0.042432",
            ),
            (
                "model-mismatch",
                {"input_tokens": 100, "output_tokens": 50},
                "gpt-other-2026-03-17",
                "model-mismatch",
                "0.000300",
            ),
        )
        for name, usage, model, expected_status, expected_cost in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "pilot-output"

                def fake_sender(_payload, _api_key, _config):
                    return {
                        "id": f"resp-{name}",
                        "model": model,
                        "status": "completed",
                        "usage": usage,
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": json.dumps({"candidate": "{}"}),
                                    }
                                ],
                            }
                        ],
                    }

                result = run_pilot(
                    self._protocol_path(),
                    output,
                    confirm_budget_usd="1.00",
                    api_key="offline-test-key",
                    sender=fake_sender,
                    counter=lambda *_args: {
                        "object": "response.input_tokens",
                        "input_tokens": 100,
                    },
                )

                self.assertFalse(result["ok"])
                self.assertEqual(result["tokenCountCalls"], 1)
                self.assertEqual(result["providerCalls"], 1)
                self.assertEqual(
                    Decimal(result["budget"]["accountedCostUsd"]),
                    Decimal(expected_cost),
                )
                self.assertEqual(len(result["trials"][0]["trajectories"]), 1)
                record = json.loads(
                    (output / "calls" / "0001.json").read_text(encoding="utf-8")
                )
                self.assertEqual(record["status"], expected_status)

    def test_budget_reservation_and_maximum_calls_reject_before_count(self) -> None:
        cases = (
            (
                "budget",
                lambda loaded: loaded.update({"budget": Decimal("0.000001")}),
                "budget-reservation-rejected",
            ),
            (
                "maximum-calls",
                lambda loaded: loaded.update({"maximumCalls": 0}),
                "maximum-calls-rejected",
            ),
        )
        for name, mutate, expected_status in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                loaded = load_pilot_protocol(self._protocol_path())
                mutate(loaded)
                count_calls = []
                generation_calls = []
                adapter = BudgetedOpenAIAdapter(
                    loaded,
                    "offline-test-key",
                    Path(directory),
                    sender=lambda *_args: generation_calls.append(True),
                    counter=lambda *_args: count_calls.append(True),
                )
                with self.assertRaises(ModelAdapterError):
                    adapter.generate(self._model_request())

                self.assertEqual(count_calls, [])
                self.assertEqual(generation_calls, [])
                record = json.loads(
                    (Path(directory) / "0001.json").read_text(encoding="utf-8")
                )
                self.assertEqual(record["status"], expected_status)

    def test_prompt_version_pin_rejects_provider_drift_before_execution(self) -> None:
        root = Path(__file__).resolve().parents[1]
        protocol = (
            root
            / "benchmarks"
            / "intentbench_evolve"
            / "openai_calibration_v4_protocol.json"
        )

        preflight = preflight_pilot(protocol)
        self.assertEqual(preflight["promptVersion"], PROMPT_VERSION)

        with mock.patch(
            "intentir.pilot.PROMPT_VERSION",
            "intentir-openai-responses-future",
        ):
            with self.assertRaises(PilotError) as context:
                preflight_pilot(protocol)

        self.assertEqual(
            context.exception.code,
            "pilot_prompt_version_mismatch",
        )
        self.assertEqual(context.exception.path, "/promptVersion")

    @staticmethod
    def _protocol_path() -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "benchmarks"
            / "intentbench_evolve"
            / "openai_pilot_protocol.json"
        )

    @staticmethod
    def _model_request() -> dict:
        return build_model_request(
            suite="pilot-budget-test",
            application="work-item",
            checkpoint=1,
            checkpoint_id="add-priority",
            condition="intent-patch",
            instruction="Add an Integer priority field with default 0.",
            source=DEMO_SOURCE,
            ir=compile_source(DEMO_SOURCE),
        )


if __name__ == "__main__":
    unittest.main()
