# Ailex + IntentIR Quickstart

Use this page for a short local or Container trial. No model API key, database server, or network service is required after installation.

## Install the prerelease wheel

Requires Python 3.11 or newer. The current public preview uses the tag `intentir-v0.15.0a1`; install its wheel without a source checkout and run the standalone demonstration:

```sh
DEMO_ENV="$(mktemp -d)"
python3 -m venv "$DEMO_ENV"
"$DEMO_ENV/bin/pip" install --no-deps \
  https://github.com/oyasumiholiday/ailex/releases/download/intentir-v0.15.0a1/intentir-0.15.0a1-py3-none-any.whl
"$DEMO_ENV/bin/intentir" demo concurrent-agent
```

This installation step downloads the wheel. The demonstration itself uses a temporary workspace and makes no model API or other network calls.

## Use a source checkout

```sh
git clone https://github.com/oyasumiholiday/ailex.git
cd ailex
```

## Try Ailex

Requires Node.js 23 or newer.

```sh
npm ci --ignore-scripts
node core/cli.ts run examples/points.ax
npm test
```

## Try IntentIR

Requires Python 3.11 or newer. IntentIR has no mandatory third-party runtime dependency.

```sh
python3 -m intentir check examples/todo_crud.intent
python3 -m intentir test examples/todo_crud.intent
python3 -m intentir demo concurrent-agent
```

The demonstration shows two agents reading the same content-addressed graph. Agent A applies a guarded Patch, Agent B's stale Patch is rejected, and Agent B refreshes before applying a verified replacement.

Install the command from the checkout in an isolated environment when preferred:

```sh
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/intentir demo concurrent-agent
```

## Todo starter (0.15.0a2 UNRELEASED)

The `init` command is currently available only from a source installation of the unreleased `0.15.0a2` development version. It creates a new directory from resources packaged inside IntentIR; it does not read examples from the repository at runtime.

```sh
python3 -m venv .venv
TODO_ENV="$(pwd)/.venv"
"$TODO_ENV/bin/pip" install .
"$TODO_ENV/bin/intentir" init todo "$HOME/intentir-todo" --json
cd "$HOME/intentir-todo"
"$TODO_ENV/bin/intentir" check todo.intent --json
"$TODO_ENV/bin/intentir" test todo.intent --json
```

The destination parent must already exist. `init` refuses every existing destination, including an empty directory, file, or symlink, and does not create a database or make API or model calls. See the generated `README_JA.md` for the persistent create/complete flow and the backup, Patch, and migration procedure.

## Persistent Todo, Patch, and Migration

This walkthrough copies the application and semantic Patch into a fresh temporary directory. It does not overwrite either checked-in sample or an existing database.

```sh
WORK="$(mktemp -d)"
cp examples/todo_crud.intent "$WORK/todo.intent"
cp examples/add_task_priority.patch.json "$WORK/add_task_priority.patch.json"

python3 -m intentir run "$WORK/todo.intent" CreateTask \
  --input '{"id":"task-1","title":"buy milk"}' --db "$WORK/todo.db"
python3 -m intentir run "$WORK/todo.intent" CompleteTask \
  --input '{"id":"task-1"}' --db "$WORK/todo.db"
```

### Optional backup before patching

For a release-gate backup rehearsal, stop every process that can write either `todo.intent` or `todo.db`. Keep all writers stopped for the entire source copy and database backup below. The destination directory is created exclusively, the database is opened through a read-only URI so a missing source cannot be created accidentally, and SQLite performs the database copy through its standard backup API.

```sh
BACKUP="$WORK-backup"
python3 - "$WORK" "$BACKUP" <<'PY'
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

work = Path(sys.argv[1])
backup = Path(sys.argv[2])
source = (work / "todo.intent").resolve(strict=True)
database = (work / "todo.db").resolve(strict=True)

backup.mkdir(mode=0o700, exist_ok=False)
shutil.copyfile(source, backup / "todo.intent")
database_uri = database.as_uri() + "?mode=ro"
with closing(sqlite3.connect(database_uri, uri=True)) as source_db:
    with closing(sqlite3.connect(backup / "todo.db")) as backup_db:
        source_db.backup(backup_db)
PY
```

This is a paired, stopped-writer capture, not an atomic cross-file snapshot or a hot-backup procedure. Once both operations finish, continue with the semantic Patch and migration:

```sh
python3 -m intentir patch "$WORK/todo.intent" \
  "$WORK/add_task_priority.patch.json" --apply
python3 -m intentir migrate "$WORK/todo.intent" --db "$WORK/todo.db"
python3 -m intentir migrate "$WORK/todo.intent" --db "$WORK/todo.db" --apply

python3 -m intentir run "$WORK/todo.intent" RenameTask \
  --input '{"id":"task-1","title":"buy oat milk"}' --db "$WORK/todo.db"
```

### Optional restore rehearsal

This step requires the optional backup above. Stop all processes that could write the backup pair or restore destination for the entire restore. Restore into a new work directory so neither the migrated database in `$WORK` nor the backup in `$BACKUP` is overwritten:

```sh
RESTORED="$WORK-restored"
python3 - "$BACKUP" "$RESTORED" <<'PY'
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

backup = Path(sys.argv[1])
restored = Path(sys.argv[2])
source = (backup / "todo.intent").resolve(strict=True)
database = (backup / "todo.db").resolve(strict=True)

restored.mkdir(mode=0o700, exist_ok=False)
shutil.copyfile(source, restored / "todo.intent")
database_uri = database.as_uri() + "?mode=ro"
with closing(sqlite3.connect(database_uri, uri=True)) as backup_db:
    with closing(sqlite3.connect(restored / "todo.db")) as restored_db:
        backup_db.backup(restored_db)

restored_uri = (restored / "todo.db").resolve(strict=True).as_uri() + "?mode=ro"
with closing(sqlite3.connect(restored_uri, uri=True)) as restored_db:
    if restored_db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise RuntimeError("restored SQLite integrity check failed")
    table = restored_db.execute(
        "SELECT table_name FROM intentir_relations "
        "WHERE module = ? AND entity = ?",
        ("TodoCrud", "Task"),
    ).fetchone()[0]
    quoted_table = '"' + table.replace('"', '""') + '"'
    columns = {
        row[1] for row in restored_db.execute(f"PRAGMA table_info({quoted_table})")
    }
    row = restored_db.execute(
        f"SELECT id, title, done FROM {quoted_table}"
    ).fetchone()
    if "priority" in columns or row != ("task-1", "buy milk", 1):
        raise RuntimeError("restored source/database pair does not match snapshot")
PY

python3 -m intentir run "$RESTORED/todo.intent" CompleteTask \
  --input '{"id":"task-1"}' --db "$RESTORED/todo.db"
```

The read-only inspection happens before the CLI action and verifies that the restored database retains the pre-patch task with `done: true` and title `buy milk`, with no `priority` column. The unchanged restored source then runs successfully against that database. The later rename is absent because restoring an older snapshot necessarily loses every post-backup write. Database transaction rollback is not migration rollback; migration recovery requires restoring the rehearsed source-and-database pair. This restore leaves both the old backup and the migrated database intact.

The original walkthrough can optionally finish by deleting the task from the migrated database; this command is separate from the restore rehearsal and intentionally changes `$WORK/todo.db`:

```sh
python3 -m intentir run "$WORK/todo.intent" DeleteTask \
  --input '{"id":"task-1"}' --db "$WORK/todo.db"
```

Every IntentIR command is a new process. The SQLite database preserves the completed task between them; the migration fills the newly added `priority` field with its default `0`. The rename output therefore contains `done: true`, the new title, and `priority: 0`, and the final delete output contains an empty `Task` list. The first `migrate` only prints the plan; the second applies it.

## Run the Container

Build the pinned Python 3.13 image:

```sh
docker build --pull -t intentir:0.14 .
```

Run the default concurrent-agent demonstration without network access and with a read-only root filesystem:

```sh
docker run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  intentir:0.14
```

Run another IntentIR command by replacing the default arguments:

```sh
docker run --rm --network none intentir:0.14 \
  test examples/todo_crud.intent
```

## Next Steps

- [Ailex language guide](AILEX_README.md)
- [IntentIR commands and architecture](README.md)
- [Concurrent-agent scenario](demo/concurrent_agent/README.md)
- [IntentBench-Evolve](benchmarks/intentbench_evolve/README.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
