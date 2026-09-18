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

## 保存状態の読み取り（IntentIR 0.15.0a3 以上）

この節は任意で、IntentIR 0.15.0a3 以上が必要です。0.15.0a3 は現在 **UNRELEASED** の開発版です。`read` は JSON を自動で出力し、action の実行やデータベースの新規作成は行いません。Complete 後の状態全体と `Task` だけの状態は、次のどちらでも確認できます。

```sh
intentir read todo.intent --db todo.db
intentir read todo.intent --db todo.db --entity Task
```

どちらの `state` も `{"Task":[{"done":true,"id":"task-1","title":"牛乳を買う"}]}` です。

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

0.15.0a3 以上では、Patch 直後の `read` はスキーマ不一致の JSON 診断を出して終了ステータス 1 で拒否されます。明示的な `migrate --apply` が成功するまで読み取りません。移行と Rename 後は、任意で次を実行できます。

```sh
intentir read todo.intent --db todo.db --entity Task
```

`state` は `{"Task":[{"done":true,"id":"task-1","priority":0,"title":"牛乳を2本買う"}]}` です。

`read` は SQLite を `mode=ro` で開き、論理データ、スキーマ、journal mode を変更しません。ただし、SQLite による `-wal` / `-shm` sidecar の利用や作成まで禁止するものではありません。

CRUD の流れを完了する場合は、最後にタスクを削除できます。

```sh
intentir run todo.intent DeleteTask \
  --input '{"id":"task-1"}' --db todo.db
```

0.15.0a3 以上では、削除後に任意で次を実行できます。

```sh
intentir read todo.intent --db todo.db
```

`state` は `{"Task":[]}` です。

## 注意事項

- これはローカル学習用の最小例です。認証、認可、同時実行制御、監査、配備設定を備えた本番アプリケーションではありません。
- `intentir init todo DEST` は新しい `DEST` だけを作成します。既存のファイル、ディレクトリ、symlink は上書きしません。
