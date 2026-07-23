# OpenAI Responses API Provider検証レポート

> 2026-07-22追記: 日付固定Model、4編集条件、最大16 call、1.00 USD上限を持つ`intentir pilot`を追加しました。実行前検証とFake Providerによる全Call記録は確認済みですが、課金を伴う実API実行はまだ行っていません。条件と停止規則は [PILOT_EXPERIMENT_PROTOCOL_JA.md](PILOT_EXPERIMENT_PROTOCOL_JA.md) を参照してください。

- 確認日: 2026-07-21
- 対象: `intentir-openai-adapter`
- Protocol: IntentBench-Evolve Model Adapter `0.1.0`
- 検証範囲: Offline Unit Test、Schema、CLI、Package
- 未検証: 実OpenAI APIへの課金を伴うRequest

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

Project全体では通常環境95 Test中94件成功、MCP専用1件のみSkip、MCP環境95 / 95件成功です。

## 実Model Trial前の条件

現時点では実API Requestを実行していないため、Model性能、API疎通、Account権限、Rate limit、Costは未検証です。最初のTrial前に次を固定します。

1. AliasではなくModel Snapshot ID
2. Reasoning effortと最大Output Token
3. Prompt IDとConfiguration ID
4. Conditionごとの同一Budget
5. Trial回数、Timeout、Retry方針
6. API KeyのSecret StoreとLog非出力
7. 評価TestをModel実行環境から分離したTask Package

この条件を満たした後、まず1 Application x 4 Conditionの少額Pilotを行い、Request/Response契約とCostを確認してから40 Checkpointへ拡張します。
