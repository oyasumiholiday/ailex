import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import intentir.verifier as verifier
from intentir.compiler import compile_source
from intentir.formatter import format_source
from intentir.generators.typescript import generate_typescript
from intentir.parser import ParseError
from intentir.patch import plan_patch_source
from intentir.validator import ValidationError
from intentir.verifier import run_action, run_function, verify_ir


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_SOURCE = (ROOT / "examples" / "local_bindings.intent").read_text(
    encoding="utf-8"
)

RUNTIME_SOURCE = """module LocalBindingRuntime

function Probe:
  input:
    value: Integer required
  returns: Integer
  body: value

function Twice:
  input:
    value: Integer required
  returns: Integer
  let:
    measured = Probe(value)
  body: measured + measured

function UnusedFailure:
  input:
    value: Integer required
  returns: Integer
  let:
    unused = 1 // 0
  body: value

function PrototypeName:
  input:
    value: Integer required
  returns: Integer
  let:
    __proto__ = value + 1
  body: __proto__

function FirstScope:
  input:
    value: Integer required
  returns: Integer
  let:
    local = value + 1
  body: local

function SecondScope:
  input:
    value: Integer required
  returns: Integer
  let:
    local = value + 2
  body: local

function InRange:
  input:
    value: Integer required
  returns: Boolean
  let:
    minimum = 0
    maximum = 100
  body: minimum <= value <= maximum

entity Metric:
  id: UUID required key
  accepted: Boolean required

action SetAccepted:
  input:
    id: UUID required
    value: Integer required
  effects:
    update Metric where id equals input.id set accepted = InRange(value)
"""


def patch_envelope(source: str, operation: dict) -> dict:
    ir = compile_source(source)
    return {
        "schemaVersion": "0.13.0",
        "baseModuleId": ir["moduleId"],
        "operations": [operation],
        "requestedObligations": ["static"],
    }


def node_id(source: str, symbol: str) -> str:
    return next(
        node["id"]
        for node in compile_source(source)["nodes"]
        if node["symbol"] == symbol
    )


class LocalBindingTest(unittest.TestCase):
    def test_bindings_lower_sequentially_without_empty_ir_metadata(self) -> None:
        ir = compile_source(EXAMPLE_SOURCE)
        invoice = next(
            node for node in ir["nodes"] if node.get("name") == "InvoiceTotal"
        )
        expression = invoice["body"]["expression"]

        self.assertNotIn("bindings", invoice)
        self.assertEqual(invoice["body"]["source"], "total")
        self.assertEqual(expression["kind"], "let")
        self.assertEqual(expression["name"], "subtotal")
        self.assertEqual(expression["body"]["kind"], "let")
        self.assertEqual(expression["body"]["name"], "total")
        self.assertEqual(expression["body"]["body"], {"kind": "variable", "name": "total"})

        no_bindings = next(
            node for node in ir["nodes"] if node.get("name") == "ServiceFee"
        )
        self.assertNotEqual(no_bindings["body"]["expression"]["kind"], "let")

    def test_examples_boundaries_dependencies_and_format_roundtrip(self) -> None:
        ir = compile_source(EXAMPLE_SOURCE)
        formatted = format_source(
            EXAMPLE_SOURCE.replace("subtotal = price * quantity", "subtotal=price * quantity")
        )

        self.assertTrue(verify_ir(ir)["ok"])
        self.assertEqual(
            run_function(
                ir,
                "InvoiceTotal",
                {"price": 10.0, "quantity": 0, "fee": 2.0},
            )["result"],
            2.0,
        )
        self.assertEqual(format_source(formatted), formatted)
        self.assertIn("  let:\n    subtotal = price * quantity", formatted)
        self.assertEqual(compile_source(formatted)["canonicalHash"], ir["canonicalHash"])

        call_edges = {
            (edge["fromSymbol"], edge["toSymbol"])
            for edge in ir["edges"]
            if edge["kind"] == "calls"
        }
        self.assertIn(
            ("function:TotalWithServiceFee", "function:ServiceFee"), call_edges
        )

    def test_forward_self_and_cross_function_scope_references_are_rejected(self) -> None:
        source = """module InvalidLocalScope

function Forward:
  input:
    value: Integer required
  returns: Integer
  let:
    first = second + 1
    second = value
  body: first

function SelfReference:
  input:
    value: Integer required
  returns: Integer
  let:
    local = local + value
  body: local

function Leaked:
  input:
    value: Integer required
  returns: Integer
  body: local + value
"""

        with self.assertRaises(ValidationError) as context:
            compile_source(source)

        unknown = [
            item
            for item in context.exception.diagnostics
            if item.code == "unknown_function_variable"
        ]
        self.assertTrue(
            any(
                item.path == "/functions/Forward/body/let/first/left"
                and "second" in item.message
                for item in unknown
            )
        )
        self.assertTrue(
            any(
                item.path == "/functions/SelfReference/body/let/local/left"
                and "local" in item.message
                for item in unknown
            )
        )
        self.assertTrue(
            any(
                item.path == "/functions/Leaked/body/left"
                and "local" in item.message
                for item in unknown
            )
        )

    def test_duplicate_shadow_reserved_and_empty_bindings_are_rejected(self) -> None:
        source = """module InvalidBindingNames

function Shadow:
  input:
    value: Integer required
  returns: Integer
  let:
    value = 1
  body: value

function Duplicate:
  returns: Integer
  let:
    local = 1
    local = 2
  body: local

function Reserved:
  returns: Integer
  let:
    true = 1
  body: 1
"""

        with self.assertRaises(ValidationError) as context:
            compile_source(source)

        codes = {item.code for item in context.exception.diagnostics}
        self.assertTrue(
            {
                "function_binding_shadows_input",
                "duplicate_function_binding",
                "reserved_function_binding",
            }
            <= codes
        )

        empty = """module EmptyBinding

function Empty:
  returns: Integer
  let:
  body: 1
"""
        with self.assertRaisesRegex(ParseError, "let section cannot be empty"):
            compile_source(empty)

    def test_initializer_and_body_type_errors_are_reported(self) -> None:
        source = """module InvalidBindingTypes

function InitializerType:
  returns: Integer
  let:
    local = "bad" - 1
  body: 0

function BodyType:
  returns: Integer
  let:
    local = 1
  body: local + "bad"
"""

        with self.assertRaises(ValidationError) as context:
            compile_source(source)

        mismatches = [
            item
            for item in context.exception.diagnostics
            if item.code == "pure_expression_type_mismatch"
        ]
        self.assertEqual(len(mismatches), 2)
        self.assertEqual(
            {item.path for item in mismatches},
            {
                "/functions/InitializerType/body/let/local",
                "/functions/BodyType/body",
            },
        )

    def test_python_runtime_is_eager_once_isolated_and_available_to_actions(self) -> None:
        ir = compile_source(RUNTIME_SOURCE)
        original_invoke = verifier.invoke_function
        probe_calls = 0

        def recording_invoke(function, *args, **kwargs):
            nonlocal probe_calls
            if function["name"] == "Probe":
                probe_calls += 1
            return original_invoke(function, *args, **kwargs)

        with patch.object(verifier, "invoke_function", side_effect=recording_invoke):
            twice = run_function(ir, "Twice", {"value": 4})

        self.assertEqual(twice["result"], 8)
        self.assertEqual(probe_calls, 1)
        self.assertEqual(run_function(ir, "PrototypeName", {"value": 7})["result"], 8)
        self.assertEqual(run_function(ir, "FirstScope", {"value": 1})["result"], 2)
        self.assertEqual(run_function(ir, "SecondScope", {"value": 1})["result"], 3)

        eager = run_function(ir, "UnusedFailure", {"value": 7})
        self.assertFalse(eager["ok"])
        self.assertEqual(eager["errors"][0]["code"], "pure_division_by_zero")

        action = run_action(
            ir,
            "SetAccepted",
            {"id": "metric-1", "value": 100},
            {"Metric": [{"id": "metric-1", "accepted": False}]},
        )
        self.assertTrue(action["ok"])
        self.assertTrue(action["state"]["Metric"][0]["accepted"])

    def test_initializer_calls_participate_in_recursion_detection(self) -> None:
        source = """module InitializerCycle

function Loop:
  input:
    value: Integer required
  returns: Integer
  let:
    next = Loop(value)
  body: next
"""

        with self.assertRaises(ValidationError) as context:
            compile_source(source)

        self.assertIn(
            "recursive_function_cycle",
            {item.code for item in context.exception.diagnostics},
        )

    def test_patch_replace_and_function_rename_preserve_local_names(self) -> None:
        base = """module LocalPatch

function Helper:
  input:
    value: Integer required
  returns: Integer
  body: value * 2
  examples:
    Helper(value=0) equals 0

function Caller:
  input:
    value: Integer required
  returns: Integer
  let:
    Helper = value + 1
    grouped = (Helper)(value)
  body: Helper + grouped
  examples:
    Caller(value=3) equals 10
"""
        replacement = """function Caller:
  input:
    value: Integer required
  returns: Integer
  let:
    Helper = value + 2
    grouped = (Helper)(value)
  body: Helper + grouped
  examples:
    Caller(value=3) equals 11"""
        replace_operation = {
            "kind": "replace_definition",
            "target": "function:Caller",
            "expectedId": node_id(base, "function:Caller"),
            "value": {"source": replacement},
        }
        replaced = plan_patch_source(base, patch_envelope(base, replace_operation))
        self.assertIn("    Helper = value + 2", replaced.source)
        self.assertEqual(
            run_function(compile_source(replaced.source), "Caller", {"value": 3})[
                "result"
            ],
            11,
        )

        rename_operation = {
            "kind": "rename_symbol",
            "target": "function:Helper",
            "expectedId": node_id(replaced.source, "function:Helper"),
            "name": "RenamedHelper",
        }
        renamed = plan_patch_source(
            replaced.source, patch_envelope(replaced.source, rename_operation)
        )
        self.assertIn("    Helper = value + 2", renamed.source)
        self.assertIn("    grouped = (RenamedHelper)(value)", renamed.source)
        self.assertIn("  body: Helper + grouped", renamed.source)
        self.assertEqual(
            run_function(compile_source(renamed.source), "Caller", {"value": 3})[
                "result"
            ],
            11,
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_generated_typescript_runs_examples_and_runtime_regressions(self) -> None:
        example_output = generate_typescript(compile_source(EXAMPLE_SOURCE))
        runtime_output = generate_typescript(compile_source(RUNTIME_SOURCE))
        marker = "export function Probe(input: ProbeInput): number {\n"
        self.assertIn(marker, runtime_output)
        runtime_output = runtime_output.replace(
            marker,
            "let probeCalls = 0;\n"
            "export function getProbeCalls(): number { return probeCalls; }\n\n"
            + marker
            + "  probeCalls += 1;\n",
            1,
        )

        with tempfile.TemporaryDirectory() as directory:
            examples_target = Path(directory) / "local_binding_examples.ts"
            runtime_target = Path(directory) / "local_binding_runtime.ts"
            examples_target.write_text(example_output, encoding="utf-8")
            runtime_target.write_text(runtime_output, encoding="utf-8")
            script = (
                f"const examples=await import({json.dumps(examples_target.as_uri())});"
                f"const runtime=await import({json.dumps(runtime_target.as_uri())});"
                "const results=examples.runIntentIRTests();"
                "if(results.length!==9||results.some(result=>!result.ok))process.exit(1);"
                "if(runtime.Twice({value:4})!==8||runtime.getProbeCalls()!==1)process.exit(2);"
                "if(runtime.PrototypeName({value:7})!==8)process.exit(3);"
                "if(runtime.FirstScope({value:1})!==2||runtime.SecondScope({value:1})!==3)process.exit(4);"
                "let eager=false;try{runtime.UnusedFailure({value:7})}catch(error){eager=String(error).includes('division by zero')}"
                "if(!eager)process.exit(5);"
                "let store={metrics:[{id:'metric-1',accepted:false}]};"
                "store=runtime.SetAccepted(store,{id:'metric-1',value:100});"
                "if(store.metrics[0].accepted!==true)process.exit(6);"
                "console.log(JSON.stringify({examples:results.length,probeCalls:runtime.getProbeCalls()}))"
            )
            completed = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout), {"examples": 9, "probeCalls": 1}
        )


if __name__ == "__main__":
    unittest.main()
