# OpenAI 校正v4 実モデル検証レポート

実施日: 2026-07-24
Protocol ID: `intentbench-evolve-openai-calibration-v4-2026-07-24`
Protocol Hash: `sha256:b852c37b76625f3a6c3a5a650b1f3060f3182cb1eb5eeab250f9ebb08160bf42`
Prompt Version: `intentir-openai-responses-v4`
Prompt ID: `sha256:9eba9265db27dca7e915a8d5b303bfa7a71a091198e9f76473f7dd9d01a8a76e`
Configuration ID: `sha256:9b5b186740ad7f40902705213a9ee60095d356d7daca40987605a411491dddbd`

## 1. 結論

校正v4はOpenAI Responses APIを16回呼び出し、全16 checkpointを受理した。4編集条件すべてが4段階の軌跡を完走し、実計上額は0.046466 USDで承認上限1.00 USD以内だった。

校正v3で残った2つの契約ギャップは、この同一課題上では解消した。

- unified-diffは変更後の未変更Contextを生成し、0/1から4/4へ到達した。
- structure-editは`kind`へ操作種別を生成し、1/2から4/4へ到達した。

成功した全候補は、構文・静的検査、変更Symbol範囲、既存Test保持、可視Test、累積hidden testを通過した。生成失敗、候補適用失敗、検証失敗はなかった。

ただし、これはv1からv3の結果を見た後、同じ1 Applicationを使った校正である。n=1であり、方式間の性能差や未使用課題への一般化を示す結果ではない。

## 2. 実験条件

| 項目 | 値 |
|---|---|
| Model | `gpt-5.4-mini-2026-03-17` |
| Prompt | `intentir-openai-responses-v4` |
| Reasoning | `medium` |
| API保存 | `store: false` |
| Conditions | full-file / unified-diff / structure-edit / intent-patch |
| Provider call | 16 |
| 入力tokens | 17,987 |
| 出力tokens | 7,328 |
| 実計上額 | 0.046466 USD |
| 事前最大予約額 | 0.678912 USD |
| 承認上限 | 1.00 USD |
| 自動再試行 | なし |

## 3. 条件別結果

| 条件 | 実行 | 成功 | 入力tokens | 出力tokens | USD |
|---|---:|---:|---:|---:|---:|
| full-file | 4 | 4 | 3,401 | 884 | 0.006529 |
| unified-diff | 4 | 4 | 3,849 | 2,568 | 0.014444 |
| structure-edit | 4 | 4 | 5,403 | 1,267 | 0.009753 |
| intent-patch | 4 | 4 | 5,334 | 2,609 | 0.015740 |
| 合計 | 16 | 16 | 17,987 | 7,328 | 0.046466 |

4条件の最終Module IDはすべて一致した。これは4種類の編集表現が、この軌跡では同じ最終プログラムへ到達したことを示す。

## 4. 事前仮説の判定

| 仮説 | 判定 | 根拠 |
|---|---|---|
| H1: unified-diffがadd-priorityを通過 | 支持 | 最初だけでなく4/4を完走 |
| H2: structure-editが正しい`kind`で最初の2 checkpointを通過 | 支持 | `kind: insert_member`を生成し4/4を完走 |
| H3: full-fileとintent-patchが各4 checkpointを完走 | 支持 | 両条件とも4/4 |
| H4: 不正structure operationに合法操作一覧を返す | 支持（Offline） | 校正v3候補を使う回帰Testで7操作の`scope`を確認 |
| H5: Prompt version不一致を通信前に拒否 | 支持（Offline） | Provider driftを模した自動Testで拒否を確認 |

## 5. 契約修正の確認

### 5.1 unified diff

v4候補は、追加行の後に空行と後続定義をContextとして含めた。v3で生成された、変更行で終了するhunkとは異なる。

```diff
@@ -3,6 +3,7 @@
 entity WorkItem:
   id: UUID required key
   title: Text required
   status: Text default "open"
+  priority: Integer default 0
 action CreateWorkItem:
```

この候補は`git apply --check`、IntentIR compile、可視Test、hidden testを通過した。hunk rangeだけでなく前後Contextを契約へ含めた判断が、同一課題上では支持された。

### 5.2 structure edit

add-owner候補は、対象種別を`target`のprefix、操作種別を`kind`へ分離した。

```json
{
  "kind": "insert_member",
  "target": "entity:WorkItem",
  "member": "fields",
  "index": 4,
  "value": {
    "name": "owner",
    "type": "Text",
    "default": "unassigned"
  }
}
```

v3の`kind: entity`と追加の`operation: insert_member`という混同は再発しなかった。

## 6. 費用内訳

| Call | 条件 / checkpoint | 入力 | 出力 | USD |
|---:|---|---:|---:|---:|
| 1 | full-file / add-priority | 844 | 161 | 0.001358 |
| 2 | full-file / add-owner | 838 | 177 | 0.001425 |
| 3 | full-file / add-archive-state | 857 | 177 | 0.001439 |
| 4 | full-file / add-archive-action | 862 | 369 | 0.002307 |
| 5 | unified-diff / add-priority | 954 | 528 | 0.003092 |
| 6 | unified-diff / add-owner | 954 | 472 | 0.002840 |
| 7 | unified-diff / add-archive-state | 968 | 639 | 0.003602 |
| 8 | unified-diff / add-archive-action | 973 | 929 | 0.004910 |
| 9 | structure-edit / add-priority | 1,346 | 302 | 0.002368 |
| 10 | structure-edit / add-owner | 1,341 | 407 | 0.002837 |
| 11 | structure-edit / add-archive-state | 1,357 | 248 | 0.002134 |
| 12 | structure-edit / add-archive-action | 1,359 | 310 | 0.002414 |
| 13 | intent-patch / add-priority | 1,326 | 616 | 0.003766 |
| 14 | intent-patch / add-owner | 1,324 | 747 | 0.004354 |
| 15 | intent-patch / add-archive-state | 1,338 | 590 | 0.003658 |
| 16 | intent-patch / add-archive-action | 1,346 | 656 | 0.003962 |

## 7. セキュリティ

- API KeyはProvider payload、Artifact、Git管理Fileへ保存していない。
- API Keyは実行直後にmacOSの一時環境変数から削除し、削除済みであることを確認した。
- クリップボードは実行前に消去した。
- TLS証明書検証は無効化せず実行した。
- API側のResponse保存は`store: false`とした。
- 生Artifactは`artifacts/`配下に置き、Git管理対象外とした。

## 8. 次の判断

同じwork-item課題を使う校正はv4で終了する。ここからv5を重ねても、同一課題への過適合と本質的改善を区別しにくい。

次は課金なしで未使用課題を作成し、次を事前登録する。

1. 10 Application、各4 checkpointの40 checkpoint Suite
2. 課題を見ずに固定するhidden testと変更Symbol範囲
3. Model、Prompt、Configuration、停止規則
4. 4編集条件に対する最大160 callの予算計画
5. 成功率、軌跡完走率、修復可能な診断、token、費用の集計方法

本評価のAPI実行は、Suiteと解析計画をGitへ固定した後、別の送信・費用承認を受けた場合だけ行う。

## 9. 成果物

- 実行Directory: `artifacts/intentbench/openai-calibration-v4-2026-07-24/`
- Protocol: `benchmarks/intentbench_evolve/openai_calibration_v4_protocol.json`
- 事前計画: `OPENAI_CALIBRATION_V4_PLAN_2026-07-24_JA.md`
- Summary: `artifacts/intentbench/openai-calibration-v4-2026-07-24/summary.json`
