from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def invoke(*arguments: str, expected_status: int = 0) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-I", "-m", "intentir", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != expected_status:
        raise AssertionError(
            f"command returned {completed.returncode}, expected {expected_status}: "
            f"{arguments!r}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"command did not emit JSON: {arguments!r}\n{completed.stdout}"
        ) from error
    if not isinstance(result, dict):
        raise AssertionError(f"command emitted non-object JSON: {arguments!r}")
    return result


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="intentir todo starter ") as directory:
        root = Path(directory)
        starter = root / "workspace with spaces"
        source = starter / "todo.intent"
        patch = starter / "add_task_priority.patch.json"
        database = starter / "todo.db"

        initialized = invoke("init", "todo", str(starter), "--json")
        assert initialized == {
            "ok": True,
            "template": "todo",
            "directory": str(starter),
            "files": [
                "todo.intent",
                "add_task_priority.patch.json",
                "README_JA.md",
            ],
        }

        checked = invoke("check", str(source), "--json")
        assert checked["ok"] is True and checked["diagnostics"] == []
        tested = invoke("test", str(source), "--json")
        assert tested["ok"] is True and tested["summary"]["failed"] == 0

        created = invoke(
            "run",
            str(source),
            "CreateTask",
            "--input",
            '{"id":"task-1","title":"buy milk"}',
            "--db",
            str(database),
        )
        assert created["ok"] is True
        assert created["state"]["Task"] == [
            {"done": False, "id": "task-1", "title": "buy milk"}
        ]

        rejected = invoke(
            "run",
            str(source),
            "CreateTask",
            "--input",
            '{"id":"task-2","title":""}',
            "--db",
            str(database),
            expected_status=1,
        )
        assert rejected["ok"] is False
        assert rejected["state"] == created["state"]

        completed = invoke(
            "run",
            str(source),
            "CompleteTask",
            "--input",
            '{"id":"task-1"}',
            "--db",
            str(database),
        )
        assert completed["state"]["Task"] == [
            {"done": True, "id": "task-1", "title": "buy milk"}
        ]

        patched = invoke("patch", str(source), str(patch), "--apply", "--json")
        assert patched["ok"] is True and patched["applied"] is True

        planned = invoke("migrate", str(source), "--db", str(database), "--json")
        assert planned["ok"] is True and planned["applied"] is False
        assert planned["plan"]["summary"] == {
            "safe": 1,
            "destructive": 0,
            "manual": 0,
        }

        migrated = invoke(
            "migrate", str(source), "--db", str(database), "--apply", "--json"
        )
        assert migrated["ok"] is True and migrated["applied"] is True
        assert migrated["records"] == {"Task": 1}

        renamed = invoke(
            "run",
            str(source),
            "RenameTask",
            "--input",
            '{"id":"task-1","title":"buy oat milk"}',
            "--db",
            str(database),
        )
        assert renamed["state"]["Task"] == [
            {
                "done": True,
                "id": "task-1",
                "priority": 0,
                "title": "buy oat milk",
            }
        ]

        deleted = invoke(
            "run",
            str(source),
            "DeleteTask",
            "--input",
            '{"id":"task-1"}',
            "--db",
            str(database),
        )
        assert deleted["ok"] is True and deleted["state"] == {"Task": []}

        final_check = invoke("check", str(source), "--json")
        final_test = invoke("test", str(source), "--json")
        assert final_check["ok"] is True
        assert final_test["ok"] is True and final_test["summary"]["failed"] == 0

    print(json.dumps({"ok": True, "scenario": "todo-starter"}))


if __name__ == "__main__":
    main()
