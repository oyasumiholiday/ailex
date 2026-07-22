# IntentBench-Evolve Trajectory / Model Adapter検証レポート

- 確認日: 2026-07-21
- Benchmark Schema: 0.1.0
- 対象Suite: `intentbench-evolve-smoke`、`intentbench-evolve-trajectory-smoke`
- 独立Task: 1 Task、4 Run
- Trajectory: 1 Application x 4 Condition、合計16 Checkpoint Run
- Model Adapter接続確認: 1 Condition、4 Checkpoint Run

## 目的

IntentBench-Evolveは、同じSoftware変更を異なるAgent編集Interfaceで実行し、同一の評価Testと意味的変更範囲で比較するためのHarnessです。単発Smokeに加え、一つのApplicationへ変更を積み重ねるTrajectory Runnerと、実Modelを外部Processで接続するProvider非依存Protocolを実装しました。現在のCandidateとAdapterはFixtureであり、方式間またはModel間の性能差を示す実験ではありません。

## 比較条件

| Condition | Candidate形式 | 適用方法 |
|---|---|---|
| `full-file` | 完全なIntentIR Source | Candidate全体を結果SourceとしてCompile |
| `unified-diff` | Git互換Unified Diff | `workspace.intent`だけに限定して`git apply` |
| `structure-edit` | Module/Node IDを持たない意味Operation | Runnerが現在IDを解決して意味Patchへ変換 |
| `intent-patch` | Module/Node IDを含むIntentPatch | Agent提示のHash Guardを検証して適用 |

`structure-edit`は構造単位編集Baselineです。IntentPatchと同じ意味Operation実装を利用しますが、Candidate自身は`baseModuleId`と`expectedId`を持ちません。この差により、古い状態の検出能力を今後の競合Checkpointで比較できます。

## 評価手順

1. Manifestと参照Pathを検証
2. ConditionごとのCandidateをBase Sourceへ適用
3. 結果Sourceを構文・型・参照・契約検証
4. Baseに存在したTestが削除されていないことを確認
5. `expectedChangedSymbols`外の意味変更を拒否
6. Candidateへ渡さない評価Testを追加して実行
7. Candidate Hash、出力量、変更行、変更Symbol、Test結果をJSON化

Smoke Fixture内の評価TestはHarness公開用のためRepositoryに含まれます。実際のModel比較では、Candidate生成時に評価TestをContextへ含めず、実行後にのみ結合します。

TrajectoryではConditionごとにSource状態を分離します。Checkpointが成功した場合だけ結果Sourceを次のBaseへ採用し、それまでの評価Testを累積します。失敗したTrajectoryはそのCheckpointで停止するため、後続を独立成功として数えません。

## Smoke結果

Requirementは「`WorkItem`へdefault 0のInteger `priority` Fieldを追加する」です。全Conditionが同じ結果Module IDへ到達しました。

| Condition | 判定 | Test | Changed Symbol | Candidate bytes |
|---|---:|---:|---|---:|
| `full-file` | PASS | 2 / 2 | `entity:WorkItem` | 384 |
| `unified-diff` | PASS | 2 / 2 | `entity:WorkItem` | 275 |
| `structure-edit` | PASS | 2 / 2 | `entity:WorkItem` | 259 |
| `intent-patch` | PASS | 2 / 2 | `entity:WorkItem` | 516 |

Candidate bytesはPretty-printやHash文字列を含む形式上の値であり、Model Token、Cost、正確性の優劣を意味しません。現時点で4/4成功を研究上の比較結果として使用してはいけません。

## Trajectory結果

`WorkItem`へ次の4変更を順番に適用しました。

1. `priority: Integer default 0`を追加
2. `owner: Text default "unassigned"`を追加
3. `archived: Boolean default false`を追加
4. `ArchiveWorkItem` Actionを追加

| Condition | 完了Trajectory | Checkpoint | 累積Test |
|---|---:|---:|---|
| `full-file` | 1 / 1 | 4 / 4 | 2、3、4、5件すべて成功 |
| `unified-diff` | 1 / 1 | 4 / 4 | 2、3、4、5件すべて成功 |
| `structure-edit` | 1 / 1 | 4 / 4 | 2、3、4、5件すべて成功 |
| `intent-patch` | 1 / 1 | 4 / 4 | 2、3、4、5件すべて成功 |

合計4 / 4 Trajectory、16 / 16 Checkpoint Runが成功し、全Conditionが同じ最終Module IDへ到達しました。Timingを無効にした結果JSONは複数実行で一致します。

## Model Adapter接続確認

`benchmark-model`は明示した外部Commandへ1行のRequest JSONをstdinで渡し、1個のResponse JSONをstdoutから受け取ります。Requestには現在Source、指示、Module/Node ID、Condition固有の出力契約を含めますが、評価Test本文は含めません。Responseは同じ`requestId`、Model識別子、Candidate、任意のToken usageを返します。

Candidate参照を持たないModel専用ManifestからFixture Adapterを`intent-patch`条件へ接続し、4 / 4 Checkpoint Runが成功しました。Request ID不一致は`model_response_request_mismatch`で拒否することも自動Testで確認しました。Fixtureは保存済みCandidateを返すだけであり、実Modelの生成能力を示す結果ではありません。

実Provider接続用に`intentir-openai-adapter`も追加しました。OpenAI Responses APIのStrict Structured Outputsを使ってCandidate文字列を受け取り、Provider Response ID、要求/実Model、Token usage、Prompt/Configuration ID、Reasoning設定をResultへ保存します。Network部分はFake ResponseでTest済みですが、課金を伴う実API Trialはまだ実施していません。詳細は [OPENAI_PROVIDER_VALIDATION_REPORT_JA.md](OPENAI_PROVIDER_VALIDATION_REPORT_JA.md) を参照してください。

失敗Runには`failure.stage`と診断Codeを付け、`failuresByCode`へ集計します。Provider失敗、Stale前提条件、意味Scope違反、評価Test失敗、その他Candidate失敗を分離できます。

## 安全性

- Manifest、Task、Structure Editの未知Fieldを拒否
- Manifest Directory外へ解決されるPathとSymbolic Linkを拒否
- Candidateを1 MBへ制限
- Unified Diffは`workspace.intent`だけを変更可能
- Rename、新規File、削除File、Binary Patchを拒否
- `git`実行はArgument配列、Temporary Directory、10秒Timeoutを使用
- Parse失敗時にCandidate本文やTemporary Pathを診断へ転載しない
- Timingは既定で無効にし、通常JSONを決定的に保持
- Model CommandはManifestから読まず、利用者がCLIで明示
- 外部ProcessはShellを使わずArgument配列で実行
- Model Responseを2 MB、Candidateを1 MBへ制限
- Timeout、終了Code、UTF-8、JSON契約、Request IDを検証
- API KeyはRequest、Command引数、Resultへ保存しない運用を要求

## 検証結果

```sh
python3 -m intentir benchmark \
  benchmarks/intentbench_evolve/smoke_manifest.json

python3 -m intentir benchmark \
  benchmarks/intentbench_evolve/trajectory_manifest.json

python3 -m intentir benchmark-model \
  benchmarks/intentbench_evolve/model_trajectory_manifest.json \
  --condition intent-patch \
  --adapter-command python3 \
  --adapter-arg tests/fixtures/model_adapter_fixture.py \
  --adapter-arg benchmarks/intentbench_evolve

python3 -m unittest discover -s tests -v
python3 -m compileall -q intentir tests
```

- Smoke Benchmark: 4 / 4 Run成功
- Fixture Trajectory: 4 / 4 Trajectory、16 / 16 Checkpoint Run成功
- Fixture Model Adapter: 1 / 1 Trajectory、4 / 4 Checkpoint Run成功
- OpenAI Provider Wrapper: Fake APIによるOffline Test成功、実API未実行
- 通常環境: 91 Test中90成功、MCP専用1 TestのみSkip
- optional MCP環境: 91 / 91 Test成功
- Benchmark JSONはTimingなしで複数回完全一致
- 7種類の公開JSON Schemaに対し、Fixture/Model Manifestを含む9実体が検証成功
- 配布wheelを別の仮想環境へ再Installした状態でも16 / 16 Trajectoryと4 / 4 Adapter実行が成功

## 現在の限界

- Handcrafted Candidate 1 Applicationだけで、Model生成結果ではない
- 競合変更とStale誤受理率をTrajectory内ではまだ測定していない
- Model、Prompt、Tool budget、Token、Cost、反復回数が未設定
- OpenAI Provider Wrapperはあるが、実API疎通、Cost、Rate limitは未検証
- 公開Smokeでは評価Testも最終的に閲覧可能
- Unified Diff Conditionは外部Commandの`git`を必要とする
- `structure-edit`はIntentIRの意味Operation Engineを共有するため、独立実装との比較ではない
- 統計検定、信頼区間、実Modelの失敗分布、Ablationは未実施

## 次のGate

次はModel Snapshot、Prompt ID、Configuration ID、ConditionごとのBudgetを固定し、1 Application x 4 Conditionの少額実API Pilotを行います。契約、Cost、Rate limitを確認したうえで10 Application x 4変更の40 Checkpointへ拡張し、二Agent競合、修復Round、Token、Latency、Stale誤受理、失敗分類を保存します。評価Testは生成Contextから物理的に分離し、Fixture検証と実Model Evidenceを別Artifactにします。
