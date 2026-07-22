import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from intentir.pilot import PilotError, preflight_pilot, run_pilot


class PilotExperimentTest(unittest.TestCase):
    def test_preflight_guards_and_offline_execution_archive_every_call(self) -> None:
        root = Path(__file__).resolve().parents[1]
        suite = root / "benchmarks" / "intentbench_evolve"
        protocol = suite / "openai_pilot_protocol.json"

        preflight = preflight_pilot(protocol)
        self.assertTrue(preflight["ok"])
        self.assertFalse(preflight["willCallProvider"])
        self.assertEqual(preflight["maximumCalls"], 16)
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

            def fake_sender(payload, _api_key, config):
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
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["providerCalls"], 16)
            self.assertEqual(result["budget"]["accountedCostUsd"], "0.004800")
            records = sorted((output / "calls").glob("*.json"))
            self.assertEqual(len(records), 16)
            first_record = json.loads(records[0].read_text(encoding="utf-8"))
            self.assertEqual(first_record["status"], "completed")
            self.assertIn("candidate", first_record["response"])
            serialized_output = "".join(
                item.read_text(encoding="utf-8")
                for item in output.rglob("*.json")
            )
            self.assertNotIn("offline-test-key", serialized_output)


if __name__ == "__main__":
    unittest.main()
