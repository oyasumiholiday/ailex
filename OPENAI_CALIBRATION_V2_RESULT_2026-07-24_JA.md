# OpenAI 校正v2 実モデル検証レポート

実施日: 2026-07-24
Protocol ID: `intentbench-evolve-openai-calibration-v2-2026-07-23`
Protocol Hash: `sha256:3fb3cda7e513ed7866ec242d8ba65963cb674f358b47f94354d6301385dee87f`

## 1. 結論

校正v2はOpenAI Responses APIを9回呼び出し、9 checkpoint中6件を受理した。実計上額は0.025839 USDで、承認上限1.00 USD以内だった。

初回パイロットは7 checkpoint中3件受理だった。停止規則により分母と到達checkpointが異なるため単純な性能比較はできないが、校正v2では次の明確な進展が確認できた。

- full-fileが3/4から4/4となり、初めて軌跡を完走した。
- unified-diffが最初のcheckpointを通過した。
- structure-editがcontent-addressed Node IDを含む最初のcheckpointを通過した。
- intent-patchは未知のトップレベルフィールドを出力しなくなった。

初回に観測した4つの契約不整合は解消した。一方、次の層としてunified diffのhunk header形式と、Patch操作の`member`値・`value`型が未定義であることが分かった。

## 2. 実験条件

| 項目 | 値 |
|---|---|
| Model | `gpt-5.4-mini-2026-03-17` |
| Reasoning | `medium` |
| API保存 | `store: false` |
| Conditions | full-file / unified-diff / structure-edit / intent-patch |
| Provider call | 9 |
| 入力tokens | 7,404 |
| 出力tokens | 4,508 |
| 実計上額 | 0.025839 USD |
| 予算上限 | 1.00 USD |

## 3. 条件別結果

| 条件 | 実行 | 成功 | 結果 |
|---|---:|---:|---|
| full-file | 4 | 4 | 全checkpoint完走 |
| unified-diff | 2 | 1 | add-priority成功、add-ownerでhunk適用失敗 |
| structure-edit | 2 | 1 | add-priority成功、add-ownerでmember collection誤り |
| intent-patch | 1 | 0 | Envelopeは正しいがmember collection誤り |

軌跡単位では4条件中1条件が完走し、3条件が途中停止した。

## 4. 事前仮説の判定

| 仮説 | 判定 | 根拠 |
|---|---|---|
| H1: unified-diff初回が形式エラーなしで通る | 支持 | add-priorityが受理されhidden testも成功 |
| H2: structure-editのsymbol/Node ID参照を受理 | 支持 | add-priorityが受理されhidden testも成功 |
| H3: intent-patchが未知トップレベルフィールドを出さない | 支持 | 許可された4フィールドだけを生成 |
| H4: full-fileのupdate構文誤りが減る | 支持 | ArchiveWorkItemを含む4/4完走 |

これらは同一課題を見た後の校正結果であり、未使用課題への一般化を示さない。

## 5. 新しく観測した言語ギャップ

### 5.1 unified-diffのhunk header型

add-owner候補は変更内容と対象pathを正しく生成したが、hunk headerを`@@`だけで出力した。標準unified diffでは旧・新ファイルの行範囲が必要である。

必要な契約:

```text
@@ -<oldStart>,<oldCount> +<newStart>,<newCount> @@
```

`requiredFileHeaders`だけでなく、hunk headerの構文も機械可読に提示する必要がある。

### 5.2 Patchのmemberは項目名ではなくCollection名

structure-editは`member: owner`、intent-patchは`member: priority`を生成した。しかし`insert_member`の`member`は追加する項目名ではなく、対象Definition内のCollection名である。Entityの場合は`fields`だけが正しい。

現在の契約は操作に存在するキー名を列挙するだけで、値域を示していない。このため、AIが自然言語として妥当な値を選んでもPatch型としては不正になった。

必要な契約:

- target kindごとの`member`列挙値
- `member`はCollection selectorであるという意味
- Collectionごとの`value`型
- 不正時の診断`scope`に利用可能なCollectionを含める

### 5.3 value型も明示が必要

Entityの`fields`へ追加するvalueは、少なくとも`name`と`type`を持つObject、またはフィールド名を含む完全なsource表現である必要がある。intent-patch候補の`Integer default 0`には`priority`という項目名が含まれず、memberだけを修正しても次の型エラーになる。

## 6. 費用内訳

| Call | 条件 / checkpoint | 入力 | 出力 | USD |
|---:|---|---:|---:|---:|
| 1 | full-file / add-priority | 763 | 167 | 0.001324 |
| 2 | full-file / add-owner | 757 | 178 | 0.001369 |
| 3 | full-file / add-archive-state | 776 | 182 | 0.001401 |
| 4 | full-file / add-archive-action | 781 | 354 | 0.002179 |
| 5 | unified-diff / add-priority | 805 | 239 | 0.001679 |
| 6 | unified-diff / add-owner | 805 | 148 | 0.001270 |
| 7 | structure-edit / add-priority | 883 | 888 | 0.004658 |
| 8 | structure-edit / add-owner | 877 | 760 | 0.004078 |
| 9 | intent-patch / add-priority | 957 | 1,592 | 0.007882 |

## 7. セキュリティ

- API KeyはProvider payload、Artifact、Git管理Fileへ保存していない。
- 実行直後にmacOSの一時環境変数からAPI Keyを削除した。
- クリップボードは実行前に消去した。
- TLS証明書検証は有効なまま実行した。
- 生Artifactは`artifacts/`配下に置き、Git管理対象外とした。

## 8. 次の校正

校正v3では次だけを変更する。

1. unified diffのhunk header形式を契約へ追加する。
2. Definition kindごとのmember collection列挙値を追加する。
3. memberはCollection名であることを明記する。
4. Collectionごとのvalue型を追加する。
5. `unsupported_patch_member`診断のscopeに利用可能なCollectionを返す。

結果は新しいProtocol IDで保存し、初回およびv2を上書きしない。v3も校正であり、未使用課題による本評価とは分離する。

## 9. 成果物

- 実行Directory: `artifacts/intentbench/openai-calibration-v2-2026-07-23/`
- Protocol: `benchmarks/intentbench_evolve/openai_calibration_v2_protocol.json`
- 事前計画: `OPENAI_CALIBRATION_V2_PLAN_2026-07-23_JA.md`
