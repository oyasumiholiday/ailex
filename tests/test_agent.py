import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from intentir.agent import TOOL_NAMES, AgentService
from intentir.compiler import compile_path


SOURCE = """
module AgentDemo

entity Item:
  id: UUID required key
  label: Text

action CreateItem:
  input:
    id: UUID required
    label: Text
  effects:
    insert Item

test "creates item":
  when CreateItem(id="item-1", label="first")
  expect Item exists with label "first"
"""


class AgentServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source_path = self.root / "agent.intent"
        self.source_path.write_text(SOURCE, encoding="utf-8")
        self.service = AgentService(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def patch(self) -> dict:
        ir = compile_path(self.source_path)
        entity = next(
            node for node in ir["nodes"] if node["symbol"] == "entity:Item"
        )
        return {
            "schemaVersion": "0.13.0",
            "baseModuleId": ir["moduleId"],
            "operations": [
                {
                    "kind": "insert_member",
                    "target": "entity:Item",
                    "expectedId": entity["id"],
                    "member": "fields",
                    "value": {
                        "name": "priority",
                        "type": "Integer",
                        "default": 0,
                    },
                }
            ],
            "requestedObligations": ["static", "affected-tests"],
        }

    def test_describe_module_and_get_node_are_content_addressed(self) -> None:
        description = self.service.invoke(
            "intentir.describe_module", {"source": "agent.intent"}
        )
        self.assertTrue(description["ok"])
        self.assertEqual(description["module"], "AgentDemo")
        self.assertEqual(description["definitionCounts"]["action"], 1)
        self.assertEqual(description["definitionCounts"]["entity"], 1)
        self.assertTrue(description["moduleId"].startswith("sha256:"))

        node = self.service.invoke(
            "intentir.get_node",
            {"source": "agent.intent", "symbol": "entity:Item"},
        )
        self.assertTrue(node["ok"])
        self.assertEqual(node["node"]["kind"], "entity")
        self.assertIn(
            "action:CreateItem",
            {edge["fromSymbol"] for edge in node["incomingEdges"]},
        )

    def test_context_and_impact_follow_graph_edges(self) -> None:
        context = self.service.invoke(
            "intentir.get_context",
            {
                "source": "agent.intent",
                "symbol": "entity:Item",
                "depth": 2,
                "max_nodes": 20,
            },
        )
        self.assertTrue(context["ok"])
        context_symbols = {node["symbol"] for node in context["nodes"]}
        self.assertIn("action:CreateItem", context_symbols)
        self.assertIn("test:creates-item", context_symbols)

        impact = self.service.invoke(
            "intentir.get_impact",
            {"source": "agent.intent", "symbols": ["entity:Item"]},
        )
        self.assertTrue(impact["ok"])
        self.assertIn("action:CreateItem", impact["affectedSymbols"])
        self.assertIn("test:creates-item", impact["affectedSymbols"])
        self.assertTrue(impact["obligations"])

    def test_patch_validation_diff_apply_and_stale_rejection(self) -> None:
        patch = self.patch()
        validated = self.service.invoke(
            "intentir.validate_patch",
            {"source": "agent.intent", "patch": patch},
        )
        self.assertTrue(validated["ok"])
        self.assertFalse(validated["applied"])
        self.assertNotIn("priority", self.source_path.read_text(encoding="utf-8"))

        rendered = self.service.invoke(
            "intentir.render_diff",
            {"source": "agent.intent", "patch": patch},
        )
        self.assertTrue(rendered["ok"])
        self.assertIn("+  priority: Integer default 0", rendered["diff"])

        disabled = self.service.invoke(
            "intentir.apply_patch",
            {"source": "agent.intent", "patch": patch},
        )
        self.assertFalse(disabled["ok"])
        self.assertEqual(
            disabled["diagnostics"][0]["code"], "write_tool_disabled"
        )

        writable_service = AgentService(self.root, allow_writes=True)
        applied = writable_service.invoke(
            "intentir.apply_patch",
            {"source": "agent.intent", "patch": patch},
        )
        self.assertTrue(applied["ok"])
        self.assertTrue(applied["applied"])
        self.assertIn("priority", self.source_path.read_text(encoding="utf-8"))

        stale = self.service.invoke(
            "intentir.validate_patch",
            {"source": "agent.intent", "patch": patch},
        )
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["diagnostics"][0]["code"], "stale_base_module")

    def test_verify_and_all_build_targets(self) -> None:
        verification = self.service.invoke(
            "intentir.verify", {"source": "agent.intent"}
        )
        self.assertTrue(verification["ok"])
        self.assertEqual(verification["summary"]["tests"], 1)

        ir = self.service.invoke(
            "intentir.build", {"source": "agent.intent", "target": "ir"}
        )
        typescript = self.service.invoke(
            "intentir.build",
            {"source": "agent.intent", "target": "typescript"},
        )
        sqlite = self.service.invoke(
            "intentir.build", {"source": "agent.intent", "target": "sqlite"}
        )
        self.assertEqual(ir["artifact"]["module"], "AgentDemo")
        self.assertIn("runIntentIRTests", typescript["artifact"])
        self.assertIn("CREATE TABLE", sqlite["artifact"])
        self.assertTrue(typescript["artifactId"].startswith("sha256:"))

    def test_project_boundary_and_tool_schema_fail_structurally(self) -> None:
        outside = self.service.invoke(
            "intentir.describe_module", {"source": "../outside.intent"}
        )
        self.assertFalse(outside["ok"])
        self.assertEqual(
            outside["diagnostics"][0]["code"], "source_outside_project_root"
        )

        unknown = self.service.invoke("intentir.unknown", {})
        self.assertFalse(unknown["ok"])
        self.assertEqual(unknown["diagnostics"][0]["code"], "unknown_agent_tool")
        self.assertEqual(tuple(unknown["diagnostics"][0]["scope"]), TOOL_NAMES)

        invalid = self.service.invoke("intentir.get_node", {"source": "agent.intent"})
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["diagnostics"][0]["code"], "invalid_tool_arguments")

    def test_agent_cli_returns_the_same_structured_contract(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "intentir",
                "agent",
                "intentir.describe_module",
                "--root",
                str(self.root),
                "--arguments",
                json.dumps({"source": "agent.intent"}),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["module"], "AgentDemo")


if __name__ == "__main__":
    unittest.main()
