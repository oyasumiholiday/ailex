import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from intentir import cli
from intentir.notation_lab import NotationError


ROOT = Path(__file__).resolve().parents[1]


class NotationCliTest(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "intentir", *arguments],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_main_demo_json_uses_notation_lab_result(self) -> None:
        completed = self.run_cli("demo", "notation-lab", "--json")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["ok"])
        self.assertTrue(result["equivalent"])
        self.assertEqual(
            {item["result"] for item in result["representations"].values()},
            {380},
        )
        self.assertEqual(result["patch"]["result"], 390)

    def test_main_demo_human_summary_includes_before_and_after_results(self) -> None:
        completed = self.run_cli("demo", "notation-lab")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("IntentIR notation lab", completed.stdout)
        self.assertIn("380", completed.stdout)
        self.assertIn("390", completed.stdout)

    def test_main_demo_reports_notation_failure_without_traceback(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        error = NotationError("notation_demo_failed", "bounded demo failed")

        with patch.object(cli, "notation_lab_demo_result", side_effect=error):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exit_error:
                    cli.main(["demo", "notation-lab", "--json"])

        self.assertEqual(exit_error.exception.code, 1)
        result = json.loads(stdout.getvalue())
        self.assertFalse(result["ok"])
        self.assertEqual(result["diagnostics"][0]["code"], "notation_demo_failed")
        self.assertEqual(result["diagnostics"][0]["message"], "bounded demo failed")
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_concurrent_agent_demo_remains_available(self) -> None:
        completed = self.run_cli("demo", "concurrent-agent", "--json")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
