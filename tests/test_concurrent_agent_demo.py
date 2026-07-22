import json
import subprocess
import sys
import unittest
from pathlib import Path

from intentir.demos.concurrent_agent import DEMO_SOURCE


class ConcurrentAgentDemoTest(unittest.TestCase):
    def test_cli_rejects_stale_patch_then_rebases_without_changing_fixture(self) -> None:
        root = Path(__file__).resolve().parents[1]
        fixture = root / "demo" / "concurrent_agent" / "workspace.intent"
        before = fixture.read_text(encoding="utf-8")
        self.assertEqual(before, DEMO_SOURCE)

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "intentir",
                "demo",
                "concurrent-agent",
                "--json",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["agentBInitial"]["diagnosticCode"], "stale_base_module"
        )
        self.assertTrue(result["agentA"]["applied"])
        self.assertTrue(result["agentBRebased"]["applied"])
        self.assertNotEqual(
            result["sharedSnapshot"]["moduleId"], result["final"]["moduleId"]
        )
        self.assertIn("owner", result["final"]["fields"])
        self.assertIn("priority", result["final"]["fields"])
        self.assertEqual(result["final"]["verification"]["failed"], 0)
        self.assertTrue(result["final"]["artifacts"]["typescript"].startswith("sha256:"))
        self.assertTrue(result["final"]["artifacts"]["sqlite"].startswith("sha256:"))
        self.assertNotIn("/private/", completed.stdout)
        self.assertIn("--- workspace.intent", result["agentA"]["diff"])
        self.assertEqual(fixture.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
