# OpenAI 校正v2 実験計画

作成日: 2026-07-23
Protocol ID: `intentbench-evolve-openai-calibration-v2-2026-07-23`
位置づけ: 2026-07-22の有料パイロットで観測した契約不整合を除去する校正実験

## 1. 目的

初回パイロットの失敗が、モデルの課題理解ではなく出力契約の曖昧さによって発生していたかを確認する。

この実験は方式間の性能比較ではない。1モデル、各条件1軌跡であり、修正後の計測系が次の反復へ進めるかを判断するための校正である。

## 2. 初回結果から固定した変更

| 観測 | 校正v2の変更 |
|---|---|
| full-fileが未提示のupdate構文を推測した | 全条件へ答えを含まない最小IntentIR文法リファレンスを渡す |
| 通常のunified diffがgit固有ヘッダー不足で拒否された | `---`と`+++`を必須、`diff --git`を任意として契約と評価器を一致させる |
| structure-editがNode IDをtargetに使って拒否された | 既存targetはsymbolとcontent-addressed IDの両方を受理し、symbolへ正規化する |
| intent-patchが契約メタデータを候補へ含めた | `interface`と`candidate`を分離し、候補の許可フィールドを列挙する |

モデルへ正解候補、hidden test、評価後の修正文は渡さない。

## 3. 校正仮説

以下は検証前の仮説であり、事実ではない。

- H1: unified-diffの最初のcheckpointは、git固有ヘッダーがなくても受理される。
- H2: structure-editの最初のcheckpointは、symbolまたはNode IDのどちらを選んでも受理される。
- H3: intent-patchは`kind`と`contentGuards`を候補トップレベルへ出力しなくなる。
- H4: full-fileは最小文法リファレンスによりArchiveWorkItemの構文誤りを減らす。

## 4. 固定条件

| 項目 | 値 |
|---|---|
| Model | `gpt-5.4-mini-2026-03-17` |
| Reasoning | `medium` |
| Conditions | full-file / unified-diff / structure-edit / intent-patch |
| Trial | 各条件1軌跡 |
| 最大Call | 16 |
| 予算上限 | 1.00 USD |
| API保存 | `store: false` |
| 自動再試行 | なし |

初回と同じモデルsnapshot、reasoning、課題、停止規則を使用する。変更するのはモデル要求の契約記述と、契約に合わせた候補適用器だけである。

## 5. 判定

主要な校正指標:

- 各条件の最初のcheckpointが候補形式エラーなしで通過するか
- 完了checkpoint数
- 診断コード
- 入力・出力token
- 条件別と累積の計上費用

成功条件は、初回に契約不整合で停止したunified-diffとstructure-editが同じ種類の候補を受理し、intent-patchが許可フィールドだけを生成することである。

full-fileの最終checkpoint成功は望ましいが、主要成功条件とは分けて記録する。

## 6. 実行前確認

次のCommandはAPIを呼ばず、Protocol Hashと最大予約額だけを計算する。

```sh
python3 -m intentir pilot \
  benchmarks/intentbench_evolve/openai_calibration_v2_protocol.json \
  --json
```

有料実行には、コード送信と費用への明示承認、`OPENAI_API_KEY`、新しい出力Directoryが必要である。

```sh
python3 -m intentir pilot \
  benchmarks/intentbench_evolve/openai_calibration_v2_protocol.json \
  --execute \
  --confirm-budget-usd 1.00 \
  --output-dir artifacts/intentbench/openai-calibration-v2-2026-07-23 \
  --json
```

## 7. 解釈上の制限

- 初回結果を見た後の校正なので、初回とv2の差を一般的な性能向上として扱わない。
- n=1のため統計的推論を行わない。
- 同一課題への再実行なので、モデルや提供基盤の非決定性を排除できない。
- 校正後の契約を固定してから、未使用課題と複数trialによる本評価を別に設計する。
