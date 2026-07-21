# IntentIR 純粋Function検証レポート

- 対象: `examples/functions.intent`
- モジュール: `FunctionDemo`
- 結果: 成功

## 概要

- Entity: 0
- Function: 4
- Action: 0
- Test: 0
- Function Example: 5
- IR Node: 4
- IR Edge: 2
- 検証義務: 5
- Module ID: `sha256:5a34b5d5276b747e76f65512d89d3b30a6d480ac5a77ecf826391279d141d07e`
- Canonical Hash: `sha256:2591cbbb950eaf5477890ecb7270b0ee07a6ee49be28e0f50101a5ad9630bc92`

## 静的検証

- エラーはありません。
- InputとReturnの組み込み型を検証
- Body変数がInput Scope内にあることを検証
- 算術、比較、論理、条件式のOperand型を検証
- 位置引数、名前付き引数、default、重複・不足・未知引数を検証
- Function間の`calls` Edgeを決定的に生成
- 再帰Cycleを静的に拒否

## Python実行検証

- 5 / 5 Function Example 成功
- `Clamp(value=-2, minimum=0, maximum=10) equals 0`: 成功
- `Clamp(value=12, minimum=0, maximum=10) equals 10`: 成功
- `ClampDouble(value=7) equals 10`: 成功
- `Double(value=4) equals 8`: 成功
- `Greeting(name="IntentIR") equals "Hello, IntentIR"`: 成功
- `call ClampDouble --input '{"value":7}'`の結果が`10`になることを確認
- 不正なRuntime Inputが`function_argument_type_mismatch`になることを確認

## TypeScript Backend検証

- 生成したFunctionをNode.jsで直接実行
- 5 / 5 Function Example 成功
- ネスト呼出しとdefault引数がPython実行器と一致
- 除算、切り捨て除算、負数剰余用Runtime Helperを生成

## 自動テスト

- 42 / 42 成功
- 純粋式IR、型検証、循環拒否、CLI、Formatter、Python/TypeScript E2Eを含む

## 実行コマンド

```sh
python3 -m intentir check examples/functions.intent
python3 -m intentir test examples/functions.intent
python3 -m intentir call examples/functions.intent ClampDouble --input '{"value":7}'
python3 -m intentir build examples/functions.intent --target typescript
python3 -m intentir report examples/functions.intent
python3 -m unittest discover -s tests -v
```
