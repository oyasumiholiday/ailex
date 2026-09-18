# Ailex + IntentIR Quickstart

Use this page for a short local or Container trial. No model API key, database server, or network service is required after installation.

## Install the prerelease wheel

Requires Python 3.11 or newer. Install the `intentir-v0.15.0a3` alpha wheel without a source checkout and run the standalone demonstration:

```sh
DEMO_ENV="$(mktemp -d)"
python3 -m venv "$DEMO_ENV"
"$DEMO_ENV/bin/pip" install --no-deps \
  https://github.com/oyasumiholiday/ailex/releases/download/intentir-v0.15.0a3/intentir-0.15.0a3-py3-none-any.whl
"$DEMO_ENV/bin/intentir" demo concurrent-agent
```

This installation step downloads the wheel. The demonstration itself uses a temporary workspace and makes no model API or other network calls.

## Todo starter from the public wheel

Reuse the isolated environment above. Create a fresh parent directory and pass a child path that does not exist yet, because `init` intentionally refuses to overwrite any existing destination:

```sh
TODO_PARENT="$(mktemp -d)"
TODO_APP="$TODO_PARENT/my-todo"
"$DEMO_ENV/bin/intentir" init todo "$TODO_APP" --json
"$DEMO_ENV/bin/intentir" check "$TODO_APP/todo.intent" --json
"$DEMO_ENV/bin/intentir" test "$TODO_APP/todo.intent" --json
"$DEMO_ENV/bin/intentir" run "$TODO_APP/todo.intent" CreateTask \
  --input '{"id":"task-1","title":"牛乳を買う"}' --db "$TODO_APP/todo.db"
"$DEMO_ENV/bin/intentir" run "$TODO_APP/todo.intent" CompleteTask \
  --input '{"id":"task-1"}' --db "$TODO_APP/todo.db"
"$DEMO_ENV/bin/intentir" read "$TODO_APP/todo.intent" --db "$TODO_APP/todo.db"
```

The starter comes from resources packaged in the wheel. Initialization creates no database and makes no API or model calls. The commands above have already completed the generated guide's Create and Complete steps; continue at its optional read section or the backup and Patch section instead of creating `task-1` again. See the generated `README_JA.md` for the full persistent CRUD, paired backup, Patch, and migration commands. The [historical alpha2 Japanese public trial checklist](docs/PUBLIC_TRIAL_JA.md) remains pinned to that release.

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

## Source checkout: Persistent Todo, Patch, and Migration

This later walkthrough is specifically for a source checkout and must be run from the repository root. It copies the checked-in application and semantic Patch into a fresh temporary directory; the standalone wheel workflow above does not require a checkout.

```sh
WORK="$(mktemp -d)"
cp examples/todo_crud.intent "$WORK/todo.intent"
cp examples/add_task_priority.patch.json "$WORK/add_task_priority.patch.json"

python3 -m intentir run "$WORK/todo.intent" CreateTask \
  --input '{"id":"task-1","title":"buy milk"}' --db "$WORK/todo.db"
python3 -m intentir run "$WORK/todo.intent" CompleteTask \
  --input '{"id":"task-1"}' --db "$WORK/todo.db"
python3 -m intentir read "$WORK/todo.intent" --db "$WORK/todo.db"
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
python3 -m intentir read "$WORK/todo.intent" --db "$WORK/todo.db" --entity Task
```

After the Patch is applied and before `migrate --apply` succeeds, `read` is rejected because the source and database schemas do not match. After migration, `read` returns the preserved `done: true`, the renamed title, and the default `priority: 0`.

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
python3 -m intentir read "$WORK/todo.intent" --db "$WORK/todo.db"
```

Every IntentIR command is a new process. The SQLite database preserves the completed task between them; the migration fills the newly added `priority` field with its default `0`. The rename output therefore contains `done: true`, the new title, and `priority: 0`, and the final delete output contains an empty `Task` list. The first `migrate` only prints the plan; the second applies it.

## Run the Container

Build the pinned Python 3.13 image:

```sh
docker build --pull -t intentir:local .
```

Run the default concurrent-agent demonstration without network access and with a read-only root filesystem:

```sh
docker run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  intentir:local
```

Run another IntentIR command by replacing the default arguments:

```sh
docker run --rm --network none intentir:local \
  test examples/todo_crud.intent
```

## Next Steps

- [Ailex language guide](AILEX_README.md)
- [IntentIR commands and architecture](README.md)
- [Concurrent-agent scenario](demo/concurrent_agent/README.md)
- [IntentBench-Evolve](benchmarks/intentbench_evolve/README.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
