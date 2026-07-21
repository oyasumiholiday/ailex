# ICSE 2027 Tool Demonstration提出計画

- 対象Track: ICSE 2027 Tool Demonstration and Data Showcase
- 公式募集要項: https://conf.researchr.org/track/icse-2027/icse-2027-demonstrations
- 確認日: 2026-07-21
- Submission deadline: 2026-10-23 AoE
- Project内の目標締切: 2026-10-16 JST
- 対象Artifact: IntentIR / IntentPatch / MCP Agent Tools

## 提出方針

IntentIRは**Tool Demonstration**として提出します。主役は新しいProgramming Language一般ではなく、AI Agentの変更を内容Hash、型、依存関係、検証義務で保護する意味編集Runtimeです。

仮Titleは次とします。

> **IntentIR: Hash-Guarded Semantic Patches for Reliable AI-Assisted Software Evolution**

中心となる候補Research Questionは次です。

> **Do hash-guarded, obligation-aware semantic patches improve the reliability and repair cost of iterative AI-generated software changes compared with text-based editing?**

このRQは提出準備の作業仮説です。比較実験の結果が出るまでは、改善効果を事実として主張しません。

## 公式要件

公式募集要項から、Tool Demonstrationに直接関係する要件を抜き出したものです。原文が更新された場合は公式ページを正とします。

| 要件 | 内容 | IntentIRでの対応 |
|---|---|---|
| Paper | IEEE conference形式、PDF、参考文献等を含め4ページ以内 | IEEEtran 10ptで英語Paperを作成 |
| Review | Single-anonymous、著者情報を記載 | 著者、所属、ORCIDを準備 |
| Video | 3〜5分、YouTubeで査読期間中に公開 | 英語音声または英語Annotation付きDemoを作成 |
| Video URL | Abstract末尾へURLを記載 | 提出前Checklistで確認 |
| Public tool | 公開Toolと利用手順へのLinkが必須 | Public repository、Release、Quickstartを用意 |
| Easy distribution | 査読者にBuildを要求せず、Web、VM、Container等で利用可能にする | Version固定Containerを第一候補にする |
| Prior publication | Demonstration形式で未発表であること | 重複投稿と既発表範囲を提出前に確認 |
| Policies | ACM/IEEEの盗用、出版、Human Participants関連Policyに従う | 引用監査、AI利用開示、Study設計確認を行う |
| Artifact Evaluation | 採択後に補助Artifactを別途提出可能 | Reusable/Available badgeを狙える状態にする |
| Carbon | 適切な場合はCarbon footprintの議論を推奨 | 実験Compute、Model呼出し、限界を記録 |

公式日程は次のとおりです。

| Event | Date |
|---|---|
| Submission deadline | 2026-10-23 AoE |
| Acceptance notification | 2026-12-11 |
| Camera ready | 2027-01-20 |

## Toolの一文説明

> IntentIR is a model-independent semantic edit runtime that turns AI-generated changes into hash-guarded, typed, and verifiable transactions.

対象利用者は、Coding Agent研究者、Agent Tool開発者、AI支援によるSoftware Evolutionの安全性を評価する研究者です。

扱うSoftware Engineering上の問題は次の3点に限定します。

1. Agentが古いContextを前提に変更を適用する
2. 行ベースPatchが構文的に適用できても意味的な回帰を起こす
3. 変更の影響範囲と実行すべき検証義務が明示されない

## 評価基準への対応

| ICSE評価基準 | 提出時に示すEvidence | 現状 |
|---|---|---|
| ICSE audienceへの関連性 | Coding Agentの反復編集と競合変更の失敗Scenario | 4段階Trajectoryは実装済み、外部Taskは未実装 |
| Technical soundness | Hash Guard、型検証、依存Impact、Transaction、91自動Test | Local検証済み、GitHub CI実行は未確認 |
| Novelty | Content addressing、semantic patch、verification obligationを統合したAgent編集Protocol | 新規性の境界を文献比較で要検証 |
| Video quality | 競合編集を中心にした3〜5分の実動Demo | Core flowは実装済み、動画は未作成 |
| Usefulness | MCP経由の利用、1コマンド実行、比較Pilot、第三者再現 | Local/installed wheelの1コマンドDemoは実装済み、Containerと外部再現は未達 |
| Relevant literature | Semantic Patch、content-addressed code、Agent interface、typed context、structure-aware editとの比較 | 候補文献あり、引用内容の一次資料確認が必要 |

## Core Demo

> **実装状況 2026-07-21:** `python3 -m intentir demo concurrent-agent`と`--json`を実装済みです。Agent A適用、Agent BのStale拒否、最新IDでの再生成、最終検証、TypeScript/SQLite Buildを一時Workspaceで再現し、通常環境とMCP環境を含む91 Testが成功しています。

DemoではToDo機能の多さではなく、競合編集を安全に処理する一つの流れを見せます。

1. Agent AとAgent Bが同じ`baseModuleId`を取得する
2. Agent Aが意味Patchを検証し、Diffを表示して適用する
3. Module IDが変わった後、Agent Bの古いPatchを`stale_base_module`で拒否する
4. Agent Bが新しいContextとImpactを取得してPatchを再生成する
5. 型、契約、影響Testを実行してからPatchを確定する
6. 同じ意味GraphからPython実行、TypeScript、SQLite DDLの整合した結果を示す

動画では、Toolの全機能を列挙せず、このWorkflowを中心にします。

## 最小比較評価

Tool Demonstrationでも、成熟ToolならValidation結果、初期Prototypeなら計画したStudy designを明確にする必要があります。IntentIRでは提出までに小規模でも実測値を用意します。

### 比較条件

| Condition | Editing interface |
|---|---|
| A | Full-file rewrite |
| B | Unified Diff |
| C | Function/Block単位のstructure-aware edit |
| D | IntentPatch |

### Pilot規模

- 10個の小型Stateful Application
- 各Applicationへ4段階の仕様変更
- 合計40 Checkpoint
- 可能なら2 Model family、最低でも1 ModelのVersion固定条件
- 公開Testと、Trajectory実行時にAgentへ見せない評価Test
- Prompt、Tool schema、Token、Latency、Patch、診断、Test結果を保存

### Primary metrics

- End-to-End trajectory completion rate
- Verification obligation / hidden test pass rate
- Patch application success rate
- Stale Patch false acceptance rate

### Secondary metrics

- Repair rounds
- Input/output token
- Wall-clock latency
- Unnecessary changed nodes
- Regression count

40 Checkpointは計画値であり、実施前に性能主張へ使いません。時間不足時もBaselineを減らさず、Task数またはModel数を明示的に縮小します。

> **Harness状況 2026-07-21:** 1 Application x 4変更 x 4編集条件のFixture Trajectoryを実装し、16 / 16 Checkpoint Runが成功しました。外部Command型Model Adapter、OpenAI Responses API Wrapper、Trial Provenance、失敗分類も実装し、Fake APIで検証しています。課金を伴う実Model Trialは未実施であり、現在の結果は性能Evidenceではありません。

## 査読者向けArtifact

査読者にSource buildを要求しないため、次の入口を用意します。

- Version固定済みOCI Container
- `docker run`から始まる5分以内のQuickstart
- 競合編集Demoを再生する1 Command
- 40 Checkpoint Pilotを再実行するCommandと、短時間のSmoke subset
- 英語README、Architecture図、制約、Troubleshooting
- Source、Test、実験Manifest、Raw result、集計Script
- Release tagと永続Archive。可能ならZenodo DOI
- Security上、書込みは既定無効のままにし、Demoだけ明示許可

公開Repository URLとContainer registryは、Local repositoryの接続先を確定してから記載します。

## 4ページPaperの構成

| 範囲 | 目的 |
|---|---|
| Abstract | 問題、Tool、Evidence、Video URL |
| Introduction | Stale/textual editの問題、対象利用者、Contribution |
| Approach | Semantic graph、Hash Guard、obligation-aware Patch |
| Tool workflow | MCP Toolと競合編集Demo |
| Evaluation | Pilot設定、結果、失敗例、制約 |
| Related work | 最も近い方式との差分 |
| Availability | Public tool、Container、Repository、Artifact |

ページ配分は結果と図の密度を見て決めます。4ページに収まらない機能説明はREADMEとArtifactへ移します。

## 3〜5分Video構成

| Time | 内容 |
|---|---|
| 0:00〜0:25 | Coding Agentが古いContextで編集する問題 |
| 0:25〜0:55 | IntentIRとIntentPatchの最小Architecture |
| 0:55〜2:35 | 二Agent競合DemoとStale拒否 |
| 2:35〜3:25 | 再取得、再検証、複数Backendへの反映 |
| 3:25〜4:10 | Pilot結果と失敗例 |
| 4:10〜4:35 | 利用方法、公開Artifact、制約 |

## 94日間の実行計画

### Gate A: 公開可能な基礎 2026-07-21〜07-31

- [x] AilexのMITを保持し、IntentIRのApache License 2.0をPackage metadataへ反映
- [x] 初回Commitで公開対象とRollback点を固定
- [x] Git remoteを確定し、既存Repositoryとの履歴を照合
- GitHub CI、Secret scanning、Push protection、Branch protectionを確認
- `CITATION.cff`、`CONTRIBUTING.md`、Issue templateを追加
- Containerと英語Quickstartの最小版を作成
- `SECURITY_QUALITY_BASELINE_2026-07-21_JA.md`の公開停止事項を解消

### Gate B: DemoとBenchmark harness 2026-08-01〜08-21

- [x] 二Agent競合ScenarioをFixture化
- [x] Demoを1 Commandで再生
- [x] IntentBench-EvolveのTask schema、Runner、Result schemaを実装
- [x] 4段階Trajectory Manifest、累積評価、途中失敗停止を実装
- [x] 外部Model Adapter Protocol、Request/Response schema、CLIを実装
- [x] OpenAI Responses API Wrapper、Trial Provenance、失敗分類を実装
- 4編集条件の公平なPrompt/Tool budgetを固定
- [x] Smoke TaskでEnd-to-End実行

### Gate C: Pilotと外部再現 2026-08-22〜09-15

- 40 Checkpoint Pilotを実行
- 結果集計と失敗分類
- Ablationまたは最小限の因果確認
- 第三者2名以上にContainerから再現を依頼
- 問題があれば主張を縮小し、Tool workflowを改善

第三者の行動を研究Dataとして分析・公表する場合は、ACM Human Participants Policyと所属機関の手続きを先に確認します。単なる動作確認と研究参加を混同しません。

### Gate D: PaperとVideo初稿 2026-09-16〜10-05

- 4ページ英語Paper初稿
- 引用と新規性のSource verification
- Architecture/Result Figure
- 3〜5分Video初稿
- Public Release候補と再現手順を凍結

### Gate E: 査読前監査 2026-10-06〜10-16

- ICSE評価基準に沿った模擬Review
- Security/Quality Checklistを再実行
- 別環境でContainerとSmoke benchmarkを再現
- IEEE形式、4ページ、著者情報、ORCID、Video URLを確認
- 2026-10-16 JSTまでに提出可能版を完成

### Gate F: 提出 2026-10-17〜10-23 AoE

- HotCRP metadataとConflictを確認
- YouTube動画の公開範囲と再生を確認
- Public toolと利用手順のLinkを確認
- PDF最終監査後、公式締切より前に提出

## Go / No-Go

2026-09-15時点で次を満たせない場合、主張または提出方針を縮小します。

- 公開Toolを査読者がBuildなしで起動できる
- Core Demoが5分以内に安定して再現できる
- Stale Patchを誤受理しないことをTestとDemoで示せる
- 比較条件と評価Dataが第三者に説明可能
- 近接研究との差分を、誇張せずに説明できる

比較結果が改善を示さない場合も隠しません。その場合は、IntentPatchが防止できる失敗条件と、効果がない条件をTool Demonstrationの貢献として明確化します。

## 直近の開発順

1. 公開停止事項のうちGitHub設定とCI確認を解消
2. `[完了]` `demo/concurrent_agent`として二Agent競合Scenarioを自動実行可能にする
3. Containerから同じDemoを1 Commandで実行できるようにする
4. Benchmark ManifestとResult schemaを定義する
5. 4条件を公平に実行する最小Runnerを作る
6. Smoke benchmarkの結果を日本語Reportへ出す

## 未確定事項

- 正式な著者と所属
- 全著者のORCID
- Public repositoryとContainer registry
- Pilotで利用するModelと予算
- 外部再現協力者
- Artifactの永続Archive先
- Human participantsに該当するStudyを行うか

これらはPaper本文の事実として推測せず、確定後に記載します。
