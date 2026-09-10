import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TODO_SOURCE = ROOT / "examples" / "todo_crud.intent"
PRIORITY_PATCH = ROOT / "examples" / "add_task_priority.patch.json"


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "intentir", *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def json_result(*arguments: str) -> dict:
    completed = run_cli(*arguments)
    if completed.returncode != 0:
        raise AssertionError(
            f"IntentIR command failed ({completed.returncode}):\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


class QuickstartTest(unittest.TestCase):
    def test_checked_in_priority_patch_remains_compatible(self) -> None:
        original = TODO_SOURCE.read_text(encoding="utf-8")
        result = json_result(
            "patch",
            str(TODO_SOURCE),
            str(PRIORITY_PATCH),
            "--json",
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["applied"])
        self.assertIn("priority: Integer default 0", result["diff"])
        self.assertEqual(TODO_SOURCE.read_text(encoding="utf-8"), original)

    def test_persistent_todo_patch_and_migration_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            app = workspace / "todo.intent"
            patch = workspace / "add_task_priority.patch.json"
            database = workspace / "todo.db"
            shutil.copyfile(TODO_SOURCE, app)
            shutil.copyfile(PRIORITY_PATCH, patch)

            created = json_result(
                "run",
                str(app),
                "CreateTask",
                "--input",
                '{"id":"task-1","title":"buy milk"}',
                "--db",
                str(database),
            )
            completed = json_result(
                "run",
                str(app),
                "CompleteTask",
                "--input",
                '{"id":"task-1"}',
                "--db",
                str(database),
            )
            patched = json_result("patch", str(app), str(patch), "--apply", "--json")
            planned = json_result("migrate", str(app), "--db", str(database), "--json")
            migrated = json_result(
                "migrate", str(app), "--db", str(database), "--apply", "--json"
            )
            renamed = json_result(
                "run",
                str(app),
                "RenameTask",
                "--input",
                '{"id":"task-1","title":"buy oat milk"}',
                "--db",
                str(database),
            )
            deleted = json_result(
                "run",
                str(app),
                "DeleteTask",
                "--input",
                '{"id":"task-1"}',
                "--db",
                str(database),
            )

        self.assertEqual(created["state"]["Task"][0]["title"], "buy milk")
        self.assertEqual(
            completed["state"]["Task"],
            [{"done": True, "id": "task-1", "title": "buy milk"}],
        )
        self.assertTrue(patched["applied"])
        self.assertFalse(planned["applied"])
        self.assertEqual(planned["plan"]["summary"], {"safe": 1, "destructive": 0, "manual": 0})
        self.assertTrue(migrated["applied"])
        self.assertEqual(migrated["records"], {"Task": 1})
        self.assertEqual(
            renamed["state"]["Task"],
            [
                {
                    "done": True,
                    "id": "task-1",
                    "priority": 0,
                    "title": "buy oat milk",
                }
            ],
        )
        self.assertEqual(deleted["state"], {"Task": []})


if __name__ == "__main__":
    unittest.main()
