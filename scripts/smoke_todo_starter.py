from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def invoke(*arguments: str, expected_status: int = 0) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-m", "intentir", *arguments],
        check=False,
        capture_output=True,
        encoding="utf-8",
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


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_read_state(
    source: Path, database: Path, expected_tasks: list[dict[str, Any]]
) -> None:
    # The writer is closed here; this checks the quiescent main DB, not WAL sidecars.
    before = file_sha256(database)
    expected_state = {"Task": expected_tasks}
    results = (
        invoke("read", str(source), "--db", str(database)),
        invoke("read", str(source), "--db", str(database), "--entity", "Task"),
    )

    for result in results:
        assert result["ok"] is True
        assert result["state"] == expected_state
        assert result["storage"] == {
            "kind": "sqlite",
            "path": str(database),
            "readOnly": True,
        }

    assert file_sha256(database) == before


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-read", action="store_true")
    arguments = parser.parse_args()

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

        if arguments.check_read:
            missing_database = root / "missing database.sqlite3"
            missing = invoke(
                "read", str(source), "--db", str(missing_database), expected_status=1
            )
            assert missing["ok"] is False
            assert not missing_database.exists()

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

        if arguments.check_read:
            assert_read_state(
                source,
                database,
                [{"done": True, "id": "task-1", "title": "buy milk"}],
            )

        patched = invoke("patch", str(source), str(patch), "--apply", "--json")
        assert patched["ok"] is True and patched["applied"] is True

        if arguments.check_read:
            before_mismatch = file_sha256(database)
            mismatch = invoke("read", str(source), "--db", str(database), expected_status=1)
            assert mismatch["ok"] is False
            assert mismatch["diagnostics"][0]["code"] == "read_error"
            assert "schema mismatch" in mismatch["diagnostics"][0]["message"]
            assert file_sha256(database) == before_mismatch

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

        if arguments.check_read:
            assert_read_state(
                source,
                database,
                [
                    {
                        "done": True,
                        "id": "task-1",
                        "priority": 0,
                        "title": "buy oat milk",
                    }
                ],
            )

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

        if arguments.check_read:
            assert_read_state(source, database, [])

        final_check = invoke("check", str(source), "--json")
        final_test = invoke("test", str(source), "--json")
        assert final_check["ok"] is True
        assert final_test["ok"] is True and final_test["summary"]["failed"] == 0

    print(json.dumps({"ok": True, "scenario": "todo-starter"}))


if __name__ == "__main__":
    main()
