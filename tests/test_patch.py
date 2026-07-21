import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from intentir.compiler import compile_source
from intentir.patch import PatchError, plan_patch_source


SOURCE = """
module PatchDemo

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


def envelope(source: str, operations: list[dict], obligations=None) -> dict:
    ir = compile_source(source)
    return {
        "schemaVersion": "0.13.0",
        "baseModuleId": ir["moduleId"],
        "operations": operations,
        "requestedObligations": obligations or ["static"],
    }


def node_id(source: str, symbol: str) -> str:
    ir = compile_source(source)
    return next(node["id"] for node in ir["nodes"] if node["symbol"] == symbol)


class PatchTest(unittest.TestCase):
    def test_definition_operations_are_content_guarded(self) -> None:
        add = envelope(
            SOURCE,
            [
                {
                    "kind": "add_definition",
                    "target": "entity:Note",
                    "value": {"source": "entity Note:\n  id: UUID required key"},
                }
            ],
        )
        added = plan_patch_source(SOURCE, add)
        self.assertIn("entity Note:", added.source)

        replace_patch = envelope(
            added.source,
            [
                {
                    "kind": "replace_definition",
                    "target": "entity:Note",
                    "expectedId": node_id(added.source, "entity:Note"),
                    "value": {
                        "source": "entity Note:\n  id: UUID required key\n  body: Text"
                    },
                }
            ],
        )
        replaced = plan_patch_source(added.source, replace_patch)
        self.assertIn("body: Text", replaced.source)

        rename_patch = envelope(
            replaced.source,
            [
                {
                    "kind": "rename_symbol",
                    "target": "entity:Note",
                    "expectedId": node_id(replaced.source, "entity:Note"),
                    "name": "Memo",
                }
            ],
        )
        renamed = plan_patch_source(replaced.source, rename_patch)
        self.assertIn("entity Memo:", renamed.source)
        self.assertIn("entity:Note", renamed.result["changedSymbols"])
        self.assertIn("entity:Memo", renamed.result["changedSymbols"])

        remove_patch = envelope(
            renamed.source,
            [
                {
                    "kind": "remove_definition",
                    "target": "entity:Memo",
                    "expectedId": node_id(renamed.source, "entity:Memo"),
                }
            ],
        )
        removed = plan_patch_source(renamed.source, remove_patch)
        self.assertNotIn("entity Memo:", removed.source)

    def test_member_operations_apply_as_one_transaction(self) -> None:
        item_id = node_id(SOURCE, "entity:Item")
        patch = envelope(
            SOURCE,
            [
                {
                    "kind": "insert_member",
                    "target": "entity:Item",
                    "expectedId": item_id,
                    "member": "fields",
                    "value": {"name": "priority", "type": "Integer", "default": 0},
                },
                {
                    "kind": "set_member",
                    "target": "entity:Item",
                    "expectedId": item_id,
                    "member": "fields.label",
                    "value": {"source": 'label: Text default "untitled"'},
                },
            ],
            ["affected-tests"],
        )

        first = plan_patch_source(SOURCE, patch)
        second = plan_patch_source(SOURCE, patch)

        self.assertIn('label: Text default "untitled"', first.source)
        self.assertIn("priority: Integer default 0", first.source)
        self.assertEqual(first.result["patchId"], second.result["patchId"])
        self.assertEqual(first.result["resultModuleId"], second.result["resultModuleId"])
        self.assertIn("test:creates-item", first.result["affectedSymbols"])
        self.assertNotEqual(first.result["executedObligations"], ["static"])

        removal = envelope(
            first.source,
            [
                {
                    "kind": "remove_member",
                    "target": "entity:Item",
                    "expectedId": node_id(first.source, "entity:Item"),
                    "member": "fields.priority",
                }
            ],
        )
        removed = plan_patch_source(first.source, removal)
        self.assertNotIn("priority: Integer", removed.source)

    def test_rename_updates_semantic_references(self) -> None:
        patch = envelope(
            SOURCE,
            [
                {
                    "kind": "rename_symbol",
                    "target": "action:CreateItem",
                    "expectedId": node_id(SOURCE, "action:CreateItem"),
                    "name": "AddItem",
                }
            ],
            ["affected-tests"],
        )

        plan = plan_patch_source(SOURCE, patch)

        self.assertIn("action AddItem:", plan.source)
        self.assertIn('when AddItem(id="item-1", label="first")', plan.source)
        self.assertIn("test:creates-item", plan.result["changedSymbols"])

    def test_stale_module_and_node_are_rejected(self) -> None:
        stale_module = envelope(
            SOURCE,
            [
                {
                    "kind": "remove_definition",
                    "target": "entity:Item",
                    "expectedId": node_id(SOURCE, "entity:Item"),
                }
            ],
        )
        stale_module["baseModuleId"] = "sha256:" + "0" * 64
        with self.assertRaises(PatchError) as module_context:
            plan_patch_source(SOURCE, stale_module)
        self.assertEqual(
            module_context.exception.diagnostics[0].code, "stale_base_module"
        )

        stale_node = envelope(
            SOURCE,
            [
                {
                    "kind": "set_member",
                    "target": "entity:Item",
                    "expectedId": "sha256:" + "0" * 64,
                    "member": "fields.label",
                    "value": {"source": "label: Text required"},
                }
            ],
        )
        with self.assertRaises(PatchError) as node_context:
            plan_patch_source(SOURCE, stale_node)
        self.assertEqual(node_context.exception.diagnostics[0].code, "stale_target_node")

        unknown_field = envelope(
            SOURCE,
            [
                {
                    "kind": "remove_definition",
                    "target": "entity:Item",
                    "expectedId": node_id(SOURCE, "entity:Item"),
                    "secret": "must-not-enter-the-patch",
                }
            ],
        )
        with self.assertRaises(PatchError) as field_context:
            plan_patch_source(SOURCE, unknown_field)
        self.assertEqual(
            field_context.exception.diagnostics[0].code,
            "unknown_patch_operation_field",
        )

    def test_invalid_result_rolls_back_the_whole_patch(self) -> None:
        patch = envelope(
            SOURCE,
            [
                {
                    "kind": "insert_member",
                    "target": "entity:Item",
                    "expectedId": node_id(SOURCE, "entity:Item"),
                    "member": "fields",
                    "value": {"source": "priority: Integer default 0"},
                },
                {
                    "kind": "remove_definition",
                    "target": "action:CreateItem",
                    "expectedId": node_id(SOURCE, "action:CreateItem"),
                },
            ],
        )

        with self.assertRaises(PatchError) as context:
            plan_patch_source(SOURCE, patch)

        self.assertIn(
            "unknown_action",
            {diagnostic.code for diagnostic in context.exception.diagnostics},
        )
        self.assertNotIn("priority: Integer", SOURCE)

    def test_requested_affected_tests_can_reject_a_patch(self) -> None:
        patch = envelope(
            SOURCE,
            [
                {
                    "kind": "set_member",
                    "target": "action:CreateItem",
                    "expectedId": node_id(SOURCE, "action:CreateItem"),
                    "member": "effects.0",
                    "value": {"source": "delete Item where id equals input.id"},
                }
            ],
            ["affected-tests"],
        )

        with self.assertRaises(PatchError) as context:
            plan_patch_source(SOURCE, patch)

        self.assertEqual(
            context.exception.diagnostics[0].code, "patch_obligation_failed"
        )

    def test_patch_cli_is_dry_run_by_default_and_applies_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "app.intent"
            patch_path = root / "patch.json"
            source_path.write_text(SOURCE, encoding="utf-8")
            patch = envelope(
                SOURCE,
                [
                    {
                        "kind": "insert_member",
                        "target": "entity:Item",
                        "expectedId": node_id(SOURCE, "entity:Item"),
                        "member": "fields",
                        "value": {"source": "priority: Integer default 0"},
                    }
                ],
            )
            patch_path.write_text(json.dumps(patch), encoding="utf-8")

            dry_run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "intentir",
                    "patch",
                    str(source_path),
                    str(patch_path),
                    "--json",
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            self.assertFalse(json.loads(dry_run.stdout)["applied"])
            self.assertNotIn("priority: Integer", source_path.read_text(encoding="utf-8"))

            applied = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "intentir",
                    "patch",
                    str(source_path),
                    str(patch_path),
                    "--apply",
                    "--json",
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertTrue(json.loads(applied.stdout)["applied"])
            self.assertIn("priority: Integer default 0", source_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
