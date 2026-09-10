# Budget Guard 検証記録

## 目的

production pilot の生成前に Responses Input Tokens API で実入力を数え、
`reservedInputTokensPerCall` 超過、固定プロトコル価格による予算予約不足、
`maximumCalls` 超過を生成送信前に停止する。count 失敗、予約拒否、生成送信、
usage 上限違反を別状態で保存し、count request と generation request も別集計にした。

参照した一次資料: [OpenAI Responses input token counting API](https://developers.openai.com/api/reference/typescript/resources/responses/subresources/input_tokens/methods/count)

## オフライン検証結果

- `python3 -m unittest tests.test_openai_provider tests.test_pilot`: 17 tests、全件成功。
- `python3 -m unittest discover -s tests`: 全126件中125件成功、ローカル環境に optional `mcp` dependency が未導入のため1件 skip。
- `python3 -m unittest -v tests.test_mcp_server`: 同じローカル環境の dependency 条件により1件 skip。
- `uv run --frozen --extra mcp python -m unittest discover -s tests`: 親検証で optional MCP を実際に含む126/126件が成功、skip なし。
- `npm test`: Ailex conformance 89/89 成功。
- `python3.11 -m pip wheel . --no-deps --no-build-isolation --wheel-dir /private/tmp/ailex-security-public-dist`: `intentir-0.14.0-py3-none-any.whl` の生成成功。
- `python3 -m build --wheel ...` と Python 3.13 の非分離 `pip wheel` は、ローカルの `build` / `setuptools.build_meta` 不足で実行不可。Python 3.11 の既存 setuptools でネットワークなしの wheel build を確認した。

テストは counter と generation sender を注入または `urlopen` を mock し、実 API、
実 API key、課金通信を使用していない。TLS context、認証 header、request/response cap、
retry なし、秘密を含まない診断、count payload と generation payload の一致も確認した。

## 制約

Input Tokens API との実サービス互換性と count 値の正しさは live 未検証であり、
counter service を信頼境界に含む。count request は generation call とは別の追加送信で、
count endpoint の価格は上記一次資料では確認できないため費用集計に含めていない。
予算集計は protocol に固定された token 単価によるもので、現在の実アカウント請求額を
保証しない。usage の一部が欠ける場合の上限推定は、サービス側 token cap の履行を前提とする。

この guard は今後この実装で実行する pilot に適用される。既存 protocol、hash、過去の
結果ファイルを書き換えておらず、過去 trial がこの guard を使用したとは扱わない。
