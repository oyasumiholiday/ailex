import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import intentir.notation_lab as notation_lab
from intentir.notation_lab import (
    MAX_INTEGER_BITS,
    MAX_SOURCE_BYTES,
    NotationError,
    decode_graph_json,
    decode_rows_json,
    encode_graph_json,
    encode_rows_json,
    evaluate_expression,
    evaluate_graph,
    expression_to_graph,
    graph_hash,
    graph_to_pure_expression,
    replace_node,
    validate_graph,
)


ROOT = Path(__file__).resolve().parents[1]
DECLARATIONS = {"price": "Integer", "quantity": "Integer", "fee": "Integer"}
VALUES = {"price": 120, "quantity": 3, "fee": 20}


class NotationLabTest(unittest.TestCase):
    def test_source_reader_allows_platforms_without_optional_open_flags(self) -> None:
        class OsWithoutOptionalOpenFlags:
            def __getattr__(self, name: str):
                if name in {"O_NONBLOCK", "O_BINARY"}:
                    raise AttributeError(name)
                return getattr(os, name)

        import os

        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "expression.txt"
            source_path.write_bytes(b"x + 1")
            with patch.object(notation_lab, "os", OsWithoutOptionalOpenFlags()):
                self.assertEqual(notation_lab._read_source(str(source_path)), "x + 1")

    def test_full_and_rows_roundtrip_preserve_graph_and_node_ids(self) -> None:
        graph = expression_to_graph("price * quantity + fee", DECLARATIONS)
        expected_ids = [node["id"] for node in graph["nodes"]]

        full = decode_graph_json(encode_graph_json(graph))
        rows = decode_rows_json(encode_rows_json(graph))

        self.assertEqual(full, graph)
        self.assertEqual(rows, graph)
        self.assertEqual([node["id"] for node in full["nodes"]], expected_ids)
        self.assertEqual([node["id"] for node in rows["nodes"]], expected_ids)
        self.assertEqual(evaluate_graph(full, VALUES), 380)
        self.assertEqual(evaluate_graph(rows, VALUES), 380)

    def test_expression_graph_equivalence_with_boundaries_and_unary(self) -> None:
        cases = [
            ("+x", {"x": 0}, 0),
            ("-x", {"x": -7}, 7),
            ("x - y * -z", {"x": -10, "y": 0, "z": -3}, -10),
            ("x + y", {"x": -(2**100), "y": 2**100 - 1}, -1),
        ]
        for source, inputs, expected in cases:
            with self.subTest(source=source, inputs=inputs):
                declarations = {name: "Integer" for name in inputs}
                graph = expression_to_graph(source, declarations)
                self.assertEqual(evaluate_expression(source, inputs), expected)
                self.assertEqual(evaluate_graph(graph, inputs), expected)

    def test_patch_is_hash_guarded_validated_and_non_mutating(self) -> None:
        graph = expression_to_graph("price * quantity + fee", DECLARATIONS)
        original = deepcopy(graph)
        fee_id = next(
            node["id"]
            for node in graph["nodes"]
            if node["op"] == "input" and node["name"] == "fee"
        )
        patched = replace_node(
            graph,
            fee_id,
            {"type": "Integer", "op": "const", "value": 30},
            graph_hash(graph),
        )

        self.assertEqual(graph, original)
        self.assertIsNot(patched, graph)
        self.assertEqual(evaluate_graph(patched, VALUES), 390)
        self.assertIn("fee", patched["inputs"])
        with self.assertRaisesRegex(NotationError, "current hash") as stale:
            replace_node(patched, fee_id, {"type": "Integer", "op": "const", "value": 40}, graph_hash(graph))
        self.assertEqual(stale.exception.code, "stale_base")
        self.assertEqual(graph, original)

        with self.assertRaises(NotationError):
            replace_node(
                graph,
                fee_id,
                {"id": "different", "type": "Integer", "op": "const", "value": 1},
                graph_hash(graph),
            )
        with self.assertRaises(NotationError):
            replace_node(
                graph,
                fee_id,
                {"type": "Integer", "op": "add", "left": "missing", "right": "missing"},
                graph_hash(graph),
            )
        self.assertEqual(graph, original)

    def test_malformed_graphs_are_rejected(self) -> None:
        graph = expression_to_graph("x + 1", {"x": "Integer"})
        mutations = []

        extra = deepcopy(graph)
        extra["extra"] = True
        mutations.append(extra)
        duplicate = deepcopy(graph)
        duplicate["nodes"][1]["id"] = duplicate["nodes"][0]["id"]
        mutations.append(duplicate)
        forward = deepcopy(graph)
        forward["nodes"][0] = {
            "id": forward["nodes"][0]["id"],
            "type": "Integer",
            "op": "positive",
            "value": forward["nodes"][1]["id"],
        }
        mutations.append(forward)
        wrong_type = deepcopy(graph)
        wrong_type["nodes"][0]["type"] = "Number"
        mutations.append(wrong_type)
        unknown_input = deepcopy(graph)
        unknown_input["nodes"][0]["name"] = "y"
        mutations.append(unknown_input)
        unreachable = deepcopy(graph)
        unreachable["nodes"].append(
            {"id": "unused", "type": "Integer", "op": "const", "value": 4}
        )
        mutations.append(unreachable)

        for candidate in mutations:
            with self.subTest(candidate=candidate):
                with self.assertRaises(NotationError):
                    validate_graph(candidate)

    def test_malformed_json_is_rejected_strictly(self) -> None:
        duplicate = '{"version":1,"version":1,"inputs":{},"nodes":[],"root":"x"}'
        nan = '{"version":1,"inputs":{},"nodes":[{"id":"x","type":"Integer","op":"const","value":NaN}],"root":"x"}'
        extra_row_field = '{"v":1,"i":[],"n":[["x","Integer","const",1,"extra"]],"r":"x"}'

        with self.assertRaises(NotationError) as duplicate_error:
            decode_graph_json(duplicate)
        self.assertEqual(duplicate_error.exception.code, "duplicate_json_key")
        with self.assertRaises(NotationError) as nan_error:
            decode_graph_json(nan)
        self.assertEqual(nan_error.exception.code, "non_finite_json")
        with self.assertRaises(NotationError):
            decode_rows_json(extra_row_field)
        with self.assertRaises(NotationError):
            decode_graph_json("not json")
        huge_integer = (
            '{"version":1,"inputs":{},"nodes":'
            '[{"id":"x","type":"Integer","op":"const","value":'
            + "9" * 5_000
            + '}],"root":"x"}'
        )
        with self.assertRaises(NotationError) as huge_error:
            decode_graph_json(huge_integer)
        self.assertEqual(huge_error.exception.code, "integer_limit")

    def test_limits_cover_source_nodes_depth_expansion_inputs_and_output(self) -> None:
        with patch("intentir.notation_lab.MAX_SOURCE_BYTES", 3):
            with self.assertRaises(NotationError) as source_error:
                expression_to_graph("1 + 2", {})
            self.assertEqual(source_error.exception.code, "source_limit")

        with patch("intentir.notation_lab.MAX_NODES", 2):
            with self.assertRaises(NotationError) as node_error:
                expression_to_graph("1 + 2", {})
            self.assertEqual(node_error.exception.code, "node_limit")

        with patch("intentir.notation_lab.MAX_DEPTH", 2):
            with self.assertRaises(NotationError) as depth_error:
                expression_to_graph("-(1 + 2)", {})
            self.assertEqual(depth_error.exception.code, "depth_limit")

        shared = {
            "version": 1,
            "inputs": {"x": "Integer"},
            "nodes": [{"id": "n0", "type": "Integer", "op": "input", "name": "x"}],
            "root": "n0",
        }
        for index in range(1, 9):
            shared["nodes"].append(
                {
                    "id": f"n{index}",
                    "type": "Integer",
                    "op": "add",
                    "left": f"n{index - 1}",
                    "right": f"n{index - 1}",
                }
            )
            shared["root"] = f"n{index}"
        with patch("intentir.notation_lab.MAX_EXPANDED_NODES", 100):
            with self.assertRaises(NotationError) as expansion_error:
                graph_to_pure_expression(shared)
            self.assertEqual(expansion_error.exception.code, "expansion_limit")

        too_large = 1 << MAX_INTEGER_BITS
        with self.assertRaises(NotationError) as input_error:
            evaluate_expression("x", {"x": too_large})
        self.assertEqual(input_error.exception.code, "integer_limit")
        with self.assertRaises(NotationError) as literal_error:
            expression_to_graph(str(too_large), {})
        self.assertEqual(literal_error.exception.code, "integer_limit")

        with patch("intentir.notation_lab.MAX_OUTPUT_INTEGER_BITS", 4):
            with self.assertRaises(NotationError) as output_error:
                evaluate_expression("x * x", {"x": 8})
            self.assertEqual(output_error.exception.code, "output_limit")

    def test_bool_misuse_and_unsupported_syntax_are_rejected(self) -> None:
        with self.assertRaises(NotationError):
            evaluate_expression("x", {"x": True})
        with self.assertRaises(NotationError):
            validate_graph(
                {
                    "version": 1,
                    "inputs": {},
                    "nodes": [{"id": "n0", "type": "Integer", "op": "const", "value": False}],
                    "root": "n0",
                }
            )
        for source in ("true", "x / 2", "x // 2", "x == 1", "f(x)", "x if true else 0"):
            with self.subTest(source=source):
                with self.assertRaises(NotationError):
                    expression_to_graph(source, {"x": "Integer"})

    def test_runtime_inputs_must_match_declarations_exactly(self) -> None:
        graph = expression_to_graph("x + 1", {"x": "Integer"})
        for inputs in ({}, {"x": 2, "extra": 3}, {"x": 2.0}, {"x": True}):
            with self.subTest(inputs=inputs):
                with self.assertRaises(NotationError):
                    evaluate_graph(graph, inputs)

    def test_cli_demo_and_structured_failure(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "intentir.notation_lab", "demo"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["ok"])
        self.assertTrue(result["equivalent"])
        self.assertEqual(set(result["representations"]), {"expression", "graph-json", "rows-json"})
        self.assertEqual(
            {item["result"] for item in result["representations"].values()},
            {380},
        )
        self.assertEqual(result["patch"]["result"], 390)
        self.assertIn("fee", result["patch"]["inputDeclarationsRemain"])

        failed = subprocess.run(
            [sys.executable, "-m", "intentir.notation_lab", "run", "--format", "bad"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(json.loads(failed.stdout)["error"]["code"], "invalid_arguments")
        self.assertNotIn("Traceback", failed.stderr)

        with tempfile.TemporaryDirectory() as directory:
            non_file = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "intentir.notation_lab",
                    "run",
                    "--format",
                    "expression",
                    "--source",
                    directory,
                    "--inputs",
                    "{}",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(non_file.returncode, 1)
        self.assertEqual(
            json.loads(non_file.stdout)["error"]["code"], "source_read_error"
        )
        self.assertNotIn("Traceback", non_file.stderr)

        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "expression.txt"
            source_path.write_text("x", encoding="utf-8")
            huge_json_integer = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "intentir.notation_lab",
                    "run",
                    "--format",
                    "expression",
                    "--source",
                    str(source_path),
                    "--inputs",
                    '{"x":' + "9" * 5_000 + "}",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            oversized_path = Path(directory) / "oversized.txt"
            oversized_path.write_bytes(b"1" * (MAX_SOURCE_BYTES + 1))
            oversized_source = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "intentir.notation_lab",
                    "run",
                    "--format",
                    "expression",
                    "--source",
                    str(oversized_path),
                    "--inputs",
                    "{}",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(huge_json_integer.returncode, 1)
        self.assertEqual(
            json.loads(huge_json_integer.stdout)["error"]["code"], "integer_limit"
        )
        self.assertNotIn("Traceback", huge_json_integer.stderr)
        self.assertEqual(oversized_source.returncode, 1)
        self.assertEqual(
            json.loads(oversized_source.stdout)["error"]["code"], "source_limit"
        )
        self.assertNotIn("Traceback", oversized_source.stderr)

    def test_run_cli_all_formats(self) -> None:
        graph = expression_to_graph("x * 2 + 1", {"x": "Integer"})
        sources = {
            "expression": "x * 2 + 1",
            "graph-json": encode_graph_json(graph),
            "rows-json": encode_rows_json(graph),
        }
        with tempfile.TemporaryDirectory() as directory:
            for format_name, source in sources.items():
                with self.subTest(format_name=format_name):
                    path = Path(directory) / f"{format_name}.txt"
                    path.write_text(source, encoding="utf-8")
                    completed = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "intentir.notation_lab",
                            "run",
                            "--format",
                            format_name,
                            "--source",
                            str(path),
                            "--inputs",
                            '{"x":4}',
                        ],
                        cwd=ROOT,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(json.loads(completed.stdout)["result"], 9)


if __name__ == "__main__":
    unittest.main()
