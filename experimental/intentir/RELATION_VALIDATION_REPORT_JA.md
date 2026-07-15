# IntentIR 検証レポート

- 対象: `examples/relations.intent`
- モジュール: `ProjectTasks`
- 結果: 成功

## 概要

- Module: 1
- Import: 0
- Entity: 2
- Function: 0
- Action: 4
- Test: 1
- Function Example: 0
- IR Node: 8
- IR Edge: 17
- 検証義務: 2
- Repository Capability: 4種類 / 4 Action参照
- Module ID: `sha256:a4f70fcce4d30686329910bb99838c016f1da89e37977c82d4b5407e87e2a758`
- Canonical Hash: `sha256:724c2516cea8558d9f4254146aa1673fc479ea1c595e0f50b7e07de7ba2b7a04`
- Storage Schema Hash: `sha256:d725a6fde0a3e02d3dfda5b5b79f4d2fea45a4c306c5302005d880d1219c61ec`
- SQLite Projection ID: `sha256:964050b400e2a75828f01f42fc405d333790a360d0b6d7935b143dac475310ad`
- SQLite Storage Format: `relational-v1`

## 静的検証

- エラーはありません。

## 実行検証

- 1 / 1 Test 成功
- `project task lifecycle`: 成功

## 純粋Function検証

- Function Example はありません。

## Relation検証

- `Task.projectId`は構造化IRで`Project.id`を参照
- `entity:Task`から`entity:Project`へ`references` Edgeを生成
- 未知Entity、未知Field、非一意Field、型不一致、循環参照を静的拒否
- 孤児Taskの作成を`reference_constraint_violation`で原子的に拒否
- Taskが残るProject削除を同じCodeで原子的に拒否
- 生成TypeScriptでも孤児作成と参照中の親削除を拒否

## SQLite検証

- `Task.projectId`を`Project.id`への外部キーとして投影
- `ON UPDATE RESTRICT / ON DELETE RESTRICT`を生成
- `PRAGMA foreign_keys = ON`で物理制約を有効化
- 親Tableを先に作成・挿入し、削除時は子Tableを先に処理
- 初回保存は`replace`、Key付きEntityの後続Actionは`incremental`
- 差分保存のSQL Traceに`UPDATE`があり、`DROP TABLE / CREATE TABLE`がないことを確認
- v0.10で作成した`relational-v1` DBをv0.11から読込・差分更新できることを確認
- 参照追加・変更はMigration `manual`、参照削除は`safe`

## 自動テスト

- `python3 -m unittest discover -s tests -v`: 59件成功
- `python3 -m compileall -q intentir tests`: 成功
- Node.js上の生成TypeScript実行: 成功

## 検証項目

- Module/importの相対解決、循環、同名衝突、依存Hash
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
