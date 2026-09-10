# OpenAI 校正v3 実モデル検証レポート

実施日: 2026-07-24
Protocol ID: `intentbench-evolve-openai-calibration-v3-2026-07-24`
Protocol Hash: `sha256:9afe9e1b17a60ab94b2ae5f4e947c01c48a76760c2b2337ea0ab426e1bed979d`

## 1. 結論

校正v3はOpenAI Responses APIを11回呼び出し、11 checkpoint中9件を受理した。実計上額は0.040957 USDで、承認上限1.00 USD以内だった。

特に、Ailex/IntentIR固有の意味編集形式である`intent-patch`が4段階をすべて完走した。校正v2で最初のcheckpointに失敗した`member` Collectionと`value`型の契約不足は、v3の機械可読な値域追加によって解消した。

一方、`unified-diff`は最初のcheckpointで停止し、`structure-edit`は2番目で停止した。残った問題は次の2点である。

- unified diffのhunk headerは正しくなったが、変更行より後の未変更行を含まない差分を`git apply`が受理しなかった。
- structure editで、モデルが`kind`を操作種別ではなく対象Definition種別の`entity`として生成した。

これは方式間の性能比較ではない。同じ1課題を使った3回目の反復校正であり、n=1かつ条件ごとに到達checkpointが異なるため、一般化性能や優劣は主張しない。

## 2. 実験条件

| 項目 | 値 |
|---|---|
| Model | `gpt-5.4-mini-2026-03-17` |
| Reasoning | `medium` |
| API保存 | `store: false` |
| Conditions | full-file / unified-diff / structure-edit / intent-patch |
| Provider call | 11 |
| 入力tokens | 11,613 |
| 出力tokens | 7,166 |
| 実計上額 | 0.040957 USD |
| 事前最大予約額 | 0.678912 USD |
| 承認上限 | 1.00 USD |
| 自動再試行 | なし |

## 3. 条件別結果

| 条件 | 実行 | 成功 | 軌跡結果 |
|---|---:|---:|---|
| full-file | 4 | 4 | 全checkpoint完走 |
| unified-diff | 1 | 0 | add-priorityで差分適用失敗 |
| structure-edit | 2 | 1 | add-priority成功、add-ownerで操作種別誤り |
| intent-patch | 4 | 4 | 全checkpoint完走 |

軌跡単位では4条件中2条件が完走し、2条件が途中停止した。成功した9件は、構文検査、変更Symbol範囲、既存Test保持、可視Test、累積hidden testをすべて通過した。

## 4. 事前仮説の判定

| 仮説 | 判定 | 根拠 |
|---|---|---|
| H1: unified-diffが2 checkpoint以上を完了 | 不支持 | 行範囲付きheaderは生成したが、最初のhunkを適用できず0/1 |
| H2: structure-editが`member: fields`とname/typeを生成 | 支持 | add-priorityで正しい`insert_member`を生成し、可視・hidden testに成功 |
| H3: intent-patchが最初のcheckpointを通過 | 支持 | 最初だけでなく4/4を完走 |
| H4: 不正member診断のscopeに`fields`を含む | 支持（Offline） | 自動回帰Testで固定。今回の実モデル候補は不正memberを生成しなかった |

H1の失敗はhunk header型の修正が無効だったことを意味しない。v2の`@@`のみという構文誤りは解消し、次の暗黙条件である「変更後の未変更Context」が観測された。

## 5. 新しく観測した契約ギャップ

### 5.1 unified diffは変更後のContextも必要

モデルは次のような行範囲付き差分を生成した。

```diff
--- a/workspace.intent
+++ b/workspace.intent
@@ -3,4 +3,5 @@
 entity WorkItem:
   id: UUID required key
   title: Text required
   status: Text default "open"
+  priority: Integer default 0
```

変更内容、対象path、hunk headerの行数は意図に沿っていたが、`git apply --check`はこのhunkを適用しなかった。現在の出力契約はheader形式だけを指定し、各変更の前後に未変更行を含める必要性を明記していない。

次の校正では、最低1行の前後Contextを要求し、差分適用失敗時には`git apply`の安全に整形した理由を診断へ残す。これにより、モデル契約の不足と評価器の不具合を区別しやすくする。

### 5.2 structure editの`kind`が二つの意味に見える

add-priorityでは正しい候補を生成した。

```json
{
  "kind": "insert_member",
  "target": "entity:WorkItem",
  "member": "fields",
  "value": {"name": "priority", "type": "Integer", "default": 0}
}
```

しかしadd-ownerでは`kind: "entity"`とし、別Fieldの`operation: "insert_member"`を追加した。契約には操作ごとのField一覧があるものの、`kind`が操作種別であり、対象Definition種別は`target`のprefixにだけ現れることが十分明確でなかった。

次の校正では、`kind`を`operationKind`へ改名するか、JSON Schemaの列挙値と短い正例を提示する。独自形式の`intent-patch`は同じ課題を完走したため、まずstructure-editとの契約差を最小化する。

## 6. 費用内訳

| Call | 条件 / checkpoint | 入力 | 出力 | USD |
|---:|---|---:|---:|---:|
| 1 | full-file / add-priority | 795 | 158 | 0.001307 |
| 2 | full-file / add-owner | 783 | 165 | 0.001330 |
| 3 | full-file / add-archive-state | 805 | 170 | 0.001369 |
| 4 | full-file / add-archive-action | 810 | 274 | 0.001840 |
| 5 | unified-diff / add-priority | 867 | 488 | 0.002846 |
| 6 | structure-edit / add-priority | 1,209 | 849 | 0.004727 |
| 7 | structure-edit / add-owner | 1,204 | 822 | 0.004602 |
| 8 | intent-patch / add-priority | 1,277 | 1,331 | 0.006947 |
| 9 | intent-patch / add-owner | 1,275 | 714 | 0.004169 |
| 10 | intent-patch / add-archive-state | 1,291 | 602 | 0.003677 |
| 11 | intent-patch / add-archive-action | 1,297 | 1,593 | 0.008141 |

## 7. セキュリティ

- API KeyはProvider payload、Artifact、Git管理Fileへ保存していない。
- API Keyは実行直後にmacOSの一時環境変数から削除し、削除済みであることを確認した。
- クリップボードは実行前に消去した。
- TLS証明書検証は無効化せず実行した。
- API側のResponse保存は`store: false`とした。
- 生Artifactは`artifacts/`配下に置き、Git管理対象外とした。

## 8. 次の判断

追加の有料校正をすぐには行わない。まずOfflineで次を実装・検証する。

1. unified diff契約へ変更前後のContext要件を追加する。
2. 差分適用失敗の安全な詳細診断を追加する。
3. structure editの操作種別Fieldを曖昧でない名前・Schemaへ寄せる。
4. 同じCandidateを使う回帰Testを追加する。
5. 変更後に別Protocol IDでpreflightを固定する。

その後の有料再実行には、新しい明示承認と新しいAPI Keyが必要である。校正系が安定した後は、同じ課題の反復ではなく未使用課題による本評価へ移る。

## 9. 成果物

- 実行Directory: `artifacts/intentbench/openai-calibration-v3-2026-07-24/`
- Protocol: `benchmarks/intentbench_evolve/openai_calibration_v3_protocol.json`
- 事前計画: `OPENAI_CALIBRATION_V3_PLAN_2026-07-24_JA.md`
- Summary: `artifacts/intentbench/openai-calibration-v3-2026-07-24/summary.json`
