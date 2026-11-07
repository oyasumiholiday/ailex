# IntentIR の MCP 依存関係の更新（2026-11-07）

IntentIR のオプション機能 `mcp` を利用している場合は、MCP サーバーを起動する Python 仮想環境の依存関係を更新してください。IntentIR 本体には外部ランタイム依存関係がなく、基本 CLI だけを使う場合は、このために `mcp` を追加する必要はありません。

## インストール済みの MCP サーバー

1. 実行中の IntentIR MCP サーバーを停止します。
2. MCP クライアントがサーバーの起動に使う仮想環境を有効にし、その環境の `python` で次のコマンドを実行します。システム全体の Python 環境にはインストールしないでください。

   ```sh
   python -m pip install --upgrade 'mcp>=1.30.0,<2' 'PyJWT[crypto]>=2.15.1,<3' 'certifi>=2026.10.19'
   ```

3. 更新した仮想環境を使う設定で MCP サーバーを再起動します。クライアントがサーバーを起動する構成では、クライアントから起動し直します。

## リポジトリから実行する場合

更新済みのデフォルトブランチをチェックアウトし、リポジトリのルートで実行します。生成した TypeScript を実行するテストには Node.js 24 が必要です。

```sh
uv sync --frozen --extra mcp
uv run --frozen --extra mcp python -m unittest discover -s tests -v
```

デフォルトブランチの依存関係を更新しても、利用者の仮想環境には自動で反映されません。公開済みのアルファ版の配布物は変更されず、今回の変更に伴う新規リリースもありません。

## 検証結果と確認範囲

- 確認に使った依存バージョンは MCP 1.30.0、PyJWT 2.15.1、certifi 2026.10.23 です。
- Python 3.12.11 で `mcp` を有効にしたテストは 168 件すべて成功し、スキップはありませんでした。PyJWT の回帰テストと MCP の標準入出力による統合テストを含みます。
- ビルドした wheel のメタデータに、`mcp` オプションの依存関係 3 件の下限が記録されていることを確認しました。チェックアウト外にインストールした wheel で、Todo スターター（同梱ファイルの読み込みを含む）、MCP の標準入出力による統合テスト、PyJWT の回帰テストが成功しました。
- ロックファイルから固定バージョン付きでエクスポートした依存関係のうち、検証ホストの環境マーカーに該当する 29 パッケージを `pip-audit` で検査し、既知の脆弱性は 0 件でした。
- 対応開始時点の GitHub Dependabot アラートは 19 件（Critical 2 件、High 6 件、Medium 11 件）でした。全件が解消されたかは、変更をデフォルトブランチに反映した後の GitHub の再評価で確認します。

## 関連情報

- MCP: [Python SDK 1.30.0 リリースノート](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v1.30.0)
- certifi: [GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2)。アドバイザリは 2026.10.19 以降への更新を推奨しています。
- PyJWT: [GHSA-ffc3-869f-jxw9](https://github.com/advisories/GHSA-ffc3-869f-jxw9) の修正版は 2.14.0 です。今回の下限には、JWS のデコード互換性を修正した [2.15.1](https://github.com/jpadilla/pyjwt/releases/tag/2.15.1) を採用しました。
- PyJWT: [GHSA-gvp8-978c-rx2q](https://github.com/advisories/GHSA-gvp8-978c-rx2q) には修正版の記載がありません。2.15.1 では、呼び出し元の検証オプションが書き換わらず、署名検証を再度有効にすると期限切れトークンが拒否されることを回帰テストで確認しました。この結果は、テストした条件での動作に限られます。
