import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from intentir.compiler import compile_path

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


SOURCE = """
module McpDemo

entity Item:
  id: UUID required key
"""


@unittest.skipUnless(MCP_AVAILABLE, "install the optional mcp dependency")
class MCPServerTest(unittest.TestCase):
    def test_stdio_discovery_and_structured_tool_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "mcp.intent"
            source_path.write_text(SOURCE, encoding="utf-8")
            ir = compile_path(source_path)
            entity = next(
                node for node in ir["nodes"] if node["symbol"] == "entity:Item"
            )
            patch = {
                "schemaVersion": "0.13.0",
                "baseModuleId": ir["moduleId"],
                "operations": [
                    {
                        "kind": "insert_member",
                        "target": "entity:Item",
                        "expectedId": entity["id"],
                        "member": "fields",
                        "value": {
                            "name": "label",
                            "type": "Text",
                        },
                    }
                ],
                "requestedObligations": ["static"],
            }

            async def scenario():
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=[
                        "-m",
                        "intentir.mcp_server",
                        "--root",
                        str(root),
                    ],
                )
                async with stdio_client(parameters) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        result = await session.call_tool(
                            "intentir.describe_module",
                            {"source": "mcp.intent"},
                        )
                        failure = await session.call_tool(
                            "intentir.get_node",
                            {"source": "mcp.intent", "symbol": "entity:Missing"},
                        )
                        patch_result = await session.call_tool(
                            "intentir.validate_patch",
                            {"source": "mcp.intent", "patch": patch},
                        )
                        apply_result = await session.call_tool(
                            "intentir.apply_patch",
                            {"source": "mcp.intent", "patch": patch},
                        )
                        return listed, result, failure, patch_result, apply_result

            listed, result, failure, patch_result, apply_result = asyncio.run(
                scenario()
            )
            names = {tool.name for tool in listed.tools}
            self.assertEqual(len(names), 9)
            self.assertIn("intentir.validate_patch", names)
            self.assertIn("intentir.apply_patch", names)
            validate_tool = next(
                tool
                for tool in listed.tools
                if tool.name == "intentir.validate_patch"
            )
            self.assertEqual(
                validate_tool.inputSchema["properties"]["patch"]["$ref"],
                "#/$defs/PatchEnvelopeInput",
            )
            self.assertTrue(validate_tool.annotations.readOnlyHint)
            apply_tool = next(
                tool for tool in listed.tools if tool.name == "intentir.apply_patch"
            )
            self.assertTrue(apply_tool.annotations.destructiveHint)
            self.assertFalse(apply_tool.annotations.readOnlyHint)
            self.assertFalse(result.isError, result)
            self.assertIsNotNone(result.structuredContent)
            self.assertTrue(result.structuredContent["ok"], result.structuredContent)
            self.assertEqual(
                result.structuredContent["result"]["module"], "McpDemo"
            )
            self.assertFalse(failure.isError, failure)
            self.assertFalse(failure.structuredContent["ok"])
            self.assertEqual(
                failure.structuredContent["diagnostics"][0]["code"],
                "unknown_symbol",
            )
            self.assertFalse(patch_result.isError, patch_result)
            self.assertTrue(patch_result.structuredContent["ok"])
            self.assertFalse(
                patch_result.structuredContent["result"]["applied"]
            )
            self.assertFalse(apply_result.isError, apply_result)
            self.assertFalse(apply_result.structuredContent["ok"])
            self.assertEqual(
                apply_result.structuredContent["diagnostics"][0]["code"],
                "write_tool_disabled",
            )
            self.assertNotIn("label", source_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
