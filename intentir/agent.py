from __future__ import annotations

import inspect
from collections import Counter, deque
from pathlib import Path
from typing import Any, Callable, Literal, TypedDict

from intentir.canonical import content_address
from intentir.compiler import compile_path
from intentir.generators.typescript import generate_typescript
from intentir.patch import PatchError, patch_path, plan_patch_path
from intentir.parser import ParseError
from intentir.sqlite_projection import render_sqlite_ddl
from intentir.storage import storage_schema
from intentir.validator import ValidationError
from intentir.verifier import verify_ir


TOOL_NAMES = (
    "intentir.describe_module",
    "intentir.get_node",
    "intentir.get_context",
    "intentir.get_impact",
    "intentir.validate_patch",
    "intentir.apply_patch",
    "intentir.verify",
    "intentir.render_diff",
    "intentir.build",
)


AgentToolResult = dict[str, Any]


class AgentFailureResult(TypedDict):
    ok: Literal[False]
    diagnostics: list[dict[str, Any]]


class DescribeModuleSuccess(TypedDict):
    ok: Literal[True]
    source: str
    schemaVersion: str
    module: str
    moduleId: str
    canonicalHash: str
    modules: list[dict[str, Any]]
    definitions: list[dict[str, Any]]
    definitionCounts: dict[str, int]
    edgeCount: int
    obligationCounts: dict[str, int]


class GetNodeSuccess(TypedDict):
    ok: Literal[True]
    source: str
    moduleId: str
    node: dict[str, Any]
    incomingEdges: list[dict[str, Any]]
    outgoingEdges: list[dict[str, Any]]
    obligations: list[dict[str, Any]]


class GetContextSuccess(TypedDict):
    ok: Literal[True]
    source: str
    moduleId: str
    rootSymbol: str
    depth: int
    truncated: bool
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    obligations: list[dict[str, Any]]


class GetImpactSuccess(TypedDict):
    ok: Literal[True]
    source: str
    moduleId: str
    seedSymbols: list[str]
    affectedSymbols: list[str]
    obligations: list[dict[str, Any]]


class PatchSuccess(TypedDict):
    ok: Literal[True]
    source: str
    schemaVersion: str
    patchId: str
    module: str
    baseModuleId: str
    resultModuleId: str
    baseCanonicalHash: str
    resultCanonicalHash: str
    changedSymbols: list[str]
    affectedSymbols: list[str]
    requestedObligations: list[str]
    executedObligations: list[str]
    diff: str
    applied: bool


class VerifyResult(TypedDict):
    ok: bool
    source: str
    moduleId: str
    canonicalHash: str
    summary: dict[str, Any]
    tests: list[dict[str, Any]]
    functionExamples: list[dict[str, Any]]


class RenderDiffSuccess(TypedDict):
    ok: Literal[True]
    source: str
    patchId: str
    baseModuleId: str
    resultModuleId: str
    changedSymbols: list[str]
    affectedSymbols: list[str]
    diff: str


class BuildSuccess(TypedDict):
    ok: Literal[True]
    source: str
    moduleId: str
    target: str
    artifactId: str
    artifact: Any


DescribeModuleResult = DescribeModuleSuccess | AgentFailureResult
GetNodeResult = GetNodeSuccess | AgentFailureResult
GetContextResult = GetContextSuccess | AgentFailureResult
GetImpactResult = GetImpactSuccess | AgentFailureResult
PatchResult = PatchSuccess | AgentFailureResult
VerificationToolResult = VerifyResult | AgentFailureResult
RenderDiffResult = RenderDiffSuccess | AgentFailureResult
BuildResult = BuildSuccess | AgentFailureResult


class AgentServiceError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        message_ja: str,
        path: str,
        *,
        scope: tuple[str, ...] = (),
        hint: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.message_ja = message_ja
        self.path = path
        self.scope = scope
        self.hint = hint
        super().__init__(message)


class AgentService:
    """Model-independent structured tools over one bounded project root."""

    def __init__(
        self,
        root: Path | str = ".",
        *,
        allow_writes: bool = False,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.allow_writes = allow_writes
        self._tools: dict[str, Callable[..., AgentToolResult]] = {
            "intentir.describe_module": self.describe_module,
            "intentir.get_node": self.get_node,
            "intentir.get_context": self.get_context,
            "intentir.get_impact": self.get_impact,
            "intentir.validate_patch": self.validate_patch,
            "intentir.apply_patch": self.apply_patch,
            "intentir.verify": self.verify,
            "intentir.render_diff": self.render_diff,
            "intentir.build": self.build,
        }

    def invoke(self, tool: str, arguments: Any) -> AgentToolResult:
        method = self._tools.get(tool)
        if method is None:
            return failure_payload(
                AgentServiceError(
                    "unknown_agent_tool",
                    f"unknown IntentIR agent tool: {tool}",
                    f"未知のIntentIR Agent Toolです: {tool}",
                    "/tool",
                    scope=TOOL_NAMES,
                )
            )
        if not isinstance(arguments, dict):
            return failure_payload(
                AgentServiceError(
                    "invalid_tool_arguments",
                    "tool arguments must be a JSON object",
                    "Tool argumentsはJSON Objectである必要があります。",
                    "/arguments",
                )
            )
        try:
            inspect.signature(method).bind(**arguments)
        except TypeError as error:
            return failure_payload(
                AgentServiceError(
                    "invalid_tool_arguments",
                    str(error),
                    f"Tool argumentsがSchemaと一致しません: {error}",
                    "/arguments",
                )
            )
        try:
            return method(**arguments)
        except (AgentServiceError, ParseError, ValidationError, PatchError, OSError) as error:
            return failure_payload(error)

    def describe_module(self, source: str) -> AgentToolResult:
        source_path, ir = self._compile(source)
        definitions = [
            compact_node(node)
            for node in ir["nodes"]
            if node["kind"] != "module"
        ]
        modules = [
            compact_node(node)
            for node in ir["nodes"]
            if node["kind"] == "module"
        ]
        counts = Counter(item["kind"] for item in definitions)
        obligation_counts = Counter(item["kind"] for item in ir["obligations"])
        return {
            "ok": True,
            "source": self._relative(source_path),
            "schemaVersion": ir["schemaVersion"],
            "module": ir["module"],
            "moduleId": ir["moduleId"],
            "canonicalHash": ir["canonicalHash"],
            "modules": sorted(modules, key=lambda item: item["symbol"]),
            "definitions": sorted(definitions, key=lambda item: item["symbol"]),
            "definitionCounts": dict(sorted(counts.items())),
            "edgeCount": len(ir["edges"]),
            "obligationCounts": dict(sorted(obligation_counts.items())),
        }

    def get_node(self, source: str, symbol: str) -> AgentToolResult:
        source_path, ir = self._compile(source)
        node = find_node(ir, symbol)
        incoming = sorted_edges(
            edge for edge in ir["edges"] if edge["toSymbol"] == symbol
        )
        outgoing = sorted_edges(
            edge for edge in ir["edges"] if edge["fromSymbol"] == symbol
        )
        obligations = sorted(
            (
                item
                for item in ir["obligations"]
                if item["ownerSymbol"] == symbol
            ),
            key=lambda item: item["id"],
        )
        return {
            "ok": True,
            "source": self._relative(source_path),
            "moduleId": ir["moduleId"],
            "node": node,
            "incomingEdges": incoming,
            "outgoingEdges": outgoing,
            "obligations": obligations,
        }

    def get_context(
        self,
        source: str,
        symbol: str,
        depth: int = 1,
        max_nodes: int = 50,
    ) -> AgentToolResult:
        source_path, ir = self._compile(source)
        find_node(ir, symbol)
        validate_range("depth", depth, 0, 5)
        validate_range("max_nodes", max_nodes, 1, 100)

        neighbors: dict[str, set[str]] = {}
        for edge in ir["edges"]:
            neighbors.setdefault(edge["fromSymbol"], set()).add(edge["toSymbol"])
            neighbors.setdefault(edge["toSymbol"], set()).add(edge["fromSymbol"])

        selected = {symbol}
        queue = deque([(symbol, 0)])
        truncated = False
        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for neighbor in sorted(neighbors.get(current, set())):
                if neighbor in selected:
                    continue
                if len(selected) >= max_nodes:
                    truncated = True
                    continue
                selected.add(neighbor)
                queue.append((neighbor, current_depth + 1))

        nodes = sorted(
            (node for node in ir["nodes"] if node["symbol"] in selected),
            key=lambda item: item["symbol"],
        )
        edges = sorted_edges(
            edge
            for edge in ir["edges"]
            if edge["fromSymbol"] in selected and edge["toSymbol"] in selected
        )
        obligations = sorted(
            (
                item
                for item in ir["obligations"]
                if item["ownerSymbol"] in selected
            ),
            key=lambda item: item["id"],
        )
        return {
            "ok": True,
            "source": self._relative(source_path),
            "moduleId": ir["moduleId"],
            "rootSymbol": symbol,
            "depth": depth,
            "truncated": truncated,
            "nodes": nodes,
            "edges": edges,
            "obligations": obligations,
        }

    def get_impact(self, source: str, symbols: list[str]) -> AgentToolResult:
        source_path, ir = self._compile(source)
        seeds = validate_symbols(ir, symbols, "/symbols")
        reverse: dict[str, set[str]] = {}
        for edge in ir["edges"]:
            reverse.setdefault(edge["toSymbol"], set()).add(edge["fromSymbol"])
        affected = set(seeds)
        queue = deque(seeds)
        while queue:
            current = queue.popleft()
            for dependent in sorted(reverse.get(current, set())):
                if dependent not in affected:
                    affected.add(dependent)
                    queue.append(dependent)
        affected_symbols = sorted(affected)
        obligations = sorted(
            (
                item
                for item in ir["obligations"]
                if item["ownerSymbol"] in affected
            ),
            key=lambda item: item["id"],
        )
        return {
            "ok": True,
            "source": self._relative(source_path),
            "moduleId": ir["moduleId"],
            "seedSymbols": seeds,
            "affectedSymbols": affected_symbols,
            "obligations": obligations,
        }

    def validate_patch(self, source: str, patch: dict[str, Any]) -> AgentToolResult:
        source_path = self._source_path(source)
        plan = plan_patch_path(source_path, patch)
        return {
            **plan.result,
            "source": self._relative(source_path),
            "applied": False,
        }

    def apply_patch(self, source: str, patch: dict[str, Any]) -> AgentToolResult:
        if not self.allow_writes:
            raise AgentServiceError(
                "write_tool_disabled",
                "agent source writes are disabled",
                "AgentによるSource書込みは無効です。",
                "/tool",
                hint="書込みを許可する場合だけ、明示的にallow_writesを有効にしてください。",
            )
        source_path = self._source_path(source)
        return {
            **patch_path(source_path, patch, apply=True),
            "source": self._relative(source_path),
        }

    def verify(
        self,
        source: str,
        symbols: list[str] | None = None,
    ) -> AgentToolResult:
        source_path, ir = self._compile(source)
        selected: set[str] | None = None
        if symbols is not None:
            selected = set(validate_symbols(ir, symbols, "/symbols"))
            allowed = {
                node["symbol"]
                for node in ir["nodes"]
                if node["kind"] in {"function", "test"}
            }
            unsupported = sorted(selected - allowed)
            if unsupported:
                raise AgentServiceError(
                    "unsupported_verification_symbol",
                    "verify symbol filters must name functions or tests",
                    "verifyのSymbol FilterにはFunctionまたはTestを指定してください。",
                    "/symbols",
                    scope=tuple(unsupported),
                )
        result = verify_ir(ir, selected)
        return {**result, "source": self._relative(source_path)}

    def render_diff(self, source: str, patch: dict[str, Any]) -> AgentToolResult:
        source_path = self._source_path(source)
        plan = plan_patch_path(source_path, patch)
        return {
            "ok": True,
            "source": self._relative(source_path),
            "patchId": plan.result["patchId"],
            "baseModuleId": plan.result["baseModuleId"],
            "resultModuleId": plan.result["resultModuleId"],
            "changedSymbols": plan.result["changedSymbols"],
            "affectedSymbols": plan.result["affectedSymbols"],
            "diff": plan.result["diff"],
        }

    def build(
        self,
        source: str,
        target: Literal["ir", "typescript", "sqlite"] = "ir",
    ) -> AgentToolResult:
        source_path, ir = self._compile(source)
        if target == "ir":
            artifact: Any = ir
            artifact_id = ir["canonicalHash"]
        elif target == "typescript":
            artifact = generate_typescript(ir)
            artifact_id = content_address(
                {"kind": "typescript_artifact", "content": artifact}
            )
        elif target == "sqlite":
            artifact = render_sqlite_ddl(ir["module"], storage_schema(ir))
            artifact_id = content_address(
                {"kind": "sqlite_artifact", "content": artifact}
            )
        else:
            raise AgentServiceError(
                "unsupported_build_target",
                f"unsupported build target: {target}",
                f"未対応のBuild Targetです: {target}",
                "/target",
                scope=("ir", "sqlite", "typescript"),
            )
        return {
            "ok": True,
            "source": self._relative(source_path),
            "moduleId": ir["moduleId"],
            "target": target,
            "artifactId": artifact_id,
            "artifact": artifact,
        }

    def _compile(self, source: str) -> tuple[Path, dict[str, Any]]:
        source_path = self._source_path(source)
        return source_path, compile_path(source_path)

    def _source_path(self, source: str) -> Path:
        if not isinstance(source, str) or not source:
            raise AgentServiceError(
                "invalid_source_path",
                "source must be a non-empty path string",
                "sourceには空でないPath Stringが必要です。",
                "/source",
            )
        candidate = Path(source).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise AgentServiceError(
                "source_outside_project_root",
                "source resolves outside the configured project root",
                "sourceが設定されたProject Root外を指しています。",
                "/source",
                hint="Project Root内の相対Pathを指定してください。",
            ) from error
        return resolved

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def find_node(ir: dict[str, Any], symbol: str) -> dict[str, Any]:
    node = next((item for item in ir["nodes"] if item["symbol"] == symbol), None)
    if node is None:
        raise AgentServiceError(
            "unknown_symbol",
            f"unknown symbol: {symbol}",
            f"未知のSymbolです: {symbol}",
            "/symbol",
            scope=tuple(sorted(item["symbol"] for item in ir["nodes"])),
        )
    return node


def validate_symbols(
    ir: dict[str, Any], symbols: Any, path: str
) -> list[str]:
    if (
        not isinstance(symbols, list)
        or not symbols
        or not all(isinstance(item, str) and item for item in symbols)
    ):
        raise AgentServiceError(
            "invalid_symbol_list",
            "symbols must be a non-empty array of strings",
            "symbolsには空でないString配列が必要です。",
            path,
        )
    known = {node["symbol"] for node in ir["nodes"]}
    normalized = sorted(set(symbols))
    unknown = sorted(set(normalized) - known)
    if unknown:
        raise AgentServiceError(
            "unknown_symbol",
            f"unknown symbols: {', '.join(unknown)}",
            f"未知のSymbolです: {', '.join(unknown)}",
            path,
            scope=tuple(unknown),
        )
    return normalized


def validate_range(name: str, value: Any, minimum: int, maximum: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise AgentServiceError(
            "invalid_tool_argument_range",
            f"{name} must be an integer from {minimum} to {maximum}",
            f"{name}は{minimum}から{maximum}のIntegerである必要があります。",
            f"/{name}",
        )


def compact_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        key: node[key]
        for key in ("id", "symbol", "kind", "name", "definedIn")
        if key in node
    }


def sorted_edges(edges: Any) -> list[dict[str, Any]]:
    return sorted(
        edges,
        key=lambda edge: (
            edge["fromSymbol"],
            edge["kind"],
            edge["toSymbol"],
            edge["id"],
        ),
    )


def failure_payload(error: Exception) -> AgentToolResult:
    if isinstance(error, (ValidationError, PatchError)):
        diagnostics = [item.to_dict() for item in error.diagnostics]
    elif isinstance(error, AgentServiceError):
        diagnostic = {
            "code": error.code,
            "severity": "error",
            "message": error.message,
            "messageJa": error.message_ja,
            "path": error.path,
            "scope": list(error.scope),
        }
        if error.hint is not None:
            diagnostic["hint"] = error.hint
        diagnostics = [diagnostic]
    elif isinstance(error, ParseError):
        code = getattr(error, "code", "parse_error")
        diagnostics = [
            {
                "code": code,
                "severity": "error",
                "message": str(error),
                "messageJa": f"構文またはImport解決に失敗しました: {error}",
                "path": getattr(error, "path", "/source"),
                "scope": [],
            }
        ]
    else:
        diagnostics = [
            {
                "code": "agent_io_error",
                "severity": "error",
                "message": "agent tool file operation failed",
                "messageJa": "Agent ToolのFile操作に失敗しました。",
                "path": "/source",
                "scope": [],
                "hint": "Project Root、対象Path、File権限を確認してください。",
            }
        ]
    return {"ok": False, "diagnostics": diagnostics}
