import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from intentir.canonical import canonical_json
from intentir.compiler import compile_path, compile_source
from intentir.expressions import parse_effect
from intentir.formatter import format_source
from intentir.generators.typescript import generate_typescript
from intentir.migration import MigrationError, apply_migration, plan_migration
from intentir.parser import ParseError
from intentir.reports import generate_validation_report
from intentir.sqlite_projection import (
    RELATIONAL_STORAGE_FORMAT,
    render_sqlite_ddl,
    sqlite_projection,
)
from intentir.storage import (
    SQLiteStateRepository,
    StorageError,
    storage_schema,
    storage_schema_hash,
)
from intentir.validator import ValidationError
from intentir.verifier import normalize_state, run_action, run_function, verify_ir


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
FUNCTION_SOURCE = (ROOT / "examples" / "functions.intent").read_text(
    encoding="utf-8"
)
FUNCTION_ACTION_SOURCE = (
    ROOT / "examples" / "function_actions.intent"
).read_text(encoding="utf-8")
MODULE_APP_PATH = ROOT / "examples" / "modules" / "app.intent"
RELATION_SOURCE = (ROOT / "examples" / "relations.intent").read_text(
    encoding="utf-8"
)
CAPABILITY_SOURCE = (ROOT / "examples" / "capabilities.intent").read_text(
    encoding="utf-8"
)

MIGRATION_BASE_SOURCE = """
module Inventory

entity Item:
  id: UUID required key
  name: Text required
"""


class CompilerTest(unittest.TestCase):
    def test_capabilities_build_nodes_bindings_and_dependency_edges(self) -> None:
        ir = compile_source(CAPABILITY_SOURCE)
        capability = next(
            node for node in ir["nodes"] if node["symbol"] == "capability:Clock"
        )
        action = next(
            node for node in ir["nodes"] if node["symbol"] == "action:CreateEvent"
        )
        test = next(node for node in ir["nodes"] if node["kind"] == "test")
        edges = {
            (edge["fromSymbol"], edge["toSymbol"], edge["kind"])
            for edge in ir["edges"]
        }

        self.assertEqual(
            capability["operations"], [{"name": "now", "returnType": "Text"}]
        )
        self.assertEqual(action["uses"][0]["binding"], "createdAt")
        self.assertEqual(action["uses"][0]["type"], "Text")
        self.assertEqual(test["givens"][0]["value"], "2026-07-16T09:00:00+09:00")
        self.assertIn(("action:CreateEvent", "capability:Clock", "uses"), edges)
        self.assertIn(
            ("test:injects-deterministic-clock", "capability:Clock", "stubs"),
            edges,
        )
        formatted = format_source(CAPABILITY_SOURCE)
        self.assertEqual(format_source(formatted), formatted)

    def test_capability_validation_reports_structured_failures(self) -> None:
        source = """
module InvalidCapabilities

capability Empty:

capability Clock:
  operation now returns Text
  operation now returns Text
  operation broken returns MissingType

entity Event:
  id: UUID required key
  createdAt: Text required

action Broken:
  input:
    id: UUID required
    createdAt: Text required
  uses:
    Missing.now as missingCapability
    Clock.missing as missingOperation
    Clock.now as createdAt
    Clock.now as secondClock
  effects:
    insert Event

action Valid:
  input:
    id: UUID required
  uses:
    Clock.now as createdAt
  effects:
    insert Event

test "missing stub":
  when Valid(id="event-1")
  expect Event count equals 1

test "wrong stub type":
  given Clock.now = 7
  when Valid(id="event-2")
  expect Event count equals 1
"""

        with self.assertRaises(ValidationError) as context:
            compile_source(source)

        codes = {item.code for item in context.exception.diagnostics}
        self.assertTrue(
            {
                "empty_capability",
                "duplicate_capability_operation",
                "unknown_type",
                "unknown_capability",
                "unknown_capability_operation",
                "capability_binding_collision",
                "duplicate_capability_use",
                "missing_test_capability",
                "literal_type_mismatch",
            }
            <= codes
        )

    def test_capability_runtime_is_typed_and_atomic(self) -> None:
        ir = compile_source(CAPABILITY_SOURCE)
        inputs = {"id": "event-1", "title": "runtime"}

        missing = run_action(ir, "CreateEvent", inputs)
        wrong = run_action(
            ir, "CreateEvent", inputs, capability_values={"Clock.now": 7}
        )
        success = run_action(
            ir,
            "CreateEvent",
            inputs,
            capability_values={"Clock.now": "2026-07-16T11:00:00+09:00"},
        )

        self.assertEqual(
            missing["errors"][0]["code"], "missing_runtime_capability"
        )
        self.assertEqual(
            wrong["errors"][0]["code"], "runtime_capability_type_mismatch"
        )
        self.assertEqual(missing["state"], {"Event": []})
        self.assertEqual(wrong["state"], {"Event": []})
        self.assertTrue(success["ok"])
        self.assertEqual(
            success["state"]["Event"][0]["createdAt"],
            "2026-07-16T11:00:00+09:00",
        )
        self.assertEqual(success["capabilitiesUsed"], ["Clock.now"])

    def test_capability_cli_accepts_json_values(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "intentir",
                "run",
                str(ROOT / "examples" / "capabilities.intent"),
                "CreateEvent",
                "--input",
                '{"id":"event-cli","title":"CLI"}',
                "--capabilities",
                '{"Clock.now":"2026-07-16T12:00:00+09:00"}',
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["capabilitiesUsed"], ["Clock.now"])
        self.assertEqual(
            result["state"]["Event"][0]["createdAt"],
            "2026-07-16T12:00:00+09:00",
        )

    def test_imported_capability_is_available_to_root_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "clock.intent").write_text(
                "module Environment\n\ncapability Clock:\n"
                "  operation now returns Text\n",
                encoding="utf-8",
            )
            app = root / "app.intent"
            app.write_text(
                'module App\n\nimport "./clock.intent"\n\n'
                "entity Event:\n  id: UUID required key\n"
                "  createdAt: Text required\n\n"
                "action CreateEvent:\n  input:\n    id: UUID required\n"
                "  uses:\n    Clock.now as createdAt\n"
                "  effects:\n    insert Event\n\n"
                'test "imported capability":\n'
                '  given Clock.now = "fixed"\n'
                '  when CreateEvent(id="event-1")\n'
                "  expect Event exists with createdAt \"fixed\"\n",
                encoding="utf-8",
            )
            ir = compile_path(app)

        capability = next(
            node for node in ir["nodes"] if node["symbol"] == "capability:Clock"
        )
        self.assertEqual(capability["definedIn"], "Environment")
        self.assertTrue(verify_ir(ir)["ok"])

    def test_capabilities_do_not_change_storage_schema(self) -> None:
        original = compile_source(CAPABILITY_SOURCE)
        extended = compile_source(
            CAPABILITY_SOURCE.replace(
                "  operation now returns Text",
                "  operation now returns Text\n  operation today returns Text",
            )
        )

        self.assertEqual(storage_schema_hash(original), storage_schema_hash(extended))
        self.assertNotEqual(original["canonicalHash"], extended["canonicalHash"])

    def test_entity_references_build_ir_edges_and_format_canonically(self) -> None:
        ir = compile_source(RELATION_SOURCE)
        task = next(node for node in ir["nodes"] if node["symbol"] == "entity:Task")
        project_id = next(
            field for field in task["fields"] if field["name"] == "projectId"
        )

        self.assertEqual(
            project_id["references"], {"entity": "Project", "field": "id"}
        )
        self.assertIn(
            ("entity:Task", "entity:Project", "references"),
            {
                (edge["fromSymbol"], edge["toSymbol"], edge["kind"])
                for edge in ir["edges"]
            },
        )
        formatted = format_source(RELATION_SOURCE)
        self.assertEqual(format_source(formatted), formatted)
        self.assertIn("projectId: UUID required ref Project.id", formatted)

    def test_reference_validation_rejects_invalid_targets_and_cycles(self) -> None:
        source = """
module InvalidRelations

entity Parent:
  id: UUID required key
  label: Text
  childId: UUID ref Child.id

entity Child:
  id: UUID required key
  parentId: UUID ref Parent.id
  missingEntity: UUID ref Missing.id
  missingField: UUID ref Parent.missing
  nonUnique: Text ref Parent.label
  wrongType: Integer ref Parent.id
"""

        with self.assertRaises(ValidationError) as context:
            compile_source(source)

        codes = {item.code for item in context.exception.diagnostics}
        self.assertTrue(
            {
                "unknown_reference_entity",
                "unknown_reference_field",
                "non_unique_reference_target",
                "reference_type_mismatch",
                "relation_cycle",
            }
            <= codes
        )

    def test_reference_constraints_are_atomic_in_python_runtime(self) -> None:
        ir = compile_source(RELATION_SOURCE)
        orphan = run_action(
            ir,
            "CreateTask",
            {"id": "task-1", "projectId": "missing", "title": "orphan"},
        )
        project = run_action(
            ir, "CreateProject", {"id": "project-1", "name": "Ailex"}
        )
        task = run_action(
            ir,
            "CreateTask",
            {
                "id": "task-1",
                "projectId": "project-1",
                "title": "linked",
            },
            project["state"],
        )
        rejected_delete = run_action(
            ir, "DeleteProject", {"id": "project-1"}, task["state"]
        )

        self.assertFalse(orphan["ok"])
        self.assertEqual(
            orphan["errors"][0]["code"], "reference_constraint_violation"
        )
        self.assertEqual(orphan["state"], {"Project": [], "Task": []})
        self.assertFalse(rejected_delete["ok"])
        self.assertEqual(
            rejected_delete["errors"][0]["code"],
            "reference_constraint_violation",
        )
        self.assertEqual(rejected_delete["state"], task["state"])

    def test_compile_source_builds_content_addressed_graph(self) -> None:
        ir = compile_source(SOURCE)

        self.assertEqual(ir["schemaVersion"], "0.12.0")
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

    def test_module_imports_build_content_addressed_graph(self) -> None:
        ir = compile_path(MODULE_APP_PATH)
        modules = {
            node["name"]: node for node in ir["nodes"] if node["kind"] == "module"
        }

        self.assertEqual(set(modules), {"ModularTodo", "TaskDomain", "TextRules"})
        self.assertEqual(ir["moduleId"], modules["ModularTodo"]["id"])
        self.assertEqual(
            {
                (edge["fromSymbol"], edge["toSymbol"])
                for edge in ir["edges"]
                if edge["kind"] == "imports"
            },
            {
                ("module:ModularTodo", "module:TaskDomain"),
                ("module:TaskDomain", "module:TextRules"),
            },
        )
        origins = {
            node["symbol"]: node["definedIn"]
            for node in ir["nodes"]
            if "definedIn" in node
        }
        self.assertEqual(origins["entity:Task"], "TaskDomain")
        self.assertEqual(origins["function:NormalizeTitle"], "TextRules")
        self.assertEqual(origins["action:RenameTask"], "ModularTodo")
        result = verify_ir(ir)
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["tests"][0]["finalState"]["Task"][0]["title"], "modular!"
        )

    def test_imported_semantics_flow_into_root_module_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "math.intent"
            first_root = root / "first.intent"
            second_root = root / "second.intent"
            dependency.write_text(
                """module Math\n\nfunction Increment:\n  input:\n    value: Integer required\n  returns: Integer\n  body: value + 1\n""",
                encoding="utf-8",
            )
            first_root.write_text(
                'module App\n\nimport "./math.intent"\n', encoding="utf-8"
            )
            second_root.write_text(
                'module App\n\nimport "math.intent"\n', encoding="utf-8"
            )
            first = compile_path(first_root)
            equivalent = compile_path(second_root)
            dependency.write_text(
                dependency.read_text(encoding="utf-8").replace("value + 1", "value + 2"),
                encoding="utf-8",
            )
            changed = compile_path(first_root)

        self.assertEqual(first["moduleId"], equivalent["moduleId"])
        self.assertEqual(first["canonicalHash"], equivalent["canonicalHash"])
        self.assertNotEqual(first["moduleId"], changed["moduleId"])
        self.assertNotEqual(first["canonicalHash"], changed["canonicalHash"])

    def test_import_resolution_rejects_cycles_duplicate_modules_and_missing_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.intent").write_text(
                'module A\n\nimport "./b.intent"\n', encoding="utf-8"
            )
            (root / "b.intent").write_text(
                'module B\n\nimport "./a.intent"\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ParseError, "import cycle: A -> B -> A"
            ) as cycle_context:
                compile_path(root / "a.intent")
            self.assertEqual(cycle_context.exception.code, "import_cycle")

            (root / "left.intent").write_text("module Shared\n", encoding="utf-8")
            (root / "right.intent").write_text("module Shared\n", encoding="utf-8")
            (root / "duplicate.intent").write_text(
                'module Root\n\nimport "./left.intent"\nimport "./right.intent"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ParseError, "duplicate module name Shared"
            ) as duplicate_context:
                compile_path(root / "duplicate.intent")
            self.assertEqual(duplicate_context.exception.code, "duplicate_module")

            (root / "missing.intent").write_text(
                'module MissingRoot\n\nimport "./absent.intent"\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ParseError, "cannot read import"
            ) as missing_context:
                compile_path(root / "missing.intent")
            self.assertEqual(missing_context.exception.code, "missing_import")

            (root / "absolute.intent").write_text(
                f"module AbsoluteRoot\n\nimport {json.dumps(str(root / 'left.intent'))}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ParseError, "import must be relative"
            ) as absolute_context:
                compile_path(root / "absolute.intent")
            self.assertEqual(absolute_context.exception.code, "absolute_import")

    def test_imports_require_paths_and_are_formatted_canonically(self) -> None:
        source = "module App\nimport './domain.intent'\n"

        with self.assertRaisesRegex(ParseError, "imports require a source path"):
            compile_source(source)

        formatted = format_source(source)
        self.assertEqual(format_source(formatted), formatted)
        self.assertEqual(
            formatted, 'module App\n\nimport "./domain.intent"\n'
        )

    def test_pure_functions_build_calls_edges_and_example_obligations(self) -> None:
        ir = compile_source(FUNCTION_SOURCE)
        functions = {
            node["name"]: node
            for node in ir["nodes"]
            if node["kind"] == "function"
        }

        self.assertEqual(set(functions), {"Clamp", "ClampDouble", "Double", "Greeting"})
        self.assertEqual(functions["Double"]["returnType"], "Integer")
        self.assertEqual(
            functions["Double"]["body"]["expression"]["op"], "multiply"
        )
        call_edges = {
            (edge["fromSymbol"], edge["toSymbol"])
            for edge in ir["edges"]
            if edge["kind"] == "calls"
        }
        self.assertEqual(
            call_edges,
            {
                ("function:ClampDouble", "function:Clamp"),
                ("function:ClampDouble", "function:Double"),
            },
        )
        function_obligations = [
            obligation
            for obligation in ir["obligations"]
            if obligation["kind"] == "function_example"
        ]
        self.assertEqual(len(function_obligations), 5)

    def test_actions_call_pure_functions_in_contracts_and_effects(self) -> None:
        ir = compile_source(FUNCTION_ACTION_SOURCE)
        call_edges = {
            (edge["fromSymbol"], edge["toSymbol"])
            for edge in ir["edges"]
            if edge["kind"] == "calls"
        }

        self.assertEqual(
            call_edges,
            {
                ("action:CreateTask", "function:IsAcceptableTitle"),
                ("action:RenameTask", "function:IsAcceptableTitle"),
                ("action:RenameTask", "function:NormalizeTitle"),
            },
        )
        result = verify_ir(ir)
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["tests"][0]["finalState"]["Task"],
            [{"id": "task-1", "title": "write docs!"}],
        )

        failed = run_action(
            ir,
            "RenameTask",
            {"id": "task-1", "title": ""},
            {"Task": [{"id": "task-1", "title": "draft"}]},
        )
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["errors"][0]["code"], "precondition_failed")

    def test_action_pure_function_values_are_statically_typed(self) -> None:
        source = FUNCTION_ACTION_SOURCE.replace(
            "set title = NormalizeTitle(title)",
            "set title = IsAcceptableTitle(title)",
        )

        with self.assertRaises(ValidationError) as context:
            compile_source(source)

        self.assertIn(
            "effect_assignment_type_mismatch",
            {diagnostic.code for diagnostic in context.exception.diagnostics},
        )

    def test_action_pure_runtime_error_is_atomic(self) -> None:
        source = """
module PureFailure

function Explode:
  input:
    value: Integer required
  returns: Number
  body: value / 0

entity Counter:
  id: UUID required key
  value: Number required

action UpdateCounter:
  input:
    id: UUID required
    value: Integer required
  effects:
    update Counter where id equals input.id set value = Explode(value)
"""
        ir = compile_source(source)
        state = {"Counter": [{"id": "counter-1", "value": 10}]}

        result = run_action(
            ir,
            "UpdateCounter",
            {"id": "counter-1", "value": 2},
            state,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["code"], "pure_division_by_zero")
        self.assertEqual(result["state"], state)

    def test_function_hash_ignores_named_argument_order(self) -> None:
        reordered = FUNCTION_SOURCE.replace(
            "Clamp(value=12, minimum=0, maximum=10) equals 10",
            "Clamp(maximum=10, value=12, minimum=0) equals 10",
        )

        first = compile_source(FUNCTION_SOURCE)
        second = compile_source(reordered)

        self.assertEqual(first["canonicalHash"], second["canonicalHash"])

    def test_run_function_supports_defaults_nested_calls_and_conditionals(self) -> None:
        ir = compile_source(FUNCTION_SOURCE)

        nested = run_function(ir, "ClampDouble", {"value": 7})
        defaulted = run_function(ir, "Greeting", {"name": "AI"})
        invalid = run_function(ir, "Double", {"value": "wrong"})

        self.assertEqual(nested["result"], 10)
        self.assertEqual(defaulted["result"], "Hello, AI")
        self.assertFalse(invalid["ok"])
        self.assertEqual(
            invalid["errors"][0]["code"], "function_argument_type_mismatch"
        )

    def test_function_validation_rejects_type_errors_and_recursive_cycles(self) -> None:
        type_error = FUNCTION_SOURCE.replace(
            "body: value * 2", 'body: value + "x"', 1
        )
        recursive = """
module Recursive

function Loop:
  input:
    value: Integer required
  returns: Integer
  body: Loop(value)
"""
        reserved = """
module Reserved

function Identity:
  input:
    true: Boolean required
  returns: Boolean
  body: true
"""

        with self.assertRaises(ValidationError) as type_context:
            compile_source(type_error)
        with self.assertRaises(ValidationError) as cycle_context:
            compile_source(recursive)
        with self.assertRaises(ValidationError) as reserved_context:
            compile_source(reserved)

        self.assertIn(
            "pure_expression_type_mismatch",
            {diagnostic.code for diagnostic in type_context.exception.diagnostics},
        )
        self.assertIn(
            "recursive_function_cycle",
            {diagnostic.code for diagnostic in cycle_context.exception.diagnostics},
        )
        self.assertIn(
            "reserved_function_input",
            {diagnostic.code for diagnostic in reserved_context.exception.diagnostics},
        )

    def test_function_formatter_is_idempotent(self) -> None:
        untidy = FUNCTION_SOURCE.replace(
            "value: Integer required", "value:Integer   required"
        )

        formatted = format_source(untidy)

        self.assertEqual(format_source(formatted), formatted)
        self.assertIn("function Double:", formatted)
        self.assertIn("  returns: Integer", formatted)
        self.assertIn("  body: value * 2", formatted)

    def test_call_cli_evaluates_pure_function(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "intentir",
                "call",
                str(ROOT / "examples" / "functions.intent"),
                "ClampDouble",
                "--input",
                '{"value":7}',
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["result"], 10)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_generated_typescript_runs_function_examples_in_node(self) -> None:
        output = generate_typescript(compile_source(FUNCTION_SOURCE))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "functions.ts"
            target.write_text(output, encoding="utf-8")
            script = (
                f"import({json.dumps(target.as_uri())}).then(m=>{{"
                "const r=m.runIntentIRTests();"
                "const nested=m.ClampDouble({value:7});"
                "const greeting=m.Greeting({name:'AI'});"
                "console.log(JSON.stringify(r));"
                "if(r.length!==5||r.some(x=>!x.ok)||nested!==10||greeting!=='Hello, AI')process.exit(1)"
                "})"
            )
            completed = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(all(result["ok"] for result in json.loads(completed.stdout)))

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_generated_typescript_runs_functions_inside_actions(self) -> None:
        output = generate_typescript(compile_source(FUNCTION_ACTION_SOURCE))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "function_actions.ts"
            target.write_text(output, encoding="utf-8")
            script = (
                f"import({json.dumps(target.as_uri())}).then(m=>{{"
                "const r=m.runIntentIRTests();"
                "let s=m.createStore();"
                "s=m.CreateTask(s,{id:'task-2',title:'draft'});"
                "s=m.RenameTask(s,{id:'task-2',title:'ship'});"
                "console.log(JSON.stringify({results:r,state:s}));"
                "if(r.some(x=>!x.ok)||s.tasks[0].title!=='ship!')process.exit(1)"
                "})"
            )
            completed = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(all(result["ok"] for result in payload["results"]))
        self.assertEqual(payload["state"]["tasks"][0]["title"], "ship!")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_generated_typescript_runs_transitive_imports(self) -> None:
        output = generate_typescript(compile_path(MODULE_APP_PATH))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "modules.ts"
            target.write_text(output, encoding="utf-8")
            script = (
                f"import({json.dumps(target.as_uri())}).then(m=>{{"
                "const r=m.runIntentIRTests();"
                "console.log(JSON.stringify(r));"
                "if(r.length!==3||r.some(x=>!x.ok))process.exit(1)"
                "})"
            )
            completed = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(all(result["ok"] for result in json.loads(completed.stdout)))

    def test_cli_resolves_transitive_imports(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "intentir", "test", str(MODULE_APP_PATH)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        report = subprocess.run(
            [sys.executable, "-m", "intentir", "report", str(MODULE_APP_PATH)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("1 passed, 0 failed, 1 total", completed.stdout)
        self.assertIn("2 function examples passed", completed.stdout)
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertIn("- Module: 3", report.stdout)
        self.assertIn("- Import: 2", report.stdout)

    def test_function_validation_report_includes_examples(self) -> None:
        report = generate_validation_report(FUNCTION_SOURCE, "functions.intent")

        self.assertIn("- Function: 4", report)
        self.assertIn("- Function Example: 5", report)
        self.assertIn("- 5 / 5 Function Example 成功", report)

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
        created = json.loads(create.stdout)
        result = json.loads(complete.stdout)
        self.assertTrue(result["state"]["Task"][0]["done"])
        self.assertEqual(result["storage"]["kind"], "sqlite")
        self.assertEqual(result["storage"]["format"], RELATIONAL_STORAGE_FORMAT)
        self.assertEqual(created["storage"]["writeMode"], "replace")
        self.assertEqual(result["storage"]["writeMode"], "incremental")

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

    def test_sqlite_projection_is_deterministic_and_typed(self) -> None:
        ir = compile_source(CRUD_SOURCE)
        schema = storage_schema(ir)

        projection = sqlite_projection(ir["module"], schema)
        repeated = sqlite_projection(ir["module"], schema)
        ddl = render_sqlite_ddl(ir["module"], schema)

        self.assertEqual(projection, repeated)
        self.assertTrue(projection["id"].startswith("sha256:"))
        self.assertEqual(projection["storageFormat"], RELATIONAL_STORAGE_FORMAT)
        task = projection["entities"][0]
        columns = {column["field"]: column for column in task["columns"]}
        self.assertEqual(columns["id"]["sqliteType"], "TEXT")
        self.assertTrue(columns["id"]["key"])
        self.assertTrue(columns["id"]["unique"])
        self.assertEqual(columns["done"]["sqliteType"], "INTEGER")
        self.assertIn(f'CREATE TABLE "{task["table"]}"', ddl)
        self.assertIn('"id" TEXT NOT NULL UNIQUE', ddl)
        self.assertIn('"done" INTEGER DEFAULT 0', ddl)
        self.assertIn("IN (0, 1)", ddl)

    def test_sqlite_repository_uses_relational_tables_and_constraints(self) -> None:
        ir = compile_source(CRUD_SOURCE)
        state = {
            "Task": [
                {"id": "task-1", "title": "first", "done": False},
                {"id": "task-2", "title": "second", "done": True},
            ]
        }
        projection = sqlite_projection(ir["module"], storage_schema(ir))
        task = projection["entities"][0]
        table = task["table"]

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "todo.db"
            with SQLiteStateRepository(database) as repository:
                repository.save(ir, state)
                stored = repository.inspect(ir["module"])
                metadata = repository.connection.execute(
                    "SELECT state_json, storage_format FROM intentir_state "
                    "WHERE module = ?",
                    (ir["module"],),
                ).fetchone()
                columns = repository.connection.execute(
                    f'PRAGMA table_info("{table}")'
                ).fetchall()
                with self.assertRaises(sqlite3.IntegrityError):
                    repository.connection.execute(
                        f'INSERT INTO "{table}" ("id", "title", "done") '
                        "VALUES (?, ?, ?)",
                        ("task-1", "duplicate", 0),
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    repository.connection.execute(
                        f'INSERT INTO "{table}" ("id", "title", "done") '
                        "VALUES (?, ?, ?)",
                        ("task-3", "bad boolean", 7),
                    )
                loaded = repository.load(ir)

        self.assertEqual(stored["storageFormat"], RELATIONAL_STORAGE_FORMAT)
        self.assertEqual(metadata, ("{}", RELATIONAL_STORAGE_FORMAT))
        self.assertEqual(loaded, state)
        column_names = {column[1] for column in columns}
        self.assertTrue({"id", "title", "done"} <= column_names)

    def test_sqlite_projects_and_enforces_entity_references(self) -> None:
        ir = compile_source(RELATION_SOURCE)
        projection = sqlite_projection(ir["module"], storage_schema(ir))
        entities = {entity["entity"]: entity for entity in projection["entities"]}
        project = entities["Project"]
        task = entities["Task"]
        state = {
            "Project": [{"id": "project-1", "name": "Ailex"}],
            "Task": [
                {
                    "id": "task-1",
                    "projectId": "project-1",
                    "title": "linked",
                    "done": False,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "relations.db"
            with SQLiteStateRepository(database) as repository:
                repository.save(ir, state)
                foreign_keys = repository.connection.execute(
                    f'PRAGMA foreign_key_list("{task["table"]}")'
                ).fetchall()
                with self.assertRaises(sqlite3.IntegrityError):
                    repository.connection.execute(
                        f'INSERT INTO "{task["table"]}" '
                        '("id", "projectId", "title", "done") '
                        "VALUES (?, ?, ?, ?)",
                        ("task-2", "missing", "orphan", 0),
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    repository.connection.execute(
                        f'DELETE FROM "{project["table"]}" WHERE "id" = ?',
                        ("project-1",),
                    )

        self.assertEqual(len(foreign_keys), 1)
        self.assertEqual(foreign_keys[0][2], project["table"])
        self.assertEqual(foreign_keys[0][3:5], ("projectId", "id"))

    def test_sqlite_keyed_actions_persist_only_changed_rows(self) -> None:
        ir = compile_source(RELATION_SOURCE)
        initial = {
            "Project": [{"id": "project-1", "name": "Ailex"}],
            "Task": [
                {
                    "id": "task-1",
                    "projectId": "project-1",
                    "title": "before",
                    "done": False,
                }
            ],
        }
        renamed = run_action(
            ir,
            "RenameTask",
            {"id": "task-1", "title": "after"},
            initial,
        )

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "incremental.db"
            with SQLiteStateRepository(database) as repository:
                repository.save(ir, initial)
                statements: list[str] = []
                repository.connection.set_trace_callback(statements.append)
                mode = repository.save_changes(
                    ir, initial, renamed["state"], {"Task"}
                )
                repository.connection.set_trace_callback(None)
                loaded = repository.load(ir)

        upper = [statement.lstrip().upper() for statement in statements]
        self.assertEqual(mode, "incremental")
        self.assertTrue(any(statement.startswith("UPDATE ") for statement in upper))
        self.assertFalse(any("CREATE TABLE" in statement for statement in upper))
        self.assertFalse(any(statement.startswith("DROP TABLE") for statement in upper))
        self.assertEqual(loaded, renamed["state"])

    def test_v06_json_database_converts_to_relational_storage(self) -> None:
        ir = compile_source(CRUD_SOURCE)
        state = {"Task": [{"id": "legacy-1", "title": "legacy", "done": False}]}
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy-v06.db"
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TABLE intentir_state (
                    module TEXT PRIMARY KEY,
                    schema_hash TEXT NOT NULL,
                    schema_json TEXT,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "INSERT INTO intentir_state("
                "module, schema_hash, schema_json, state_json) VALUES (?, ?, ?, ?)",
                (
                    ir["module"],
                    storage_schema_hash(ir),
                    canonical_json(storage_schema(ir)),
                    canonical_json(state),
                ),
            )
            connection.commit()
            connection.close()

            with SQLiteStateRepository(database) as repository:
                before = repository.inspect(ir["module"])
                mode = repository.save_changes(
                    ir, before["state"], before["state"], set()
                )
                after = repository.inspect(ir["module"])
                relation_count = repository.connection.execute(
                    "SELECT COUNT(*) FROM intentir_relations WHERE module = ?",
                    (ir["module"],),
                ).fetchone()[0]

        self.assertEqual(before["storageFormat"], "json-v1")
        self.assertEqual(mode, "replace")
        self.assertEqual(after["storageFormat"], RELATIONAL_STORAGE_FORMAT)
        self.assertEqual(after["state"], state)
        self.assertEqual(relation_count, 1)

    def test_sqlite_repository_rejects_unsafe_relation_metadata(self) -> None:
        ir = compile_source(CRUD_SOURCE)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "tampered.db"
            with SQLiteStateRepository(database) as repository:
                repository.save(ir, {"Task": []})
                repository.connection.execute(
                    "CREATE TABLE user_data (value TEXT)"
                )
                repository.connection.execute(
                    "UPDATE intentir_relations SET table_name = 'user_data' "
                    "WHERE module = ?",
                    (ir["module"],),
                )
                with self.assertRaises(StorageError):
                    repository.save(ir, {"Task": []})
                user_table = repository.connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'user_data'"
                ).fetchone()

        self.assertEqual(user_table, ("user_data",))

    def test_build_sqlite_cli_emits_relational_ddl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "todo.sql"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "intentir",
                    "build",
                    str(ROOT / "examples" / "todo_crud.intent"),
                    "--target",
                    "sqlite",
                    "-o",
                    str(output),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            ddl = output.read_text(encoding="utf-8") if output.exists() else ""

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("IntentIR SQLite projection sha256:", ddl)
        self.assertIn("CREATE TABLE", ddl)

    def test_safe_migration_adds_default_and_optional_fields(self) -> None:
        source_ir = compile_source(MIGRATION_BASE_SOURCE)
        target_ir = compile_source(
            MIGRATION_BASE_SOURCE.replace(
                "  name: Text required",
                "  name: Text required\n  note: Text\n  active: Boolean default true",
            )
        )
        state = {"Item": [{"id": "item-1", "name": "milk"}]}
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "inventory.db"
            with SQLiteStateRepository(database) as repository:
                with repository.transaction():
                    repository.save(source_ir, state)
                stored = repository.inspect("Inventory")
                self.assertIsNotNone(stored)
                plan = plan_migration(stored["schema"], target_ir)
                repeated = plan_migration(stored["schema"], target_ir)

                self.assertEqual(plan["id"], repeated["id"])
                self.assertEqual(plan["summary"], {"safe": 2, "destructive": 0, "manual": 0})
                self.assertTrue(plan["applicable"])
                with repository.transaction():
                    migrated = apply_migration(state, plan)
                    normalized = normalize_state(target_ir, migrated)
                    repository.save(target_ir, normalized)

                loaded = repository.load(target_ir)

        self.assertEqual(
            loaded,
            {"Item": [{"id": "item-1", "name": "milk", "active": True}]},
        )

    def test_adding_reference_requires_manual_migration(self) -> None:
        without_reference = compile_source(
            RELATION_SOURCE.replace(" required ref Project.id", " required")
        )
        with_reference = compile_source(RELATION_SOURCE)

        added = plan_migration(storage_schema(without_reference), with_reference)
        removed = plan_migration(storage_schema(with_reference), without_reference)

        self.assertEqual(added["summary"]["manual"], 1)
        self.assertFalse(added["applicable"])
        self.assertEqual(removed["summary"]["safe"], 1)
        self.assertTrue(removed["applicable"])

    def test_migration_rejects_required_field_without_default(self) -> None:
        source_ir = compile_source(MIGRATION_BASE_SOURCE)
        target_ir = compile_source(
            MIGRATION_BASE_SOURCE.replace(
                "  name: Text required",
                "  name: Text required\n  owner: Text required",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "inventory.db"
            original = {"Item": [{"id": "item-1", "name": "milk"}]}
            with SQLiteStateRepository(database) as repository:
                with repository.transaction():
                    repository.save(source_ir, original)
                stored = repository.inspect("Inventory")
                plan = plan_migration(stored["schema"], target_ir)

                self.assertFalse(plan["applicable"])
                self.assertEqual(plan["summary"]["manual"], 1)
                with self.assertRaises(MigrationError):
                    with repository.transaction():
                        migrated = apply_migration(stored["state"], plan)
                        repository.save(target_ir, migrated)
                unchanged = repository.load(source_ir)

        self.assertEqual(unchanged, original)

    def test_relational_migration_table_rebuild_rolls_back(self) -> None:
        source_ir = compile_source(MIGRATION_BASE_SOURCE)
        target_ir = compile_source(
            MIGRATION_BASE_SOURCE.replace(
                "  name: Text required",
                "  name: Text required\n  active: Boolean default true",
            )
        )
        original = {"Item": [{"id": "item-1", "name": "milk"}]}

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "rollback.db"
            with SQLiteStateRepository(database) as repository:
                repository.save(source_ir, original)
                stored = repository.inspect("Inventory")
                plan = plan_migration(stored["schema"], target_ir)
                with self.assertRaises(RuntimeError):
                    with repository.transaction():
                        migrated = apply_migration(stored["state"], plan)
                        repository.save(target_ir, migrated)
                        raise RuntimeError("abort after relational table rebuild")
                restored = repository.load(source_ir)
                restored_metadata = repository.inspect("Inventory")
                with self.assertRaises(StorageError):
                    repository.load(target_ir)

        self.assertEqual(restored, original)
        self.assertEqual(restored_metadata["schemaHash"], storage_schema_hash(source_ir))
        self.assertEqual(
            restored_metadata["storageFormat"], RELATIONAL_STORAGE_FORMAT
        )

    def test_destructive_migration_requires_explicit_approval(self) -> None:
        source_ir = compile_source(MIGRATION_BASE_SOURCE)
        target_ir = compile_source(
            MIGRATION_BASE_SOURCE.replace("  name: Text required\n", "")
        )
        state = {"Item": [{"id": "item-1", "name": "milk"}]}
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "inventory.db"
            with SQLiteStateRepository(database) as repository:
                with repository.transaction():
                    repository.save(source_ir, state)
                stored = repository.inspect("Inventory")
                plan = plan_migration(stored["schema"], target_ir)

        self.assertEqual(plan["summary"]["destructive"], 1)
        with self.assertRaises(MigrationError):
            apply_migration(state, plan)
        migrated = apply_migration(state, plan, allow_destructive=True)
        self.assertEqual(migrated, {"Item": [{"id": "item-1"}]})

    def test_migrate_cli_plans_and_applies_schema_change(self) -> None:
        source_ir = compile_source(MIGRATION_BASE_SOURCE)
        target_source = MIGRATION_BASE_SOURCE.replace(
            "  name: Text required",
            "  name: Text required\n  active: Boolean default true",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_path = root / "inventory.intent"
            target_path.write_text(target_source, encoding="utf-8")
            database = root / "inventory.db"
            with SQLiteStateRepository(database) as repository:
                with repository.transaction():
                    repository.save(
                        source_ir,
                        {"Item": [{"id": "item-1", "name": "milk"}]},
                    )

            planned = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "intentir",
                    "migrate",
                    str(target_path),
                    "--db",
                    str(database),
                    "--json",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            applied = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "intentir",
                    "migrate",
                    str(target_path),
                    "--db",
                    str(database),
                    "--apply",
                    "--json",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            with SQLiteStateRepository(database) as repository:
                stored = repository.inspect("Inventory")

        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertFalse(json.loads(planned.stdout)["applied"])
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertTrue(json.loads(applied.stdout)["applied"])
        self.assertEqual(stored["schemaHash"], storage_schema_hash(compile_source(target_source)))
        self.assertEqual(stored["state"]["Item"][0]["active"], True)
        self.assertEqual(stored["storageFormat"], RELATIONAL_STORAGE_FORMAT)

    def test_v05_database_can_backfill_schema_snapshot(self) -> None:
        ir = compile_source(CRUD_SOURCE)
        state = {"Task": []}
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.db"
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TABLE intentir_state (
                    module TEXT PRIMARY KEY,
                    schema_hash TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "INSERT INTO intentir_state(module, schema_hash, state_json) VALUES (?, ?, ?)",
                (ir["module"], storage_schema_hash(ir), json.dumps(state)),
            )
            connection.commit()
            connection.close()

            with SQLiteStateRepository(database) as repository:
                self.assertEqual(repository.load(ir), state)
                self.assertIsNone(repository.inspect(ir["module"])["schema"])
                with repository.transaction():
                    repository.save(ir, state)
                stored = repository.inspect(ir["module"])

        self.assertIsNotNone(stored["schema"])
        self.assertEqual(stored["schemaHash"], storage_schema_hash(ir))
        self.assertEqual(stored["storageFormat"], RELATIONAL_STORAGE_FORMAT)

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

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_generated_typescript_enforces_entity_references(self) -> None:
        output = generate_typescript(compile_source(RELATION_SOURCE))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "relations.ts"
            target.write_text(output, encoding="utf-8")
            script = (
                f"import({json.dumps(target.as_uri())}).then(m => {{"
                "let s=m.createStore();"
                "let orphanRejected=false;"
                "try{m.CreateTask(s,{id:'task-1',projectId:'missing',title:'x'})}"
                "catch{orphanRejected=true}"
                "s=m.CreateProject(s,{id:'project-1',name:'Ailex'});"
                "s=m.CreateTask(s,{id:'task-1',projectId:'project-1',title:'x'});"
                "let deleteRejected=false;"
                "try{m.DeleteProject(s,{id:'project-1'})}"
                "catch{deleteRejected=true}"
                "if(!orphanRejected||!deleteRejected) process.exit(1)"
                "})"
            )
            completed = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_generated_typescript_injects_and_checks_capabilities(self) -> None:
        output = generate_typescript(compile_source(CAPABILITY_SOURCE))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "capabilities.ts"
            target.write_text(output, encoding="utf-8")
            script = (
                f"import({json.dumps(target.as_uri())}).then(m => {{"
                "const tests=m.runIntentIRTests();"
                "const initial=m.createStore();"
                "const next=m.CreateEvent(initial,{id:'event-2',title:'node'},"
                "{Clock:{now:()=> 'node-time'}});"
                "let wrongTypeRejected=false;"
                "try{m.CreateEvent(initial,{id:'event-3',title:'bad'},"
                "{Clock:{now:()=> 7}})}catch{wrongTypeRejected=true}"
                "if(tests.some(x=>!x.ok)||next.events[0].createdAt!=='node-time'"
                "||!wrongTypeRejected||initial.events.length!==0) process.exit(1)"
                "})"
            )
            completed = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_validation_report_includes_static_and_runtime_results(self) -> None:
        report = generate_validation_report(SOURCE, "todo.intent")

        self.assertIn("# IntentIR 検証レポート", report)
        self.assertIn("- 結果: 成功", report)
        self.assertIn("- エラーはありません。", report)
        self.assertIn("- 1 / 1 Test 成功", report)
        self.assertIn("- 検証義務: 2", report)
        self.assertIn("- Canonical Hash: `sha256:", report)
        self.assertIn("- Storage Schema Hash: `sha256:", report)
        self.assertIn("- SQLite Projection ID: `sha256:", report)
        self.assertIn("- SQLite Storage Format: `relational-v1`", report)

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
