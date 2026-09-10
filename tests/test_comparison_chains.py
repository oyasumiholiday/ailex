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
from intentir.pure import parse_pure_expression
from intentir.validator import ValidationError
from intentir.verifier import run_action, run_function, verify_ir


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_SOURCE = (ROOT / "examples" / "comparison_chains.intent").read_text(
    encoding="utf-8"
)

SINGLE_COMPARISON_SOURCE = """module SingleComparison

function IsPositive:
  input:
    value: Integer required
  returns: Boolean
  body: value > 0
  examples:
    IsPositive(value=0) equals false
"""

RUNTIME_SOURCE = """module ComparisonChainRuntime

function operand0:
  input:
    value: Integer required
  returns: Integer
  body: value - 1

function Middle:
  input:
    value: Integer required
  returns: Integer
  body: value

function Right:
  input:
    value: Integer required
  returns: Integer
  body: value + 1

function OrderedOnce:
  input:
    value: Integer required
  returns: Boolean
  body: operand0(value) < Middle(value) < Right(value)

function Guarded:
  input:
    value: Integer required
  returns: Boolean
  body: 0 > value > (1 // 0)
  examples:
    Guarded(value=0) equals false

entity Metric:
  id: UUID required key
  accepted: Boolean required

action SetAccepted:
  input:
    id: UUID required
    value: Integer required
  effects:
    update Metric where id equals input.id set accepted = 0 <= value <= 100
"""


class ComparisonChainTest(unittest.TestCase):
    def test_lowering_is_explicit_and_preserves_single_comparison_hashes(self) -> None:
        single = parse_pure_expression("value > 0")
        chain = parse_pure_expression("0 <= value <= 100")

        self.assertEqual(
            single,
            {
                "kind": "comparison",
                "op": "greater_than",
                "left": {"kind": "variable", "name": "value"},
                "right": {"kind": "literal", "type": "Integer", "value": 0},
            },
        )
        self.assertEqual(
            chain,
            {
                "kind": "comparison_chain",
                "operands": [
                    {"kind": "literal", "type": "Integer", "value": 0},
                    {"kind": "variable", "name": "value"},
                    {"kind": "literal", "type": "Integer", "value": 100},
                ],
                "operators": ["less_than_or_equal", "less_than_or_equal"],
            },
        )

        ir = compile_source(SINGLE_COMPARISON_SOURCE)
        function = next(node for node in ir["nodes"] if node["kind"] == "function")
        self.assertEqual(
            function["body"]["id"],
            "sha256:938469848899e86a346ff75a48fd3100348a75a024f33a493cbafe4a1bf49093",
        )
        self.assertEqual(
            function["id"],
            "sha256:a3031a1dcc5a6afc2c7ebac6df306e54597d78a07d06ebdc4a22af1ead14b9a2",
        )
        self.assertEqual(
            ir["canonicalHash"],
            "sha256:94078d012a68003b40e5fbe9e1214fddca5d4c9dbb106e9b4da9016ae4577c2b",
        )

    def test_boundaries_mixed_operators_dependencies_and_format_hashes(self) -> None:
        ir = compile_source(EXAMPLE_SOURCE)

        self.assertTrue(verify_ir(ir)["ok"])
        self.assertTrue(run_function(ir, "IsPercentage", {"value": 0})["result"])
        self.assertTrue(run_function(ir, "IsPercentage", {"value": 100})["result"])
        self.assertFalse(run_function(ir, "IsPercentage", {"value": 101})["result"])
        self.assertTrue(run_function(ir, "MixedChain", {"value": 49})["result"])
        self.assertFalse(run_function(ir, "MixedChain", {"value": 50})["result"])

        call_edges = {
            (edge["fromSymbol"], edge["toSymbol"])
            for edge in ir["edges"]
            if edge["kind"] == "calls"
        }
        self.assertTrue(
            {
                ("function:OrderedAround", "function:Lower"),
                ("function:OrderedAround", "function:Middle"),
                ("function:OrderedAround", "function:Upper"),
            }
            <= call_edges
        )

        untidy = EXAMPLE_SOURCE.replace(
            "body: 0 <= value <= 100", "body:    0 <= value <= 100"
        )
        formatted = format_source(untidy)
        self.assertEqual(format_source(formatted), formatted)
        self.assertEqual(compile_source(untidy)["canonicalHash"], ir["canonicalHash"])
        self.assertEqual(compile_source(formatted)["canonicalHash"], ir["canonicalHash"])

    def test_type_checker_validates_each_adjacent_pair(self) -> None:
        source = """module InvalidComparisonChain

function Invalid:
  input:
    value: Integer required
  returns: Boolean
  body: "left" < value < true
"""

        with self.assertRaises(ValidationError) as context:
            compile_source(source)

        mismatches = [
            diagnostic
            for diagnostic in context.exception.diagnostics
            if diagnostic.code == "pure_expression_type_mismatch"
        ]
        self.assertEqual(len(mismatches), 2)
        self.assertEqual(
            {diagnostic.path for diagnostic in mismatches},
            {
                "/functions/Invalid/body/operators/0",
                "/functions/Invalid/body/operators/1",
            },
        )
        self.assertTrue(all("less_than" in item.message for item in mismatches))

    def test_python_runtime_short_circuits_and_evaluates_middle_once(self) -> None:
        ir = compile_source(RUNTIME_SOURCE)
        original_invoke = verifier.invoke_function
        call_order: list[str] = []

        def recording_invoke(function, *args, **kwargs):
            if function["name"] in {"operand0", "Middle", "Right"}:
                call_order.append(function["name"])
            return original_invoke(function, *args, **kwargs)

        with patch.object(verifier, "invoke_function", side_effect=recording_invoke):
            ordered = run_function(ir, "OrderedOnce", {"value": 50})

        self.assertTrue(ordered["result"])
        self.assertEqual(call_order, ["operand0", "Middle", "Right"])
        self.assertEqual(call_order.count("Middle"), 1)

        short_circuited = run_function(ir, "Guarded", {"value": 0})
        reached = run_function(ir, "Guarded", {"value": -1})
        self.assertEqual(short_circuited["result"], False)
        self.assertFalse(reached["ok"])
        self.assertEqual(reached["errors"][0]["code"], "pure_division_by_zero")

        updated = run_action(
            ir,
            "SetAccepted",
            {"id": "metric-1", "value": 100},
            {"Metric": [{"id": "metric-1", "accepted": False}]},
        )
        self.assertTrue(updated["ok"])
        self.assertTrue(updated["state"]["Metric"][0]["accepted"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_generated_typescript_runs_all_example_contracts(self) -> None:
        output = generate_typescript(compile_source(EXAMPLE_SOURCE))

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "comparison_chain_examples.ts"
            target.write_text(output, encoding="utf-8")
            script = (
                f"import({json.dumps(target.as_uri())}).then(m=>{{"
                "const results=m.runIntentIRTests();"
                "console.log(JSON.stringify(results));"
                "if(results.length===0||results.some(result=>!result.ok))process.exit(1)"
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
        self.assertEqual(len(results), 24)
        self.assertTrue(all(result["ok"] for result in results))

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_generated_typescript_matches_order_short_circuit_and_action_use(self) -> None:
        output = generate_typescript(compile_source(RUNTIME_SOURCE))
        marker = "export function Middle(input: MiddleInput): number {\n"
        self.assertIn(marker, output)
        output = output.replace(
            marker,
            "let middleCalls = 0;\n"
            "export function getMiddleCalls(): number { return middleCalls; }\n\n"
            + marker
            + "  middleCalls += 1;\n",
            1,
        )

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "comparison_chains.ts"
            target.write_text(output, encoding="utf-8")
            script = (
                f"import({json.dumps(target.as_uri())}).then(m=>{{"
                "if(m.OrderedOnce({value:50})!==true||m.getMiddleCalls()!==1)process.exit(1);"
                "if(m.Guarded({value:0})!==false)process.exit(2);"
                "let reached=false;try{m.Guarded({value:-1})}catch(e){reached=String(e).includes('division by zero')}"
                "if(!reached)process.exit(3);"
                "let s={metrics:[{id:'metric-1',accepted:false}]};"
                "s=m.SetAccepted(s,{id:'metric-1',value:100});"
                "if(s.metrics[0].accepted!==true)process.exit(4);"
                "console.log(JSON.stringify({middleCalls:m.getMiddleCalls(),accepted:s.metrics[0].accepted}))"
                "})"
            )
            completed = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout), {"middleCalls": 1, "accepted": True}
        )


if __name__ == "__main__":
    unittest.main()
