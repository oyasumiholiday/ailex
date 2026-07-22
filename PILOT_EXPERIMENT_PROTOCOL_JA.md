# IntentBench-Evolve 実モデル・パイロット実験計画

実施結果: [OpenAI 実モデル・パイロット検証レポート](OPENAI_PILOT_RESULT_2026-07-22_JA.md)

## Material Passport

- Schema: ARS Material Passport 9
- Material ID: `intentbench-evolve-openai-pilot-2026-07-22`
- Stage: Experiment plan
- Verification status: DESIGNED
- Data access: 実API未実行、実験結果なし
- Input: IntentIR v0.14、IntentBench-Evolve 4条件・4 checkpoint
- Output: 固定Protocol、実行前検証、Request/Response/費用記録
- Next gate: 課金を伴う1回のPilot実行について所有者が明示承認すること

## まず何をする実験か

同じ4つの変更要求を、AIへ渡す編集形式だけ変えて実行します。

| 条件 | AIが返すもの |
|---|---|
| `full-file` | Program全体 |
| `unified-diff` | 行単位の差分 |
| `structure-edit` | 内容Hashを持たない構造編集 |
| `intent-patch` | Module/Nodeの内容Hashを持つ意味Patch |

各条件は同じ初期Programから始まり、成功した変更を次のcheckpointへ引き継ぎます。評価用Test本文はAIへ渡しません。

## 研究上の問い

### RQ1

内容Hashと意味単位の編集を使う`intent-patch`は、他の編集形式より連続変更を最後まで完了しやすいか。

### RQ2

`intent-patch`は、要求されたSymbol以外を誤って変更する割合を減らせるか。

### RQ3

`intent-patch`は、AIが返す文字数、Token使用量、修復回数、費用を減らせるか。

これらは**検証前の仮説**であり、現在のFixture成功結果や今回の1回Pilotは優位性の証拠ではありません。

## 今回固定する条件

| 項目 | 固定値 |
|---|---|
| Protocol | `openai_pilot_protocol.json` |
| Provider | OpenAI Responses API |
| Model snapshot | `gpt-5.4-mini-2026-03-17` |
| Reasoning effort | `medium` |
| 最大出力 | 4,096 Token / call |
| Timeout | 120秒 / call |
| 条件 | 4条件 |
| Application | `work-item` 1件 |
| Checkpoint | 4段階 |
| Trial | 1回 |
| 最大Call | 16回 |
| 再試行 | なし |
| API保存 | `store: false` |
| 費用上限 | 1.00 USD |

ModelはAliasではなく日付固定Snapshotを使います。価格は2026-07-22にOpenAI公式の[GPT-5.4 mini Model](https://developers.openai.com/api/docs/models/gpt-5.4-mini)で確認した、入力0.75 USD / 100万Token、出力4.50 USD / 100万TokenをProtocolへ記録しています。

## 費用の安全策

1 callごとに入力32,000 Token相当と最大出力4,096 Tokenを予約すると、最大予約額は次のとおりです。

```text
1 call  = (32,000 x 0.75 + 4,096 x 4.50) / 1,000,000
        = 0.042432 USD
16 call = 0.678912 USD
```

これは1.00 USDの上限内です。実行中はProviderが返したToken数から費用を再計算します。Token数を取得できない失敗は、安全側に倒して予約額を消費したものとして扱います。

次のすべてが揃わない限りAPIへ接続しません。

- `--execute`がある
- `--confirm-budget-usd 1.00`がProtocolと一致する
- `OPENAI_API_KEY`が存在する
- 出力Directoryがまだ存在しない
- 最大予約額が上限以下である

## 実行前確認

このCommandは課金されません。

```sh
python3 -m intentir pilot \
  benchmarks/intentbench_evolve/openai_pilot_protocol.json \
  --json
```

## 課金実行

所有者が費用を明示承認した後だけ実行します。

```sh
python3 -m intentir pilot \
  benchmarks/intentbench_evolve/openai_pilot_protocol.json \
  --execute \
  --confirm-budget-usd 1.00 \
  --output-dir artifacts/intentbench-pilot-2026-07-22
```

API Keyは環境変数からだけ読み、Command引数、Protocol、結果Fileには保存しません。

## 保存する証拠

実行すると次のFileを新しい出力Directoryへ保存します。

- `protocol.snapshot.json`: 実行した条件の正規化Copy
- `preflight.json`: Model、最大Call、上限額、Protocol Hash
- `calls/NNNN.json`: AIへ渡したRequest、秘密を除いたProvider Payload、Candidate、Token、費用
- `trial_01.result.json`: 4条件の検証結果
- `summary.json`: 全体の成否、Call数、累積費用

Call記録は各Response直後に書き出すため、途中で失敗しても完了済みRequestを失いません。

## Pilotの成功条件

- 固定Snapshot以外のModel応答を拒否する
- 1.00 USDを超えない
- 最大16 callのRequest/Response対応を追跡できる
- CandidateがHidden Test、既存Test、変更範囲検査を通るか判定できる
- API KeyがArtifactへ混入しない
- 同じProtocolから同じProtocol Hashを再生成できる

## 解釈上の制限

今回のTrial数は各条件1回です。目的は計測系と安全策の確認であり、性能差の主張や統計的検定には使いません。Model出力の確率性、条件の実行順、単一Application、単一Providerが交絡要因として残ります。

本実験ではApplicationを増やし、複数Trial、条件順の入替え、事前登録した主要評価指標、効果量と信頼区間を導入します。
