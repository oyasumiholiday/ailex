import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
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
        self.assertEqual(
            planned["plan"]["summary"],
            {"safe": 1, "destructive": 0, "manual": 0},
        )
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

    def test_backup_restore_rehearsal_preserves_the_pre_migration_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live"
            backup = root / "backup"
            restored = root / "restored"
            live.mkdir(mode=0o700, exist_ok=False)

            app = live / "todo.intent"
            patch = live / "add_task_priority.patch.json"
            database = live / "todo.db"
            shutil.copyfile(TODO_SOURCE, app)
            shutil.copyfile(PRIORITY_PATCH, patch)

            json_result(
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

            source = app.resolve(strict=True)
            source_database = database.resolve(strict=True)
            backup.mkdir(mode=0o700, exist_ok=False)
            shutil.copyfile(source, backup / "todo.intent")
            source_uri = source_database.as_uri() + "?mode=ro"
            with closing(sqlite3.connect(source_uri, uri=True)) as source_db:
                with closing(sqlite3.connect(backup / "todo.db")) as backup_db:
                    source_db.backup(backup_db)

            json_result("patch", str(app), str(patch), "--apply", "--json")
            json_result("migrate", str(app), "--db", str(database), "--json")
            json_result(
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

            backup_app = (backup / "todo.intent").resolve(strict=True)
            backup_database = (backup / "todo.db").resolve(strict=True)
            restored.mkdir(mode=0o700, exist_ok=False)
            shutil.copyfile(backup_app, restored / "todo.intent")
            backup_uri = backup_database.as_uri() + "?mode=ro"
            with closing(sqlite3.connect(backup_uri, uri=True)) as backup_db:
                with closing(sqlite3.connect(restored / "todo.db")) as restored_db:
                    backup_db.backup(restored_db)

            restored_database = (restored / "todo.db").resolve(strict=True)
            restored_uri = restored_database.as_uri() + "?mode=ro"
            with closing(sqlite3.connect(restored_uri, uri=True)) as restored_db:
                integrity = restored_db.execute("PRAGMA integrity_check").fetchone()
                restored_table = restored_db.execute(
                    "SELECT table_name FROM intentir_relations "
                    "WHERE module = ? AND entity = ?",
                    ("TodoCrud", "Task"),
                ).fetchone()[0]
                quoted_restored_table = (
                    '"' + restored_table.replace('"', '""') + '"'
                )
                restored_columns = {
                    row[1]
                    for row in restored_db.execute(
                        f"PRAGMA table_info({quoted_restored_table})"
                    )
                }
                restored_row = restored_db.execute(
                    f"SELECT id, title, done FROM {quoted_restored_table}"
                ).fetchone()

            live_uri = database.resolve(strict=True).as_uri() + "?mode=ro"
            with closing(sqlite3.connect(live_uri, uri=True)) as live_db:
                live_table = live_db.execute(
                    "SELECT table_name FROM intentir_relations "
                    "WHERE module = ? AND entity = ?",
                    ("TodoCrud", "Task"),
                ).fetchone()[0]
                quoted_live_table = '"' + live_table.replace('"', '""') + '"'
                live_columns = {
                    row[1]
                    for row in live_db.execute(
                        f"PRAGMA table_info({quoted_live_table})"
                    )
                }
                live_row = live_db.execute(
                    f"SELECT id, title, done, priority FROM {quoted_live_table}"
                ).fetchone()

            restored_result = json_result(
                "run",
                str(restored / "todo.intent"),
                "CompleteTask",
                "--input",
                '{"id":"task-1"}',
                "--db",
                str(restored_database),
            )
            backup_source_text = (backup / "todo.intent").read_text(
                encoding="utf-8"
            )

        self.assertEqual(
            completed["state"]["Task"],
            [{"done": True, "id": "task-1", "title": "buy milk"}],
        )
        self.assertEqual(integrity, ("ok",))
        self.assertNotIn("priority", restored_columns)
        self.assertEqual(restored_row, ("task-1", "buy milk", 1))
        self.assertIn("priority", live_columns)
        self.assertEqual(live_row, ("task-1", "buy oat milk", 1, 0))
        self.assertNotIn("priority: Integer", backup_source_text)
        self.assertEqual(
            restored_result["state"]["Task"],
            [{"done": True, "id": "task-1", "title": "buy milk"}],
        )
        expected_migrated_state = [
            {
                "done": True,
                "id": "task-1",
                "priority": 0,
                "title": "buy oat milk",
            }
        ]
        self.assertEqual(renamed["state"]["Task"], expected_migrated_state)


if __name__ == "__main__":
    unittest.main()
