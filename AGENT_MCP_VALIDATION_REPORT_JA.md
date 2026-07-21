# IntentIR v0.14 Agent/MCP検証レポート

## 目的

v0.14では、IntentIRの意味GraphとIntentPatchを特定Modelに依存しないTool APIとして公開しました。AgentはSource全文を毎回読み直す代わりに、内容ID、対象Node、依存Context、影響範囲、検証義務を構造化データとして取得できます。

Tool本体は外部依存のない`AgentService`です。同じ契約を`intentir agent` CLIと、optionalなMCP stdio Adapterから利用します。

Package versionは`0.14.0`です。今回は接続面の追加で意味Graph形式を変更していないため、IR SchemaとPatch Schemaは互換性を保って`0.13.0`のままです。

## 公開Tool

| Tool | 役割 | 書込み |
|---|---|---:|
| `intentir.describe_module` | Module ID、定義、Import、義務の要約 | なし |
| `intentir.get_node` | 1 Nodeの意味Payload、入出力Edge、義務 | なし |
| `intentir.get_context` | 深さと件数を制限した局所依存Context | なし |
| `intentir.get_impact` | 変更候補から逆依存をたどった影響範囲 | なし |
| `intentir.validate_patch` | Hash Guardと要求義務を検証するdry-run | なし |
| `intentir.apply_patch` | 検証済みPatchを原子的にSourceへ保存 | あり |
| `intentir.verify` | 全体または選択したTest/Exampleを実行 | なし |
| `intentir.render_diff` | 検証済みPatchの人間向けDiff | なし |
| `intentir.build` | IR、TypeScript、SQLite DDLをMemory上で生成 | なし |

`validate_patch`と`apply_patch`を分離したため、AgentまたはHost ApplicationはDiff確認や利用者承認を適用前に挟めます。書込みToolも`baseModuleId`と`expectedId`を省略できません。

`AgentService`、Agent CLI、MCP Serverはいずれも書込みが既定で無効です。`intentir.apply_patch`は発見可能なままですが、明示許可がない呼出しには`write_tool_disabled`を返します。MCP Tool annotationでは読取りToolをread-only、`apply_patch`をdestructiveとして公開します。

## Agent CLI

MCP SDKを導入しなくても、全ToolをJSON入出力で実行できます。

```sh
python3 -m intentir agent intentir.describe_module \
  --root . \
  --arguments '{"source":"examples/todo_crud.intent"}'

python3 -m intentir agent intentir.get_context \
  --root . \
  --arguments '{
    "source":"examples/todo_crud.intent",
    "symbol":"entity:Task",
    "depth":2,
    "max_nodes":30
  }'
```

成功時は`ok: true`とTool固有Result、失敗時は`ok: false`と安定した`diagnostics`を返します。CLIは失敗結果をJSONで出力して終了Code 1になります。

## MCP stdio Adapter

MCPはToolを名前、説明、入力JSON Schema、任意の出力JSON Schemaとして発見できるProtocolです。[MCP Tools仕様](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

公式Python SDKのFastMCPはstdio Transportと構造化出力を提供します。v0.14ではstable v1系列へ`mcp>=1.27,<2`で接続しました。[公式Python SDK](https://github.com/modelcontextprotocol/python-sdk)

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[mcp]'
.venv/bin/intentir-mcp --root .
```

MCP Clientは上のCommandをstdio subprocessとして起動します。HTTP Portは開かず、この起動方法では書込みも行えません。Host側で利用者承認と監査を実装した場合だけ、次のように書込みを許可します。

```sh
.venv/bin/intentir-mcp --root . --allow-writes
```

## Schema

Tool discoveryでは9 Toolすべての入力・出力Schemaを取得できます。Patch系Toolの`patch`引数には、次の要素がSchemaとして含まれます。

- `schemaVersion: "0.13.0"`
- `baseModuleId`
- 7種類の判別可能なOperation Union
- Operationごとの`target / expectedId / member / value / index`
- `static / affected-tests / all-tests`の検証義務

MCP Resultは常に次のEnvelopeです。

```json
{
  "ok": true,
  "result": {
    "ok": true,
    "module": "TodoCrud",
    "moduleId": "sha256:..."
  },
  "diagnostics": []
}
```

外側の`ok`はTool呼出し自体の成否です。内側の`result.ok`は、たとえば`verify`でTestが成功したかを表します。構文Errorや未知SymbolはMCP Protocol Errorにせず、外側`ok: false`と構造化診断で返します。

## Project Root境界

`AgentService`とMCP Serverは起動時にProject Rootを1つ固定します。

- 相対PathはRootを基準に解決
- 絶対PathもRoot内だけ許可
- `..`およびSymbolic Link解決後にRoot外へ出るPathを拒否
- `apply_patch`は既定で拒否し、明示許可時もRoot内Sourceだけに書込み可能
- MCP Serverは現在Local stdioのみ

Root外への要求は`source_outside_project_root`として拒否します。これはOS Sandboxの代替ではなく、Server自身が持つ追加境界です。

## 検証結果

2026-07-21に通常環境とMCP optional環境の両方で検証しました。

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q intentir tests

/tmp/intentir-mcp-venv/bin/python -m unittest discover -s tests -v
```

- 合計91 Test
- 90 Testは外部依存なしで成功
- 公式MCP Python SDK 1.28.1を使う1 Testも成功
- MCP initialize、Tool discovery、入力Schema、stdio実呼出しを確認
- 書込み既定拒否と`write_tool_disabled`診断を確認
- read-only/destructive/idempotentのTool annotationを確認
- TypedなPatch Operation Unionをstdio経由で送信し、dry-run成功とSource未変更を確認
- 成功Resultと未知Symbolの構造化失敗を確認
- Root外Path拒否、Context/Impact、Agent CLI、Patch dry-run/apply/stale拒否を確認
- IR/TypeScript/SQLiteの3 Build Targetを確認

MCP SDKが未導入の通常環境ではMCP専用TestだけがSkipされ、残り90件は成功します。

## 現在の制約

- MCP TransportはLocal stdioのみ
- Streamable HTTP、認証、Remote Deploymentは未実装
- MCP ResourceとPromptは未実装
- Host Applicationごとの自動Install設定は未実装
- Tool呼出しの永続監査Log、Rate Limit、利用者承認UIはHost側の責務であり、書込み有効化前に実装確認が必要
- OpenAI Provider Wrapperはあるが、実API疎通とCostは未検証
- IntentBench-EvolveはFixture 1 Applicationだけで、実Model Pilotは未実施

次は、固定した実ModelとPromptで少額疎通を確認してから`IntentBench-Evolve`を40 Checkpointへ拡張し、成功率、古いPatch誤受理率、Token、Latency、修復回数を記録します。
