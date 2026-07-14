# IntentIR 検証レポート

- 対象: `examples/todo_crud.intent`
- モジュール: `TodoCrud`
- 結果: 成功

## 概要

- Entity: 1
- Action: 4
- Test: 2
- IR Node: 7
- IR Edge: 11
- 検証義務: 11
- Repository Capability: 3種類 / 4 Action参照
- Module ID: `sha256:1569746c9b44017ff7d087c40727e92619f168dcb0731a76022383c855bd832f`
- Canonical Hash: `sha256:cd2e329721580bd95b110faf587884b3414feeb4f91214b9f60ea7f588530a37`
- Storage Schema Hash: `sha256:309658e2c8bb87e6363ddf0b266d82032d5c44b75626ad0e7a13dad60b97f78d`

## 静的検証

- エラーはありません。

## 実行検証

- 2 / 2 Test 成功
- `タスクを削除できる`: 成功
- `タスクを完了して改名できる`: 成功

## 検証項目

- 重複定義、シンボル衝突、組み込み型、デフォルト値
- Requirement / Ensure の参照先と型の整合性
- Effect の対象、CRUD操作、更新値の型、必須 Field への値の供給
- Key / Unique制約、Effect selectorの一意性、Stateの整合性
- Test の Action、Input、リテラル型、期待対象
- 内容アドレス、依存 Edge、検証義務の決定的生成
- 事前条件、Effect、事後条件、期待値の実行検証

## Migration検証

- 移行元: `examples/inventory_v1.intent`
- 移行先: `examples/inventory_v2.intent`
- Plan ID: `sha256:7e4a487df66987a9f67d1a11f60b1e50d582358993c6c07902e6e10430fafc34`
- 判定: `safe` 2件、`destructive` 0件、`manual` 0件
- 操作: Optional Field `Item.note`の追加
- 操作: Default付きField `Item.active`の追加
- Planのみの実行ではDBが更新されないことを確認
- `--apply`後も既存Recordを保持し、`active: true`が補完されることを確認
- 手動対応が必要な必須Field追加は適用拒否とRollbackを確認
- Entity/Field削除は`--allow-destructive`なしでは適用拒否を確認
- v0.5形式DBのSchema Snapshot補完を確認

## 自動テスト

- 28 / 28 成功
- Python実行器、SQLite永続化、Migration、生成TypeScriptのNode.js E2Eを含む

## 実行コマンド

```sh
python3 -m intentir check examples/todo_crud.intent
python3 -m intentir test examples/todo_crud.intent
python3 -m intentir run examples/todo_crud.intent CreateTask --input '{"id":"db-1","title":"保存"}' --db /tmp/todo.db
python3 -m intentir migrate examples/inventory_v2.intent --db /tmp/inventory.db
python3 -m intentir migrate examples/inventory_v2.intent --db /tmp/inventory.db --apply
python3 -m intentir report examples/todo_crud.intent
python3 -m unittest discover -s tests -v
```
