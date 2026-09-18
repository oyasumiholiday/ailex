import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from intentir.canonical import canonical_json
from intentir.compiler import compile_source
from intentir.storage import SQLiteStateRepository, StorageError, storage_schema_hash


ROOT = Path(__file__).resolve().parents[1]
SOURCE = """module ReadTodo

entity Task:
  id: UUID required key
  title: Text required
  done: Boolean default false

entity Note:
  id: UUID required key
  text: Text required

action CreateTask:
  input:
    id: UUID required
    title: Text required
  effects:
    insert Task
"""


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "intentir", *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        encoding="utf-8",
    )


def json_cli(*arguments: str, status: int = 0) -> dict:
    completed = run_cli(*arguments)
    if completed.returncode != status:
        raise AssertionError(
            f"status {completed.returncode}, expected {status}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    if "Traceback" in completed.stderr:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReadCommandTest(unittest.TestCase):
    def source_path(self, root: Path, source: str = SOURCE) -> Path:
        path = root / "read.intent"
        path.write_text(source, encoding="utf-8")
        return path

    def create_database(self, source: Path, database: Path) -> None:
        result = json_cli(
            "run", str(source), "CreateTask",
            "--input", '{"id":"task-1","title":"first"}',
            "--db", str(database),
        )
        self.assertTrue(result["ok"])

    def test_full_filter_and_empty_entity_from_new_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_path(root)
            database = root / "state.db"
            self.create_database(source, database)
            full = json_cli("read", str(source), "--db", str(database))
            task = json_cli(
                "read", str(source), "--db", str(database), "--entity", "Task"
            )
            note = json_cli(
                "read", str(source), "--db", str(database), "--entity", "Note"
            )

        self.assertEqual(full["module"], "ReadTodo")
        self.assertEqual(full["state"]["Note"], [])
        self.assertEqual(full["state"]["Task"][0]["title"], "first")
        self.assertEqual(task["state"], {"Task": full["state"]["Task"]})
        self.assertEqual(note["state"], {"Note": []})
        self.assertEqual(
            full["storage"],
            {"kind": "sqlite", "path": str(database), "readOnly": True},
        )

    def test_missing_database_source_and_invalid_source_are_structured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_path(root)
            databases = (root / "missing" / "state.db", root / "absent.db")
            for database in databases:
                result = json_cli("read", str(source), "--db", str(database), status=1)
                self.assertFalse(result["ok"])
                self.assertFalse(database.exists())
            self.assertFalse((root / "missing").exists())

            invalid = root / "invalid.intent"
            invalid.write_text("module Broken\nentity", encoding="utf-8")
            for candidate in (invalid, root / "missing.intent"):
                result = json_cli(
                    "read", str(candidate), "--db", str(databases[1]), status=1
                )
                self.assertFalse(result["ok"])
                self.assertFalse(databases[1].exists())

    def test_unknown_entity_is_rejected_before_database_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_path(root)
            database = root / "missing.db"
            result = json_cli(
                "read", str(source), "--db", str(database),
                "--entity", "Missing", status=1,
            )
            self.assertEqual(result["diagnostics"][0]["code"], "unknown_entity")
            self.assertIn("Note", result["diagnostics"][0]["message"])
            self.assertFalse(database.exists())

    def test_quiescent_database_and_schema_mismatch_are_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_path(root)
            database = root / "state.db"
            self.create_database(source, database)
            with closing(sqlite3.connect(database)) as connection:
                with connection:
                    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    schema_before = connection.execute(
                        "SELECT type, name, sql FROM sqlite_schema ORDER BY type, name"
                    ).fetchall()
            hash_before = digest(database)
            header_before = database.read_bytes()[:100]
            json_cli("read", str(source), "--db", str(database))
            with closing(sqlite3.connect(database)) as connection:
                schema_after = connection.execute(
                    "SELECT type, name, sql FROM sqlite_schema ORDER BY type, name"
                ).fetchall()
            self.assertEqual(digest(database), hash_before)
            self.assertEqual(database.read_bytes()[:100], header_before)
            self.assertEqual(schema_after, schema_before)

            changed = self.source_path(
                root,
                SOURCE.replace(
                    "  done: Boolean default false",
                    "  priority: Integer default 0\n  done: Boolean default false",
                ),
            )
            result = json_cli("read", str(changed), "--db", str(database), status=1)
            self.assertFalse(result["ok"])
            self.assertEqual(digest(database), hash_before)

    def test_unrelated_database_and_absent_module_fail_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_path(root)
            unrelated = root / "unrelated.db"
            with closing(sqlite3.connect(unrelated)) as connection:
                with connection:
                    connection.execute("CREATE TABLE user_data(value TEXT)")
                    connection.execute("INSERT INTO user_data VALUES ('keep')")
            before = digest(unrelated)
            self.assertFalse(
                json_cli("read", str(source), "--db", str(unrelated), status=1)["ok"]
            )
            self.assertEqual(digest(unrelated), before)

            absent = root / "absent-module.db"
            other_ir = compile_source(SOURCE.replace("ReadTodo", "OtherTodo"))
            with SQLiteStateRepository(absent) as repository:
                repository.save(other_ir, {"Task": [], "Note": []})
            before = digest(absent)
            result = json_cli("read", str(source), "--db", str(absent), status=1)
            self.assertEqual(result["diagnostics"][0]["code"], "module_not_found")
            self.assertEqual(digest(absent), before)

    def test_legacy_json_metadata_is_read_without_alter(self) -> None:
        ir = compile_source(SOURCE)
        state = {
            "Task": [{"id": "legacy", "title": "old", "done": False}],
            "Note": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_path(root)
            database = root / "legacy.db"
            with closing(sqlite3.connect(database)) as connection:
                with connection:
                    connection.execute(
                        "CREATE TABLE intentir_state (module TEXT PRIMARY KEY, "
                        "schema_hash TEXT NOT NULL, state_json TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO intentir_state VALUES (?, ?, ?)",
                        (ir["module"], storage_schema_hash(ir), canonical_json(state)),
                    )
            before = digest(database)
            result = json_cli("read", str(source), "--db", str(database))
            with closing(sqlite3.connect(database)) as connection:
                columns = [
                    row[1]
                    for row in connection.execute("PRAGMA table_info(intentir_state)")
                ]
            self.assertEqual(result["state"], state)
            self.assertEqual(columns, ["module", "schema_hash", "state_json"])
            self.assertEqual(digest(database), before)

    def test_invalid_stored_state_is_structured_and_unchanged(self) -> None:
        ir = compile_source(SOURCE)
        invalid_state = {
            "Task": [{"id": "bad", "title": "bad", "done": "wrong"}],
            "Note": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_path(root)
            database = root / "invalid-state.db"
            with closing(sqlite3.connect(database)) as connection:
                with connection:
                    connection.execute(
                        "CREATE TABLE intentir_state (module TEXT PRIMARY KEY, "
                        "schema_hash TEXT NOT NULL, state_json TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO intentir_state VALUES (?, ?, ?)",
                        (
                            ir["module"],
                            storage_schema_hash(ir),
                            canonical_json(invalid_state),
                        ),
                    )
            before = digest(database)
            result = json_cli("read", str(source), "--db", str(database), status=1)
            self.assertFalse(result["ok"])
            self.assertEqual(result["diagnostics"][0]["code"], "read_error")
            self.assertEqual(digest(database), before)

    def test_malformed_relational_schema_is_structured_and_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_path(root)
            database = root / "state.db"
            self.create_database(source, database)
            with closing(sqlite3.connect(database)) as connection:
                with connection:
                    connection.execute(
                        "UPDATE intentir_state SET schema_json = ? WHERE module = ?",
                        ('{"kind":"storage-schema","entities":null}', "ReadTodo"),
                    )
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            before = digest(database)
            result = json_cli("read", str(source), "--db", str(database), status=1)
            self.assertFalse(result["ok"])
            self.assertIn("malformed", result["diagnostics"][0]["message"])
            self.assertEqual(digest(database), before)

    def test_utf8_spaces_question_and_hash_path_is_uri_escaped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_path(root)
            database = root / (
                "状態 # space.db" if sys.platform == "win32" else "状態 ? # space.db"
            )
            self.create_database(source, database)
            result = json_cli("read", str(source), "--db", str(database))
            self.assertEqual(result["state"]["Task"][0]["title"], "first")

    def test_wal_committed_data_visible_and_writer_transaction_not_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_path(root)
            database = root / "state.db"
            self.create_database(source, database)
            writer = sqlite3.connect(database, isolation_level=None)
            try:
                table = writer.execute(
                    "SELECT table_name FROM intentir_relations "
                    "WHERE module = 'ReadTodo' AND entity = 'Task'"
                ).fetchone()[0]
                writer.execute(f'UPDATE "{table}" SET "title" = ?', ("committed",))
                committed = json_cli("read", str(source), "--db", str(database))
                self.assertEqual(
                    committed["state"]["Task"][0]["title"], "committed"
                )

                writer.execute("BEGIN IMMEDIATE")
                writer.execute(f'UPDATE "{table}" SET "title" = ?', ("pending",))
                snapshot = json_cli("read", str(source), "--db", str(database))
                self.assertEqual(
                    snapshot["state"]["Task"][0]["title"], "committed"
                )
                writer.execute("ROLLBACK")
            finally:
                writer.close()

    def test_read_only_repository_rejects_save(self) -> None:
        ir = compile_source(SOURCE)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "state.db"
            with SQLiteStateRepository(database) as repository:
                repository.save(ir, {"Task": [], "Note": []})
            with SQLiteStateRepository(database, read_only=True) as repository:
                with self.assertRaisesRegex(StorageError, "read-only"):
                    repository.save(ir, {"Task": [], "Note": []})


if __name__ == "__main__":
    unittest.main()
