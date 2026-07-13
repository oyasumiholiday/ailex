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
- Canonical Hash: `sha256:fa74dd254c6cef4ebd7865c9b6c1bc02f3f79bc0e89665a7d2480b063148f2a6`
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

## 実行コマンド

```sh
python3 -m intentir check examples/todo_crud.intent
python3 -m intentir test examples/todo_crud.intent
python3 -m intentir run examples/todo_crud.intent CreateTask --input '{"id":"db-1","title":"保存"}' --db /tmp/todo.db
python3 -m intentir report examples/todo_crud.intent
```
