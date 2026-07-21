from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Literal, Sequence, TypedDict

from intentir.agent import (
    AgentService,
    BuildSuccess,
    DescribeModuleSuccess,
    GetContextSuccess,
    GetImpactSuccess,
    GetNodeSuccess,
    PatchSuccess,
    RenderDiffSuccess,
    VerifyResult,
)


PatchValue = str | dict[str, Any]


class AddDefinitionInput(TypedDict):
    kind: Literal["add_definition"]
    target: str
    value: PatchValue


class ReplaceDefinitionInput(TypedDict):
    kind: Literal["replace_definition"]
    target: str
    expectedId: str
    value: PatchValue


class RemoveDefinitionInput(TypedDict):
    kind: Literal["remove_definition"]
    target: str
    expectedId: str


class RenameSymbolInput(TypedDict):
    kind: Literal["rename_symbol"]
    target: str
    expectedId: str
    name: str


class SetMemberInput(TypedDict):
    kind: Literal["set_member"]
    target: str
    expectedId: str
    member: str
    value: PatchValue


class InsertMemberInput(TypedDict):
    kind: Literal["insert_member"]
    target: str
    expectedId: str
    member: str
    value: PatchValue


class IndexedInsertMemberInput(TypedDict):
    kind: Literal["insert_member"]
    target: str
    expectedId: str
    member: str
    value: PatchValue
    index: int


class RemoveMemberInput(TypedDict):
    kind: Literal["remove_member"]
    target: str
    expectedId: str
    member: str


PatchOperationInput = (
    AddDefinitionInput
    | ReplaceDefinitionInput
    | RemoveDefinitionInput
    | RenameSymbolInput
    | SetMemberInput
    | InsertMemberInput
    | IndexedInsertMemberInput
    | RemoveMemberInput
)


class PatchEnvelopeInput(TypedDict):
    schemaVersion: Literal["0.13.0"]
    baseModuleId: str
    operations: list[PatchOperationInput]
    requestedObligations: list[Literal["static", "affected-tests", "all-tests"]]


class DescribeModuleEnvelope(TypedDict):
    ok: bool
    result: DescribeModuleSuccess | None
    diagnostics: list[dict[str, Any]]


class GetNodeEnvelope(TypedDict):
    ok: bool
    result: GetNodeSuccess | None
    diagnostics: list[dict[str, Any]]


class GetContextEnvelope(TypedDict):
    ok: bool
    result: GetContextSuccess | None
    diagnostics: list[dict[str, Any]]


class GetImpactEnvelope(TypedDict):
    ok: bool
    result: GetImpactSuccess | None
    diagnostics: list[dict[str, Any]]


class PatchEnvelopeResult(TypedDict):
    ok: bool
    result: PatchSuccess | None
    diagnostics: list[dict[str, Any]]


class VerificationEnvelope(TypedDict):
    ok: bool
    result: VerifyResult | None
    diagnostics: list[dict[str, Any]]


class RenderDiffEnvelope(TypedDict):
    ok: bool
    result: RenderDiffSuccess | None
    diagnostics: list[dict[str, Any]]


class BuildEnvelope(TypedDict):
    ok: bool
    result: BuildSuccess | None
    diagnostics: list[dict[str, Any]]


def mcp_result(result: dict[str, Any]) -> dict[str, Any]:
    if "diagnostics" in result:
        return {"ok": False, "result": None, "diagnostics": result["diagnostics"]}
    return {"ok": True, "result": result, "diagnostics": []}


def create_mcp_server(
    root: Path | str = ".",
    *,
    allow_writes: bool = False,
) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError as error:
        raise RuntimeError(
            "MCP support is optional; install IntentIR with `pip install -e '.[mcp]'`"
        ) from error

    service = AgentService(root, allow_writes=allow_writes)
    server = FastMCP(
        "IntentIR",
        instructions=(
            "Inspect content-addressed IntentIR modules before editing. "
            "Use intentir.validate_patch before intentir.apply_patch. "
            "Every source path is restricted to the configured project root. "
            + (
                "Source writes were explicitly enabled at server startup."
                if allow_writes
                else "Source writes are disabled for this server."
            )
        ),
        json_response=True,
    )
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    write_source = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    )

    @server.tool(name="intentir.describe_module", annotations=read_only)
    def describe_module(source: str) -> DescribeModuleEnvelope:
        """List a module's content IDs, definitions, imports, and obligations."""
        return mcp_result(service.invoke("intentir.describe_module", {"source": source}))

    @server.tool(name="intentir.get_node", annotations=read_only)
    def get_node(source: str, symbol: str) -> GetNodeEnvelope:
        """Return one semantic node with incoming/outgoing edges and obligations."""
        return mcp_result(
            service.invoke(
                "intentir.get_node", {"source": source, "symbol": symbol}
            )
        )

    @server.tool(name="intentir.get_context", annotations=read_only)
    def get_context(
        source: str,
        symbol: str,
        depth: int = 1,
        max_nodes: int = 50,
    ) -> GetContextEnvelope:
        """Return bounded dependency context around one semantic symbol."""
        return mcp_result(
            service.invoke(
                "intentir.get_context",
                {
                    "source": source,
                    "symbol": symbol,
                    "depth": depth,
                    "max_nodes": max_nodes,
                },
            )
        )

    @server.tool(name="intentir.get_impact", annotations=read_only)
    def get_impact(source: str, symbols: list[str]) -> GetImpactEnvelope:
        """Compute reverse-dependency impact and affected verification obligations."""
        return mcp_result(
            service.invoke(
                "intentir.get_impact", {"source": source, "symbols": symbols}
            )
        )

    @server.tool(name="intentir.validate_patch", annotations=read_only)
    def validate_patch(source: str, patch: PatchEnvelopeInput) -> PatchEnvelopeResult:
        """Validate a guarded semantic patch without writing the source file."""
        return mcp_result(
            service.invoke(
                "intentir.validate_patch", {"source": source, "patch": patch}
            )
        )

    @server.tool(name="intentir.apply_patch", annotations=write_source)
    def apply_patch(source: str, patch: PatchEnvelopeInput) -> PatchEnvelopeResult:
        """Atomically write a validated patch; this tool modifies the source file."""
        return mcp_result(
            service.invoke(
                "intentir.apply_patch", {"source": source, "patch": patch}
            )
        )

    @server.tool(name="intentir.verify", annotations=read_only)
    def verify(
        source: str, symbols: list[str] | None = None
    ) -> VerificationEnvelope:
        """Run all tests/examples or a selected set of function/test symbols."""
        return mcp_result(
            service.invoke(
                "intentir.verify", {"source": source, "symbols": symbols}
            )
        )

    @server.tool(name="intentir.render_diff", annotations=read_only)
    def render_diff(source: str, patch: PatchEnvelopeInput) -> RenderDiffEnvelope:
        """Render the verified human-readable diff for a semantic patch."""
        return mcp_result(
            service.invoke(
                "intentir.render_diff", {"source": source, "patch": patch}
            )
        )

    @server.tool(name="intentir.build", annotations=read_only)
    def build(
        source: str,
        target: Literal["ir", "typescript", "sqlite"] = "ir",
    ) -> BuildEnvelope:
        """Build IR JSON, TypeScript, or deterministic SQLite DDL in memory."""
        return mcp_result(
            service.invoke(
                "intentir.build", {"source": source, "target": target}
            )
        )

    return server


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="intentir-mcp",
        description="Serve IntentIR agent tools over local MCP stdio.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="project root that bounds all source access",
    )
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="explicitly enable intentir.apply_patch source writes",
    )
    args = parser.parse_args(argv)
    try:
        server = create_mcp_server(args.root, allow_writes=args.allow_writes)
    except RuntimeError as error:
        parser.error(str(error))
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
