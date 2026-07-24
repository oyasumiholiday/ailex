import json
import subprocess
import sys
import unittest
from pathlib import Path

from intentir.model_adapter import (
    ExternalCommandModelAdapter,
    ModelAdapterError,
    build_model_request,
)
from intentir.trajectory import run_trajectory_manifest
from intentir.compiler import compile_source
from intentir.demos.concurrent_agent import DEMO_SOURCE


class IntentBenchTrajectoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.suite = cls.root / "benchmarks" / "intentbench_evolve"
        cls.manifest = cls.suite / "trajectory_manifest.json"
        cls.model_manifest = cls.suite / "model_trajectory_manifest.json"
        cls.adapter_script = cls.root / "tests" / "fixtures" / "model_adapter_fixture.py"

    def test_four_conditions_complete_four_cumulative_checkpoints(self) -> None:
        result = run_trajectory_manifest(self.manifest)
        repeated = run_trajectory_manifest(self.manifest)

        self.assertEqual(result, repeated)
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["trajectories"], 4)
        self.assertEqual(result["summary"]["runs"], 16)
        self.assertEqual(result["summary"]["failed"], 0)
        self.assertEqual(
            len({item["finalModuleId"] for item in result["trajectories"]}),
            1,
        )
        for trajectory in result["trajectories"]:
            self.assertEqual(trajectory["completedCheckpoints"], 4)
            self.assertEqual(
                [run["verification"]["summary"]["tests"] for run in trajectory["checkpoints"]],
                [2, 3, 4, 5],
            )

    def test_external_adapter_drives_intent_patch_trajectory(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "intentir",
                "benchmark-model",
                str(self.model_manifest),
                "--condition",
                "intent-patch",
                "--adapter-command",
                sys.executable,
                "--adapter-arg",
                str(self.adapter_script),
                "--adapter-arg",
                str(self.suite),
                "--json",
            ],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertTrue(result["ok"])
        self.assertEqual(result["adapter"]["kind"], "external-command")
        self.assertEqual(result["summary"]["runs"], 4)
        for run in result["trajectories"][0]["checkpoints"]:
            self.assertEqual(run["model"]["model"], "fixture-adapter")
            self.assertEqual(
                run["model"]["provenance"]["provider"],
                "fixture",
            )
            self.assertGreater(run["model"]["usage"]["inputTokens"], 0)
            self.assertGreater(run["model"]["usage"]["outputTokens"], 0)

    def test_adapter_rejects_response_for_another_request(self) -> None:
        ir = compile_source(DEMO_SOURCE)
        request = build_model_request(
            suite="adapter-test",
            application="work-item",
            checkpoint=1,
            checkpoint_id="add-priority",
            condition="intent-patch",
            instruction="Add priority.",
            source=DEMO_SOURCE,
            ir=ir,
        )
        serialized_request = json.dumps(request)
        self.assertNotIn("priority defaults to zero", serialized_request)
        self.assertIn(
            "expectedId",
            request["outputContract"]["candidate"]["operations"]["insert_member"],
        )
        self.assertEqual(
            request["languageReference"]["syntax"]["updateEffect"],
            (
                "update <Entity> where <field> equals input.<field> "
                "set <field> = <value>"
            ),
        )
        candidate_contract = request["outputContract"]["candidate"]
        self.assertEqual(
            candidate_contract["allowedTopLevelFields"],
            [
                "schemaVersion",
                "baseModuleId",
                "operations",
                "requestedObligations",
            ],
        )
        self.assertNotIn("kind", candidate_contract["allowedTopLevelFields"])
        self.assertNotIn(
            "contentGuards",
            candidate_contract["allowedTopLevelFields"],
        )
        adapter = ExternalCommandModelAdapter(
            [
                sys.executable,
                str(self.adapter_script),
                str(self.suite),
                "mismatch",
            ]
        )

        with self.assertRaises(ModelAdapterError) as context:
            adapter.generate(request)
        self.assertEqual(context.exception.code, "model_response_request_mismatch")

        result = run_trajectory_manifest(
            self.model_manifest,
            conditions=["intent-patch"],
            adapter=adapter,
        )
        self.assertFalse(result["ok"])
        run = result["trajectories"][0]["checkpoints"][0]
        self.assertEqual(run["failure"]["stage"], "generation")
        self.assertEqual(
            result["summary"]["failuresByCode"],
            {"model_response_request_mismatch": 1},
        )

    def test_model_output_contracts_define_headers_and_target_references(self) -> None:
        ir = compile_source(DEMO_SOURCE)

        unified = build_model_request(
            suite="adapter-test",
            application="work-item",
            checkpoint=1,
            checkpoint_id="add-priority",
            condition="unified-diff",
            instruction="Add priority.",
            source=DEMO_SOURCE,
            ir=ir,
        )["outputContract"]
        self.assertEqual(
            unified["candidate"]["requiredFileHeaders"],
            ["--- a/workspace.intent", "+++ b/workspace.intent"],
        )
        self.assertEqual(
            unified["candidate"]["optionalGitHeader"],
            "diff --git a/workspace.intent b/workspace.intent",
        )
        self.assertEqual(
            unified["candidate"]["hunkHeaderFormat"],
            "@@ -<oldStart>,<oldCount> +<newStart>,<newCount> @@",
        )

        structure = build_model_request(
            suite="adapter-test",
            application="work-item",
            checkpoint=1,
            checkpoint_id="add-priority",
            condition="structure-edit",
            instruction="Add priority.",
            source=DEMO_SOURCE,
            ir=ir,
        )["outputContract"]
        self.assertEqual(
            structure["candidate"]["targetReferences"]["existingDefinition"],
            ["context.nodes[].symbol", "context.nodes[].id"],
        )
        self.assertEqual(
            structure["candidate"]["memberCollectionsByTargetKind"]["entity"],
            ["fields"],
        )
        self.assertEqual(
            structure["candidate"]["memberValueContracts"]["fields"][
                "objectRequired"
            ],
            ["name", "type"],
        )


if __name__ == "__main__":
    unittest.main()
