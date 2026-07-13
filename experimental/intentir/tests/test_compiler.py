import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from intentir.canonical import canonical_json
from intentir.compiler import compile_source
from intentir.expressions import parse_effect
from intentir.formatter import format_source
from intentir.generators.typescript import generate_typescript
from intentir.reports import generate_validation_report
from intentir.storage import SQLiteStateRepository, StorageError
from intentir.validator import ValidationError
from intentir.verifier import run_action, verify_ir


SOURCE = """
module TodoApp

entity Task:
  id: UUID
  title: Text required
  done: Boolean default false

action CreateTask:
  input:
    title: Text
  requires:
    title is not empty
  effects:
    insert Task
  ensures:
    created Task.title equals input.title

test "creates task":
  when CreateTask(title="buy milk")
  expect Task exists with title "buy milk"
"""

ROOT = Path(__file__).resolve().parents[1]
CRUD_SOURCE = (ROOT / "examples" / "todo_crud.intent").read_text(encoding="utf-8")


class CompilerTest(unittest.TestCase):
    def test_compile_source_builds_content_addressed_graph(self) -> None:
        ir = compile_source(SOURCE)

        self.assertEqual(ir["schemaVersion"], "0.5.0")
        self.assertEqual(ir["hashAlgorithm"], "sha256")
        self.assertTrue(ir["moduleId"].startswith("sha256:"))
        self.assertTrue(ir["canonicalHash"].startswith("sha256:"))

        action = next(
            node for node in ir["nodes"] if node["symbol"] == "action:CreateTask"
        )
        self.assertEqual(ir["symbols"]["action:CreateTask"], action["id"])
        self.assertEqual(
            action["effects"][0]["effect"],
            {"op": "insert", "entity": "Task"},
        )
        self.assertEqual(
            action["requires"][0]["condition"],
            {"kind": "not_empty", "target": {"kind": "input", "name": "title"}},
        )
        self.assertEqual(
            action["ensures"][0]["condition"],
            {
                "kind": "equals",
                "left": {"kind": "created_field", "entity": "Task", "field": "title"},
                "right": {"kind": "input", "name": "title"},
            },
        )
        self.assertIn(
            {
                "fromSymbol": "action:CreateTask",
                "toSymbol": "entity:Task",
                "kind": "writes",
            },
            [
                {
                    "fromSymbol": edge["fromSymbol"],
                    "toSymbol": edge["toSymbol"],
                    "kind": edge["kind"],
                }
                for edge in ir["edges"]
            ],
        )
        self.assertEqual(len(ir["obligations"]), 2)
        json.dumps(ir)

    def test_canonical_hash_ignores_field_declaration_order(self) -> None:
        reordered = SOURCE.replace(
            "  id: UUID\n  title: Text required\n  done: Boolean default false",
            "  done: Boolean default false\n  title: Text required\n  id: UUID",
        )

        first = compile_source(SOURCE)
        second = compile_source(reordered)

        self.assertEqual(first["canonicalHash"], second["canonicalHash"])
        self.assertEqual(canonical_json(first), canonical_json(second))

    def test_semantic_hash_ignores_equivalent_surface_spelling(self) -> None:
        explicit = SOURCE.replace(
            "title is not empty",
            "input.title is not empty",
        )

        first = compile_source(SOURCE)
        second = compile_source(explicit)

        self.assertEqual(first["canonicalHash"], second["canonicalHash"])
        self.assertNotEqual(canonical_json(first), canonical_json(second))

    def test_test_call_and_expectation_are_structured(self) -> None:
        ir = compile_source(SOURCE)
        test = next(node for node in ir["nodes"] if node["kind"] == "test")

        self.assertEqual(test["steps"][0]["action"], "CreateTask")
        self.assertEqual(test["steps"][0]["args"][0]["value"]["value"], "buy milk")
        self.assertEqual(test["expects"][0]["expectation"]["kind"], "entity_exists")
        self.assertEqual(
            test["expects"][0]["expectation"]["where"]["right"]["value"],
            "buy milk",
        )

    def test_verifier_executes_pre_effect_post_and_expectation(self) -> None:
        result = verify_ir(compile_source(SOURCE))

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], {"tests": 1, "passed": 1, "failed": 0})
        self.assertEqual(
            [check["kind"] for check in result["tests"][0]["checks"]],
            ["precondition", "effect", "postcondition", "expectation"],
        )
        self.assertEqual(
            result["tests"][0]["finalState"]["Task"][0],
            {"done": False, "title": "buy milk"},
        )

    def test_verifier_reports_failed_expectation(self) -> None:
        source = SOURCE.replace(
            'expect Task exists with title "buy milk"',
            'expect Task exists with title "sleep"',
        )

        result = verify_ir(compile_source(source))

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["tests"][0]["errors"][0]["code"],
            "expectation_failed",
        )

    def test_generate_typescript_checks_contracts_and_tests(self) -> None:
        output = generate_typescript(compile_source(SOURCE))

        self.assertIn("export type Task", output)
        self.assertIn("export function CreateTask", output)
        self.assertIn("precondition failed: title is not empty", output)
        self.assertIn(
            "postcondition failed: created Task.title equals input.title",
            output,
        )
        self.assertIn("tasks: [...nextStore.tasks, newTask0]", output)
        self.assertIn("export function runIntentIRTests", output)
        self.assertNotIn("undefined as never", output)

    def test_validation_exposes_code_path_scope_and_hint(self) -> None:
        source = """
module Broken

entity Task:
  title: Text required

action CreateTask:
  input:
    name: Text
  requires:
    title is not empty
  effects:
    insert MissingTask
  ensures:
    created Task.missing equals input.title

test "bad":
  when MissingAction(title="x")
  expect MissingTask exists
"""

        with self.assertRaises(ValidationError) as context:
            compile_source(source)

        diagnostics = context.exception.diagnostics
        codes = {diagnostic.code for diagnostic in diagnostics}
        self.assertIn("unknown_input", codes)
        self.assertIn("unknown_effect_entity", codes)
        self.assertIn("unknown_field", codes)
        self.assertIn("unknown_action", codes)
        self.assertIn("unknown_expected_entity", codes)
        unknown_input = next(item for item in diagnostics if item.code == "unknown_input")
        self.assertTrue(unknown_input.path.startswith("/actions/CreateTask/"))
        self.assertEqual(unknown_input.scope, ("name",))
        self.assertIsNotNone(unknown_input.hint)
        self.assertEqual(unknown_input.to_dict()["code"], "unknown_input")

    def test_validation_rejects_invalid_update_field_and_value_type(self) -> None:
        source = """
module Updates

entity Task:
  id: UUID required
  title: Text required

action UpdateTask:
  input:
    id: UUID required
  effects:
    update Task where id equals input.id set missing = true, title = false

test "update":
  when UpdateTask(id="task-1")
  expect Task exists
"""

        with self.assertRaises(ValidationError) as context:
            compile_source(source)

        codes = {item.code for item in context.exception.diagnostics}
        self.assertIn("unknown_effect_field", codes)
        self.assertIn("effect_assignment_type_mismatch", codes)

    def test_crud_effects_are_structured(self) -> None:
        update = parse_effect(
            "update Task where id equals input.id set done = true, title = input.title"
        )
        delete = parse_effect("delete Task where id equals input.id")

        self.assertEqual(update["op"], "update")
        self.assertEqual(update["where"]["left"]["field"], "id")
        self.assertEqual([item["field"] for item in update["set"]], ["done", "title"])
        self.assertEqual(delete["op"], "delete")
        self.assertEqual(delete["where"]["right"]["name"], "id")

    def test_key_and_repository_capability_are_structured(self) -> None:
        ir = compile_source(CRUD_SOURCE)
        task = next(node for node in ir["nodes"] if node["symbol"] == "entity:Task")
        complete = next(
            node for node in ir["nodes"] if node["symbol"] == "action:CompleteTask"
        )
        key = next(field for field in task["fields"] if field["name"] == "id")

        self.assertTrue(key["key"])
        self.assertTrue(key["unique"])
        self.assertEqual(
            [
                {
                    "kind": capability["kind"],
                    "entity": capability["entity"],
                    "operations": capability["operations"],
                }
                for capability in complete["capabilities"]
            ],
            [{"kind": "repository", "entity": "Task", "operations": ["update"]}],
        )

    def test_validation_enforces_key_and_unique_selectors(self) -> None:
        source = """
module InvalidIdentity

entity Task:
  firstId: UUID key default "fixed"
  secondId: UUID required key
  title: Text

action DeleteByTitle:
  input:
    title: Text required
  effects:
    delete Task where title equals input.title

test "delete":
  when DeleteByTitle(title="same")
  expect Task count equals 0
"""

        with self.assertRaises(ValidationError) as context:
            compile_source(source)

        codes = {item.code for item in context.exception.diagnostics}
        self.assertIn("key_requires_required", codes)
        self.assertIn("key_default_not_allowed", codes)
        self.assertIn("multiple_entity_keys", codes)
        self.assertIn("non_unique_effect_selector", codes)

    def test_verifier_executes_multi_step_crud_scenarios(self) -> None:
        result = verify_ir(compile_source(CRUD_SOURCE))

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], {"tests": 2, "passed": 2, "failed": 0})
        lifecycle = next(
            test for test in result["tests"] if test["name"] == "タスクを完了して改名できる"
        )
        self.assertEqual(
            lifecycle["finalState"]["Task"],
            [{"done": True, "id": "task-1", "title": "牛乳を2本買う"}],
        )
        self.assertEqual({check.get("step") for check in lifecycle["checks"] if "step" in check}, {0, 1, 2})

    def test_run_action_updates_state_and_is_transactional_on_failure(self) -> None:
        ir = compile_source(CRUD_SOURCE)
        initial = {
            "Task": [{"id": "task-1", "title": "牛乳を買う", "done": False}]
        }

        completed = run_action(ir, "CompleteTask", {"id": "task-1"}, initial)
        missing = run_action(ir, "CompleteTask", {"id": "missing"}, initial)

        self.assertTrue(completed["ok"])
        self.assertTrue(completed["state"]["Task"][0]["done"])
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["errors"][0]["code"], "effect_target_not_found")
        self.assertEqual(missing["state"], initial)

    def test_duplicate_key_insert_is_rejected_atomically(self) -> None:
        ir = compile_source(CRUD_SOURCE)
        first = run_action(
            ir, "CreateTask", {"id": "task-1", "title": "first"}
        )
        duplicate = run_action(
            ir,
            "CreateTask",
            {"id": "task-1", "title": "duplicate"},
            first["state"],
        )

        self.assertTrue(first["ok"])
        self.assertFalse(duplicate["ok"])
        self.assertEqual(
            duplicate["errors"][0]["code"], "unique_constraint_violation"
        )
        self.assertEqual(duplicate["state"], first["state"])

    def test_duplicate_key_in_loaded_state_is_rejected(self) -> None:
        ir = compile_source(CRUD_SOURCE)
        duplicate_state = {
            "Task": [
                {"id": "same", "title": "one", "done": False},
                {"id": "same", "title": "two", "done": False},
            ]
        }

        with self.assertRaisesRegex(ValueError, "unique constraint"):
            run_action(ir, "CompleteTask", {"id": "same"}, duplicate_state)

    def test_unique_field_update_collision_is_rejected_atomically(self) -> None:
        source = """
module Accounts

entity User:
  id: UUID required key
  email: Text required unique

action CreateUser:
  input:
    id: UUID required
    email: Text required
  effects:
    insert User

action ChangeEmail:
  input:
    id: UUID required
    email: Text required
  effects:
    update User where id equals input.id set email = input.email
"""
        ir = compile_source(source)
        first = run_action(
            ir, "CreateUser", {"id": "user-1", "email": "one@example.com"}
        )
        second = run_action(
            ir,
            "CreateUser",
            {"id": "user-2", "email": "two@example.com"},
            first["state"],
        )
        collision = run_action(
            ir,
            "ChangeEmail",
            {"id": "user-2", "email": "one@example.com"},
            second["state"],
        )

        self.assertFalse(collision["ok"])
        self.assertEqual(
            collision["errors"][0]["code"], "unique_constraint_violation"
        )
        self.assertEqual(collision["state"], second["state"])

    def test_sqlite_cli_persists_state_across_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "todo.db"
            create = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "intentir",
                    "run",
                    str(ROOT / "examples" / "todo_crud.intent"),
                    "CreateTask",
                    "--input",
                    '{"id":"db-1","title":"persistent"}',
                    "--db",
                    str(database),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            complete = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "intentir",
                    "run",
                    str(ROOT / "examples" / "todo_crud.intent"),
                    "CompleteTask",
                    "--input",
                    '{"id":"db-1"}',
                    "--db",
                    str(database),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(create.returncode, 0, create.stderr)
        self.assertEqual(complete.returncode, 0, complete.stderr)
        result = json.loads(complete.stdout)
        self.assertTrue(result["state"]["Task"][0]["done"])
        self.assertEqual(result["storage"]["kind"], "sqlite")

    def test_sqlite_rejects_changed_entity_schema(self) -> None:
        original = compile_source(CRUD_SOURCE)
        changed = compile_source(
            CRUD_SOURCE.replace("  done: Boolean default false", "  note: Text\n  done: Boolean default false")
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "todo.db"
            with SQLiteStateRepository(database) as repository:
                with repository.transaction():
                    repository.save(original, {"Task": []})
                with self.assertRaises(StorageError):
                    with repository.transaction():
                        repository.load(changed)

    def test_formatter_is_idempotent(self) -> None:
        untidy = ("# module comment\n" + SOURCE).replace("module TodoApp", "module   TodoApp").replace(
            "  title: Text required", "  title:Text   required"
        )

        formatted = format_source(untidy)

        self.assertEqual(format_source(formatted), formatted)
        self.assertIn("module TodoApp", formatted)
        self.assertIn("  title: Text required", formatted)
        self.assertIn("# module comment", formatted)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_generated_typescript_runs_crud_tests_in_node(self) -> None:
        output = generate_typescript(compile_source(CRUD_SOURCE))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "todo_crud.ts"
            target.write_text(output, encoding="utf-8")
            script = (
                f"import({json.dumps(target.as_uri())}).then(m => {{"
                "const r=m.runIntentIRTests();"
                "let s=m.createStore();"
                "s=m.CreateTask(s,{id:'same',title:'first'});"
                "let duplicateRejected=false;"
                "try{m.CreateTask(s,{id:'same',title:'second'})}"
                "catch{duplicateRejected=true}"
                "console.log(JSON.stringify(r));"
                "if(r.some(x=>!x.ok)||!duplicateRejected) process.exit(1)"
                "})"
            )
            completed = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        results = json.loads(completed.stdout)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result["ok"] for result in results))

    def test_validation_report_includes_static_and_runtime_results(self) -> None:
        report = generate_validation_report(SOURCE, "todo.intent")

        self.assertIn("# IntentIR 検証レポート", report)
        self.assertIn("- 結果: 成功", report)
        self.assertIn("- エラーはありません。", report)
        self.assertIn("- 1 / 1 Test 成功", report)
        self.assertIn("- 検証義務: 2", report)
        self.assertIn("- Canonical Hash: `sha256:", report)
        self.assertIn("- Storage Schema Hash: `sha256:", report)

    def test_validation_report_includes_runtime_failure(self) -> None:
        source = SOURCE.replace(
            'expect Task exists with title "buy milk"',
            'expect Task exists with title "sleep"',
        )

        report = generate_validation_report(source, "failing.intent")

        self.assertIn("- 結果: 失敗", report)
        self.assertIn("期待式を満たしませんでした", report)
        self.assertIn("義務ID: `sha256:", report)


if __name__ == "__main__":
    unittest.main()
