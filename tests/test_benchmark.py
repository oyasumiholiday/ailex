import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from intentir.benchmark import (
    BenchmarkError,
    materialize_benchmark_candidate,
    run_benchmark_manifest,
)
from intentir.compiler import compile_source


class IntentBenchEvolveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.suite = cls.root / "benchmarks" / "intentbench_evolve"
        cls.manifest = cls.suite / "smoke_manifest.json"

    def test_smoke_suite_passes_all_conditions_deterministically(self) -> None:
        first = run_benchmark_manifest(self.manifest)
        second = run_benchmark_manifest(self.manifest)

        self.assertEqual(first, second)
        self.assertTrue(first["ok"])
        self.assertEqual(first["summary"]["runs"], 4)
        self.assertEqual(first["summary"]["passed"], 4)
        self.assertEqual(
            {run["condition"] for run in first["runs"]},
            {"full-file", "unified-diff", "structure-edit", "intent-patch"},
        )
        self.assertEqual(len({run["resultModuleId"] for run in first["runs"]}), 1)
        for run in first["runs"]:
            self.assertEqual(run["changedSymbols"], ["entity:WorkItem"])
            self.assertEqual(run["verification"]["hiddenTests"], 1)
            self.assertEqual(run["verification"]["summary"]["failed"], 0)
            self.assertNotIn("elapsedMs", run["metrics"])

    def test_cli_can_select_one_condition(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "intentir",
                "benchmark",
                str(self.manifest),
                "--condition",
                "intent-patch",
                "--json",
            ],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["conditions"], ["intent-patch"])
        self.assertEqual(result["summary"]["runs"], 1)

    def test_manifest_rejects_references_outside_suite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.intent"
            outside.write_text("module Outside\n", encoding="utf-8")
            suite = root / "suite"
            suite.mkdir()
            manifest = suite / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": "0.1.0",
                        "suite": "unsafe",
                        "description": "path boundary test",
                        "conditions": ["full-file"],
                        "tasks": [
                            {
                                "id": "escape",
                                "application": "unsafe",
                                "checkpoint": 1,
                                "instruction": "escape the suite",
                                "baseSource": "../outside.intent",
                                "hiddenTests": "hidden.intent",
                                "expectedChangedSymbols": [],
                                "candidates": {"full-file": "candidate.intent"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(BenchmarkError) as context:
                run_benchmark_manifest(manifest)
            self.assertEqual(context.exception.code, "benchmark_path_outside_suite")

    def test_unified_diff_cannot_target_another_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "suite"
            shutil.copytree(self.suite, copied)
            diff = (
                copied
                / "candidates"
                / "work_item"
                / "checkpoint_01"
                / "unified.diff"
            )
            diff.write_text(
                "diff --git a/workspace.intent b/../outside.intent\n"
                "--- a/workspace.intent\n"
                "+++ b/../outside.intent\n"
                "@@ -1 +1 @@\n"
                "-module ConcurrentAgentDemo\n"
                "+module Escaped\n",
                encoding="utf-8",
            )
            result = run_benchmark_manifest(
                copied / "smoke_manifest.json",
                conditions=["unified-diff"],
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["summary"]["failed"], 1)
            self.assertEqual(
                result["summary"]["failuresByCode"],
                {"unsafe_unified_diff": 1},
            )
            self.assertEqual(result["runs"][0]["failure"]["stage"], "candidate")
            self.assertEqual(
                result["runs"][0]["diagnostics"][0]["code"],
                "unsafe_unified_diff",
            )
            self.assertFalse((Path(directory) / "outside.intent").exists())

    def test_unified_diff_accepts_standard_headers_without_git_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "suite"
            shutil.copytree(self.suite, copied)
            diff = (
                copied
                / "candidates"
                / "work_item"
                / "checkpoint_01"
                / "unified.diff"
            )
            lines = diff.read_text(encoding="utf-8").splitlines(keepends=True)
            self.assertTrue(lines[0].startswith("diff --git "))
            diff.write_text("".join(lines[1:]), encoding="utf-8")

            result = run_benchmark_manifest(
                copied / "smoke_manifest.json",
                conditions=["unified-diff"],
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["summary"]["passed"], 1)

    def test_v3_unified_diff_failure_explains_required_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "suite"
            shutil.copytree(self.suite, copied)
            diff = (
                copied
                / "candidates"
                / "work_item"
                / "checkpoint_01"
                / "unified.diff"
            )
            diff.write_text(
                "--- a/workspace.intent\n"
                "+++ b/workspace.intent\n"
                "@@ -3,4 +3,5 @@\n"
                " entity WorkItem:\n"
                "   id: UUID required key\n"
                "   title: Text required\n"
                '   status: Text default "open"\n'
                "+  priority: Integer default 0\n",
                encoding="utf-8",
            )

            result = run_benchmark_manifest(
                copied / "smoke_manifest.json",
                conditions=["unified-diff"],
            )

            self.assertFalse(result["ok"])
            diagnostic = result["runs"][0]["diagnostics"][0]
            self.assertEqual(diagnostic["code"], "unified_diff_apply_failed")
            self.assertIn(
                "unchanged context lines before and after",
                diagnostic["message"],
            )
            self.assertNotIn(str(copied), diagnostic["message"])

    def test_v3_structure_edit_failure_returns_operation_scope(self) -> None:
        base_source = (
            self.suite / "tasks" / "work_item" / "base.intent"
        ).read_text(encoding="utf-8")
        candidate = json.dumps(
            {
                "schemaVersion": "0.1.0",
                "operations": [
                    {
                        "kind": "entity",
                        "target": "entity:WorkItem",
                        "member": "fields",
                        "index": 4,
                        "value": {
                            "name": "owner",
                            "type": "Text",
                            "default": "unassigned",
                        },
                        "operation": "insert_member",
                    }
                ],
            }
        )

        with self.assertRaises(BenchmarkError) as context:
            materialize_benchmark_candidate(
                "structure-edit",
                base_source,
                compile_source(base_source),
                candidate,
            )

        diagnostic = context.exception.to_dict()
        self.assertEqual(diagnostic["code"], "unknown_structure_operation")
        self.assertEqual(
            diagnostic["scope"],
            [
                "add_definition",
                "insert_member",
                "remove_definition",
                "remove_member",
                "rename_symbol",
                "replace_definition",
                "set_member",
            ],
        )
        self.assertIn("target prefix", diagnostic["message"])

    def test_structure_edit_accepts_content_addressed_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "suite"
            shutil.copytree(self.suite, copied)
            base_source = (
                copied / "tasks" / "work_item" / "base.intent"
            ).read_text(encoding="utf-8")
            ir = compile_source(base_source)
            entity_id = next(
                node["id"]
                for node in ir["nodes"]
                if node["symbol"] == "entity:WorkItem"
            )
            candidate_path = (
                copied
                / "candidates"
                / "work_item"
                / "checkpoint_01"
                / "structure_edit.json"
            )
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["operations"][0]["target"] = entity_id
            candidate_path.write_text(
                json.dumps(candidate),
                encoding="utf-8",
            )

            result = run_benchmark_manifest(
                copied / "smoke_manifest.json",
                conditions=["structure-edit"],
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["summary"]["passed"], 1)


if __name__ == "__main__":
    unittest.main()
