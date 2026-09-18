# IntentIR notation lab alpha を試す

> **Alpha プレビュー (`0.15.0a2`)**
>
> これは実験用の限定デモです。互換性、継続提供、性能、セキュリティ、または本番利用への適合を約束するものではありません。本番システムや重要な計算には使用しないでください。

このガイドは、次のどちらからでも利用できます。

- **共有 ZIP を受け取った場合**: ZIP を展開し、そのディレクトリで「共有 ZIP から試す」を実行します。Git、Node.js、npm、API キー、実行時ネットワーク接続は不要です。
- **ソースチェックアウトを使う場合**: リポジトリのルートで「ソースチェックアウトから試す」を実行します。共有 ZIP の wheel をソースからインストールする手順ではありません。

必要なのは Python 3.11 以上と、標準の `venv` / `pip` です。Windows のコマンド例では、ネイティブコマンドへの JSON 引数を引用符どおり渡すため PowerShell 7.3 以上を使用してください。コマンドは仮想環境を有効化せず、仮想環境内の実行ファイルを直接呼び出します。

この alpha は macOS 上でローカル検証済みで、Linux は GitHub Actions CI で検証済みです。Windows は未実施です。

## 共有 ZIP から試す

以下の手順は **ZIP を展開した後**、`README_JA.md` と `intentir-0.15.0a2-py3-none-any.whl` が見えるディレクトリで実行してください。

### macOS / Linux

```sh
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps ./intentir-0.15.0a2-py3-none-any.whl
.venv/bin/intentir demo notation-lab
```

同じデモの機械可読な詳細は `.venv/bin/intentir demo notation-lab --json` で確認できます。

### Windows PowerShell

```powershell
py -3.11 --version
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --no-index --no-deps .\intentir-0.15.0a2-py3-none-any.whl
.venv\Scripts\intentir.exe demo notation-lab
```

同じデモの機械可読な詳細は `.venv\Scripts\intentir.exe demo notation-lab --json` で確認できます。

`--no-index --no-deps` により、インストール対象は ZIP 内のローカル wheel だけです。コマンドが成功すると、3 形式の結果がすべて `380`、置換後の結果が `390` と表示されます。

## Todo スターターを試す

以下は macOS / Linux の例です。ZIP を展開したルートから実行し、仮想環境を有効化せず、その絶対パスを使い続けます。

```sh
ZIP_ROOT="$(pwd)"
INTENTIR="$ZIP_ROOT/.venv/bin/intentir"
APP="$ZIP_ROOT/my-todo"
"$INTENTIR" init todo "$APP" --json
"$INTENTIR" check "$APP/todo.intent" --json
"$INTENTIR" test "$APP/todo.intent" --json
"$INTENTIR" run "$APP/todo.intent" CreateTask \
  --input '{"id":"task-1","title":"牛乳を買う"}' --db "$APP/todo.db"
"$INTENTIR" run "$APP/todo.intent" CompleteTask \
  --input '{"id":"task-1"}' --db "$APP/todo.db"
```

Patch の前に、書き込みプロセスをすべて停止し、停止したままソースと DB を必ず対でバックアップしてください。以下は既存のバックアップ先を上書きせず、DB を read-only URI で開いて SQLite の backup API で複製します。

```sh
BACKUP="$ZIP_ROOT/my-todo-backup"
"$ZIP_ROOT/.venv/bin/python" - "$APP" "$BACKUP" <<'PY'
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

app = Path(sys.argv[1])
backup = Path(sys.argv[2])
source = (app / "todo.intent").resolve(strict=True)
database = (app / "todo.db").resolve(strict=True)

backup.mkdir(mode=0o700, exist_ok=False)
shutil.copyfile(source, backup / "todo.intent")
database_uri = database.as_uri() + "?mode=ro"
with closing(sqlite3.connect(database_uri, uri=True)) as source_db:
    with closing(sqlite3.connect(backup / "todo.db")) as backup_db:
        source_db.backup(backup_db)
PY

"$INTENTIR" patch "$APP/todo.intent" \
  "$APP/add_task_priority.patch.json" --apply --json
"$INTENTIR" migrate "$APP/todo.intent" --db "$APP/todo.db" --json
"$INTENTIR" migrate "$APP/todo.intent" --db "$APP/todo.db" --apply --json
"$INTENTIR" run "$APP/todo.intent" RenameTask \
  --input '{"id":"task-1","title":"牛乳を2本買う"}' --db "$APP/todo.db"
```

これは停止中の writer を前提とした対の取得であり、ホットバックアップやソースと DB をまたぐ原子的スナップショットではありません。ロールバック時も、ソースだけではなく同じバックアップにある DB と対で復元してください。

移行後の出力では、完了状態が保持され、`priority` が既定値 `0` になっていることを確認できます。不要になったタスクは任意で削除できます。

```sh
"$INTENTIR" run "$APP/todo.intent" DeleteTask \
  --input '{"id":"task-1"}' --db "$APP/todo.db"
```

## 3 形式のサンプルを実行する

同じ計算を次の 3 ファイルで表しています。

- `examples/notation_lab/price.expr`: 式 `price * quantity + fee`
- `examples/notation_lab/price.graph.json`: 明示的なグラフ JSON
- `examples/notation_lab/price.rows.json`: 同じグラフのコンパクトな行形式 JSON

入力は `price=120`、`quantity=3`、`fee=20` です。各コマンドの JSON 出力で `"ok": true` と `"result": 380` を確認してください。

### macOS / Linux

```sh
.venv/bin/intentir-notation run --format expression --source examples/notation_lab/price.expr --inputs '{"price":120,"quantity":3,"fee":20}'
.venv/bin/intentir-notation run --format graph-json --source examples/notation_lab/price.graph.json --inputs '{"price":120,"quantity":3,"fee":20}'
.venv/bin/intentir-notation run --format rows-json --source examples/notation_lab/price.rows.json --inputs '{"price":120,"quantity":3,"fee":20}'
```

### Windows PowerShell

```powershell
.venv\Scripts\intentir-notation.exe run --format expression --source examples\notation_lab\price.expr --inputs '{"price":120,"quantity":3,"fee":20}'
.venv\Scripts\intentir-notation.exe run --format graph-json --source examples\notation_lab\price.graph.json --inputs '{"price":120,"quantity":3,"fee":20}'
.venv\Scripts\intentir-notation.exe run --format rows-json --source examples\notation_lab\price.rows.json --inputs '{"price":120,"quantity":3,"fee":20}'
```

`graph-json` と `rows-json` の成功出力には、読み込んだグラフの `graphHash` も含まれます。`demo notation-lab` は `fee` 入力ノードを定数 `30` に置換する決定的な例も実行し、その `patch.result` は `390` です。この置換はデモ内だけで行われ、サンプルファイルは変更されません。

## ソースチェックアウトから試す

リポジトリのルートでは、インストールせずに Python モジュールとして実行できます。

### macOS / Linux

```sh
python3 -m venv .venv
.venv/bin/python -m intentir demo notation-lab
.venv/bin/python -m intentir.notation_lab run --format expression --source examples/notation_lab/price.expr --inputs '{"price":120,"quantity":3,"fee":20}'
```

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m intentir demo notation-lab
.venv\Scripts\python.exe -m intentir.notation_lab run --format expression --source examples\notation_lab\price.expr --inputs '{"price":120,"quantity":3,"fee":20}'
```

ソース自体を仮想環境へインストールする場合は、リポジトリのルートで `.venv/bin/python -m pip install --no-deps .`、PowerShell では `.venv\Scripts\python.exe -m pip install --no-deps .` を使います。これは共有 ZIP 内のローカル wheel を使うオフライン手順とは別です。

## このデモが示す範囲

notation lab は、同じ整数式を式、グラフ JSON、行形式 JSONで表し、同じ既存評価器で実行する手設計の決定的な比較です。実モデルや生成 AI は呼び出さず、API キーも使いません。出力が毎回同じになるように作られており、モデルや手法の優位性を示すものではありません。

現在の実験範囲は整数のリテラルと入力、二項演算 `+` / `-` / `*`、単項演算 `+` / `-` に限定されています。除算、浮動小数点、文字列、関数呼び出し、比較、条件式などは対象外です。入力サイズ、ノード数、深さ、整数ビット長にも上限があります。これは表記法を比較するための alpha 実験であり、汎用の算術処理系、本番向けランタイム、または研究上の新規性を主張するものではありません。

## 配布物を確認する

`SHA256SUMS` には wheel、ガイド、3 サンプル、ライセンスの SHA-256 が記録されています。改行や空白もハッシュに含まれるため、ファイルを編集する前に確認してください。

### macOS / Linux

Linux:

```sh
sha256sum -c SHA256SUMS
```

macOS:

```sh
shasum -a 256 -c SHA256SUMS
```

### Windows PowerShell

```powershell
Get-Content SHA256SUMS
Get-FileHash -Algorithm SHA256 .\intentir-0.15.0a2-py3-none-any.whl
```

## 不具合を報告する

[GitHub Issues](https://github.com/oyasumiholiday/ailex/issues) に、OS、Python バージョン、実行したコマンド、期待した結果、実際の JSON 出力またはエラー、`SHA256SUMS` の wheel ハッシュを添えてください。

API キー、トークン、パスワード、`.env` の内容、個人情報、非公開の研究データ、社内パスは送らないでください。コマンドや出力に含まれるユーザー名、絶対パス、入力データも必要に応じて伏せてください。
