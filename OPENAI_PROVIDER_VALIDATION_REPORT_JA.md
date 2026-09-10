# OpenAI Responses API Provider検証レポート

> 2026-07-24追記: 日付固定Modelを使う有料Pilotと校正v2/v3/v4を実行し、API疎通、Account権限、Token usage、費用計上、停止規則、Artifact保存を確認しました。最新の校正v4は16 call、0.046466 USD、16/16 checkpoint成功です。結果は [校正v4実モデル検証レポート](OPENAI_CALIBRATION_V4_RESULT_2026-07-24_JA.md) を参照してください。

- 確認日: 2026-07-21
- 対象: `intentir-openai-adapter`
- Protocol: IntentBench-Evolve Model Adapter `0.1.0`
- 検証範囲: Offline Unit Test、Schema、CLI、Package、少額の実OpenAI API Request
- 未検証: Rate limit、Retry、長時間・反復運転、未使用課題での本評価

## 目的

IntentBench-EvolveのProvider非依存Request/Response Protocolを、実際のModel APIへ接続できる参照Wrapperへ落とし込みます。Benchmark本体はProvider SDKへ依存せず、外部Commandの差替えだけでModel条件を変更できる構造を維持します。

## 公式仕様との対応

実装前にOpenAI公式API Referenceを確認しました。Responses APIは`model`、`instructions`、`input`、`max_output_tokens`、`reasoning`、`store`、`text.format`を受け取り、Responseの`output`内に`output_text`、`usage`内に`input_tokens`と`output_tokens`を返します。

- [Create a model response](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

Wrapperは`text.format.type = json_schema`と`strict = true`を使い、Model出力を`{"candidate": string}`へ限定します。SDK専用の`output_text`補助Propertyには依存せず、REST Responseの`output[].content[]`から`output_text`を抽出します。

## 実装

`intentir-openai-adapter`はPython標準Libraryだけで`POST https://api.openai.com/v1/responses`を実行します。

- Model IDは`--model`で必須指定し、暗黙の最新版を使わない
- API Keyは`OPENAI_API_KEY`からだけ読み、CLI引数を用意しない
- `store: false`でResponse保存を無効化
- Reasoning effortと最大Output Tokenを明示可能
- Request/Responseを4 MB、最終Candidateを共通Protocol側で1 MBへ制限
- HTTP BodyやProvider内部MessageをBenchmark診断へ転載しない
- 未完了、Text欠落、非JSON、Candidate欠落、Token形式不正を拒否

## Trial Provenance

成功Resultには次を保存します。

| Field | 内容 |
|---|---|
| `provider` | `openai-responses` |
| `responseId` | Provider Response ID |
| `requestedModel` | CLIで要求したModel ID |
| `model` | Providerが返した実Model ID |
| `promptId` | Prompt TemplateとStructured Output Schemaの内容Address |
| `configurationId` | Model、Reasoning、Output上限、Prompt ID、Store設定の内容Address |
| `reasoningEffort` | 明示したReasoning設定または`null` |
| `maxOutputTokens` | 最大Output Token |
| `usage` | Input/Output Token |
| `elapsedMs` | Wrapper起動からCandidate評価終了までの時間 |

API Key、Authorization Header、Provider Response本文、評価Test本文は保存しません。`requestId`は現在Source、指示、Module/Node ID、出力契約から決定されるため、どの入力に対するTrialかを照合できます。

## 失敗分類

各失敗Runには`failure.stage`と診断Codeを付け、Suite Summaryの`failuresByCode`へ集計します。

- `generation`: Provider、Timeout、Protocol Responseの失敗
- `precondition`: 古いModule/Node IDなど内容前提条件の失敗
- `semantic-scope`: Baseline Test削除や許可外Symbol変更
- `verification`: 評価TestまたはFunction Example失敗
- `candidate`: その他のCandidate Parse、適用、Compile失敗

## Offline検証結果

Fake Responses API応答を使い、次をNetwork・Credential・課金なしで確認しました。

- PayloadとPrompt/Configuration IDの決定性
- `store: false`とStrict Structured Output Schema
- API KeyがPayload、Candidate、Resultへ含まれないこと
- Model設定変更で`configurationId`が変わること
- REST `output_text`の抽出とCandidate JSONの解析
- Token usageとProvider Provenanceの変換
- 未完了Responseの構造化拒否とProvider Body非転載
- Adapter失敗が`generation`として集計されること
- 評価Test MarkerがModel Requestへ含まれないこと

Project全体では通常環境101 Test中100件成功、MCP専用1件のみSkip、MCP環境101 / 101件成功です。TLS CAの優先順位、証明書検証専用診断、Patch member Collectionとstructure operationの修復scope、Prompt version不一致の通信前拒否もOffline Testで固定しています。

## 実Model Trialの固定条件

少額の実API校正では、次を固定してAPI疎通、Account権限、Token usage、Costを確認しました。Rate limit、Retry、長時間運転、未使用課題への一般化は未検証です。

1. AliasではなくModel Snapshot ID
2. Reasoning effortと最大Output Token
3. Prompt IDとConfiguration ID
4. Conditionごとの同一Budget
5. Trial回数、Timeout、Retry方針
6. API KeyのSecret StoreとLog非出力
7. 評価TestをModel実行環境から分離したTask Package

1 Application x 4 Conditionの少額校正はv4まで完了し、全16 checkpointを受理した。同一課題の契約校正は終了し、次は別に固定した未使用課題の40 Checkpoint本評価へ拡張する。
