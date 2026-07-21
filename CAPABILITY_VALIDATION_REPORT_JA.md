# IntentIR 検証レポート

- 対象: `examples/capabilities.intent`
- モジュール: `AuditedEvents`
- 結果: 成功

## 概要

- Module: 1
- Import: 0
- Capability: 1
- Entity: 1
- Function: 0
- Action: 1
- Test: 1
- Function Example: 0
- IR Node: 5
- IR Edge: 9
- 検証義務: 2
- Repository Capability: 1種類 / 1 Action参照
- Module ID: `sha256:49cf2d5ca0ef283e5525501cec6b9ba78a6c2dda993b181c67a0b5409669d273`
- Canonical Hash: `sha256:49e8b839ca56687f75f108697341e325c7a65427358046e979ec51bf2ae9944d`
- Storage Schema Hash: `sha256:bff3f8b6e69feb72e35e4a3678fcb9b4285c30414e9147d982c290957d0deae1`
- SQLite Projection ID: `sha256:56b24b8de7e2f8dc73bebc4ec8385a9215e99306e3c086d58b8d2bdf37f3e380`
- SQLite Storage Format: `relational-v1`

## 静的検証

- エラーはありません。

## 実行検証

- 1 / 1 Test 成功
- `injects deterministic clock`: 成功

## 純粋Function検証

- Function Example はありません。

## Capability検証

- `Clock.now`をReturn型`Text`のCapability Operationとして宣言
- `CreateEvent`が`Clock.now as createdAt`を明示的に使用
- ActionからCapabilityへ`uses` Edgeを生成
- TestからCapabilityへ`stubs` Edgeを生成
- `given Clock.now = "..."`を内容アドレス付きStubへ変換
- Capability BindingをRequirement、Effect、Ensureの型付きScopeへ追加
- 未知Capability、未知Operation、Binding衝突、重複使用、Stub不足、型不一致を構造化診断

## Runtime検証

- Python実行器へ`Clock.now`の固定値を注入し、`Event.createdAt`へ保存
- Capability未指定を`missing_runtime_capability`で原子的に拒否
- 戻り値型不一致を`runtime_capability_type_mismatch`で原子的に拒否
- CLIの`--capabilities`へJSONまたは`@file`から値を供給可能
- 実行結果の`capabilitiesUsed`に値を含めず、使用したOperation名だけを記録

## TypeScript Backend検証

- `ClockCapability`とAction固有の`CreateEventCapabilities`型を生成
- Providerの`Clock.now()`をAction開始時に一度だけ評価
- JavaScript実行時にもReturn型を検査
- Testの`given`を決定的なProvider関数へ生成
- Node.jsで生成Test、直接注入、誤型Providerの拒否を確認

## 分離と互換性

- Capability変更はModule Canonical Hashへ反映
- Capabilityは永続データ構造ではないためStorage Schema Hashへ含めない
- ImportされたCapabilityをルートModuleのActionから利用可能
- v0.12は引数なしOperationの値注入までを対象とし、引数付きI/O呼出しは未実装

## 自動テスト

- `python3 -m unittest discover -s tests -v`: 66件成功
- `python3 -m compileall -q intentir tests`: 成功
- Capabilityサンプルのcheck / test / fmt: 成功
- 生成TypeScriptのNode.js実行: 成功

## 検証項目

- Module/importの相対解決、循環、同名衝突、依存Hash
- Capability Operation、Action Binding、Test Stubの参照先と型
- 重複定義、シンボル衝突、組み込み型、デフォルト値
- Requirement / Ensure の参照先と型の整合性
- 純粋FunctionのInput、Return、式、呼出し、循環依存、Example
- Effect の対象、CRUD操作、更新値の型、必須 Field への値の供給
- Key / Unique制約、Effect selectorの一意性、Stateの整合性
- Entity参照先の存在、一意性、型、循環と実行時参照整合性
- SQLite関係表、列型、Key / Unique / Foreign Key制約の決定的投影
- Test の Action、Input、リテラル型、期待対象
- 内容アドレス、依存 Edge、検証義務の決定的生成
- 事前条件、Effect、事後条件、期待値の実行検証
