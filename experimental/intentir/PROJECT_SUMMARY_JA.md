# IntentIR プロジェクトまとめ

## 現在の位置づけ

このプロジェクトでは、AI向け中間表現の参照実装 **IntentIR v0.9** を開発しました。

IntentIRは、AIまたは人間が書く小さな表層構文を、内容アドレス付き意味グラフへ変換し、そのグラフを静的検証、直接実行、TypeScript生成に利用します。AilexのようなAI向け言語と競合するものではなく、その下で意味、依存関係、Effect、契約、テスト、診断を保持する層を想定しています。

v0.9では、`check / test / call / run / migrate / build / fmt`という開発ループに、Action内で利用できる型付き純粋Function、内容アドレス付きMigration IR、決定的なSQLite関係表投影を統合しました。ただし、現段階は汎用言語ではなく、純粋Function、Entity、Actionを中心にした実行可能DSLです。

Ailexの弱点分析と改善案は [AILEX_ANALYSIS_JA.md](AILEX_ANALYSIS_JA.md) にまとめています。

## v0.9までに実装したもの

### 型付き純粋Function

Functionは型付きInput、Return型、単一の純粋式Body、実行可能Exampleを持ちます。

```intentir
function Clamp:
  input:
    value: Integer required
    minimum: Integer required
    maximum: Integer required
  returns: Integer
  body: minimum if value < minimum else maximum if value > maximum else value
  examples:
    Clamp(value=12, minimum=0, maximum=10) equals 10
```

BodyはPython ASTを直接実行せず、許可したNodeだけを次の構造化IRへ変換します。

- Scalar literalとInput変数
- `+ / - / * / / / // / %`
- `== / != / < / <= / > / >=`
- `and / or / not`と単項符号
- Python形式の条件式
- 位置引数・名前付き引数による純粋Function呼出し

Function BodyとExampleには内容アドレスが付き、Function間呼出しは`calls` Edge、Exampleは検証義務になります。Input、Return、Operand、呼出し引数を静的に型検証し、再帰Cycleは終了性義務を導入するまで拒否します。

`intentir call`でFunctionを直接実行でき、同じFunctionとExampleをTypeScriptへ生成できます。

### Action内の純粋Function呼出し

Requirement、update/deleteのSelector、updateの代入値、Ensureから純粋Functionと一般式を呼び出せます。純粋式内の裸の名前はAction Inputを参照します。

```intentir
action RenameTask:
  input:
    id: UUID required
    title: Text required
  requires:
    IsAcceptableTitle(title) equals true
  effects:
    update Task where id equals input.id set title = NormalizeTitle(title)
  ensures:
    affected Task.title equals NormalizeTitle(title)
```

Action Inputを変数Scopeとして式とFunction引数を静的型検証し、ActionからFunctionへの依存を`calls` EdgeとしてIRへ記録します。Python実行器とTypeScript生成器は同じ純粋式ASTを評価します。ゼロ除算などの実行時失敗は構造化診断になり、ActionのState変更は確定されません。

### SQLite Relational Projection

Entityを専用Tableへ、Fieldを型付きColumnへ決定的に投影します。物理Table名はModuleとEntityの内容アドレスから生成し、宣言順や実行時刻に依存しません。

- `Text / UUID`は`TEXT`
- `Boolean / Integer`は`INTEGER`
- `Number`は`NUMERIC`
- `required`は`NOT NULL`
- `key / unique`は`UNIQUE`
- Field defaultはSQLite `DEFAULT`
- Booleanなどは`CHECK`制約で物理型も検証

`intentir build --target sqlite`で、Projection IDを含むDDLを生成できます。Repositoryが使うTable定義と同じ生成器を使うため、確認用DDLと実際の永続化定義がずれません。

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

v0.7ではEntityごとの関係TableをStateの正本とし、メタデータ行にはSchema Snapshot、Schema Hash、`relational-v1`形式識別子を保存します。v0.5/v0.6のJSON DBも引き続き読込でき、次回の成功した保存またはMigration適用時に関係Tableへ変換します。

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
python3 -m intentir call examples/functions.intent ClampDouble --input '{"value":7}'
python3 -m intentir run examples/todo_crud.intent CreateTask \
  --input '{"id":"task-1","title":"牛乳を買う"}'
python3 -m intentir migrate examples/inventory_v2.intent --db /tmp/inventory.db
python3 -m intentir migrate examples/inventory_v2.intent --db /tmp/inventory.db --apply
python3 -m intentir build examples/todo_crud.intent --target typescript
python3 -m intentir build examples/todo_crud.intent --target sqlite
python3 -m intentir fmt --check examples/todo_crud.intent
python3 -m intentir report examples/todo_crud.intent -o /tmp/report.md
python3 -m intentir ir examples/todo_crud.intent --canonical
```

Formatterは同じ入力に繰り返し適用しても結果が変わらず、行全体の`#`コメントを保持します。v0.3の`SOURCE --emit ...`形式も互換用に残しています。

## 主なファイル

- `intentir/canonical.py`: 正規JSONと内容アドレス
- `intentir/expressions.py`: 条件、CRUD Effect、Call、Expectationの構造化
- `intentir/pure.py`: 純粋式とFunction Exampleの安全なAST lowering
- `intentir/ir.py`: 内容アドレス付きグラフと検証義務
- `intentir/validator.py`: 静的検証と構造化診断
- `intentir/verifier.py`: トランザクション型実行器とTest検証
- `intentir/storage.py`: SQLite State RepositoryとSchema Hash
- `intentir/sqlite_projection.py`: SQLite関係表投影とDDL生成
- `intentir/migration.py`: Migration Plan生成、安全性分類、State変換
- `intentir/generators/typescript.py`: TypeScript生成
- `intentir/formatter.py`: 表層構文Formatter
- `intentir/cli.py`: 開発用CLI
- `intentir/reports.py`: 日本語検証レポート
- `examples/todo_crud.intent`: CRUDライフサイクル例
- `examples/functions.intent`: 型付き純粋Functionと呼出し例
- `examples/function_actions.intent`: Requirement、Effect、EnsureからのFunction呼出し例
- `examples/inventory_v1.intent` / `inventory_v2.intent`: Migration例
- `VALIDATION_REPORT_JA.md`: v0.8 CRUD/SQLite/Migrationの検証結果
- `FUNCTION_VALIDATION_REPORT_JA.md`: v0.8純粋Functionの検証結果
- `ACTION_FUNCTION_VALIDATION_REPORT_JA.md`: v0.9 Action内Function呼出しの検証結果
- `tests/test_compiler.py`: 46件の自動テスト

## 検証済み

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q intentir tests
python3 -m intentir check examples/todo_crud.intent
python3 -m intentir test examples/todo_crud.intent
python3 -m intentir test examples/functions.intent
python3 -m intentir test examples/function_actions.intent
python3 -m intentir call examples/functions.intent ClampDouble --input '{"value":7}'
python3 -m intentir run examples/todo_crud.intent CreateTask --input '{"id":"db-1","title":"保存"}' --db /tmp/todo.db
python3 -m intentir migrate examples/inventory_v2.intent --db /tmp/inventory.db
python3 -m intentir build examples/todo_crud.intent --target typescript
python3 -m intentir build examples/todo_crud.intent --target sqlite
python3 -m intentir fmt --check examples/todo_crud.intent
python3 -m intentir report examples/todo_crud.intent
python3 -m intentir examples/todo.intent --emit verify
```

自動テストは46件で、Action内Function呼出しの型検証・原子的失敗・Python/TypeScript実行、純粋Functionの正規化、関係表投影、SQLite物理制約、改ざんMetadata保護、Migrationの安全適用・拒否・Table再構築ロールバック、v0.5/v0.6 DB互換、別プロセス間のSQLite永続化を含みます。

## 現在の制約

まだ次の要素はありません。

- Statement、Local変数、Collection、Pattern matching、Loop
- 再帰Functionと終了性検証
- 複数Module、import、package管理
- 非同期処理、HTTP、File、Clockなどの明示Capability
- Entity間のForeign KeyとRelation
- Action Effectからの部分SQL更新
- Migrationでのrename推論と手動値入力
- Debugger、Language Server
- 内容ハッシュを前提条件にするPatch IR

したがって、現時点でGoやPythonを置き換えるものではありません。次はModule/import、Entity Relation、部分SQL更新を追加し、その後に内容ハッシュを前提条件とするPatch IRへ進むのが妥当です。
