# IntentIR 0.15.0a2 公開試用チェックリスト

これは、希望する方が公開版を試すときに手元で使える実務的なチェックリストです。学術研究への参加募集、調査票、個人データ収集ではありません。結果は自動送信されず、この手順を試したり通常のサポート報告を行ったりすることは、研究発表への利用に同意することを意味しません。独立した試用が完了したという主張も本書では行いません。

## 固定対象

- Release: [`intentir-v0.15.0a2`](https://github.com/oyasumiholiday/ailex/releases/tag/intentir-v0.15.0a2)
- Source commit: [`cb154fb1f56476644b9237fb191dad5002fe3f99`](https://github.com/oyasumiholiday/ailex/commit/cb154fb1f56476644b9237fb191dad5002fe3f99)
- 固定版ガイド: [`docs/TRY_IT_JA.md`](https://github.com/oyasumiholiday/ailex/blob/cb154fb1f56476644b9237fb191dad5002fe3f99/docs/TRY_IT_JA.md)
- ZIP SHA-256: `b9e755a26dde53a29a54e49878ff567ac23fe1789372b8b0ec9e0b772a6e0570`
- wheel SHA-256: `8c82ebddaced33d9eba4dd7bcb9014057ebeced21ec51d21e09329d7bbeebdf8`

Python 3.11 以上が必要です。ソース checkout、API キー、モデル呼び出し、有料 API は不要です。入力と SQLite DB はローカルにだけ保存されます。macOS はローカル検証済み、Linux は CI 検証済みです。Windows は限定された公開 wheel CI のみ確認済みです。条件と範囲は [Windows 公開 wheel 確認](WINDOWS_RELEASE_CHECK_JA.md) を参照してください。

各項目の状態は `未実施`、`成功`、`失敗`、`該当なし` のいずれかで記録します。追加チェックを行わない場合は `該当なし` とし、未実施の変更・移行をワークフロー全体の成功として扱わないでください。

## SHA-256 の確認

ダウンロードした ZIP は展開前に確認します。

```sh
# Linux
sha256sum intentir-0.15.0a2-preview.zip

# macOS
shasum -a 256 intentir-0.15.0a2-preview.zip
```

ZIP を展開した後、そのルートで wheel を確認します。

```sh
# Linux
sha256sum intentir-0.15.0a2-py3-none-any.whl

# macOS
shasum -a 256 intentir-0.15.0a2-py3-none-any.whl
```

各コードブロックでは、このうち自分の OS の1行だけを実行し、表示された値を「固定対象」の値と照合します。一致しなければ停止してください。

Windows の公開 wheel は CI で限定的に確認していますが、以降は人向けの POSIX 手順であり、Windows 向け手順としては未検証です。`mktemp`、POSIX パス、shell コマンドを PowerShell へそのまま貼り付けないでください。Windows でこのチェックリストを使う場合、Todo 操作は `該当なし` とし、CI の技術的な再現だけが必要な場合は [Windows 公開 wheel 確認](WINDOWS_RELEASE_CHECK_JA.md) のスクリプトを使用してください。

## 基本チェック

Release ZIP を新しいディレクトリへ展開し、固定版ガイドのコマンドを使います。各コマンドは成功時の JSON 内容も確認し、終了コードだけで判定しないでください。

| 状態 | 確認内容 | 期待する結果 |
|---|---|---|
| 未実施 | ZIP の SHA-256 を確認 | 上記 ZIP SHA-256 と一致 |
| 未実施 | wheel の SHA-256 を確認 | 上記 wheel SHA-256 と一致 |
| 未実施 | 新しい venv へ `--no-index --no-deps` で wheel をインストール | 外部依存を取得せず完了 |
| 未実施 | `intentir demo notation-lab --json` | 3形式が `380`、置換後が `390` |
| 未実施 | 存在しない子パスへ `intentir init todo` | 3つのテンプレートファイルを生成 |
| 未実施 | 生成した `todo.intent` を `check --json`、`test --json` | 両方とも `ok: true` |
| 未実施 | 新しいプロセスで `CreateTask`、続いて別プロセスで `CompleteTask` | 同じ DB に1件保持され、`done: true` |

ZIP は毎回新しい場所へ展開し、ガイドの `my-todo` がまだ存在しないことを確認してください。既存なら削除や上書きをせず、別の新規展開先を使ってください。

## 追加チェック

変更・移行も確認する場合は、以下のうち削除以外をバックアップから順にすべて実施します。Patch 前に、固定版ガイドどおり writer を停止し、ソースをコピーして SQLite の read-only URI と `Connection.backup` で DB を同じ新規バックアップディレクトリへ保存します。DB ファイルを実行中に raw copy しないでください。

| 状態 | 確認内容 | 期待する結果 |
|---|---|---|
| 未実施 | ソースと DB の対バックアップ | 新規バックアップ先に両方存在 |
| 未実施 | priority Patch を適用 | `applied: true` |
| 未実施 | migration plan を表示 | safe 1、destructive 0、manual 0、未適用 |
| 未実施 | migration を適用 | `applied: true`、Task 1件 |
| 未実施 | `RenameTask` を実行 | `done: true` を保持し、`priority: 0` |
| 未実施 | `DeleteTask` を実行（任意） | `Task` が空 |

追加チェックの成功は、対バックアップ、Patch、migration plan、migration 適用、Rename のすべてが成功した場合にだけ記録します。Delete は省略しても追加チェックを成功とできます。

## 試用メモ（空欄）

- 全体状態: 未実施
- OS: 未実施
- Python バージョン: 未実施
- IntentIR バージョン: `0.15.0a2`
- 基本チェックの結果: 未実施
- 追加チェックの結果: 未実施
- ヘルプを受けたか: 未実施
- 最初に失敗した手順: 未実施
- 最初の失敗時の診断（必要部分のみ匿名化）: 未実施
- 再試行: 未実施
- 備考: 未実施

## 失敗時

最初に失敗した workspace は変更せず保持し、元の失敗と匿名化した診断を記録してください。再試行する場合は別の新しい workspace を作り、元の失敗を上書きしないでください。保存するのは必要な構造化診断だけです。全ログ、環境変数一覧、ホームディレクトリの絶対パス、秘密、個人情報、非公開ソース、`.env`、DB 本体は収集・添付しないでください。

通常の不具合は [GitHub Issues](https://github.com/oyasumiholiday/ailex/issues) へ、OS、Python、IntentIR の最小限のバージョン情報、失敗手順、期待結果、匿名化した診断を添えて報告できます。セキュリティ上の問題は公開 Issue に詳細を書かず、[SECURITY.md](../SECURITY.md) に従って [GitHub Private Vulnerability Reporting](https://github.com/oyasumiholiday/ailex/security/advisories/new) を使用してください。
