from __future__ import annotations

from intentir.ir import build_ir
from intentir.parser import ParseError, parse_source
from intentir.storage import storage_schema_hash
from intentir.validator import Diagnostic, collect_diagnostics
from intentir.verifier import verify_ir


CHECK_ITEMS = [
    "重複定義、シンボル衝突、組み込み型、デフォルト値",
    "Requirement / Ensure の参照先と型の整合性",
    "Effect の対象、CRUD操作、更新値の型、必須 Field への値の供給",
    "Key / Unique制約、Effect selectorの一意性、Stateの整合性",
    "Test の Action、Input、リテラル型、期待対象",
    "内容アドレス、依存 Edge、検証義務の決定的生成",
    "事前条件、Effect、事後条件、期待値の実行検証",
]

HINTS_JA = {
    "unknown_input": "Scope内のInputへ変更するか、必要なInputをActionへ追加してください。",
    "unknown_effect_entity": "Scope内のEntityをEffectの対象にしてください。",
    "unknown_entity": "Scope内のEntityを参照してください。",
    "unknown_field": "Scopeに表示されたFieldを参照してください。",
    "unbound_created_entity": "対象Entityのinsertを追加するか、事後条件を変更してください。",
    "unbound_affected_entity": "対象EntityのEffectを追加するか、事後条件を変更してください。",
    "ambiguous_affected_entity": "参照するEntityへのEffectを1つに絞ってください。",
    "unknown_action": "Scope内のActionを呼び出してください。",
    "unknown_expected_entity": "Scope内のEntityを期待対象にしてください。",
    "unknown_expected_field": "Scope内のFieldを期待条件に使用してください。",
    "unknown_test_input": "ActionのScope内にあるInput名を使用してください。",
    "missing_test_input": "必須Inputを名前付き引数として追加してください。",
    "literal_type_mismatch": "宣言された型と互換性のあるリテラルへ変更してください。",
    "unknown_effect_field": "更新対象をScope内のFieldへ変更してください。",
    "effect_assignment_type_mismatch": "更新値をFieldと互換性のある型へ変更してください。",
    "unsupported_effect_value": "Effectの値にはInput参照またはリテラルを使用してください。",
    "key_requires_required": "Key Fieldへrequiredを追加してください。",
    "key_default_not_allowed": "Key Fieldのdefaultを削除し、明示的に値を渡してください。",
    "multiple_entity_keys": "Keyを1つに絞り、追加識別子にはuniqueを使用してください。",
    "non_unique_effect_selector": "update/deleteの対象にはkeyまたはunique Fieldを使用してください。",
    "key_update_not_allowed": "Keyを変更せず、新しいEntityを作成してください。",
    "missing_effect_binding": "同名InputまたはEntity Fieldのdefaultを追加してください。",
    "optional_effect_binding": "Inputをrequiredにするか、defaultまたは事前条件を追加してください。",
    "effect_binding_type_mismatch": "InputとEntity Fieldの型を一致させてください。",
    "condition_type_mismatch": "互換性のある型同士を比較してください。",
    "empty_test": "少なくとも1つのexpectを追加してください。",
}


def generate_validation_report(source: str, source_name: str | None = None) -> str:
    target = source_name or "(memory)"
    lines = ["# IntentIR 検証レポート", "", f"- 対象: `{target}`"]

    try:
        program = parse_source(source)
    except ParseError as error:
        lines.extend(
            [
                "- 結果: 失敗",
                "",
                "## 構文エラー",
                "",
                f"- {error}",
            ]
        )
        return "\n".join(lines) + "\n"

    diagnostics = collect_diagnostics(program)
    ir = build_ir(program) if not diagnostics else None
    verification = verify_ir(ir) if ir is not None else None
    passed = not diagnostics and verification is not None and verification["ok"]

    lines.extend(
        [
            f"- モジュール: `{program.module}`",
            f"- 結果: {'成功' if passed else '失敗'}",
            "",
            "## 概要",
            "",
            f"- Entity: {len(program.entities)}",
            f"- Action: {len(program.actions)}",
            f"- Test: {len(program.tests)}",
        ]
    )
    if ir is not None:
        capabilities = [
            capability
            for node in ir["nodes"]
            if node["kind"] == "action"
            for capability in node.get("capabilities", [])
        ]
        lines.extend(
            [
                f"- IR Node: {len(ir['nodes'])}",
                f"- IR Edge: {len(ir['edges'])}",
                f"- 検証義務: {len(ir['obligations'])}",
                f"- Repository Capability: {len({item['id'] for item in capabilities})}種類 / {len(capabilities)} Action参照",
                f"- Module ID: `{ir['moduleId']}`",
                f"- Canonical Hash: `{ir['canonicalHash']}`",
                f"- Storage Schema Hash: `{storage_schema_hash(ir)}`",
            ]
        )

    lines.extend(["", "## 静的検証", ""])
    if not diagnostics:
        lines.append("- エラーはありません。")
    else:
        for index, diagnostic in enumerate(diagnostics, start=1):
            lines.extend(render_diagnostic(index, diagnostic))

    lines.extend(["", "## 実行検証", ""])
    if verification is None:
        lines.append("- 静的検証に失敗したため実行していません。")
    elif not verification["tests"]:
        lines.append("- Test はありません。")
    else:
        summary = verification["summary"]
        lines.append(
            f"- {summary['passed']} / {summary['tests']} Test 成功"
        )
        for test in verification["tests"]:
            mark = "成功" if test["ok"] else "失敗"
            lines.append(f"- `{test['name']}`: {mark}")
            for error in test["errors"]:
                lines.append(f"  - {error['messageJa']}")
                lines.append(f"  - 義務ID: `{error['obligationId']}`")

    lines.extend(["", "## 検証項目", ""])
    lines.extend(f"- {item}" for item in CHECK_ITEMS)
    return "\n".join(lines) + "\n"


def render_diagnostic(index: int, diagnostic: Diagnostic) -> list[str]:
    lines = [
        f"{index}. [{diagnostic.code}] {diagnostic.message_ja}",
        f"   - Path: `{diagnostic.path}`",
    ]
    if diagnostic.scope:
        lines.append(f"   - Scope: `{', '.join(diagnostic.scope)}`")
    if diagnostic.hint:
        hint = HINTS_JA.get(diagnostic.code, diagnostic.hint)
        lines.append(f"   - 修復候補: {hint}")
    return lines


def translate_diagnostic(diagnostic: Diagnostic) -> str:
    return diagnostic.message_ja
