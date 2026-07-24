# OpenAI 実モデル・パイロット検証レポート

実施日: 2026-07-22  
対象: IntentBench Evolve model trajectory smoke suite  
位置づけ: 計測系とAI向け出力契約を確認する校正パイロット

## 1. 結論

OpenAI Responses APIを使った実モデル評価は正常に実行できた。成功したAPI呼び出しは7回、実計上額は0.031191 USDだった。

全ファイル方式は4チェックポイント中3件に成功した。一方、unified-diff、structure-edit、intent-patchは最初のチェックポイントで停止した。ただし、3件とも単純なモデル能力不足とは判断できない。モデルの候補は課題の意味を概ね捉えており、出力契約に明記されていない評価器固有の要件、または契約メタデータと候補フィールドの曖昧さによって拒否された。

この結果は方式間の優劣を示すものではない。1モデル、各条件1軌跡の校正実験であり、統計的推論には使えない。

## 2. 実験条件

| 項目 | 値 |
|---|---|
| モデル | `gpt-5.4-mini-2026-03-17` |
| reasoning effort | `medium` |
| API | OpenAI Responses API |
| API側保存 | `store: false` |
| 条件 | full-file / unified-diff / structure-edit / intent-patch |
| 試行 | 各条件1軌跡 |
| 最大出力 | 4,096 tokens / call |
| 承認予算 | 1.00 USD |
| 成功したAPI呼び出し | 7 |
| 入力トークン合計 | 4,106 |
| 出力トークン合計 | 6,247 |
| 実計上額 | 0.031191 USD |

実験前の最初の試行では、Mac上のPython 3.13がCA証明書を発見できず、TLSハンドシェイク前に4回失敗した。OpenAI APIへHTTPリクエストは到達していない。パイロット実装は利用量を取得できない失敗を安全側に扱い、0.169728 USDを予約上限として記録した。`certifi`のCAバンドルを`SSL_CERT_FILE`に指定した再実行ではTLS接続が正常化した。

2026-07-24に、OpenAI Providerが明示的な`SSL_CERT_FILE`、利用可能な`certifi`、OS/Python標準trust storeの順でCAを自動選択するよう改善した。証明書検証は無効化しない。API Keyを送らない接続確認でTLSを通過し、期待どおりHTTP 401へ到達した。証明書検証失敗は一般的なnetwork errorではなく`openai_tls_error`として診断する。

## 3. 条件別結果

| 条件 | 実行チェックポイント | 成功 | 最初の失敗 | 結果 |
|---|---:|---:|---|---|
| full-file | 4 | 3 | `candidate_parse_error` | priority、owner、archivedの追加に成功。ArchiveWorkItemで停止 |
| unified-diff | 1 | 0 | `unsafe_unified_diff` | 意味上正しい差分だが、非明示の`diff --git`ヘッダー要件で拒否 |
| structure-edit | 1 | 0 | `unknown_structure_target` | 文脈に提示されたエンティティIDをtargetに使用したが、評価器はシンボル名を要求 |
| intent-patch | 1 | 0 | `unknown_patch_field` | 出力契約の`kind`と`contentGuards`を候補フィールドとして再掲し拒否 |

全体では7チェックポイント中3件成功、4件失敗だった。軌跡は失敗時に停止するため、4条件すべての4チェックポイントを比較できる結果ではない。

## 4. 観測されたAI・契約間の不一致

### 4.1 full-file: 未提示の文法を推測した

モデルはArchiveWorkItemの意図を理解し、更新アクションを追加した。しかし、正しいIntentIR構文である`where id equals input.id set archived = true`ではなく、複数行のSQL風構文を生成した。入力には更新アクションの例や十分な文法要約が含まれていなかった。

解釈: モデル誤りであると同時に、未知の構文を要求する課題へ最小限の言語リファレンスを渡していない実験設計上の弱点でもある。

### 4.2 unified-diff: 契約と評価器が一致していない

モデルは`--- a/workspace.intent`と`+++ b/workspace.intent`を含む通常のunified diffを生成し、要求されたpriorityフィールドだけを追加した。出力契約はこのfrom/to pathを提示していたが、評価器が必須とする`diff --git a/workspace.intent b/workspace.intent`行は提示していなかった。

解釈: 現結果をモデル失敗として方式比較に利用してはならない。契約にヘッダー要件を追加するか、評価器が通常のunified diffも受理する必要がある。

### 4.3 structure-edit: targetの意味が未定義

文脈は各ノードについて`symbol`と`id`を提示した。モデルは安定識別子に見える`id`をtargetへ設定したが、評価器は`entity:WorkItem`というsymbolだけを受理する。出力契約にはtargetがどちらを指すか記載されていない。

解釈: AI向け中間表現では、フィールド名だけでなく参照方式も型として明示する必要がある。

### 4.4 intent-patch: メタデータと候補スキーマが混在した

出力契約自身に`kind: intent-patch`と`contentGuards: true`が含まれていた。モデルはこれらを候補JSONへ忠実に含めたが、実際のPatchスキーマでは未知フィールドとして拒否された。

解釈: 「インターフェースを説明するメタデータ」と「そのまま出力すべきJSON Schema」を別オブジェクトへ分離する必要がある。

## 5. 費用内訳

| 呼び出し | 条件 / checkpoint | 入力tokens | 出力tokens | 費用USD |
|---:|---|---:|---:|---:|
| 1 | full-file / add-priority | 549 | 188 | 0.001258 |
| 2 | full-file / add-owner | 547 | 205 | 0.001333 |
| 3 | full-file / add-archive-state | 566 | 208 | 0.001360 |
| 4 | full-file / add-archive-action | 564 | 648 | 0.003339 |
| 5 | unified-diff / add-priority | 568 | 145 | 0.001078 |
| 6 | structure-edit / add-priority | 630 | 1,542 | 0.007412 |
| 7 | intent-patch / add-priority | 682 | 3,311 | 0.015411 |

構造化方式ほど出力トークンが増えた。ただし、n=1かつ契約が曖昧な状態なので、方式固有のコスト差とは結論づけられない。特にintent-patchは契約解釈に多くの推論を使った可能性があるが、これは解釈上の仮説であり追加検証が必要である。

## 6. 次の校正変更

1. unified-diffの受理条件と出力契約を一致させる。
2. structure-editのtargetを`symbol`と明記し、利用可能な値を列挙する。
3. intent-patchの契約を`interfaceMetadata`と`candidateSchema`へ分離し、許可されるトップレベルフィールドを列挙する。
4. full-fileには課題に必要な最小文法だけを機械可読な言語リファレンスとして渡す。
5. 校正後は別protocol IDと別protocol hashで再実行し、今回の結果を上書きしない。
6. 計測系が安定してから複数trialを事前登録し、方式比較を行う。

## 6.1 校正v2の実装状況

2026-07-23に上記1から5を校正v2として実装した。

- unified-diffは安全なfrom/to headerを必須とし、`diff --git` headerを任意として受理する。
- structure-editは既存Nodeのsymbolとcontent-addressed IDを受理し、内部でsymbolへ正規化する。
- 4条件の出力契約を`interface`と`candidate`へ分離した。
- JSON候補は許可されるトップレベルフィールドとtarget参照方式を機械可読に列挙する。
- 全条件へ同じversioned最小文法リファレンスを渡す。
- OpenAI向けPrompt IDをv2へ更新し、契約メタデータを候補へコピーしないよう明記する。

再実験は初回と混同しないよう、`intentbench-evolve-openai-calibration-v2-2026-07-23`として事前登録する。計画は`OPENAI_CALIBRATION_V2_PLAN_2026-07-23_JA.md`を参照する。

## 7. 再現用成果物

- 成功した実行: `artifacts/intentbench/openai-pilot-2026-07-22-rerun-01/`
- TLS失敗を記録した実行: `artifacts/intentbench/openai-pilot-2026-07-22/`
- プロトコル: `benchmarks/intentbench_evolve/openai_pilot_protocol.json`

`artifacts/`はGit管理対象外である。各call記録には正規化されたリクエスト、プロバイダーpayload、候補、token使用量、費用を保存するが、APIキーは保存しない。
