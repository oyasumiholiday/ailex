# IntentIR

[English](README.md) · [試す手順](QUICKSTART.md) · [開発目標](GOALS_JA.md)

IntentIR は、AI が型のあるプログラムを作り、別の AI に渡し、検証し、必要な部分を変更するための中間言語です。関数やデータだけでなく、依存関係、契約、変更前の状態を確認するための ID も機械が扱える形で表します。

## 公開版でできること

この公開リポジトリと alpha wheel では、テキスト形式の `.intent` を入力に使います。型検査、純粋関数の実行、実行例とシナリオの検証、SQLite への保存、TypeScript の生成、変更前の ID を照合する Patch に対応しています。Agent Tools と任意のローカル MCP サーバーからも操作できます。

構造化された JSON を直接書く `.intent.json` の入力機能は、ローカル開発段階のものです。この公開リポジトリにも公開 wheel にも含まれません。JSON の診断、Patch、出力用の意味 IR は、それとは別のものです。

公開版の参照先は [IntentIR 0.15.0a3 alpha](https://github.com/oyasumiholiday/ailex/releases/tag/intentir-v0.15.0a3) と [タグ固定の日本語ガイド](https://github.com/oyasumiholiday/ailex/blob/intentir-v0.15.0a3/docs/TRY_IT_JA.md)です。以前の版の確認手順は [alpha2 公開試用チェックリスト](docs/PUBLIC_TRIAL_JA.md)に残しています。

## まず試す

Python 3.11 以上を使います。[Quickstart](QUICKSTART.md)には、公開 wheel のインストール、Todo の作成、状態の読み取り、バックアップ・復元、Patch と移行、Container の手順があります。インストール後の基本的な試用にモデル API キーは不要です。

ソースを取得済みなら、リポジトリのルートで次を実行できます。

```sh
python3 -m intentir check examples/todo_crud.intent
python3 -m intentir test examples/todo_crud.intent
python3 -m intentir demo concurrent-agent
```

最後の実演では、同じプログラムを読んだ二つのエージェントのうち、一方の変更後に古くなった Patch を拒否し、情報を読み直してから変更します。これは決められた手順の実演であり、異なるベンダーの AI 同士で交換できたという実験結果ではありません。

## 開発の方向と限界

現在の開発対象は IntentIR です。今後は、要素数と処理量に上限のあるコレクション、AI による作成・変更・交換、独立した利用者による試用を段階的に確かめます。CRUD は公開版で試せる用途の一つであり、将来の用途をそれだけに限定しません。詳しくは [開発目標](GOALS_JA.md)を参照してください。

公開版の純粋関数は単一の値を扱い、コレクション、汎用ループ、一般再帰には対応していません。Patch の ID 照合や型検査は、完全な実行隔離や全入力に対する正しさの証明ではありません。研究発表や有料モデル比較は、通常の言語開発とは分けて判断します。過去の実験承認は、新たな課金や外部送信の承認として使いません。

## 開発時の検証

生成 TypeScript の実行には、CI と同じ Node.js 24 を使います。

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q intentir tests
```

任意の MCP 依存関係や Node がなく実行できなかった検査は、その旨を報告します。詳しい手順は [Contributing](CONTRIBUTING.md)、AI 向けの指示は [AGENTS.md](AGENTS.md)、脆弱性の連絡先は [SECURITY.md](SECURITY.md)を参照してください。

## 旧 Ailex とライセンス

旧実装と資料は削除せず、[Ailex の履歴案内](docs/LEGACY_AILEX.md)から参照できます。旧日本語 README も原文のまま保存しています。Ailex と IntentIR の構文や実装は別であり、両者の統合を前提にしません。

旧 Ailex 実装は [MIT](LICENSE)、IntentIR Python パッケージと新しい関連ファイルは [Apache-2.0](LICENSE-APACHE)です。この文書整理でライセンスは変わりません。
