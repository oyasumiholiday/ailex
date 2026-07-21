from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from intentir.agent import AgentService


DEMO_SOURCE = """\
module ConcurrentAgentDemo

entity WorkItem:
  id: UUID required key
  title: Text required
  status: Text default "open"

action CreateWorkItem:
  input:
    id: UUID required
    title: Text required
  effects:
    insert WorkItem

test "creates work item":
  when CreateWorkItem(id="item-1", title="first")
  expect WorkItem exists with title "first"
"""


class ConcurrentAgentDemoError(RuntimeError):
    """Raised when the demo cannot establish one of its expected guarantees."""


def run_concurrent_agent_demo() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="intentir-concurrent-agent-") as directory:
        root = Path(directory)
        source_path = root / "workspace.intent"
        source_path.write_text(DEMO_SOURCE, encoding="utf-8")

        reader = AgentService(root)
        writer = AgentService(root, allow_writes=True)
        source = source_path.name

        initial = _require_ok(
            reader.invoke("intentir.describe_module", {"source": source}),
            "read the shared module snapshot",
        )
        initial_node = _require_ok(
            reader.invoke(
                "intentir.get_node",
                {"source": source, "symbol": "entity:WorkItem"},
            ),
            "read the shared WorkItem node",
        )

        patch_a = _insert_field_patch(
            initial["moduleId"],
            initial_node["node"]["id"],
            name="priority",
            field_type="Integer",
            default=0,
        )
        patch_b = _insert_field_patch(
            initial["moduleId"],
            initial_node["node"]["id"],
            name="owner",
            field_type="Text",
            default="unassigned",
        )

        preview_a = _require_ok(
            reader.invoke(
                "intentir.validate_patch", {"source": source, "patch": patch_a}
            ),
            "validate Agent A's patch",
        )
        preview_b = _require_ok(
            reader.invoke(
                "intentir.validate_patch", {"source": source, "patch": patch_b}
            ),
            "validate Agent B's initial patch",
        )

        applied_a = _require_ok(
            writer.invoke(
                "intentir.apply_patch", {"source": source, "patch": patch_a}
            ),
            "apply Agent A's patch",
        )

        stale_b = writer.invoke(
            "intentir.apply_patch", {"source": source, "patch": patch_b}
        )
        stale_code = _require_stale_rejection(stale_b)

        refreshed = _require_ok(
            reader.invoke("intentir.describe_module", {"source": source}),
            "refresh the module after Agent A",
        )
        refreshed_node = _require_ok(
            reader.invoke(
                "intentir.get_node",
                {"source": source, "symbol": "entity:WorkItem"},
            ),
            "refresh the WorkItem node after Agent A",
        )
        rebased_patch_b = _insert_field_patch(
            refreshed["moduleId"],
            refreshed_node["node"]["id"],
            name="owner",
            field_type="Text",
            default="unassigned",
        )
        rebased_preview_b = _require_ok(
            reader.invoke(
                "intentir.validate_patch",
                {"source": source, "patch": rebased_patch_b},
            ),
            "validate Agent B's refreshed patch",
        )
        applied_b = _require_ok(
            writer.invoke(
                "intentir.apply_patch",
                {"source": source, "patch": rebased_patch_b},
            ),
            "apply Agent B's refreshed patch",
        )

        final_module = _require_ok(
            reader.invoke("intentir.describe_module", {"source": source}),
            "read the final module",
        )
        final_node = _require_ok(
            reader.invoke(
                "intentir.get_node",
                {"source": source, "symbol": "entity:WorkItem"},
            ),
            "read the final WorkItem node",
        )
        verification = _require_ok(
            reader.invoke("intentir.verify", {"source": source}),
            "verify the final module",
        )
        typescript = _require_ok(
            reader.invoke(
                "intentir.build", {"source": source, "target": "typescript"}
            ),
            "build the final TypeScript artifact",
        )
        sqlite = _require_ok(
            reader.invoke(
                "intentir.build", {"source": source, "target": "sqlite"}
            ),
            "build the final SQLite artifact",
        )

        fields = sorted(field["name"] for field in final_node["node"]["fields"])
        if "priority" not in fields or "owner" not in fields:
            raise ConcurrentAgentDemoError(
                "both independently proposed fields must exist after rebasing"
            )
        if not verification["ok"]:
            raise ConcurrentAgentDemoError("final verification did not pass")

        return {
            "ok": True,
            "demo": "concurrent-agent",
            "schemaVersion": "0.1.0",
            "sharedSnapshot": {
                "moduleId": initial["moduleId"],
                "target": "entity:WorkItem",
                "targetId": initial_node["node"]["id"],
            },
            "agentA": {
                "intent": "add priority with a deterministic default",
                "patchId": preview_a["patchId"],
                "baseModuleId": preview_a["baseModuleId"],
                "resultModuleId": applied_a["resultModuleId"],
                "diff": _portable_diff(preview_a["diff"]),
                "applied": applied_a["applied"],
            },
            "agentBInitial": {
                "intent": "add an owner with a deterministic default",
                "patchId": preview_b["patchId"],
                "baseModuleId": preview_b["baseModuleId"],
                "rejected": True,
                "diagnosticCode": stale_code,
            },
            "agentBRebased": {
                "patchId": rebased_preview_b["patchId"],
                "baseModuleId": rebased_preview_b["baseModuleId"],
                "resultModuleId": applied_b["resultModuleId"],
                "diff": _portable_diff(rebased_preview_b["diff"]),
                "applied": applied_b["applied"],
            },
            "final": {
                "moduleId": final_module["moduleId"],
                "fields": fields,
                "verification": verification["summary"],
                "artifacts": {
                    "typescript": typescript["artifactId"],
                    "sqlite": sqlite["artifactId"],
                },
            },
        }


def render_concurrent_agent_demo(result: dict[str, Any]) -> str:
    shared = result["sharedSnapshot"]
    agent_a = result["agentA"]
    agent_b_initial = result["agentBInitial"]
    agent_b_rebased = result["agentBRebased"]
    final = result["final"]
    summary = final["verification"]
    return "\n".join(
        [
            "IntentIR concurrent-agent demo",
            "",
            f"1. Shared snapshot       {_short_id(shared['moduleId'])}",
            f"2. Agent A applied       {_short_id(agent_a['resultModuleId'])}",
            (
                "3. Agent B stale patch  PASS rejected with "
                f"{agent_b_initial['diagnosticCode']}"
            ),
            f"4. Agent B refreshed     {_short_id(agent_b_rebased['baseModuleId'])}",
            f"5. Agent B applied       {_short_id(agent_b_rebased['resultModuleId'])}",
            (
                "6. Final verification   PASS "
                f"{summary['passed']}/{summary['tests']} tests"
            ),
            "",
            "Final WorkItem fields: " + ", ".join(final["fields"]),
            "",
            "Agent A diff:",
            agent_a["diff"].rstrip(),
            "",
            "Agent B rebased diff:",
            agent_b_rebased["diff"].rstrip(),
            "",
            "RESULT: PASS",
            "",
        ]
    )


def _insert_field_patch(
    module_id: str,
    target_id: str,
    *,
    name: str,
    field_type: str,
    default: Any,
) -> dict[str, Any]:
    return {
        "schemaVersion": "0.13.0",
        "baseModuleId": module_id,
        "operations": [
            {
                "kind": "insert_member",
                "target": "entity:WorkItem",
                "expectedId": target_id,
                "member": "fields",
                "value": {
                    "name": name,
                    "type": field_type,
                    "default": default,
                },
            }
        ],
        "requestedObligations": ["static", "affected-tests"],
    }


def _require_ok(result: dict[str, Any], action: str) -> dict[str, Any]:
    if result.get("ok"):
        return result
    codes = [item.get("code", "unknown") for item in result.get("diagnostics", [])]
    raise ConcurrentAgentDemoError(f"could not {action}: {', '.join(codes)}")


def _require_stale_rejection(result: dict[str, Any]) -> str:
    if result.get("ok"):
        raise ConcurrentAgentDemoError("Agent B's stale patch was unexpectedly accepted")
    codes = [item.get("code") for item in result.get("diagnostics", [])]
    if "stale_base_module" not in codes:
        raise ConcurrentAgentDemoError(
            "Agent B's stale patch failed without stale_base_module"
        )
    return "stale_base_module"


def _short_id(identifier: str) -> str:
    prefix, separator, digest = identifier.partition(":")
    if not separator:
        return identifier
    return f"{prefix}:{digest[:12]}"


def _portable_diff(diff: str) -> str:
    lines = diff.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("--- "):
            lines[index] = "--- workspace.intent\n"
        elif line.startswith("+++ "):
            lines[index] = "+++ workspace.intent.patched\n"
    return "".join(lines)
