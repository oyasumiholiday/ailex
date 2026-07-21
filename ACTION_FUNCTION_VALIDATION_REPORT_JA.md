# IntentIR 検証レポート

- 対象: `examples/function_actions.intent`
- モジュール: `FunctionActions`
- 結果: 成功

## 概要

- Entity: 1
- Function: 2
- Action: 2
- Test: 1
- Function Example: 2
- IR Node: 6
- IR Edge: 8
- 検証義務: 4
- Repository Capability: 2種類 / 2 Action参照
- Module ID: `sha256:3bbf12959fe358c00ad30b821a85b9654071233da436ecfe19d71b4b11de4982`
- Canonical Hash: `sha256:f34d0a3a7574faae26bee8df00978c5056f18081eaa5d7bda7a0df8efb85e9fd`
- Storage Schema Hash: `sha256:876ad113a30599a794c0c1ccffea38dbdf56298e53cb76b99a079171a57f6245`
- SQLite Projection ID: `sha256:f2520c565cfd1eed8fc8b9375d3721ef16835dd0d6daf099a2d515d9431c9685`
- SQLite Storage Format: `relational-v1`

## 静的検証

- エラーはありません。
- Action Inputを純粋式の変数Scopeとして検証
- Requirement、Effect代入値、EnsureのFunction引数とReturn型を検証
- `CreateTask`と`RenameTask`からFunctionへの`calls` Edgeを生成
- Text FieldへBoolean Function結果を代入する不正例を`effect_assignment_type_mismatch`として拒否

## 実行検証

- 1 / 1 Test 成功
- `rename through a pure function`: 成功
- Requirementの`IsAcceptableTitle(title)`を実行
- Effectの`NormalizeTitle(title)`で`Task.title`を`write docs!`へ更新
- Ensureでも同じFunctionを再評価し、更新結果との一致を確認
- 純粋式のゼロ除算を`pure_division_by_zero`として返し、Stateが変更されないことを確認

## 純粋Function検証

- 2 / 2 Function Example 成功
- `IsAcceptableTitle(title="task") equals true`: 成功
- `NormalizeTitle(title="task") equals "task!"`: 成功

## TypeScript Backend検証

- 同じFunction、Requirement、Effect、EnsureをTypeScriptへ生成
- Node.jsで生成済み`CreateTask`と`RenameTask`を実行
- 生成済みTest Runnerと直接Action呼出しの両方で`Task.title == "ship!"`を確認

## 自動テスト

- 46 / 46 成功
- Python構文検証、静的型検証、依存Edge、原子的失敗、Node.js E2Eを含む

## 検証項目

- 重複定義、シンボル衝突、組み込み型、デフォルト値
- Requirement / Ensure の参照先と型の整合性
- 純粋FunctionのInput、Return、式、呼出し、循環依存、Example
- Effect の対象、CRUD操作、更新値の型、必須 Field への値の供給
- Key / Unique制約、Effect selectorの一意性、Stateの整合性
- SQLite関係表、列型、NOT NULL、Key / Unique制約の決定的投影
- Test の Action、Input、リテラル型、期待対象
- 内容アドレス、依存 Edge、検証義務の決定的生成
- 事前条件、Effect、事後条件、期待値の実行検証
