# IntentIR 検証レポート

- 対象: `examples/modules/app.intent`
- モジュール: `ModularTodo`
- 結果: 成功

## 概要

- Module: 3
- Import: 2
- Entity: 1
- Function: 2
- Action: 2
- Test: 1
- Function Example: 2
- IR Node: 9
- IR Edge: 15
- 検証義務: 4
- Repository Capability: 2種類 / 2 Action参照
- Module ID: `sha256:ebe5bbed322de051444d245f14b87bac3106743b5d29f410546f346c40831305`
- Canonical Hash: `sha256:91ca433af368cc206c4e05e9f10a95cafe00aa5a787c9683a711e64e05d63251`
- Storage Schema Hash: `sha256:876ad113a30599a794c0c1ccffea38dbdf56298e53cb76b99a079171a57f6245`
- SQLite Projection ID: `sha256:3a502d6104c9ff7d5fb88bcf2fafa9882b24de23e0972ce05d0c8a8add22af44`
- SQLite Storage Format: `relational-v1`

## 静的検証

- エラーはありません。
- `ModularTodo -> TaskDomain -> TextRules`の推移Importを解決
- Moduleを内容アドレス付きNodeとして生成
- Module間に2本の`imports` Edge、Moduleから各定義へ`defines` Edgeを生成
- 各Entity、Function、Action、Testへ`definedIn`を記録
- 循環Import、同名Module、欠落Import、絶対Importを拒否
- Importパスの表記差を意味Hashから除外
- 依存Moduleの意味変更をルートModule IDへ伝播

## 実行検証

- 1 / 1 Test 成功
- `transitive imports are executable`: 成功

## 純粋Function検証

- 2 / 2 Function Example 成功
- `IsAcceptableTitle(title="task") equals true`: 成功
- `NormalizeTitle(title="task") equals "task!"`: 成功

## TypeScript Backend検証

- 3つのModuleを1つの実行可能TypeScriptへリンク
- Node.jsで推移Import先のFunction、Entity、Action、Testを実行
- 1 Scenario Testと2 Function Exampleがすべて成功

## 自動テスト

- 52 / 52 成功
- Parser、Formatter、Linker、依存Hash、循環診断、CLI、Python/Node.js E2Eを含む

## 検証項目

- Module/importの相対解決、循環、同名衝突、依存Hash
- 重複定義、シンボル衝突、組み込み型、デフォルト値
- Requirement / Ensure の参照先と型の整合性
- 純粋FunctionのInput、Return、式、呼出し、循環依存、Example
- Effect の対象、CRUD操作、更新値の型、必須 Field への値の供給
- Key / Unique制約、Effect selectorの一意性、Stateの整合性
- SQLite関係表、列型、NOT NULL、Key / Unique制約の決定的投影
- Test の Action、Input、リテラル型、期待対象
- 内容アドレス、依存 Edge、検証義務の決定的生成
- 事前条件、Effect、事後条件、期待値の実行検証
