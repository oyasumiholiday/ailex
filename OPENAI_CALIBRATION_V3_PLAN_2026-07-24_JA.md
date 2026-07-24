# OpenAI 校正v3 実験計画

作成日: 2026-07-24
Protocol ID: `intentbench-evolve-openai-calibration-v3-2026-07-24`
位置づけ: 校正v2で観測した値域・構文型不足を除去する校正実験

## 1. 目的

校正v2では初回の契約不整合を解消し、9 checkpoint中6件を受理した。残る失敗が、unified diffのhunk header型と、Patch member/valueの型情報不足によるものかを確認する。

この実験も方式間の性能比較ではない。同じ課題を使った反復校正であり、未使用課題への一般化を主張しない。

## 2. v2からの変更

| v2の観測 | v3の変更 |
|---|---|
| unified diffが`@@`だけを生成 | 行範囲を含むhunk header形式を機械可読に追加 |
| `member: owner`と`member: priority`を生成 | target kindごとの合法Collectionを列挙 |
| memberと項目名を混同 | insert/set/removeごとのmember意味を明記 |
| field valueの名前・型が不足 | Collectionごとのvalue contractを追加 |
| 不正member診断のscopeが空 | 利用可能なCollectionをscopeへ返す |

正解候補、hidden test、v2候補そのものはモデルへ渡さない。

## 3. 校正仮説

以下は実行前の仮説である。

- H1: unified-diffはadd-ownerで行範囲付きhunk headerを生成し、2 checkpoint以上を完了する。
- H2: structure-editはEntityのinsert_memberで`member: fields`を選び、name/typeを含むvalueを生成する。
- H3: intent-patchはEntityのinsert_memberで`member: fields`を選び、最初のcheckpointを通過する。
- H4: 不正なmemberが生成された場合、診断scopeに`fields`が含まれる。

H4はOffline Testで検証し、H1からH3は実モデル実行で検証する。

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

## 5. 実行前確認

このCommandはAPIを呼ばない。

```sh
python3 -m intentir pilot \
  benchmarks/intentbench_evolve/openai_calibration_v3_protocol.json \
  --json
```

有料実行には、v3のコード送信と費用への別承認、`OPENAI_API_KEY`、新しい出力Directoryが必要である。

```sh
python3 -m intentir pilot \
  benchmarks/intentbench_evolve/openai_calibration_v3_protocol.json \
  --execute \
  --confirm-budget-usd 1.00 \
  --output-dir artifacts/intentbench/openai-calibration-v3-2026-07-24 \
  --json
```

## 6. 解釈上の制限

- v1とv2の結果を見た後の校正である。
- 同一課題のため、改善しても一般化性能とは呼ばない。
- n=1なので統計的推論を行わない。
- v3で計測系を安定させた後、未使用課題を固定して本評価へ移る。

## 7. 実行結果

2026-07-24に明示承認を受けて有料実行した。11回のAPI呼び出しで9 checkpointを受理し、実計上額は0.040957 USDだった。full-fileとintent-patchが4/4を完走した。

H2、H3、OfflineのH4は支持された。H1は不支持で、unified diffに変更後Contextの契約不足が残った。structure-editでは`kind`を対象種別と解釈する新しい曖昧さを観測した。

詳細、費用内訳、解釈上の注意、次のOffline修正は [校正v3実モデル検証レポート](OPENAI_CALIBRATION_V3_RESULT_2026-07-24_JA.md) に記録した。
