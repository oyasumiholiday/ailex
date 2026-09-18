import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from intentir.starter import create_starter


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "intentir", *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class InitCommandTest(unittest.TestCase):
    def test_todo_starter_matches_canonical_examples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "todo starter"
            completed = run_cli("init", "todo", str(destination), "--json")

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(
                result,
                {
                    "ok": True,
                    "template": "todo",
                    "directory": str(destination),
                    "files": [
                        "todo.intent",
                        "add_task_priority.patch.json",
                        "README_JA.md",
                    ],
                },
            )
            self.assertEqual(
                (destination / "todo.intent").read_bytes(),
                (EXAMPLES / "todo_crud.intent").read_bytes(),
            )
            self.assertEqual(
                (destination / "add_task_priority.patch.json").read_bytes(),
                (EXAMPLES / "add_task_priority.patch.json").read_bytes(),
            )

    def test_existing_directory_and_file_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing_directory = root / "directory"
            existing_directory.mkdir()
            existing_file = root / "file"
            existing_file.write_text("keep", encoding="utf-8")

            for destination in (existing_directory, existing_file):
                with self.subTest(destination=destination.name):
                    completed = run_cli(
                        "init", "todo", str(destination), "--json"
                    )
                    self.assertEqual(completed.returncode, 1)
                    result = json.loads(completed.stdout)
                    self.assertFalse(result["ok"])
                    self.assertEqual(
                        result["diagnostics"][0]["code"], "init_error"
                    )

            self.assertEqual(list(existing_directory.iterdir()), [])
            self.assertEqual(existing_file.read_text(encoding="utf-8"), "keep")

    def test_dangling_symlink_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dangling = root / "dangling"
            try:
                dangling.symlink_to(root / "missing-target")
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")

            completed = run_cli("init", "todo", str(dangling), "--json")
            self.assertEqual(completed.returncode, 1)
            self.assertFalse(json.loads(completed.stdout)["ok"])
            self.assertTrue(dangling.is_symlink())
            self.assertEqual(os.readlink(dangling), str(root / "missing-target"))

    def test_bad_parent_and_unknown_template_are_structured_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent_file = root / "parent-file"
            parent_file.write_text("keep", encoding="utf-8")
            cases = (
                ("todo", root / "missing" / "starter"),
                ("todo", parent_file / "starter"),
                ("unknown", root / "starter"),
            )
            for template, destination in cases:
                with self.subTest(template=template):
                    completed = run_cli(
                        "init", template, str(destination), "--json"
                    )
                    self.assertEqual(completed.returncode, 1)
                    result = json.loads(completed.stdout)
                    self.assertFalse(result["ok"])
                    self.assertEqual(len(result["diagnostics"]), 1)
                    self.assertFalse(destination.exists())
            self.assertEqual(parent_file.read_text(encoding="utf-8"), "keep")

    def test_missing_packaged_resource_does_not_create_destination(self) -> None:
        class MissingResource:
            def joinpath(self, filename: str) -> "MissingResource":
                return self

            def read_bytes(self) -> bytes:
                raise FileNotFoundError("missing packaged resource")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "starter"
            with patch("intentir.starter.resources.files", return_value=MissingResource()):
                with self.assertRaisesRegex(
                    FileNotFoundError, "missing packaged resource"
                ):
                    create_starter("todo", destination)
            self.assertFalse(os.path.lexists(destination))

    def test_repeated_invocation_preserves_first_starter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "starter"
            first = run_cli("init", "todo", str(destination), "--json")
            original = {
                path.name: path.read_bytes() for path in destination.iterdir()
            }
            second = run_cli("init", "todo", str(destination), "--json")

            self.assertEqual(first.returncode, 0)
            self.assertEqual(second.returncode, 1)
            self.assertEqual(
                {path.name: path.read_bytes() for path in destination.iterdir()},
                original,
            )

    def test_write_failure_leaves_only_the_new_partial_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "starter"
            original_open = Path.open

            def fail_destination_write(path: Path, mode: str = "r", *args, **kwargs):
                if path.parent == destination and mode == "xb":
                    raise OSError("simulated write failure")
                return original_open(path, mode, *args, **kwargs)

            with patch.object(Path, "open", fail_destination_write):
                with self.assertRaisesRegex(OSError, "simulated write failure"):
                    create_starter("todo", destination)

            self.assertTrue(destination.is_dir())
            self.assertEqual(list(destination.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
