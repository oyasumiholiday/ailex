# IntentIR Todo スターター

このディレクトリには、永続化できる Todo の IntentIR ソースと、`priority` フィールドを追加するセマンティック Patch が含まれます。`intentir init` 自体はデータベースを作成せず、API やモデルも呼び出しません。

## 作成と永続化

Python 3.11 以上と IntentIR 0.15.0a2 が必要です。以下は macOS / Linux の shell 例です。`DEST` は `intentir init todo DEST` で作成したディレクトリに置き換え、生成先から実行してください。Quickstart のように仮想環境を有効化していない場合は、各 `intentir` を `"$TODO_ENV/bin/intentir"` に置き換えます。

```sh
cd DEST
intentir check todo.intent --json
intentir test todo.intent --json
intentir run todo.intent CreateTask \
  --input '{"id":"task-1","title":"牛乳を買う"}' --db todo.db
intentir run todo.intent CompleteTask \
  --input '{"id":"task-1"}' --db todo.db
```

各コマンドは別プロセスで実行できます。`todo.db` が状態を保持します。`intentir test` が検証するのはソース内のテストシナリオであり、永続 DB の内容ではありません。空のタイトルは契約違反として拒否され、保存済みタスクの内容は変更されません。

## Patch とマイグレーション

Patch を適用する前に、書き込みプロセスを停止し、`todo.intent` と `todo.db` を対でバックアップしてください。ソースだけ、または DB だけの復元はスキーマ不一致の原因になります。最初の `migrate` は計画だけを表示し、2回目で適用します。

```sh
intentir patch todo.intent add_task_priority.patch.json --apply --json
intentir migrate todo.intent --db todo.db --json
intentir migrate todo.intent --db todo.db --apply --json
intentir run todo.intent RenameTask \
  --input '{"id":"task-1","title":"牛乳を2本買う"}' --db todo.db
```

移行後も `done` は保持され、新しい `priority` は既定値 `0` になります。

CRUD の流れを完了する場合は、最後にタスクを削除できます。

```sh
intentir run todo.intent DeleteTask \
  --input '{"id":"task-1"}' --db todo.db
```

## 注意事項

- これはローカル学習用の最小例です。認証、認可、同時実行制御、監査、配備設定を備えた本番アプリケーションではありません。
- `intentir init todo DEST` は新しい `DEST` だけを作成します。既存のファイル、ディレクトリ、symlink は上書きしません。
