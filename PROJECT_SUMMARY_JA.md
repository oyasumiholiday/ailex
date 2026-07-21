# IntentIR プロジェクトまとめ

## 現在の位置づけ

このプロジェクトでは、AI向け中間表現の参照実装 **IntentIR v0.14** を開発しました。

IntentIRは、AIまたは人間が書く小さな表層構文を、内容アドレス付き意味グラフへ変換し、そのグラフを静的検証、直接実行、TypeScript生成に利用します。AilexのようなAI向け言語と競合するものではなく、その下で意味、依存関係、Effect、契約、テスト、診断を保持する層を想定しています。

v0.14では、内容アドレス付きGraph、影響解析、Verifier、Build、IntentPatchを9個のAgent Toolとして公開しました。同じ構造化契約を依存なしのCLIと、公式SDKを使うoptionalなMCP stdio Serverから利用できます。ただし、現段階は汎用言語ではなく、純粋Function、Entity、Actionを中心にした実行可能DSLです。

Ailexの弱点分析と改善案は [AILEX_ANALYSIS_JA.md](AILEX_ANALYSIS_JA.md) にまとめています。

第一の外部提出目標は、2026年10月23日AoE締切のICSE 2027 Tool Demonstration and Data Showcaseです。提出要件、評価基準との対応、94日間のGateは [ICSE_2027_DEMO_SUBMISSION_PLAN_JA.md](ICSE_2027_DEMO_SUBMISSION_PLAN_JA.md) にまとめています。

## v0.14までに実装したもの

### モデル非依存Agent ToolとMCP接続

`describe_module / get_node / get_context / get_impact / validate_patch / apply_patch / verify / render_diff / build`を実装しました。Agentは全文Sourceを毎回読む代わりに、対象Node、局所Context、逆依存Impact、検証義務を構造化JSONとして取得できます。

Agent Toolの本体は外部依存のない`AgentService`です。`intentir agent`から直接呼び出せるほか、optionalな公式MCP Python SDKを導入すると`intentir-mcp --root .`でstdio Serverとして公開できます。全Source Pathは指定したProject Root内に制限され、Source書込みは既定で無効です。書込みには`--allow-writes`が必要で、MCP上でも読取りToolと破壊的Toolをannotationで区別します。詳細は [AGENT_MCP_VALIDATION_REPORT_JA.md](AGENT_MCP_VALIDATION_REPORT_JA.md) にまとめています。

### 二Agent競合編集Demo

`python3 -m intentir demo concurrent-agent`で、二つのAgentが同じModule/Node IDからPatchを作るScenarioを再現できます。Agent Aの適用後、Agent Bの古いPatchは`stale_base_module`で拒否されます。Agent Bは最新Graphを取得してPatchを再生成し、検証後に適用します。最終的にTypeScriptとSQLite Artifactも生成し、Repository内のFixtureは変更しません。機械可読な証跡は`--json`で取得できます。

### IntentBench-Evolve Harness

`python3 -m intentir benchmark benchmarks/intentbench_evolve/smoke_manifest.json`で、Full-file、Unified Diff、Structure Edit、IntentPatchの4条件を同じ評価Testへ通せます。Manifest外Path、別Fileを狙うDiff、Baseline Test削除、想定外Symbol変更を拒否し、Candidate Hash、出力量、変更行、変更Symbol、Test結果を決定的JSONとして保存できます。最初の4/4 SmokeはHarness検証であり、Model間・方式間の性能証拠ではありません。詳細は [BENCHMARK_VALIDATION_REPORT_JA.md](BENCHMARK_VALIDATION_REPORT_JA.md) にまとめています。

`trajectory_manifest.json`では、一つのApplicationへ4段階の変更を順に適用します。ConditionごとにSource状態を分離し、成功した結果だけを次のCheckpointへ渡し、それまでの評価Testを累積します。Fixtureでは4編集条件の4 / 4 Trajectory、合計16 / 16 Checkpoint Runが成功しました。

`benchmark-model`は、特定Providerへ依存しないJSON stdin/stdout Protocolで一つのConditionを外部Model Wrapperへ接続します。Requestは現在Source、指示、Module/Node ID、出力契約を含み、評価Test本文を含みません。CommandはManifestから受け取らずCLIで明示し、Shellなし、Timeout、Response/Candidate Size上限、Request ID照合を行います。Fixture Adapterによる4 / 4接続確認は完了していますが、実Modelの性能証拠ではありません。

実Provider参照実装として、Python標準LibraryだけでOpenAI Responses APIへ接続する`intentir-openai-adapter`を追加しました。Strict Structured OutputsでCandidateを受け取り、API Keyは環境変数からのみ読みます。ResultにはToken、Provider Response ID、要求/実Model、Prompt/Configuration Hash、Reasoning設定を保存し、失敗を段階別に集計します。Network部分はFake Responseで検証済みですが、実API Trialはまだ実施していません。詳細は [OPENAI_PROVIDER_VALIDATION_REPORT_JA.md](OPENAI_PROVIDER_VALIDATION_REPORT_JA.md) にまとめています。

### 内容ハッシュで保護されたIntentPatch

`schemaVersion / baseModuleId / operations / requestedObligations`を持つJSON Envelopeで、AIが定義またはメンバー単位の変更を提案できます。`add_definition`、`replace_definition`、`remove_definition`、`rename_symbol`、`set_member`、`insert_member`、`remove_member`の7操作を実装しました。

古いModuleやNodeを前提にしたPatchは安定した診断Codeで拒否します。全操作の適用後に再コンパイルし、静的検証と指定されたTest義務を実行するため、途中まで書き換えた状態は保存されません。成功時にはPatch ID、新Module ID、変更Symbol、影響Symbol、実行義務、人間向けDiffを返します。詳細は [PATCH_VALIDATION_REPORT_JA.md](PATCH_VALIDATION_REPORT_JA.md) にまとめています。

### 明示Capabilityと決定的な環境注入

Clockのような外部環境値を、暗黙のグローバル処理ではなく型付きCapabilityとして宣言できます。

```intentir
capability Clock:
  operation now returns Text

entity Event:
  id: UUID required key
  title: Text required
  createdAt: Text required

action CreateEvent:
  input:
    id: UUID required
    title: Text required
  uses:
    Clock.now as createdAt
  effects:
    insert Event

test "fixed clock":
  given Clock.now = "2026-07-16T09:00:00+09:00"
  when CreateEvent(id="event-1", title="ship")
  expect Event exists with createdAt "2026-07-16T09:00:00+09:00"
```

Capabilityは内容アドレス付きNode、Actionからは`uses` Edge、Testからは`stubs` Edgeになります。BindingはAction Inputとは分離したままRequirement、Effect、Ensureの型付きScopeへ追加されます。

Python実行器とCLIは`{"Clock.now":"固定値"}`形式で値を受け取り、欠落と型不一致をEffect前に拒否します。生成TypeScriptはProvider型、Actionごとの必要Operation型、実行時Return型検査、Test Stubを生成します。Capabilityの意味変更はModule Hashへ入りますが、永続データ構造ではないためStorage Schema Hashには入りません。

### Entity Relationと部分SQL保存

Fieldに`ref Entity.field`を宣言し、参照先を構造化IRと`references` Edgeへ変換できます。

```intentir
entity Project:
  id: UUID required key

entity Task:
  id: UUID required key
  projectId: UUID required ref Project.id
```

コンパイル時に参照先Entity/Fieldの存在、Key/Unique、一致する型、循環参照を検証します。Python実行器とTypeScript生成コードは、孤児レコードの作成や子が残る親の削除を原子的に拒否します。SQLiteでは同じ制約を`FOREIGN KEY ... ON UPDATE RESTRICT ON DELETE RESTRICT`へ投影し、親から子の順でTable作成・挿入、子から親の順で削除します。

`run --db`の初回保存は従来どおり全Tableを構築します。2回目以降、変更対象EntityにKeyがある場合は差分行だけを`INSERT / UPDATE / DELETE`し、結果の`storage.writeMode`で`replace`または`incremental`を確認できます。KeyなしEntityは安全のため全置換へフォールバックします。

既存Fieldへの参照追加・変更はデータ修復が必要になり得るためMigrationでは`manual`、参照削除は`safe`と判定します。

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

### 内容アドレス付きModule/import

相対ImportでFunction、Entity、Action、Testを複数ファイルへ分割できます。

```intentir
module ModularTodo

import "./task.intent"
```

Importは推移的に解決され、各定義には`definedIn`、Module間には`imports` Edge、Moduleから定義には`defines` Edgeが付きます。Module NodeはローカルMember IDと依存Module IDを含むため、依存先の意味変更がルートModule IDへ伝播します。一方、`./task.intent`と`task.intent`のようなパス表記差は意味Hashへ入りません。

循環Import、同名Module、欠落ファイル、絶対Import、リンク後の同名Symbolは拒否します。現段階では全Symbolが公開され、リンク後は1つのフラット名前空間になります。

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

Repository CapabilityはEffectから決定的に推論します。v0.12ではこれとは別に、Clockなどの外部環境値を表す明示Capabilityを追加しました。

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
python3 -m intentir patch examples/todo_crud.intent examples/add_task_priority.patch.json
python3 -m intentir agent intentir.describe_module --root . \
  --arguments '{"source":"examples/todo_crud.intent"}'
python3 -m intentir build examples/todo_crud.intent --target typescript
python3 -m intentir build examples/todo_crud.intent --target sqlite
python3 -m intentir fmt --check examples/todo_crud.intent
python3 -m intentir report examples/todo_crud.intent -o /tmp/report.md
python3 -m intentir ir examples/todo_crud.intent --canonical
```

Formatterは同じ入力に繰り返し適用しても結果が変わらず、行全体の`#`コメントを保持します。v0.3の`SOURCE --emit ...`形式も互換用に残しています。

## 主なファイル

- `intentir/canonical.py`: 正規JSONと内容アドレス
- `intentir/compiler.py`: 再帰的なImport解決とModule Link
- `intentir/expressions.py`: 条件、CRUD Effect、Call、Expectationの構造化
- `intentir/pure.py`: 純粋式とFunction Exampleの安全なAST lowering
- `intentir/ir.py`: 内容アドレス付きグラフと検証義務
- `intentir/validator.py`: 静的検証と構造化診断
- `intentir/verifier.py`: トランザクション型実行器とTest検証
- `intentir/storage.py`: SQLite State RepositoryとSchema Hash
- `intentir/sqlite_projection.py`: SQLite関係表投影とDDL生成
- `intentir/migration.py`: Migration Plan生成、安全性分類、State変換
- `intentir/patch.py`: 意味Patch、Hash Guard、影響解析、原子的適用
- `intentir/agent.py`: Project Rootで境界付けた9個のAgent Tool
- `intentir/mcp_server.py`: optional MCP stdio AdapterとJSON Schema
- `intentir/trajectory.py`: 累積評価を行う複数Checkpoint Runner
- `intentir/model_adapter.py`: 外部Model用Request/Response Protocol
- `intentir/providers/openai_responses.py`: OpenAI Responses API参照Wrapper
- `intentir/generators/typescript.py`: TypeScript生成
- `intentir/formatter.py`: 表層構文Formatter
- `intentir/cli.py`: 開発用CLI
- `intentir/reports.py`: 日本語検証レポート
- `examples/todo_crud.intent`: CRUDライフサイクル例
- `examples/functions.intent`: 型付き純粋Functionと呼出し例
- `examples/function_actions.intent`: Requirement、Effect、EnsureからのFunction呼出し例
- `examples/modules/app.intent`: 3ファイルの推移Import例
- `examples/relations.intent`: Entity参照と親子ライフサイクル例
- `examples/capabilities.intent`: 明示Capabilityと決定的Clock注入例
- `examples/inventory_v1.intent` / `inventory_v2.intent`: Migration例
- `VALIDATION_REPORT_JA.md`: v0.8 CRUD/SQLite/Migrationの検証結果
- `FUNCTION_VALIDATION_REPORT_JA.md`: v0.8純粋Functionの検証結果
- `ACTION_FUNCTION_VALIDATION_REPORT_JA.md`: v0.9 Action内Function呼出しの検証結果
- `MODULE_VALIDATION_REPORT_JA.md`: v0.10 Module/importの検証結果
- `RELATION_VALIDATION_REPORT_JA.md`: v0.11 Entity Relation/部分SQLの検証結果
- `CAPABILITY_VALIDATION_REPORT_JA.md`: v0.12 Capabilityの検証結果
- `PATCH_VALIDATION_REPORT_JA.md`: v0.13 IntentPatchの検証結果
- `AGENT_MCP_VALIDATION_REPORT_JA.md`: v0.14 Agent/MCP接続の検証結果
- `SECURITY_QUALITY_CHECKLIST_JA.md`: Releaseごとに使うセキュリティ・品質運用Checklist
- `SECURITY_QUALITY_BASELINE_2026-07-21_JA.md`: 初回の判定、公開停止事項、検証証跡
- `ICSE_2027_DEMO_SUBMISSION_PLAN_JA.md`: ICSE 2027 Tool Demonstrationの提出要件と逆算計画
- `demo/concurrent_agent/`: 二Agent競合編集のSource Fixtureと利用手順
- `intentir/demos/concurrent_agent.py`: 自己完結Demo Runnerと人間向け表示
- `benchmarks/intentbench_evolve/`: 4条件Smoke、4段階Trajectory、Candidate、JSON Schema
- `intentir/benchmark.py`: Manifest自動判別、4 Adapter、共通評価、Result集計
- `BENCHMARK_VALIDATION_REPORT_JA.md`: Harness、Trajectory、Model Adapterの検証結果と限界
- `OPENAI_PROVIDER_VALIDATION_REPORT_JA.md`: Provider Wrapper、Provenance、安全性、未検証範囲
- `docs/SECURITY_QUALITY_REVIEW_CRITERIA_JA.md`: 改変しない完全版Review基準
- `SECURITY.md`: 脆弱性の非公開報告方針
- `AILEX_README.md`: Ailex表層言語の概要、利用方法、研究上の根拠
- `core/` / `package.json`: Ailex実装とnpm Package設定
- `uv.lock`: optional MCP依存を含む再現可能な依存Lock
- `LICENSE`: Ailex既存実装のMIT License
- `LICENSE-APACHE`: IntentIR Python Packageと新規関連FileのApache License 2.0全文
- `tests/test_agent.py` / `tests/test_mcp_server.py`: Agent接続の自動テスト
- `tests/`: 合計91件の自動テスト

## 検証済み

```sh
npm test
python3 -m unittest discover -s tests -v
python3 -m compileall -q intentir tests
python3 -m intentir check examples/todo_crud.intent
python3 -m intentir test examples/todo_crud.intent
python3 -m intentir test examples/functions.intent
python3 -m intentir test examples/function_actions.intent
python3 -m intentir test examples/modules/app.intent
python3 -m intentir test examples/relations.intent
python3 -m intentir test examples/capabilities.intent
python3 -m intentir call examples/functions.intent ClampDouble --input '{"value":7}'
python3 -m intentir run examples/todo_crud.intent CreateTask --input '{"id":"db-1","title":"保存"}' --db /tmp/todo.db
python3 -m intentir migrate examples/inventory_v2.intent --db /tmp/inventory.db
python3 -m intentir build examples/todo_crud.intent --target typescript
python3 -m intentir build examples/todo_crud.intent --target sqlite
python3 -m intentir fmt --check examples/todo_crud.intent
python3 -m intentir report examples/todo_crud.intent
python3 -m intentir patch examples/todo_crud.intent examples/add_task_priority.patch.json
python3 -m intentir agent intentir.get_impact --root . --arguments \
  '{"source":"examples/todo_crud.intent","symbols":["entity:Task"]}'
python3 -m intentir benchmark benchmarks/intentbench_evolve/trajectory_manifest.json
python3 -m intentir benchmark-model benchmarks/intentbench_evolve/model_trajectory_manifest.json \
  --condition intent-patch --adapter-command python3 \
  --adapter-arg tests/fixtures/model_adapter_fixture.py \
  --adapter-arg benchmarks/intentbench_evolve
python3 -m intentir examples/todo.intent --emit verify
```

Ailexは89件の適合Testが成功します。IntentIRの自動Testは91件です。90件は外部依存なしで実行でき、1件はoptional MCP環境でTool discovery、入力・出力Schema、stdio実呼出し、構造化失敗を検証します。Benchmark境界、4段階Trajectory、Model Adapter契約、OpenAI ProviderのOffline Response、Provenance、失敗分類、二Agent競合Demo、従来のPatch、Capability、Module Link、Entity参照、部分SQL、Migration、旧DB互換、SQLite永続化も引き続き含みます。

セキュリティ・品質の運用基準と初回確認結果は、[SECURITY_QUALITY_CHECKLIST_JA.md](SECURITY_QUALITY_CHECKLIST_JA.md) と [SECURITY_QUALITY_BASELINE_2026-07-21_JA.md](SECURITY_QUALITY_BASELINE_2026-07-21_JA.md) に分離しました。AilexのMIT Licenseを保持したままIntentIRをApache-2.0として分離し、初回Commitで公開対象とRollback点を固定しました。Git remoteは既存v0.12履歴と照合済みですが、GitHub側の保護設定とCI実行結果が未確認のため、公開・Release可能という判定にはしていません。

## 現在の制約

まだ次の要素はありません。

- Statement、Local変数、Collection、Pattern matching、Loop
- 再帰Functionと終了性検証
- Import alias、private export、package manifest、registry、version constraint
- Capability Operationへの引数と実際の外部I/O実行
- Relationの循環、Cardinality、Cascade、Join Query
- KeyなしEntityに対する部分SQL更新
- 引数付きCapability Operation、HTTP/File Adapter、Async、Retry、Secret Policy
- Migrationでのrename推論と手動値入力
- Debugger、Language Server
- Patch対象はRoot Source内の定義に限定され、Import先の変更はそのSourceへ直接Patchする必要がある
- PatchのMember Pathは現在のEntity、Action、Function、Capability、Test構造に限定される
- 変更した定義内のコメントはCanonical Formatで保持されない場合がある
- MCP接続はLocal stdioのみで、Remote HTTP、認証、Resource、Promptは未実装
- 書込み有効時の利用者承認UIと永続監査LogはHost側で未確認
- OpenAI Provider Wrapperは実装済みだが、実API疎通、Account権限、Cost、Rate limitは未検証
- TrajectoryはHandcraftedな1 Applicationだけで、実Modelを使う40 Checkpoint Pilotは未実施

したがって、現時点でGoやPythonを置き換えるものではありません。次はModel Snapshot、Prompt、Budgetを固定した少額実API Pilotを行い、その後10 Application x 4変更の40 Checkpointへ拡張します。そこで実測Evidenceを作った後、引数付きCapability、Package境界、Relation Queryへ進むのが妥当です。
