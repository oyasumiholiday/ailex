# OpenAI 校正v4 実験計画

作成日: 2026-07-24
Protocol ID: `intentbench-evolve-openai-calibration-v4-2026-07-24`
Protocol Hash: `sha256:b852c37b76625f3a6c3a5a650b1f3060f3182cb1eb5eeab250f9ebb08160bf42`
位置づけ: 校正v3で観測したdiff Contextと操作種別の曖昧さを除去する校正実験

## 1. 目的

校正v3では11 checkpoint中9件を受理し、full-fileとintent-patchが4/4を完走した。一方、unified-diffは変更後の未変更Contextを含めず最初のcheckpointで停止し、structure-editは2番目で`kind: entity`を生成して停止した。

校正v4では、次の2点が出力契約と診断の不足によるものかを確認する。

1. unified diffには変更の前後に未変更Contextが必要である。
2. structure editの`kind`は対象Definition種別ではなく操作種別である。

同じ課題を使った反復校正であるため、方式間の性能比較や未使用課題への一般化は主張しない。

## 2. v3からの変更

| v3の観測 | v4の変更 |
|---|---|
| 行範囲付きhunkでも変更後Contextがなく適用失敗 | 前後1行以上の未変更Contextを機械可読に要求 |
| diff失敗理由が一般的なMessageだけ | Contextと行範囲を確認する安全な診断へ改善 |
| structure editが`kind: entity`を生成 | `kind`は操作判別子であると意味・合法値・短い正例を追加 |
| 不正操作の修復候補が診断にない | `scope`へ合法な7操作を返す |
| ProtocolがPrompt世代を直接固定しない | `promptVersion`をProtocol Hashへ含め、実装との不一致を通信前に拒否 |

正解候補、hidden test、v3候補そのものはモデルへ渡さない。v3候補は評価器のOffline回帰Testにだけ使用する。

## 3. 校正仮説

以下は実モデル実行前の仮説である。

- H1: unified-diffはadd-priorityを通過する。
- H2: structure-editは`kind: insert_member`を維持し、最初の2 checkpointを通過する。
- H3: full-fileとintent-patchは各4 checkpointを再び完走する。
- H4: 不正なstructure operationには合法な操作一覧が返る。
- H5: Protocolの`promptVersion`と実装が異なる場合、Provider呼出し前に拒否する。

H4とH5はOffline Testで検証する。H1からH3は、別途承認された場合だけ実モデルで検証する。

## 4. 固定条件

| 項目 | 値 |
|---|---|
| Model | `gpt-5.4-mini-2026-03-17` |
| Prompt | `intentir-openai-responses-v4` |
| Reasoning | `medium` |
| Conditions | full-file / unified-diff / structure-edit / intent-patch |
| Trial | 各条件1軌跡 |
| 最大Call | 16 |
| 予算上限 | 1.00 USD |
| 最大予約額 | 0.678912 USD |
| API保存 | `store: false` |
| 自動再試行 | なし |

## 5. 通信なしPreflight

次を実行し、Providerを呼ばないことを確認した。

```sh
python3 -m intentir pilot \
  benchmarks/intentbench_evolve/openai_calibration_v4_protocol.json \
  --json
```

確認結果:

- `ok: true`
- `willCallProvider: false`
- `maximumCalls: 16`
- `maximumReservedCostUsd: 0.678912`
- `promptVersion: intentir-openai-responses-v4`
- Protocol Hashは本書冒頭と一致

## 6. 有料実行の状態

校正v4の有料実行は行っていない。実行には次のすべてが必要である。

1. v4のコードと実験データをOpenAI APIへ送信する明示承認
2. 費用上限への明示承認
3. 新しい`OPENAI_API_KEY`
4. 未使用の出力Directory

過去の承認やAPI Keyを校正v4へ流用しない。

## 7. 解釈上の制限

- v1からv3の結果を見た後の校正である。
- 同一の1 Application、4 checkpointを再利用する。
- n=1なので統計的推論を行わない。
- 成功しても「IntentPatchが他方式より優れる」とは結論しない。
- 校正が安定した後、未使用課題による40 Checkpoint本評価へ移る。
