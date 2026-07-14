# IntentIR プロジェクトまとめ

## 現在の位置づけ

このプロジェクトでは、AI向け中間表現の参照実装 **IntentIR v0.6** を開発しました。

IntentIRは、AIまたは人間が書く小さな表層構文を、内容アドレス付き意味グラフへ変換し、そのグラフを静的検証、直接実行、TypeScript生成に利用します。AilexのようなAI向け言語と競合するものではなく、その下で意味、依存関係、Effect、契約、テスト、診断を保持する層を想定しています。

v0.6では、`check / test / run / migrate / build / fmt`という開発ループに、内容アドレス付きMigration IRを追加しました。ただし、現段階は汎用言語ではなく、EntityとActionを中心にした実行可能DSLです。

Ailexの弱点分析と改善案は [AILEX_ANALYSIS_JA.md](AILEX_ANALYSIS_JA.md) にまとめています。

## v0.6で実装したもの

### Migration IR

SQLiteに保存した旧Schema Snapshotと新しいIntentIRを比較し、変更を内容アドレス付きOperationへ変換します。

```json
{
  "kind": "migration_plan",
  "fromSchemaHash": "sha256:...",
  "toSchemaHash": "sha256:...",
  "operations": [
    {
      "op": "add_field",
      "entity": "Item",
      "field": "active",
      "safety": "safe"
    }
  ]
}
```

Planと各OperationにはSHA-256 IDが付きます。同じSchema差分からは同じPlan IDが生成されます。

変更は次の3種類へ分類します。

- `safe`: 任意Field追加、default付きField追加、空Entity追加、互換制約変更
- `destructive`: Field削除、Entity削除
- `manual`: 型変更、defaultなし必須Field追加など、既存値を自動生成できない変更

`migrate`は既定ではPlanを表示するだけです。`--apply`で初めて書き込み、破壊的変更にはさらに`--allow-destructive`が必要です。State変換、新Schema検証、保存は1つのSQLiteトランザクションで行われます。

### KeyとUnique制約

Entityの識別子と追加の一意Fieldを表層構文から宣言できます。

```intentir
entity Task:
  id: UUID required key
  externalId: Text unique
  title: Text required
```

- `key`はEntityごとに1つで、`required`が必要
- Keyにdefaultは指定不可
- `unique`は複数宣言可能
- `update/delete`のselectorはKeyまたはUnique Fieldに限定
- Keyの更新は禁止
- State読込、insert、updateで重複値を拒否

制約違反時はAction全体が失敗し、変更前のStateを維持します。

### Repository Capability

ActionのEffectから、必要なRepository CapabilityをIRへ明示します。

```json
{
  "kind": "repository",
  "entity": "Task",
  "operations": ["update"]
}
```

現在はEffectから決定的に推論します。将来はHTTP、File、Clockなどの明示Capability宣言へ拡張できます。

### SQLite永続化

`run --db`で、別々のCLIプロセスから同じStateを更新できます。

```sh
python3 -m intentir run examples/todo_crud.intent CreateTask \
  --input '{"id":"task-1","title":"牛乳を買う"}' \
  --db /tmp/todo.db

python3 -m intentir run examples/todo_crud.intent CompleteTask \
  --input '{"id":"task-1"}' \
  --db /tmp/todo.db
```

SQLiteでは読込、Action実行、保存を1つの`BEGIN IMMEDIATE`トランザクションとして扱います。またEntity定義からStorage Schema Hashを生成し、互換性のないスキーマで既存DBを黙って開くことを防ぎます。

v0.6からSchema Snapshot自体もDBへ保存します。v0.5 DBはSchema Hashが一致する場合に引き続き読込でき、次回保存時にSnapshotを補完します。

### CRUD Effect

次の3操作を構造化IRへ変換し、Python実行器とTypeScript生成コードの両方で実行できます。

```intentir
insert Task
update Task where id equals input.id set done = true
delete Task where id equals input.id
```

`update`と`delete`は静的にKey/Unique selectorを要求し、実行時にも対象がちょうど1件であることを確認します。0件または複数件の場合は失敗し、Storeは変更されません。

### トランザクション型Action実行

Actionは次の順で実行されます。

1. Inputの必須値と型を検証
2. Requirementを検証
3. Effectを仮のStoreへ適用
4. Ensureを検証
5. すべて成功した場合だけStoreを確定

途中で失敗した場合に部分的な更新を残しません。JSON Storeを読み込み、Action実行後のStateをJSONへ保存できます。

### 複数ステップのシナリオTest

1つのTestに複数の`when`を書き、同じStore上でライフサイクルを検証できます。

```intentir
test "タスクを完了できる":
  when CreateTask(id="task-1", title="牛乳を買う")
  when CompleteTask(id="task-1")
  expect Task count equals 1
  expect Task exists with done true
```

期待式は存在、条件付き存在、非存在、件数比較に対応しています。

### `created`と`affected`

- `created Task.field`: `insert`で生成したレコード
- `affected Task.field`: `insert / update / delete`が処理したレコード

静的検証では、対象Entityが本当にEffectへ束縛されているか、同一Entityへの複数Effectで参照が曖昧になっていないかも確認します。

### 静的検証とAI修復向け診断

主な検証項目は次のとおりです。

- Entity、Action、Test、Field、Inputの重複
- 組み込み型とデフォルト値
- Key、Unique、selectorの一意性
- 条件式、更新対象、代入値の参照先と型
- `insert`が必須Fieldへ値を供給できるか
- TestのAction、引数、期待対象
- `created`と`affected`の束縛および曖昧性

診断は安定した`code`、意味グラフ上の`path`、利用可能な`scope`、修復用`hint`、英語・日本語メッセージを持ちます。

### 内容アドレス付き意味グラフ

Entity、Action、Test、Constraint、Effect、Edge、ObligationにSHA-256 IDを付与します。人間向けの`symbol`と、意味に基づく不変IDを分けています。Fieldの宣言順など意味を持たない差は正規化されます。

### TypeScriptバックエンド

生成コードには次が含まれます。

- Entity型、Store、`createStore()`
- ActionごとのInput型と関数
- RequirementとEnsureの実行時ガード
- `insert / update / delete`
- 複数ステップTestから生成した`runIntentIRTests()`

生成したCRUDコードはNode.js上で実行し、Python実行器と同じ2シナリオが成功することを確認しています。

### CLIとFormatter

```sh
python3 -m intentir check examples/todo_crud.intent
python3 -m intentir test examples/todo_crud.intent
python3 -m intentir run examples/todo_crud.intent CreateTask \
  --input '{"id":"task-1","title":"牛乳を買う"}'
python3 -m intentir migrate examples/inventory_v2.intent --db /tmp/inventory.db
python3 -m intentir migrate examples/inventory_v2.intent --db /tmp/inventory.db --apply
python3 -m intentir build examples/todo_crud.intent --target typescript
python3 -m intentir fmt --check examples/todo_crud.intent
python3 -m intentir report examples/todo_crud.intent -o /tmp/report.md
python3 -m intentir ir examples/todo_crud.intent --canonical
```

Formatterは同じ入力に繰り返し適用しても結果が変わらず、行全体の`#`コメントを保持します。v0.3の`SOURCE --emit ...`形式も互換用に残しています。

## 主なファイル

- `intentir/canonical.py`: 正規JSONと内容アドレス
- `intentir/expressions.py`: 条件、CRUD Effect、Call、Expectationの構造化
- `intentir/ir.py`: 内容アドレス付きグラフと検証義務
- `intentir/validator.py`: 静的検証と構造化診断
- `intentir/verifier.py`: トランザクション型実行器とTest検証
- `intentir/storage.py`: SQLite State RepositoryとSchema Hash
- `intentir/migration.py`: Migration Plan生成、安全性分類、State変換
- `intentir/generators/typescript.py`: TypeScript生成
- `intentir/formatter.py`: 表層構文Formatter
- `intentir/cli.py`: 開発用CLI
- `intentir/reports.py`: 日本語検証レポート
- `examples/todo_crud.intent`: CRUDライフサイクル例
- `examples/inventory_v1.intent` / `inventory_v2.intent`: Migration例
- `VALIDATION_REPORT_JA.md`: v0.6サンプルの検証結果
- `tests/test_compiler.py`: 28件の自動テスト

## 検証済み

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q intentir tests
python3 -m intentir check examples/todo_crud.intent
python3 -m intentir test examples/todo_crud.intent
python3 -m intentir run examples/todo_crud.intent CreateTask --input '{"id":"db-1","title":"保存"}' --db /tmp/todo.db
python3 -m intentir migrate examples/inventory_v2.intent --db /tmp/inventory.db
python3 -m intentir build examples/todo_crud.intent --target typescript
python3 -m intentir fmt --check examples/todo_crud.intent
python3 -m intentir report examples/todo_crud.intent
python3 -m intentir examples/todo.intent --emit verify
```

自動テストは28件で、Migrationの安全適用・拒否・ロールバック、v0.5 DB互換、別プロセス間のSQLite永続化、生成TypeScriptのNode.js E2Eを含みます。

## 現在の制約

まだ次の要素はありません。

- 一般的な関数、式、分岐、繰り返し
- Entity間のRelation
- 複数Module、import、package管理
- 非同期処理、HTTP、File、Clockなどの明示Capability
- SQLite StateからEntityテーブルへのRelational Mapping
- Migrationでのrename推論と手動値入力
- Debugger、Language Server
- 内容ハッシュを前提条件にするPatch IR

したがって、現時点でGoやPythonを置き換えるものではありません。次はEntityの関係テーブル投影、関数、Moduleを追加し、その後に内容ハッシュを前提条件とするPatch IRへ進むのが妥当です。
